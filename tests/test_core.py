from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml
from typer.testing import CliRunner

from handoff.config import AppConfig, ensure_config, load_config
from handoff.cli import app
from handoff.handoff import HandoffDraft, parse_combined_draft, parse_draft_or_files, parse_last_sections, render_combined_draft
from handoff.launcher import CODEX_FINALIZE_PROMPT, LaunchError, codex_finalize_command, run_command
from handoff.session import parse_session_file, render_handoff
from handoff.tui import merge_next_text, strip_handoff_frontmatter
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

    assert config.editor.default == "nvim"
    assert config.tools == {"codex": "codex", "claude": "claude"}


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
    assert "brief summary of important `git diff` details" in text
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
