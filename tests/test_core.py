from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml
from typer.testing import CliRunner

from handoff.config import ensure_config, load_config
from handoff.cli import app
from handoff.handoff import HandoffDraft, parse_combined_draft, render_combined_draft
from handoff.launcher import LaunchError, run_command
from handoff.session import parse_session_file, render_handoff
from handoff.tui import strip_handoff_frontmatter
from handoff.workspace import current_directory_workspace, ensure_workspace_files, infer_workspace_type, workspace_type


def test_config_creation(tmp_path: Path) -> None:
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


def test_current_directory_workspace_uses_local_ws_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    workspace = current_directory_workspace(repo)
    ensure_workspace_files(workspace, workspace_kind="regular")

    assert workspace.external is True
    assert workspace.path == repo.resolve()
    assert workspace.meta == (repo / ".ws").resolve()
    assert (repo / ".ws" / "WORKSPACE.md").exists()
    assert (repo / ".ws" / "LAST.md").exists()
    assert (repo / ".ws" / "NEXT.md").exists()
    assert workspace_type(workspace) == "regular"


def test_init_directory_command_creates_local_workspace(tmp_path: Path) -> None:
    runner = CliRunner()
    target = tmp_path / "my-notes"
    config_root = tmp_path / "global"

    result = runner.invoke(app, ["init", str(target), "--root", str(config_root)])

    assert result.exit_code == 0
    assert target.is_dir()
    assert (target / ".ws" / "WORKSPACE.md").exists()
    assert (target / ".ws" / "LAST.md").exists()
    assert (target / ".ws" / "NEXT.md").exists()


def test_workspace_type_infers_code_only_from_git_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    regular = tmp_path / "regular"
    regular.mkdir()
    (repo / ".git").mkdir()

    assert infer_workspace_type(current_directory_workspace(repo)) == "code"
    assert infer_workspace_type(current_directory_workspace(regular)) == "regular"


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
        run_command(["definitely-not-installed-ws-tool"], cwd=tmp_path)
    except LaunchError as exc:
        assert "Could not find executable" in str(exc)
    else:
        raise AssertionError("Expected LaunchError")


def test_combined_handoff_draft_roundtrip() -> None:
    rendered = render_combined_draft(HandoffDraft(last="# Last\n\nDone.", next="# Next\n\n- Continue."))

    parsed = parse_combined_draft(rendered)

    assert parsed.last == "# Last\n\nDone."
    assert parsed.next == "# Next\n\n- Continue."


def test_strip_handoff_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "LAST.md"
    path.write_text("---\nworkspace: test\n---\n\n# Last Session\n\nDone.\n", encoding="utf-8")

    strip_handoff_frontmatter(path)

    assert path.read_text(encoding="utf-8") == "# Last Session\n\nDone.\n"
