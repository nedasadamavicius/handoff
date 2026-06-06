from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml


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
