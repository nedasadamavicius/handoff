from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from handoff.documents import (
    first_occurrences,
    parse_markdown_sections,
    render_bullets,
    render_frontmatter,
    split_frontmatter,
    strip_bullet_prefix,
)


@dataclass(frozen=True)
class SessionFile:
    path: Path
    metadata: dict
    body: str


@dataclass
class SessionState:
    workspace: str
    started_at: datetime
    files_opened: list[str] = field(default_factory=list)
    tools_launched: list[str] = field(default_factory=list)


def now_local() -> datetime:
    return datetime.now().astimezone()


def session_filename(ended_at: datetime) -> str:
    return ended_at.strftime("%Y-%m-%d-%H%M%S.md")


def summary_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned
    return ""


def parse_session_file(path: Path) -> SessionFile:
    metadata, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return SessionFile(path=path, metadata=metadata, body=body)


def read_handoff(path: Path) -> SessionFile | None:
    if not path.exists():
        return None
    return parse_session_file(path)


def session_metadata(
    workspace: str,
    started_at: datetime,
    ended_at: datetime,
    files_opened: list[str],
    tools_launched: list[str],
) -> dict:
    return {
        "workspace": workspace,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "summary_version": 1,
        "tools_launched": tools_launched,
        "files_opened": files_opened,
    }


def render_handoff(
    workspace: str,
    started_at: datetime,
    ended_at: datetime,
    files_opened: list[str],
    tools_launched: list[str],
    summary: str,
) -> str:
    metadata = session_metadata(workspace, started_at, ended_at, files_opened, tools_launched)
    body = summary.strip() or (
        "## Summary\n"
        "Manual handoff created without a summary.\n\n"
        "## Done\n"
        "- \n\n"
        "## Open Loops\n"
        "- \n\n"
        "## Next\n"
        "- \n"
    )
    return f"{render_frontmatter(metadata)}{body}\n"


def render_session_log(
    workspace: str,
    started_at: datetime,
    ended_at: datetime,
    files_opened: list[str],
    tools_launched: list[str],
    summary: str,
    completed: str,
    open_issues: str,
    evidence: str = "",
) -> str:
    metadata = session_metadata(workspace, started_at, ended_at, files_opened, tools_launched)
    body = [
        "# Session",
        "## Summary\n\n" + (summary.strip() or "Not recorded."),
        "## Completed\n\n" + normalize_bullets(completed),
        "## Open Issues\n\n" + normalize_bullets(open_issues),
    ]
    if evidence.strip():
        body.append("## Evidence\n\n```text\n" + evidence.strip() + "\n```")
    return render_frontmatter(metadata) + "\n\n".join(body) + "\n"


def normalize_bullets(text: str) -> str:
    return render_bullets(bullet_items(text))


def bullet_items(text: str) -> list[str]:
    items = (strip_bullet_prefix(line) for line in text.splitlines() if line.strip())
    return [item for item in items if item.lower() != "none"]


def merge_items(existing: list[str], incoming: list[str]) -> list[str]:
    candidates = [item.strip() for item in existing + incoming]
    return first_occurrences(item for item in candidates if item and item.lower() != "none")


def render_day_log(
    workspace: str,
    day: date,
    session_files: list[str],
    latest_summary: str,
    completed: list[str],
    open_issues: list[str],
    session_rows: list[str],
) -> str:
    metadata = {
        "workspace": workspace,
        "date": day.isoformat(),
        "summary_version": 1,
        "sessions": session_files,
    }
    summary = f"Workday contains {len(session_files)} recorded session"
    summary += "s" if len(session_files) != 1 else ""
    summary += f". Latest: {summary_line(latest_summary) or 'Not recorded.'}"
    body = [
        f"# Day: {day.isoformat()}",
        "## Summary\n\n" + summary,
        "## Completed\n\n" + render_bullets(completed),
        "## Open Issues\n\n" + render_bullets(open_issues),
        "## Sessions\n\n" + ("\n".join(session_rows) if session_rows else "- None"),
    ]
    return render_frontmatter(metadata) + "\n\n".join(body) + "\n"


@dataclass
class DayLogContent:
    session_files: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    open_issues: list[str] = field(default_factory=list)
    session_rows: list[str] = field(default_factory=list)


def read_day_log(path: Path) -> DayLogContent:
    if not path.exists():
        return DayLogContent()
    day_log = parse_session_file(path)
    sessions = day_log.metadata.get("sessions") or []
    sections = parse_markdown_sections(day_log.body)
    return DayLogContent(
        session_files=[str(item) for item in sessions] if isinstance(sessions, list) else [],
        completed=bullet_items(sections.get("completed", "")),
        open_issues=bullet_items(sections.get("open issues", "")),
        session_rows=[
            line.strip()
            for line in sections.get("sessions", "").splitlines()
            if line.strip() and line.strip().lower() != "- none"
        ],
    )


def update_day_log(
    path: Path,
    workspace: str,
    ended_at: datetime,
    session_file: str,
    summary: str,
    completed: str,
    open_issues: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_day_log(path)
    session_row = (
        f"- {ended_at.strftime('%H:%M')} - {summary_line(summary) or 'Session recorded.'} (`sessions/{session_file}`)"
    )
    path.write_text(
        render_day_log(
            workspace=workspace,
            day=ended_at.date(),
            session_files=merge_items(existing.session_files, [session_file]),
            latest_summary=summary,
            completed=merge_items(existing.completed, bullet_items(completed)),
            open_issues=merge_items(existing.open_issues, bullet_items(open_issues)),
            session_rows=merge_items(existing.session_rows, [session_row]),
        ),
        encoding="utf-8",
    )


def save_handoff(
    path: Path,
    workspace: str,
    started_at: datetime,
    files_opened: list[str],
    tools_launched: list[str],
    summary: str,
) -> Path:
    ended_at = now_local()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_handoff(
            workspace=workspace,
            started_at=started_at,
            ended_at=ended_at,
            files_opened=files_opened,
            tools_launched=tools_launched,
            summary=summary,
        ),
        encoding="utf-8",
    )
    return path
