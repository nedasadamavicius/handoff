"""Two-way sync of a workspace's handoff notes with a Nextcloud/WebDAV folder.

Remote layout: ``<server>/remote.php/dav/files/<user>/<folder>/<repository-id>/<file>``.
Only handoff notes are synced (never DRAFT.md). Deletions are never propagated. When
both sides changed a file the two versions are combined (see ``note_merge``), the
result is pushed so every machine converges, and the user reviews it in place.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from handoff.git import repository_id
from handoff.note_merge import combine_versions, has_merge_markers
from handoff.webdav import (
    PreconditionFailed,
    SyncError,
    SyncSettings,
    WebDAVClient,
    load_password,
)

TOP_LEVEL_NOTES = ("WORKSPACE.md", "LAST.md", "NEXT.md", "WORKLOG.md")
NOTE_DIRECTORIES = ("sessions", "days", "weeks")
STATE_FILENAME = ".sync-state.json"
DEADLINE_SECONDS = 60.0

SyncState = dict[str, dict[str, str]]


@dataclass
class SyncReport:
    pushed: list[str] = field(default_factory=list)
    pulled: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{len(self.pushed)} pushed", f"{len(self.pulled)} pulled"]
        if self.merged:
            parts.append(f"{len(self.merged)} merged")
        if self.needs_review:
            parts.append(f"review markers in {', '.join(self.needs_review)}")
        return ", ".join(parts)


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local_notes(meta: Path) -> dict[str, bytes]:
    """Relative path -> content for every syncable note under ``meta``."""
    notes: dict[str, bytes] = {}
    for filename in TOP_LEVEL_NOTES:
        if (meta / filename).is_file():
            notes[filename] = (meta / filename).read_bytes()
    for directory in NOTE_DIRECTORIES:
        if not (meta / directory).is_dir():
            continue
        for path in (meta / directory).glob("*.md"):
            if path.is_file():
                notes[f"{directory}/{path.name}"] = path.read_bytes()
    return notes


def load_sync_state(meta: Path) -> SyncState:
    path = meta / STATE_FILENAME
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return {}


def has_unsynced(meta: Path) -> bool:
    state = load_sync_state(meta)
    return any(state.get(path, {}).get("hash") != content_hash(data) for path, data in local_notes(meta).items())


def notes_needing_review(meta: Path) -> list[str]:
    """Notes that still contain merge markers from a combined edit."""
    return sorted(
        relative_path
        for relative_path, data in local_notes(meta).items()
        if has_merge_markers(data.decode("utf-8", errors="replace"))
    )


class WorkspaceSync:
    """Reconciles one workspace's notes with one remote folder."""

    def __init__(
        self,
        meta: Path,
        client: WebDAVClient,
        remote_base: str,
        on_progress: Callable[[str], None] | None = None,
        deadline_seconds: float = DEADLINE_SECONDS,
    ) -> None:
        self.meta = meta
        self.client = client
        self.remote_base = remote_base
        self.on_progress = on_progress
        self.deadline_seconds = deadline_seconds
        self.report = SyncReport()
        self.state: SyncState = {}
        self._started_at = 0.0

    def run(self) -> SyncReport:
        self._started_at = time.monotonic()
        self.meta.mkdir(parents=True, exist_ok=True)
        self.state = load_sync_state(self.meta)
        self._ensure_remote_folders()
        remote_etags = self._list_remote_notes()
        local = local_notes(self.meta)
        try:
            for relative_path in sorted(set(local) | set(remote_etags)):
                self._checkpoint(relative_path)
                self._reconcile(relative_path, local.get(relative_path), remote_etags.get(relative_path))
        finally:
            (self.meta / STATE_FILENAME).write_text(json.dumps(self.state, indent=1), encoding="utf-8")
        self.report.needs_review = notes_needing_review(self.meta)
        return self.report

    def _checkpoint(self, message: str) -> None:
        if time.monotonic() - self._started_at > self.deadline_seconds:
            raise SyncError("Sync timed out")
        if self.on_progress:
            self.on_progress(message)

    def _remote_path(self, relative_path: str) -> str:
        return f"{self.remote_base}/{relative_path}"

    def _ensure_remote_folders(self) -> None:
        self._checkpoint("Preparing remote folder")
        folder_path = ""
        for part in self.remote_base.strip("/").split("/"):
            folder_path = f"{folder_path}/{part}" if folder_path else part
            self.client.make_collection(folder_path)
        for directory in NOTE_DIRECTORIES:
            self.client.make_collection(self._remote_path(directory))

    def _list_remote_notes(self) -> dict[str, str]:
        etags: dict[str, str] = {}
        for directory in ("", *NOTE_DIRECTORIES):
            self._checkpoint("Listing remote files")
            entries = self.client.list_directory(self._remote_path(directory).rstrip("/"))
            for name, (etag, is_directory) in entries.items():
                if not is_directory and name.endswith(".md"):
                    etags[f"{directory}/{name}" if directory else name] = etag
        return etags

    def _reconcile(self, relative_path: str, local_data: bytes | None, remote_etag: str | None) -> None:
        if local_data is not None and remote_etag is None:
            self._push(relative_path, local_data, expected_etag=None)
        elif local_data is None and remote_etag is not None:
            self._pull(relative_path, remote_etag)
        elif local_data is not None and remote_etag is not None:
            self._reconcile_both(relative_path, local_data, remote_etag)

    def _reconcile_both(self, relative_path: str, local_data: bytes, remote_etag: str) -> None:
        local_hash = content_hash(local_data)
        last_synced = self.state.get(relative_path)
        local_changed = last_synced is None or last_synced["hash"] != local_hash
        remote_changed = last_synced is None or last_synced["etag"] != remote_etag
        if local_changed and remote_changed:
            self._merge_with_remote(relative_path, local_data, remote_etag)
        elif local_changed:
            self._push(relative_path, local_data, expected_etag=remote_etag)
        elif remote_changed:
            self._pull(relative_path, remote_etag)

    def _merge_with_remote(self, relative_path: str, local_data: bytes, remote_etag: str) -> None:
        remote_data = self.client.download(self._remote_path(relative_path))
        if remote_data == local_data:
            self.state[relative_path] = {"hash": content_hash(local_data), "etag": remote_etag}
            return
        merged_text = combine_versions(
            local_data.decode("utf-8", errors="replace"), remote_data.decode("utf-8", errors="replace")
        )
        merged_data = merged_text.encode("utf-8")
        (self.meta / relative_path).write_bytes(merged_data)
        try:
            new_etag = self.client.upload(self._remote_path(relative_path), merged_data, remote_etag)
        except PreconditionFailed:
            return
        self.state[relative_path] = {"hash": content_hash(merged_data), "etag": new_etag}
        self.report.merged.append(relative_path)

    def _push(self, relative_path: str, data: bytes, expected_etag: str | None) -> None:
        try:
            new_etag = self.client.upload(self._remote_path(relative_path), data, expected_etag)
        except PreconditionFailed:
            self._merge_after_lost_race(relative_path, data)
            return
        self.state[relative_path] = {"hash": content_hash(data), "etag": new_etag}
        self.report.pushed.append(relative_path)

    def _merge_after_lost_race(self, relative_path: str, local_data: bytes) -> None:
        parent, _, name = self._remote_path(relative_path).rpartition("/")
        current_etag = self.client.list_directory(parent).get(name, ("", False))[0]
        if current_etag:
            self._merge_with_remote(relative_path, local_data, current_etag)

    def _pull(self, relative_path: str, remote_etag: str) -> None:
        content = self.client.download(self._remote_path(relative_path))
        target = self.meta / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        self.state[relative_path] = {"hash": content_hash(content), "etag": remote_etag}
        self.report.pulled.append(relative_path)


def sync_workspace(
    meta: Path,
    client: WebDAVClient,
    remote_base: str,
    on_progress: Callable[[str], None] | None = None,
    deadline_seconds: float = DEADLINE_SECONDS,
) -> SyncReport:
    return WorkspaceSync(meta, client, remote_base, on_progress, deadline_seconds).run()


def sync_for_repo(
    root: Path,
    settings: SyncSettings | None,
    repo: Path,
    on_progress: Callable[[str], None] | None = None,
) -> SyncReport | None:
    """Sync ``repo/.handoff``; None when sync is not configured or has no password."""
    password = load_password(root)
    if settings is None or not password:
        return None
    client = WebDAVClient(settings, password)
    return sync_workspace(repo / ".handoff", client, f"{settings.folder.strip('/')}/{repository_id(repo)}", on_progress)
