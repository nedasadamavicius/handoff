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

