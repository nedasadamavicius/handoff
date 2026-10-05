from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from handoff.documents import parse_body_sections, render_bullets, render_frontmatter
from handoff.session import bullet_items, merge_items, normalize_bullets, parse_session_file

MONTH_ABBREVIATIONS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
ISO_WEEK_ONE_ANCHOR_DAY = 4

WeekKey = tuple[int, int]


def week_key(day: date) -> WeekKey:
    iso_year, iso_week, _ = day.isocalendar()
    return iso_year, iso_week


def week_filename(year: int, week: int) -> str:
    return f"{year}-W{week:02d}.md"


def week_start(year: int, week: int) -> date:
    anchor_day = date(year, 1, ISO_WEEK_ONE_ANCHOR_DAY)
    first_monday = anchor_day - timedelta(days=anchor_day.isoweekday() - 1)
    return first_monday + timedelta(weeks=week - 1)


def week_date_range(year: int, week: int) -> str:
    first_day = week_start(year, week)
    last_day = first_day + timedelta(days=6)
    first_label = f"{MONTH_ABBREVIATIONS[first_day.month - 1]} {first_day.day}"
    if first_day.month == last_day.month:
        return f"{first_label}–{last_day.day}, {last_day.year}"
    return f"{first_label}–{MONTH_ABBREVIATIONS[last_day.month - 1]} {last_day.day}, {last_day.year}"


def week_label(year: int, week: int) -> str:
    return f"{year}-W{week:02d} · {week_date_range(year, week)}"


def pluralize(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


@dataclass(frozen=True)
class WeekData:
    year: int
    week: int
    days: list[date]
    completed: list[str]
    open_issues: list[str]
    session_count: int


def day_logs(days_dir: Path) -> list[tuple[date, Path]]:
    """Day log files named ``YYYY-MM-DD.md``, oldest first; other files are ignored."""
    entries: list[tuple[date, Path]] = []
    if not days_dir.exists():
        return entries
    for path in sorted(days_dir.glob("*.md")):
        try:
            entries.append((date.fromisoformat(path.stem), path))
        except ValueError:
            continue
    return entries


def collect_week_data(days_dir: Path, year: int, week: int) -> WeekData:
    days: list[date] = []
    completed: list[str] = []
    open_issues: list[str] = []
    session_count = 0

    for day, path in day_logs(days_dir):
        if week_key(day) != (year, week):
            continue
        days.append(day)
        day_log = parse_session_file(path)
        sections = parse_body_sections(day_log.body)
        completed = merge_items(completed, bullet_items(sections.get("completed", "")))
        open_issues = merge_items(open_issues, bullet_items(sections.get("open issues", "")))
        sessions = day_log.metadata.get("sessions") or []
        session_count += len(sessions) if isinstance(sessions, list) else 1

    return WeekData(
        year=year,
        week=week,
        days=days,
        completed=completed,
        open_issues=open_issues,
        session_count=session_count,
    )


def render_week_draft(workspace_name: str, data: WeekData) -> str:
    metadata = {
        "workspace": workspace_name,
        "week": f"{data.year}-W{data.week:02d}",
        "days": [day.isoformat() for day in data.days],
        "session_count": data.session_count,
        "status": "draft",
    }
    summary = f"Week contained {pluralize(data.session_count, 'session')} across {pluralize(len(data.days), 'day')}."
    body = "\n\n".join(
        [
            f"# Week {week_label(data.year, data.week)}",
            f"## Summary\n\n{summary}",
            f"## Highlights\n\n{render_bullets(data.completed)}",
            f"## Carry-forwards\n\n{render_bullets(data.open_issues)}",
        ]
    )
    return f"{render_frontmatter(metadata)}{body}\n"


def find_pending_weeks(days_dir: Path, weeks_dir: Path) -> list[WeekKey]:
    """ISO (year, week) pairs that have day logs but no finalized week file, oldest first."""
    current_week = week_key(date.today())
    past_weeks = {week_key(day) for day, _ in day_logs(days_dir) if week_key(day) < current_week}
    return [
        week
        for week in sorted(past_weeks)
        if not (weeks_dir / week_filename(*week)).exists() or is_draft(weeks_dir / week_filename(*week))
    ]


def is_draft(path: Path) -> bool:
    return parse_session_file(path).metadata.get("status") != "finalized"


def auto_generate_draft(workspace_name: str, days_dir: Path, weeks_dir: Path, year: int, week: int) -> Path:
    weeks_dir.mkdir(parents=True, exist_ok=True)
    data = collect_week_data(days_dir, year, week)
    path = weeks_dir / week_filename(year, week)
    path.write_text(render_week_draft(workspace_name, data), encoding="utf-8")
    return path


def read_week_draft(weeks_dir: Path, year: int, week: int) -> tuple[str, str, str] | None:
    """(summary, highlights, carry_forwards) from a draft week file, or None."""
    path = weeks_dir / week_filename(year, week)
    if not path.exists():
        return None
    sections = parse_body_sections(parse_session_file(path).body)
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
    """Prepend a finalized week entry to WORKLOG.md, newest first."""
    entry = "\n".join(
        [
            f"## {week_label(year, week)}",
            "",
            "### Summary",
            "",
            summary.strip() or "Not recorded.",
            "",
            "### Highlights",
            "",
            normalize_bullets(highlights),
            "",
            "### Carry-forwards",
            "",
            normalize_bullets(carry_forwards),
        ]
    )
    worklog_path.write_text(prepend_worklog_entry(worklog_path, entry), encoding="utf-8")


def prepend_worklog_entry(worklog_path: Path, entry: str) -> str:
    if not worklog_path.exists():
        return f"# Work Log\n\n{entry}\n"
    existing = worklog_path.read_text(encoding="utf-8")
    if existing.lstrip().startswith("# Work Log"):
        title, _, previous_entries = existing.partition("\n")
        return f"{title}\n\n{entry}\n\n---\n\n{previous_entries.lstrip()}".rstrip() + "\n"
    return f"# Work Log\n\n{entry}\n\n---\n\n{existing}".rstrip() + "\n"


def finalize_week_draft(weeks_dir: Path, year: int, week: int) -> None:
    path = weeks_dir / week_filename(year, week)
    if not path.exists():
        return
    path.write_text(path.read_text(encoding="utf-8").replace("status: draft", "status: finalized", 1), encoding="utf-8")
