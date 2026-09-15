from pathlib import Path

from handoff.agent_runs import RunLedger
from handoff.workspace import Workspace


def workspace(tmp_path: Path) -> Workspace:
    return Workspace("test", tmp_path, tmp_path)


def draft(summary: str, completed: str, issues: str, next_text: str) -> str:
    return (
        "## LAST.md\n\n"
        f"### Summary\n\n{summary}\n\n"
        f"### Completed\n\n{completed}\n\n"
        f"### Open Issues\n\n{issues}\n\n"
        f"## NEXT.md\n\n{next_text}\n"
    )


def test_snapshots_are_pending_and_collision_free(tmp_path: Path, monkeypatch) -> None:
    ws = workspace(tmp_path)
    ws.draft_file.write_text("draft", encoding="utf-8")
    ledger = RunLedger(ws)
    run = ledger.begin("Agent/One", "codex")
    monkeypatch.setattr("handoff.agent_runs.datetime", type("Clock", (), {
        "now": staticmethod(lambda: __import__("datetime").datetime(2026, 1, 2, 3, 4, 5, 6)),
    }))
    first = ledger.snapshot(run)
    second = ledger.snapshot(run)
    assert first is not None and second is not None and first != second
    assert "Agent-One" in first.name
    assert first.read_text(encoding="utf-8") == "draft"
    assert ledger.has_pending


def test_merge_deduplicates_and_preserves_next(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    ws.draft_file.write_text(draft("B", "- Shared\n- Two", "- None", "- Shared next"), encoding="utf-8")
    ledger = RunLedger(ws)
    first = ledger.begin("a", "cmd")
    ledger.snapshot(first)
    ws.draft_file.write_text(draft("B", "- Shared\n- Three", "- Blocked", "- Shared next"), encoding="utf-8")
    merged = ledger.merged_draft("- Added next")
    assert sum(line == "- Shared" for line in merged.last.splitlines()) == 1
    assert "- Two" in merged.last and "- Three" in merged.last
    assert "- None" not in merged.last
    assert "- Blocked" in merged.last
    assert sum(line == "- Shared next" for line in merged.next.splitlines()) == 1
    assert "- Added next" in merged.next


def test_absent_draft_is_safe_and_consume_stops_replay(tmp_path: Path) -> None:
    ledger = RunLedger(workspace(tmp_path))
    run = ledger.begin("a", "cmd")
    assert ledger.snapshot(run) is None
    assert ledger.merged_draft("").last == ""
    assert not ledger.has_pending

    ledger.workspace.draft_file.write_text(draft("A", "- Done", "- None", "- Later"), encoding="utf-8")
    ledger.snapshot(run)
    assert ledger.has_pending
    ledger.consume()
    assert not ledger.has_pending
    assert "- Done" in ledger.merged_draft("").last


def test_finish_records_status_and_time(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    ws.draft_file.write_text("draft", encoding="utf-8")
    ledger = RunLedger(ws)
    run = ledger.begin("agent", "command")
    finished = ledger.finish(run, "error")
    assert finished.status == "error"
    assert finished.ended_at is not None
    assert finished.draft_snapshot is not None
    assert ledger.tools_launched == ["agent"]
