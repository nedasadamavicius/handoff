from __future__ import annotations

from datetime import datetime
from pathlib import Path

from handoff.session import parse_session_file
from handoff.workflows import save_workspace_handoff
from handoff.workspace import current_directory_workspace


def test_save_workspace_handoff_persists_history_and_avoids_collisions(tmp_path: Path) -> None:
    workspace = current_directory_workspace(tmp_path)
    workspace.meta.mkdir(parents=True)
    workspace.draft_file.write_text("Draft content", encoding="utf-8")
    started_at = datetime.fromisoformat("2026-07-16T10:00:00+02:00")
    ended_at = datetime.fromisoformat("2026-07-16T11:00:00+02:00")
    fields = {
        "summary": "Refactored the save workflow.",
        "done": "- Extracted persistence from the UI.",
        "open": "- None",
        "next": "- Continue with the audit.",
        "evidence": "M src/handoff/tui.py",
    }

    first_session = save_workspace_handoff(
        workspace=workspace,
        started_at=started_at,
        ended_at=ended_at,
        files_opened=["src/handoff/tui.py"],
        tools_launched=["codex"],
        fields=fields,
    )
    second_session = save_workspace_handoff(
        workspace=workspace,
        started_at=started_at,
        ended_at=ended_at,
        files_opened=["src/handoff/tui.py"],
        tools_launched=["codex"],
        fields=fields,
    )

    assert first_session.name == "2026-07-16-110000.md"
    assert second_session.name == "2026-07-16-110000-2.md"
    assert "Refactored the save workflow." in workspace.last_file.read_text(encoding="utf-8")
    assert "Continue with the audit." in workspace.next_file.read_text(encoding="utf-8")
    assert not workspace.draft_file.exists()

    session = parse_session_file(first_session)
    assert session.metadata["files_opened"] == ["src/handoff/tui.py"]
    assert session.metadata["tools_launched"] == ["codex"]
    assert "M src/handoff/tui.py" in session.body

    day = parse_session_file(workspace.day_file(ended_at.date()))
    assert day.metadata["sessions"] == [first_session.name, second_session.name]
