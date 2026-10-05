from __future__ import annotations

import re
import subprocess
from pathlib import Path


def git_status_short(path: Path) -> str:
    if not (path / ".git").is_dir():
        return ""
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(path),
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


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
