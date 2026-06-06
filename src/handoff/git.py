from __future__ import annotations

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
