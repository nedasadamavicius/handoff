from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from handoff.documents import render_last_markdown, render_next_markdown
from handoff.session import render_session_log, session_filename, update_day_log
from handoff.workspace import Workspace


def _available_session_path(workspace: Workspace, ended_at: datetime) -> Path:
    """Return a collision-free session path for the supplied end time."""
    filename = session_filename(ended_at)
    path = workspace.sessions_dir / filename
    counter = 2
    while path.exists():
        filename = f"{session_filename(ended_at).removesuffix('.md')}-{counter}.md"
        path = workspace.sessions_dir / filename
        counter += 1
    return path


def save_workspace_handoff(
    *,
    workspace: Workspace,
    started_at: datetime,
    ended_at: datetime,
    files_opened: Sequence[str],
    tools_launched: Sequence[str],
    fields: Mapping[str, str],
) -> Path:
    """Persist a handoff and its session/day history as one workflow."""
    last_text = render_last_markdown(fields)
    next_text = render_next_markdown(fields["next"])

    workspace.sessions_dir.mkdir(parents=True, exist_ok=True)
    session_path = _available_session_path(workspace, ended_at)
    session_path.write_text(
        render_session_log(
            workspace=workspace.name,
            started_at=started_at,
            ended_at=ended_at,
            files_opened=list(files_opened),
            tools_launched=list(tools_launched),
            summary=fields["summary"],
            completed=fields["done"],
            open_issues=fields["open"],
            evidence=fields.get("evidence", ""),
        ),
        encoding="utf-8",
    )
    update_day_log(
        path=workspace.day_file(ended_at.date()),
        workspace=workspace.name,
        ended_at=ended_at,
        session_file=session_path.name,
        summary=fields["summary"],
        completed=fields["done"],
        open_issues=fields["open"],
    )
    workspace.last_file.write_text(last_text.rstrip() + "\n", encoding="utf-8")
    if next_text.strip():
        workspace.next_file.write_text(next_text.rstrip() + "\n", encoding="utf-8")
    if workspace.draft_file.exists():
        workspace.draft_file.unlink()

    return session_path
