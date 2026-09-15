from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path

import yaml
from textual.app import App
from textual.widgets import Input, MarkdownViewer, TextArea
from typer.testing import CliRunner

from handoff.config import AppConfig, ensure_config, load_config
from handoff.cli import app
from handoff.handoff import HandoffDraft, parse_combined_draft, parse_draft_or_files, parse_last_sections, render_combined_draft
from handoff.launcher import CODEX_FINALIZE_PROMPT, LaunchError, codex_finalize_command, run_command
from handoff.session import parse_session_file, render_handoff, render_session_log, update_day_log
from handoff.tui import HandoffScreen, LogBrowserScreen, NewEntryScreen, WorkspaceShell, merge_next_text, strip_handoff_frontmatter
from handoff.weekly import (
    append_week_to_worklog,
    auto_generate_draft,
    collect_week_data,
    find_pending_weeks,
    finalize_week_draft,
    read_week_draft,
    week_date_range,
    week_key,
    week_label,
)
from handoff.workspace import (
    current_directory_workspace,
    ensure_tool_file,
    ensure_tool_files,
    ensure_workspace_files,
    infer_workspace_type,
    workspace_type,
)


def test_default_config_uses_in_code_defaults() -> None:
    config = AppConfig()

    assert config.editor.default in config.editor.options
    assert config.tools == {"grok": "grok", "codex": "codex", "claude": "claude"}


def test_config_creation_uses_handoff_root(tmp_path: Path) -> None:
    config = ensure_config(tmp_path)

    assert config.root == tmp_path
    assert (tmp_path / "config.yaml").exists()
    assert (tmp_path / "workspaces").is_dir()


def test_load_config_filters_removed_default_tools(tmp_path: Path) -> None:
    ensure_config(tmp_path)
    config_file = tmp_path / "config.yaml"
    data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    data["tools"] = {"claude": "claude", "gemini": "gemini"}
    config_file.write_text(yaml.safe_dump(data), encoding="utf-8")

    config = load_config(tmp_path)

    assert config.tools == {"claude": "claude"}


def test_current_directory_workspace_uses_local_handoff_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    workspace = current_directory_workspace(repo)
    ensure_workspace_files(workspace, workspace_kind="regular")

    assert workspace.external is True
    assert workspace.path == repo.resolve()
    assert workspace.meta == (repo / ".handoff").resolve()
    assert (repo / ".handoff" / "WORKSPACE.md").exists()
    assert (repo / ".handoff" / "LAST.md").exists()
    assert (repo / ".handoff" / "NEXT.md").exists()
    assert workspace_type(workspace) == "regular"


def test_init_directory_command_creates_local_workspace(tmp_path: Path) -> None:
    runner = CliRunner()
    target = tmp_path / "my-notes"
    config_root = tmp_path / "global"

    result = runner.invoke(app, ["init", str(target), "--root", str(config_root)])

    assert result.exit_code == 0
    assert target.is_dir()
    assert (target / ".handoff" / "WORKSPACE.md").exists()
    assert (target / ".handoff" / "LAST.md").exists()
    assert (target / ".handoff" / "NEXT.md").exists()


def test_workspace_type_infers_code_only_from_git_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    regular = tmp_path / "regular"
    regular.mkdir()
    (repo / ".git").mkdir()

    assert infer_workspace_type(current_directory_workspace(repo)) == "code"
    assert infer_workspace_type(current_directory_workspace(regular)) == "regular"


def test_codex_tool_creates_agents_memory_file(tmp_path: Path) -> None:
    workspace = current_directory_workspace(tmp_path)

    ensure_tool_files(workspace, {"codex": "codex"})

    path = tmp_path / "AGENTS.md"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "Read `.handoff/WORKSPACE.md`" in text
    assert "Treat it as the live handoff ledger" in text
    assert "Before handing control back to the user after material work" in text
    assert "only the files that matter" in text
    assert "Do not list agent process steps" in text
    assert "running tests" in text
    assert "Do not spend time expanding the NEXT.md section" in text


def test_codex_command_creates_agents_memory_file(tmp_path: Path) -> None:
    workspace = current_directory_workspace(tmp_path)

    ensure_tool_files(workspace, {"openai": "codex --full-auto"})

    assert (tmp_path / "AGENTS.md").exists()


def test_selected_tool_creates_only_its_memory_file(tmp_path: Path) -> None:
    workspace = current_directory_workspace(tmp_path)

    ensure_tool_file(workspace, "codex", "codex")

    assert (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / "GEMINI.md").exists()


def test_render_and_parse_session(tmp_path: Path) -> None:
    started = datetime.fromisoformat("2026-06-05T18:00:00+02:00")
    ended = datetime.fromisoformat("2026-06-05T19:00:00+02:00")
    text = render_handoff(
        workspace="software",
        started_at=started,
        ended_at=ended,
        files_opened=["NEXT.md"],
        tools_launched=["codex"],
        summary="## Summary\nWorked on the product.",
    )
    path = tmp_path / "session.md"
    path.write_text(text, encoding="utf-8")

    session = parse_session_file(path)

    assert session.metadata["workspace"] == "software"
    assert session.metadata["files_opened"] == ["NEXT.md"]
    assert "Worked on the product." in session.body


def test_missing_executable_is_launch_error(tmp_path: Path) -> None:
    try:
        run_command(["definitely-not-installed-handoff-tool"], cwd=tmp_path)
    except LaunchError as exc:
        assert "Could not find executable" in str(exc)
    else:
        raise AssertionError("Expected LaunchError")


def test_run_command_resolves_windows_command_wrapper(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[list[str], str, bool]] = []
    wrapper = r"C:\Program Files\Microsoft VS Code\bin\code.cmd"
    monkeypatch.setattr("handoff.launcher.shutil.which", lambda executable: wrapper)
    monkeypatch.setattr(
        "handoff.launcher.subprocess.call",
        lambda command, cwd, shell: calls.append((command, cwd, shell)) or 0,
    )

    assert run_command(["code", "--wait", "notes.md"], cwd=tmp_path) == 0
    assert calls == [([wrapper, "--wait", "notes.md"], str(tmp_path), False)]


def test_codex_finalize_command_uses_exec_resume_last() -> None:
    command = codex_finalize_command("codex", "codex --full-auto")

    assert command is not None
    assert command.startswith("codex exec resume --last ")
    assert CODEX_FINALIZE_PROMPT in command
    assert "Do not list agent process steps" in command


def test_codex_finalize_command_skips_non_codex_tools() -> None:
    assert codex_finalize_command("claude", "claude") is None
    assert codex_finalize_command("codex", "npx codex") is None


def test_combined_handoff_draft_roundtrip() -> None:
    rendered = render_combined_draft(HandoffDraft(last="# Last\n\nDone.", next="# Next\n\n- Continue."))

    parsed = parse_combined_draft(rendered)

    assert parsed.last == "# Last\n\nDone."
    assert parsed.next == "# Next\n\n- Continue."


def test_parse_last_sections_drops_passive_completed_items() -> None:
    summary, done, open_issues = parse_last_sections(
        "### Summary\n\nUpdated handoff behavior.\n\n"
        "### Completed\n\n"
        "- Read `.handoff/WORKSPACE.md`.\n"
        "- Re-read `.handoff/NEXT.md`.\n"
        "- Implemented completed-item filtering.\n"
        "- Ran pytest.\n\n"
        "### Open Issues\n\n- None"
    )

    assert summary == "Updated handoff behavior."
    assert "- Read" not in done
    assert "- Re-read" not in done
    assert "- Implemented completed-item filtering." in done
    assert "- Ran pytest." not in done
    assert open_issues == "- None"


def test_legacy_draft_prefill_normalizes_diff_markers() -> None:
    draft = parse_draft_or_files(
        "# Current Session Summary\n\n"
        "## Summary\n\n"
        "+Implemented a modal prefill fix.\n\n"
        "## Completed\n\n"
        "-- Fixed strict draft parsing.\n"
        "+- Added regression coverage.\n\n"
        "## Open Issues\n\n"
        "+- None\n\n"
        "# Next\n\n"
        "+- Verify handoff save from the TUI."
    )

    summary, done, open_issues = parse_last_sections(draft.last)

    assert summary == "Implemented a modal prefill fix."
    assert done == "- Fixed strict draft parsing.\n- Added regression coverage."
    assert open_issues == "- None"
    assert draft.next == "# Next\n\n- Verify handoff save from the TUI."


def test_strip_handoff_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "LAST.md"
    path.write_text("---\nworkspace: test\n---\n\n# Last Session\n\nDone.\n", encoding="utf-8")

    strip_handoff_frontmatter(path)

    assert path.read_text(encoding="utf-8") == "# Last Session\n\nDone.\n"


def test_merge_next_text_preserves_existing_items() -> None:
    existing = "# Next\n\n- Keep prior follow-up.\n- Revisit carryover."
    incoming = "# Next\n\n- Add new follow-up."

    merged = merge_next_text(existing, incoming)

    assert "- Keep prior follow-up." in merged
    assert "- Revisit carryover." in merged
    assert "- Add new follow-up." in merged


def test_merge_next_text_deduplicates_and_replaces_placeholder() -> None:
    existing = "# Next\n\n- Define the next action."
    incoming = "## NEXT.md\n\n- Real next action.\n- Real next action."

    assert merge_next_text(existing, incoming) == "- Real next action."


def test_handoff_fields_support_standard_selection_and_clipboard_shortcuts() -> None:
    class HandoffApp(App):
        def on_mount(self) -> None:
            self.push_screen(HandoffScreen("test", "Original text", "- Done", "- None", "- Next"))

    async def exercise_editor() -> None:
        app = HandoffApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            field = app.screen.query_one("#handoff-summary", TextArea)

            field.load_text("First line\nSecond line")
            field.move_cursor((0, 3))
            await pilot.press("down")
            assert field.cursor_location == (1, 3)
            await pilot.press("up", "shift+down")
            assert field.selected_text == "st line\nSec"

            await pilot.press("ctrl+a", "ctrl+c")
            assert field.selected_text == "First line\nSecond line"
            assert app.clipboard == "First line\nSecond line"

            await pilot.press("backspace")
            assert field.text == ""

            app.copy_to_clipboard("Pasted text")
            await pilot.press("ctrl+v")
            assert field.text == "Pasted text"

            await pilot.press("ctrl+shift+left", "ctrl+x")
            assert field.text == "Pasted "
            assert app.clipboard == "text"

    asyncio.run(exercise_editor())

    arrow_bindings = {
        binding.key: binding
        for binding in WorkspaceShell.BINDINGS
        if binding.key in {"up", "down"}
    }
    assert not arrow_bindings["up"].priority
    assert not arrow_bindings["down"].priority


def test_ctrl_s_saves_open_handoff_instead_of_stacking_modal(tmp_path: Path) -> None:
    workspace = current_directory_workspace(tmp_path)
    app = WorkspaceShell(AppConfig(root=tmp_path / "config"), workspace)

    async def exercise_handoff() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("h")
            await pilot.pause()
            assert isinstance(app.screen, HandoffScreen)
            assert len(app.screen_stack) == 2

            await pilot.press("ctrl+s")
            await pilot.pause()

            assert not isinstance(app.screen, HandoffScreen)
            assert len(app.screen_stack) == 1
            assert workspace.last_file.exists()

    asyncio.run(exercise_handoff())


def test_new_folder_action_creates_folder_in_workspace(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    workspace = current_directory_workspace(workspace_path)
    app = WorkspaceShell(AppConfig(root=tmp_path / "config"), workspace)

    async def exercise_new_folder() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            assert isinstance(app.screen, NewEntryScreen)

            app.screen.query_one("#new-entry-input", Input).value = "notes"
            await pilot.press("enter")
            await pilot.pause()

            assert (workspace_path / "notes").is_dir()

    asyncio.run(exercise_new_folder())


def test_log_browser_separates_loading_from_pane_focus(tmp_path: Path) -> None:
    workspace = current_directory_workspace(tmp_path)
    workspace.sessions_dir.mkdir(parents=True)
    (workspace.sessions_dir / "2026-06-20-120000.md").write_text(
        "# Newest\n\n" + "\n\n".join(f"Paragraph {number}" for number in range(100)),
        encoding="utf-8",
    )
    (workspace.sessions_dir / "2026-06-19-120000.md").write_text(
        "# Older\n\nOlder content.",
        encoding="utf-8",
    )

    class LogBrowserApp(App):
        def on_mount(self) -> None:
            self.push_screen(LogBrowserScreen(workspace))

    async def exercise_browser() -> None:
        app = LogBrowserApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, LogBrowserScreen)
            preview_pane = screen.query_one("#log-preview-pane")
            pane_region = preview_pane.region

            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert screen._focus_pane == "list"
            assert screen.focused is screen.query_one("#tab-sessions")
            assert preview_pane.region == pane_region

            preview = screen.query_one("#log-preview", MarkdownViewer)
            await pilot.press("right")
            await pilot.pause()
            assert screen._focus_pane == "preview"
            assert screen.focused is preview

            await pilot.press("down")
            await pilot.pause()
            assert preview.scroll_y > 0

            await pilot.press("left")
            await pilot.pause()
            assert screen._focus_pane == "list"
            assert screen.focused is screen.query_one("#tab-sessions")
            assert preview_pane.region == pane_region
            assert preview.scroll_x == 0
            loaded_path = screen._preview_path
            scroll_y = preview.scroll_y

            await pilot.press("down")
            await pilot.pause()
            assert screen.query_one("#tab-sessions").index == 1
            assert screen._preview_path == loaded_path
            assert preview.scroll_y == scroll_y

            await pilot.press("right")
            await pilot.pause()
            assert screen._focus_pane == "preview"
            assert screen.focused is preview
            assert screen._preview_path == loaded_path
            assert preview.scroll_x == 0
            assert preview.scroll_y == scroll_y

            await pilot.press("left", "enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert screen._preview_path is not None
            assert screen._preview_path.name == "2026-06-19-120000.md"
            assert screen._focus_pane == "list"
            assert preview.scroll_y == 0

    asyncio.run(exercise_browser())


# --- weekly ---

def _write_day(days_dir: Path, day: date, completed: str, open_issues: str, sessions: list[str]) -> None:
    days_dir.mkdir(parents=True, exist_ok=True)
    from handoff.session import render_day_log
    content = render_day_log(
        workspace="test",
        day=day,
        session_files=sessions,
        latest_summary="Did some work.",
        completed=[c.lstrip("- ").strip() for c in completed.splitlines() if c.strip()],
        open_issues=[o.lstrip("- ").strip() for o in open_issues.splitlines() if o.strip()],
        session_rows=[f"- 10:00 - Did some work. (`sessions/{s}`)" for s in sessions],
    )
    (days_dir / f"{day.isoformat()}.md").write_text(content, encoding="utf-8")


def test_week_key_and_date_range() -> None:
    assert week_key(date(2026, 6, 15)) == (2026, 25)  # Monday of W25
    assert week_key(date(2026, 6, 21)) == (2026, 25)  # Sunday of W25
    assert week_key(date(2026, 6, 22)) == (2026, 26)  # Monday of W26

    label = week_date_range(2026, 25)
    assert "Jun" in label
    assert "15" in label
    assert "21" in label

    cross_month = week_date_range(2026, 27)  # Jun 29 – Jul 5
    assert "Jun" in cross_month
    assert "Jul" in cross_month


def test_collect_week_data_aggregates_days(tmp_path: Path) -> None:
    days_dir = tmp_path / "days"
    _write_day(days_dir, date(2026, 6, 15), "- Shipped feature A", "- Blocker X", ["s1.md"])
    _write_day(days_dir, date(2026, 6, 16), "- Fixed bug B", "- None", ["s2.md", "s3.md"])
    _write_day(days_dir, date(2026, 6, 22), "- Unrelated next week", "- None", ["s4.md"])

    data = collect_week_data(days_dir, 2026, 25)

    assert data.year == 2026
    assert data.week == 25
    assert len(data.days) == 2
    assert data.session_count == 3
    assert any("Shipped feature A" in item for item in data.completed)
    assert any("Fixed bug B" in item for item in data.completed)
    assert not any("Unrelated" in item for item in data.completed)


def test_find_pending_weeks_detects_unfinalized_week(tmp_path: Path) -> None:
    days_dir = tmp_path / "days"
    weeks_dir = tmp_path / "weeks"
    # W24 (Jun 8) is a genuinely past week relative to today (Jun 20, W25)
    _write_day(days_dir, date(2026, 6, 8), "- Done A", "- None", ["s1.md"])

    pending = find_pending_weeks(days_dir, weeks_dir)

    assert (2026, 24) in pending


def test_find_pending_weeks_skips_current_week(tmp_path: Path, monkeypatch) -> None:
    days_dir = tmp_path / "days"
    weeks_dir = tmp_path / "weeks"
    today = date.today()
    _write_day(days_dir, today, "- Done today", "- None", ["s1.md"])

    pending = find_pending_weeks(days_dir, weeks_dir)

    assert week_key(today) not in pending


def test_auto_generate_draft_creates_week_file(tmp_path: Path) -> None:
    days_dir = tmp_path / "days"
    weeks_dir = tmp_path / "weeks"
    _write_day(days_dir, date(2026, 6, 15), "- Shipped feature A", "- None", ["s1.md"])

    path = auto_generate_draft("test", days_dir, weeks_dir, 2026, 25)

    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "2026-W25" in text
    assert "status: draft" in text
    assert "Shipped feature A" in text


def test_read_week_draft_returns_sections(tmp_path: Path) -> None:
    days_dir = tmp_path / "days"
    weeks_dir = tmp_path / "weeks"
    _write_day(days_dir, date(2026, 6, 15), "- Shipped feature A", "- Carry this", ["s1.md"])
    auto_generate_draft("test", days_dir, weeks_dir, 2026, 25)

    fields = read_week_draft(weeks_dir, 2026, 25)

    assert fields is not None
    summary, highlights, carry_forwards = fields
    assert "session" in summary.lower()
    assert "Shipped feature A" in highlights
    assert "Carry this" in carry_forwards


def test_append_week_to_worklog_creates_and_prepends(tmp_path: Path) -> None:
    worklog = tmp_path / "WORKLOG.md"

    append_week_to_worklog(worklog, 2026, 24, "First week.", "- Built X", "- None")
    append_week_to_worklog(worklog, 2026, 25, "Second week.", "- Built Y", "- Follow up on Z")

    text = worklog.read_text(encoding="utf-8")
    assert text.startswith("# Work Log")
    # W25 is newer, should appear before W24
    assert text.index("2026-W25") < text.index("2026-W24")
    assert "Built Y" in text
    assert "Follow up on Z" in text


def test_finalize_week_draft_marks_as_finalized(tmp_path: Path) -> None:
    days_dir = tmp_path / "days"
    weeks_dir = tmp_path / "weeks"
    _write_day(days_dir, date(2026, 6, 15), "- Done", "- None", ["s1.md"])
    auto_generate_draft("test", days_dir, weeks_dir, 2026, 25)

    finalize_week_draft(weeks_dir, 2026, 25)
    pending = find_pending_weeks(days_dir, weeks_dir)

    assert (2026, 25) not in pending
