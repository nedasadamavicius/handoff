from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from handoff.documents import merge_next_text
from handoff.handoff import (
    HandoffDraft,
    draft_has_content,
    parse_draft_or_files,
    parse_last_sections,
)
from handoff.workspace import Workspace


@dataclass
class AgentRun:
    name: str
    command: str
    started_at: datetime
    ended_at: datetime | None = None
    status: str = "ok"
    prompt_count: int = 0
    draft_snapshot: Path | None = None


class RunLedger:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.runs: list[AgentRun] = []
        self._pending: list[Path] = []

    def begin(self, name: str, command: str) -> AgentRun:
        run = AgentRun(name=name, command=command, started_at=datetime.now().astimezone())
        self.runs.append(run)
        return run

    @staticmethod
    def _safe_name(value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
        return safe or "agent"

    def snapshot(self, run: AgentRun) -> Path | None:
        draft = self.workspace.draft_file
        if not draft.exists():
            return None
        directory = self.workspace.meta / "runs"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        stem = f"{stamp}-{self._safe_name(run.name)}"
        path = directory / f"{stem}.md"
        counter = 2
        while path.exists():
            path = directory / f"{stem}-{counter}.md"
            counter += 1
        path.write_text(draft.read_text(encoding="utf-8"), encoding="utf-8")
        run.draft_snapshot = path
        self._pending.append(path)
        return path

    def finish(self, run: AgentRun, status: str) -> AgentRun:
        if status not in {"ok", "error", "cancelled"}:
            raise ValueError("status must be ok, error, or cancelled")
        run.status = status
        run.ended_at = datetime.now().astimezone()
        self.snapshot(run)
        return run

    @staticmethod
    def _unique_lines(texts: list[str], *, placeholder: str = "- ") -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for text in texts:
            for line in text.splitlines():
                value = line.strip()
                if not value or value in {"-", "- None", "None"}:
                    continue
                if not value.startswith(("- ", "* ")):
                    value = f"- {value}"
                key = value[2:].strip().casefold()
                if key and key not in seen:
                    seen.add(key)
                    result.append(value)
        return result

    def merged_draft(self, next_text: str) -> HandoffDraft:
        drafts: list[HandoffDraft] = []
        for path in self._pending:
            if path.exists():
                drafts.append(parse_draft_or_files(path.read_text(encoding="utf-8")))
        current = self.workspace.draft_file.read_text(encoding="utf-8") if self.workspace.draft_file.exists() else ""
        current_next = self.workspace.next_file.read_text(encoding="utf-8") if self.workspace.next_file.exists() else ""
        if not drafts and not current.strip():
            return HandoffDraft(last="", next=merge_next_text(current_next, next_text))
        drafts.append(parse_draft_or_files(current, current_next))
        summaries: list[str] = []
        completed: list[str] = []
        issues: list[str] = []
        merged_next = ""
        for draft in drafts:
            summary, done, opened = parse_last_sections(draft.last)
            if summary.strip() and summary.strip() not in summaries:
                summaries.append(summary.strip())
            completed.extend([done])
            issues.extend([opened])
            merged_next = merge_next_text(merged_next, draft.next)
        merged_next = merge_next_text(merged_next, next_text)
        last = "\n\n".join([
            "### Summary\n\n" + ("\n\n".join(summaries) or "Not recorded."),
            "### Completed\n\n" + ("\n".join(self._unique_lines(completed)) or "- None"),
            "### Open Issues\n\n" + ("\n".join(self._unique_lines(issues)) or "- None"),
        ])
        return HandoffDraft(last=last, next=merged_next or "- None")

    def consume(self) -> None:
        self._pending.clear()

    @property
    def tools_launched(self) -> list[str]:
        return [run.name for run in self.runs]

    @property
    def has_pending(self) -> bool:
        for path in self._pending:
            if path.exists() and draft_has_content(path.read_text(encoding="utf-8")):
                return True
        return False
