from __future__ import annotations

from dataclasses import dataclass


LAST_MARKER = "## LAST.md"
NEXT_MARKER = "## NEXT.md"


@dataclass(frozen=True)
class HandoffDraft:
    last: str
    next: str


def render_combined_draft(draft: HandoffDraft) -> str:
    return f"{LAST_MARKER}\n\n{draft.last.strip()}\n\n{NEXT_MARKER}\n\n{draft.next.strip()}\n"


def parse_combined_draft(text: str) -> HandoffDraft:
    if LAST_MARKER not in text or NEXT_MARKER not in text:
        return HandoffDraft(last=text.strip(), next="")
    _, rest = text.split(LAST_MARKER, 1)
    last, next_text = rest.split(NEXT_MARKER, 1)
    return HandoffDraft(last=last.strip(), next=next_text.strip())


def parse_last_sections(text: str) -> tuple[str, str, str]:
    """Extract (summary, done, open_issues) from a structured LAST.md draft section."""
    lines_by_section: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("### "):
            current = line[4:].strip().lower()
            lines_by_section[current] = []
        elif current is not None:
            lines_by_section[current].append(line)
    summary = done = open_issues = ""
    for key, lines in lines_by_section.items():
        content = "\n".join(lines).strip()
        if "summary" in key:
            summary = content
        elif "completed" in key or "done" in key:
            done = content
        elif "open" in key or "issue" in key:
            open_issues = content
    if not any([summary, done, open_issues]):
        summary = text.strip()
    return summary, done or "- ", open_issues or "- "

