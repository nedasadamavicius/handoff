from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from handoff.documents import parse_markdown_sections


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
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return SessionFile(path=path, metadata={}, body=text)

    try:
        _, frontmatter, body = text.split("---\n", 2)
    except ValueError:
        return SessionFile(path=path, metadata={}, body=text)

    return SessionFile(
        path=path,
        metadata=yaml.safe_load(frontmatter) or {},
        body=body.lstrip(),
    )


def read_handoff(path: Path) -> SessionFile | None:
    if not path.exists():
        return None
    return parse_session_file(path)


def render_handoff(
    workspace: str,
    started_at: datetime,
    ended_at: datetime,
    files_opened: list[str],
    tools_launched: list[str],
    summary: str,
) -> str:
    metadata = {
        "workspace": workspace,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "summary_version": 1,
        "tools_launched": tools_launched,
        "files_opened": files_opened,
    }
    frontmatter = yaml.safe_dump(metadata, sort_keys=False).strip()
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
    return f"---\n{frontmatter}\n---\n\n{body}\n"


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
    metadata = {
        "workspace": workspace,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "summary_version": 1,
        "tools_launched": tools_launched,
        "files_opened": files_opened,
    }
    frontmatter = yaml.safe_dump(metadata, sort_keys=False).strip()
    body = [
        "# Session",
        "## Summary\n\n" + (summary.strip() or "Not recorded."),
        "## Completed\n\n" + normalize_bullets(completed),
        "## Open Issues\n\n" + normalize_bullets(open_issues),
    ]
    if evidence.strip():
        body.append("## Evidence\n\n```text\n" + evidence.strip() + "\n```")
    return f"---\n{frontmatter}\n---\n\n" + "\n\n".join(body) + "\n"


def normalize_bullets(text: str) -> str:
    bullets = bullet_items(text)
    return "\n".join(f"- {item}" for item in bullets) if bullets else "- None"


def bullet_items(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        item = line.strip()
        if not item:
            continue
        if item.startswith(("- ", "* ")):
            item = item[2:].strip()
        if item.lower() == "none":
            continue
        items.append(item)
    return items


def merge_items(existing: list[str], incoming: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in existing + incoming:
        normalized = item.strip()
        if not normalized or normalized.lower() == "none":
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
    return merged


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
    frontmatter = yaml.safe_dump(metadata, sort_keys=False).strip()
    summary = f"Workday contains {len(session_files)} recorded session"
    summary += "s" if len(session_files) != 1 else ""
    summary += f". Latest: {summary_line(latest_summary) or 'Not recorded.'}"
    body = [
        f"# Day: {day.isoformat()}",
        "## Summary\n\n" + summary,
        "## Completed\n\n" + ("\n".join(f"- {item}" for item in completed) if completed else "- None"),
        "## Open Issues\n\n" + ("\n".join(f"- {item}" for item in open_issues) if open_issues else "- None"),
        "## Sessions\n\n" + ("\n".join(session_rows) if session_rows else "- None"),
    ]
    return f"---\n{frontmatter}\n---\n\n" + "\n\n".join(body) + "\n"


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
    existing_session_files: list[str] = []
    existing_completed: list[str] = []
    existing_open_issues: list[str] = []
    existing_session_rows: list[str] = []

    if path.exists():
        existing = parse_session_file(path)
        raw_sessions = existing.metadata.get("sessions") or []
        if isinstance(raw_sessions, list):
            existing_session_files = [str(item) for item in raw_sessions]
        sections = parse_markdown_sections(existing.body)
        existing_completed = bullet_items(sections.get("completed", ""))
        existing_open_issues = bullet_items(sections.get("open issues", ""))
        existing_session_rows = [
            line.strip()
            for line in sections.get("sessions", "").splitlines()
            if line.strip() and line.strip().lower() != "- none"
        ]

    session_files = merge_items(existing_session_files, [session_file])
    session_row = f"- {ended_at.strftime('%H:%M')} - {summary_line(summary) or 'Session recorded.'} (`sessions/{session_file}`)"
    session_rows = merge_items(existing_session_rows, [session_row])
    path.write_text(
        render_day_log(
            workspace=workspace,
            day=ended_at.date(),
            session_files=session_files,
            latest_summary=summary,
            completed=merge_items(existing_completed, bullet_items(completed)),
            open_issues=merge_items(existing_open_issues, bullet_items(open_issues)),
            session_rows=session_rows,
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
