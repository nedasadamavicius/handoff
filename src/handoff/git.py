from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path


def _run_git(path: Path, *args: str) -> str | None:
    if not (path / ".git").is_dir():
        return None
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(path),
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def git_status_short(path: Path) -> str:
    return _run_git(path, "status", "--short") or ""


def head_commit(path: Path) -> str:
    """Current HEAD sha, or "" outside a repository or before the first commit."""
    return _run_git(path, "rev-parse", "--verify", "--quiet", "HEAD") or ""


def committed_files_since(path: Path, start_commit: str, started_at: datetime) -> list[str]:
    """Files touched by commits made since the session started.

    Diffs from the commit that was HEAD at session start; a repository that had
    no commits then falls back to every commit dated after the start time.
    """
    if start_commit:
        output = _run_git(path, "diff", "--name-only", f"{start_commit}..HEAD")
    else:
        output = _run_git(path, "log", f"--since={started_at.isoformat()}", "--name-only", "--format=")
    files: list[str] = []
    for line in (output or "").splitlines():
        line = line.strip()
        if line and line not in files:
            files.append(line)
    return files


def session_changed_files(status: str, committed: list[str]) -> list[str]:
    """Uncommitted files from status, then committed ones not already listed."""
    files = changed_files_from_status(status)
    return files + [item for item in committed if item not in files]


def changed_files_from_status(status: str) -> list[str]:
    files: list[str] = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path:
            files.append(path)
    return files


def origin_url(repo: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(repo),
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def repository_id(repo: Path) -> str:
    """Machine-independent id: the normalised origin URL, else the folder name."""
    url = origin_url(repo)
    if not url:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", repo.resolve().name) or "repo"
    url = re.sub(r"^[a-z+]+://", "", url, flags=re.I)
    url = re.sub(r"^[^@/]+@", "", url)
    is_scp_style = re.match(r"^[^/]+:[^/\d]", url)
    if is_scp_style:
        url = url.replace(":", "/", 1)
    url = re.sub(r"\.git$", "", url.strip("/"), flags=re.I).lower()
    return re.sub(r"[^a-z0-9._-]+", "__", url)
