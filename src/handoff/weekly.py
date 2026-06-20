from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

from handoff.session import SessionFile, bullet_items, merge_items, parse_session_file


_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def week_key(d: date) -> tuple[int, int]:
    cal = d.isocalendar()
    return cal[0], cal[1]


def week_filename(year: int, week: int) -> str:
    return f"{year}-W{week:02d}.md"


def _week_start(year: int, week: int) -> date:
    # ISO week 1 contains Jan 4; week starts on Monday
    jan4 = date(year, 1, 4)
    week1_monday = jan4 - timedelta(days=jan4.isoweekday() - 1)
    return week1_monday + timedelta(weeks=week - 1)


def week_date_range(year: int, week: int) -> str:
    start = _week_start(year, week)
    end = start + timedelta(days=6)
    s = f"{_MONTHS[start.month - 1]} {start.day}"
    if start.month == end.month:
        return f"{s}–{end.day}, {end.year}"
    return f"{s}–{_MONTHS[end.month - 1]} {end.day}, {end.year}"


def week_label(year: int, week: int) -> str:
    return f"{year}-W{week:02d} · {week_date_range(year, week)}"


@dataclass(frozen=True)
class WeekData:
    year: int
    week: int
    days: list[date]
    completed: list[str]
    open_issues: list[str]
    session_count: int


def _parse_sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("## ") or line.startswith("### "):
            current = line.lstrip("#").strip().lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def collect_week_data(days_dir: Path, year: int, week: int) -> WeekData:
    days: list[date] = []
    completed: list[str] = []
    open_issues: list[str] = []
    session_count = 0

    if not days_dir.exists():
        return WeekData(year=year, week=week, days=[], completed=[], open_issues=[], session_count=0)

    for path in sorted(days_dir.glob("*.md")):
        try:
            d = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if week_key(d) != (year, week):
            continue
        days.append(d)
        sf = parse_session_file(path)
        body_no_h1 = "\n".join(l for l in sf.body.splitlines() if not l.startswith("# "))
        sections = _parse_sections(body_no_h1)
        completed = merge_items(completed, bullet_items(sections.get("completed", "")))
        open_issues = merge_items(open_issues, bullet_items(sections.get("open issues", "")))
        raw_sessions = sf.metadata.get("sessions") or []
        session_count += len(raw_sessions) if isinstance(raw_sessions, list) else 1

    return WeekData(
        year=year,
        week=week,
        days=sorted(days),
        completed=completed,
        open_issues=open_issues,
        session_count=session_count,
    )


def render_week_draft(workspace_name: str, data: WeekData) -> str:
    label = week_label(data.year, data.week)
    day_count = len(data.days)
    metadata = {
        "workspace": workspace_name,
        "week": f"{data.year}-W{data.week:02d}",
        "days": [d.isoformat() for d in data.days],
        "session_count": data.session_count,
        "status": "draft",
    }
    frontmatter = yaml.safe_dump(metadata, sort_keys=False).strip()
    summary = (
        f"Week contained {data.session_count} session"
        + ("s" if data.session_count != 1 else "")
        + f" across {day_count} day"
        + ("s" if day_count != 1 else "")
        + "."
    )
    completed_text = _normalize_bullets_list(data.completed)
    open_text = _normalize_bullets_list(data.open_issues)
    body = "\n\n".join([
        f"# Week {label}",
        f"## Summary\n\n{summary}",
        f"## Highlights\n\n{completed_text}",
        f"## Carry-forwards\n\n{open_text}",
    ])
    return f"---\n{frontmatter}\n---\n\n{body}\n"


def find_pending_weeks(days_dir: Path, weeks_dir: Path) -> list[tuple[int, int]]:
    """Return ISO (year, week) tuples that have day logs but no finalized week file, oldest first."""
    if not days_dir.exists():
        return []

    current_week = week_key(date.today())
    found: set[tuple[int, int]] = set()

    for path in days_dir.glob("*.md"):
        try:
            d = date.fromisoformat(path.stem)
        except ValueError:
            continue
        wk = week_key(d)
        if wk >= current_week:
            continue
        found.add(wk)

    pending = []
    for wk in sorted(found):
        week_path = weeks_dir / week_filename(*wk)
        if not week_path.exists() or _is_draft(week_path):
            pending.append(wk)

    return pending


def _is_draft(path: Path) -> bool:
    sf = parse_session_file(path)
    return sf.metadata.get("status") != "finalized"


def auto_generate_draft(workspace_name: str, days_dir: Path, weeks_dir: Path, year: int, week: int) -> Path:
    weeks_dir.mkdir(parents=True, exist_ok=True)
    data = collect_week_data(days_dir, year, week)
    content = render_week_draft(workspace_name, data)
    path = weeks_dir / week_filename(year, week)
    path.write_text(content, encoding="utf-8")
    return path


def read_week_draft(weeks_dir: Path, year: int, week: int) -> tuple[str, str, str] | None:
    """Return (summary, highlights, carry_forwards) from a draft week file, or None."""
    path = weeks_dir / week_filename(year, week)
    if not path.exists():
        return None
    sf = parse_session_file(path)
    body_no_h1 = "\n".join(l for l in sf.body.splitlines() if not l.startswith("# "))
    sections = _parse_sections(body_no_h1)
    return (
        sections.get("summary", ""),
        sections.get("highlights", ""),
        sections.get("carry-forwards", sections.get("carry forwards", "")),
    )


def append_week_to_worklog(
    worklog_path: Path,
    year: int,
    week: int,
    summary: str,
    highlights: str,
    carry_forwards: str,
) -> None:
    """Prepend a finalized week entry to WORKLOG.md (reverse chronological)."""
    label = week_label(year, week)
    entry_lines = [
        f"## {label}",
        "",
        "### Summary",
        "",
        summary.strip() or "Not recorded.",
        "",
        "### Highlights",
        "",
        _normalize_bullets(highlights),
        "",
        "### Carry-forwards",
        "",
        _normalize_bullets(carry_forwards),
    ]
    entry = "\n".join(entry_lines)

    if worklog_path.exists():
        existing = worklog_path.read_text(encoding="utf-8")
        if existing.lstrip().startswith("# Work Log"):
            header, _, rest = existing.partition("\n")
            new_content = f"{header}\n\n{entry}\n\n---\n\n{rest.lstrip()}".rstrip() + "\n"
        else:
            new_content = f"# Work Log\n\n{entry}\n\n---\n\n{existing}".rstrip() + "\n"
    else:
        new_content = f"# Work Log\n\n{entry}\n"

    worklog_path.write_text(new_content, encoding="utf-8")


def finalize_week_draft(weeks_dir: Path, year: int, week: int) -> None:
    path = weeks_dir / week_filename(year, week)
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    text = text.replace("status: draft", "status: finalized", 1)
    path.write_text(text, encoding="utf-8")


def _normalize_bullets(text: str) -> str:
    items = bullet_items(text)
    return "\n".join(f"- {item}" for item in items) if items else "- None"


def _normalize_bullets_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- None"
