"""Per-repo handoff state kept outside the repository.

``state_root`` is any folder the user syncs themselves (for example a Nextcloud
folder). Each repo's ``.handoff`` becomes a link to ``<state_root>/<repository-id>``,
so notes follow the user across machines and never enter the repo.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from handoff.git import repository_id

BACKUP_DIRECTORY_NAME = ".handoff.local-backup"
SYNC_CONFLICT_NAME_FRAGMENT = "conflict"


class LinkStatus(Enum):
    LINKED = "linked"
    ALREADY_LINKED = "already linked"
    SKIPPED = "skipped"
    NEEDS_MIGRATION = "needs migration"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class LinkResult:
    status: LinkStatus
    message: str = ""
    target: Path | None = None


def _create_directory_link(link: Path, target: Path) -> None:
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        os.symlink(target, link, target_is_directory=True)


def _is_link_to(link: Path, target: Path) -> bool:
    return link.exists() and link.resolve() == target.resolve()


def _is_link_or_file_elsewhere(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", lambda _path: False)(path)
    return path.is_symlink() or is_junction or (path.exists() and not path.is_dir())


def _has_entries(directory: Path) -> bool:
    return directory.is_dir() and any(directory.iterdir())


def conflict_files(directory: Path) -> list[Path]:
    return [
        path for path in directory.rglob("*") if path.is_file() and SYNC_CONFLICT_NAME_FRAGMENT in path.name.lower()
    ]


def _blocking_result(link: Path, target: Path, migrate: bool) -> LinkResult | None:
    """Why ``link`` cannot be pointed at ``target`` right now, or None when it can."""
    if _is_link_to(link, target):
        return LinkResult(LinkStatus.ALREADY_LINKED, target=target)
    if _is_link_or_file_elsewhere(link):
        return LinkResult(LinkStatus.CONFLICT, f"{link} is a link or file pointing elsewhere; leaving it alone")
    if _has_entries(link) and _has_entries(target):
        return LinkResult(
            LinkStatus.CONFLICT, f"Both local .handoff and {target} contain data; merge by hand, then re-run"
        )
    if _has_entries(link) and not migrate:
        return LinkResult(LinkStatus.NEEDS_MIGRATION, f"Move existing .handoff into {target}?", target)
    return None


def link_state(repo: Path, state_root: Path | None, *, migrate: bool = False) -> LinkResult:
    """Point ``repo/.handoff`` at the synced store. Never deletes user data."""
    if state_root is None:
        return LinkResult(LinkStatus.SKIPPED)
    state_root = state_root.expanduser()
    if not state_root.is_dir():
        return LinkResult(
            LinkStatus.UNAVAILABLE,
            f"state_root {state_root} does not exist (is it synced/mounted?); using local .handoff",
        )
    target = state_root / repository_id(repo)
    link = repo / ".handoff"
    blocking_result = _blocking_result(link, target, migrate)
    if blocking_result is not None:
        return blocking_result

    target.mkdir(parents=True, exist_ok=True)
    if _has_entries(link):
        shutil.copytree(link, target, dirs_exist_ok=True)
        link.rename(repo / BACKUP_DIRECTORY_NAME)
    elif link.is_dir():
        link.rmdir()
    _create_directory_link(link, target)
    return LinkResult(LinkStatus.LINKED, target=target)
