from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from handoff.config import AppConfig
from handoff.git import committed_files_since, git_status_short, head_commit, session_changed_files
from handoff.tui import WorkspaceShell
from handoff.tui_screens import HandoffScreen
from handoff.workspace import current_directory_workspace


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def init_repo(repo: Path) -> Path:
    repo.mkdir(exist_ok=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "commit.gpgsign", "false")
    return repo


def commit(repo: Path, name: str, text: str = "x\n") -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"add {name}")


def test_committed_files_since_lists_files_from_commits_after_start(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, "before.py")
    start = head_commit(repo)
    assert start

    commit(repo, "src/one.py")
    commit(repo, "src/two.py")
    commit(repo, "src/one.py", "changed\n")

    assert committed_files_since(repo, start, datetime.now().astimezone()) == ["src/one.py", "src/two.py"]


def test_committed_files_since_without_start_commit_uses_start_time(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    assert head_commit(repo) == ""
    started_at = datetime.now().astimezone() - timedelta(minutes=1)

    commit(repo, "first.py")

    assert committed_files_since(repo, "", started_at) == ["first.py"]


def test_committed_files_since_outside_repository_is_empty(tmp_path: Path) -> None:
    assert head_commit(tmp_path) == ""
    assert committed_files_since(tmp_path, "abc123", datetime.now().astimezone()) == []


def test_session_changed_files_merges_uncommitted_and_committed_without_duplicates() -> None:
    status = " M src/a.py\n?? notes.md\n"
    assert session_changed_files(status, ["src/b.py", "src/a.py"]) == ["src/a.py", "notes.md", "src/b.py"]


def test_handoff_lists_committed_files_and_keeps_their_source_tags(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    workspace = current_directory_workspace(repo)
    commit(repo, ".gitignore", ".handoff/\n")
    app = WorkspaceShell(AppConfig(root=tmp_path / "config"), workspace)

    commit(repo, "src/committed.py")
    (repo / "dirty.py").write_text("y\n", encoding="utf-8")
    assert "committed.py" not in git_status_short(repo)
    workspace.draft_file.parent.mkdir(parents=True, exist_ok=True)
    workspace.draft_file.write_text(
        "## LAST.md\n\n### Summary\n\nDid work.\n\n### Completed\n\n"
        "- Committed change [src/committed.py]\n- Uncommitted change [dirty.py]\n\n"
        "### Open Issues\n\n- None\n\n## NEXT.md\n\n- Next\n",
        encoding="utf-8",
    )

    async def exercise() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("h")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, HandoffScreen)
            assert "1. dirty.py\n2. src/committed.py" in screen.evidence
            assert "- Committed change [2]" in screen.done
            assert "- Uncommitted change [1]" in screen.done

    asyncio.run(exercise())
