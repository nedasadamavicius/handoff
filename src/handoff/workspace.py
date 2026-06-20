from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from handoff.session import SessionFile, read_handoff


WORKSPACE_TYPES = {"code", "regular"}


@dataclass(frozen=True)
class Workspace:
    name: str
    path: Path
    metadata_path: Path | None = None
    external: bool = False

    @property
    def meta(self) -> Path:
        return self.metadata_path or self.path

    @property
    def workspace_file(self) -> Path:
        return self.meta / "WORKSPACE.md"

    @property
    def next_file(self) -> Path:
        return self.meta / "NEXT.md"

    @property
    def last_file(self) -> Path:
        return self.meta / "LAST.md"

    @property
    def draft_file(self) -> Path:
        return self.meta / "DRAFT.md"

    @property
    def sessions_dir(self) -> Path:
        return self.meta / "sessions"

    @property
    def days_dir(self) -> Path:
        return self.meta / "days"

    @property
    def weeks_dir(self) -> Path:
        return self.meta / "weeks"

    @property
    def worklog_file(self) -> Path:
        return self.meta / "WORKLOG.md"

    def day_file(self, value: date) -> Path:
        return self.days_dir / f"{value.isoformat()}.md"

    def week_file(self, year: int, week: int) -> Path:
        return self.weeks_dir / f"{year}-W{week:02d}.md"

    def last_handoff(self) -> SessionFile | None:
        return read_handoff(self.last_file)


def current_directory_workspace(path: Path) -> Workspace:
    target = path.resolve()
    return Workspace(
        name=target.name or str(target),
        path=target,
        metadata_path=target / ".handoff",
        external=True,
    )


def initialize_directory_workspace(path: Path) -> Workspace:
    target = path.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    workspace = current_directory_workspace(target)
    ensure_workspace_files(workspace, workspace_kind=infer_workspace_type(workspace))
    return workspace


def ensure_workspace_files(workspace: Workspace, workspace_kind: str = "regular") -> None:
    if workspace_kind not in WORKSPACE_TYPES:
        workspace_kind = "regular"
    workspace.meta.mkdir(parents=True, exist_ok=True)
    if not workspace.workspace_file.exists():
        workspace.workspace_file.write_text(render_workspace_file(workspace, workspace_kind), encoding="utf-8")
    elif workspace_type(workspace) is None:
        existing = workspace.workspace_file.read_text(encoding="utf-8")
        workspace.workspace_file.write_text(render_workspace_header(workspace_kind) + existing, encoding="utf-8")
    if not workspace.last_file.exists():
        workspace.last_file.write_text("# Last Session\n\nNo previous session recorded.\n", encoding="utf-8")
    if not workspace.next_file.exists():
        workspace.next_file.write_text("# Next\n\n- Define the next action.\n", encoding="utf-8")


def render_workspace_file(workspace: Workspace, workspace_type: str) -> str:
    description = (
        "Code repository workspace. Handoff templates may include development evidence such as tools launched, "
        "files opened, and git status."
        if workspace_type == "code"
        else "Regular workspace for notes, learning, content, or general files."
    )
    return render_workspace_header(workspace_type) + f"# {workspace.name}\n\n{description}\n"


def render_workspace_header(workspace_type: str) -> str:
    frontmatter = yaml.safe_dump({"workspace_type": workspace_type}, sort_keys=False).strip()
    return (
        f"---\n{frontmatter}\n---\n\n"
        "<!-- handoff uses the workspace_type front matter to choose handoff templates. "
        "Do not remove it unless you intentionally change the workspace type. -->\n\n"
    )


def workspace_type(workspace: Workspace) -> str | None:
    if not workspace.workspace_file.exists():
        return None
    text = workspace.workspace_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    try:
        _, frontmatter, _ = text.split("---\n", 2)
    except ValueError:
        return None
    data = yaml.safe_load(frontmatter) or {}
    value = data.get("workspace_type")
    return value if value in WORKSPACE_TYPES else None


def infer_workspace_type(workspace: Workspace) -> str:
    return "code" if (workspace.path / ".git").is_dir() else "regular"




TOOL_MEMORY_FILES: dict[str, str] = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
    "gemini": "GEMINI.md",
}

_TOOL_MEMORY_TEMPLATE = """\
Read `.handoff/WORKSPACE.md` to understand this workspace - its goals, context, and constraints.

During the session, keep `.handoff/DRAFT.md` current when you make material progress. Treat it as the live handoff ledger, not only an exit note. After meaningful code or content changes, update the draft's LAST.md section with:

- what was done
- files or areas affected
- a brief summary of important `git diff` details, when relevant
- unresolved questions or blockers

The Completed section must describe shipped changes, decisions, fixes, or artifacts created. Do not list agent process steps such as reading, re-reading, inspecting, reviewing, searching, opening files, or running tests. Mention only the concrete outcome those steps produced.

Before handing control back to the user after material work, make sure `.handoff/DRAFT.md` reflects the latest completed work and evidence. Do this even if the user did not say the session is ending.

Do not spend time expanding the NEXT.md section during ordinary progress updates. Fill or revise NEXT.md only when the agent session is ending or when the next action is already clear and durable.

Before ending any session, make sure `.handoff/DRAFT.md` uses this exact format:

Write normal human-readable Markdown. Do not write patch or diff notation in `.handoff/DRAFT.md`; bullets should start with `- `, never `+- ` or `-- `.

## LAST.md

### Summary

One or two sentences describing what was accomplished.

### Completed

- List of completed items.

### Open Issues

- Unresolved questions or blockers (use "- None" if there are none).

## NEXT.md

- Next action items for the following session.
"""


def _memory_filename(tool_name: str, command: str) -> str | None:
    combined = (tool_name + " " + command).lower()
    for key, filename in TOOL_MEMORY_FILES.items():
        if key in combined:
            return filename
    return None


def ensure_tool_files(workspace: Workspace, tools: dict[str, str]) -> None:
    for name, command in tools.items():
        ensure_tool_file(workspace, name, command)


def ensure_tool_file(workspace: Workspace, tool_name: str, command: str) -> None:
    filename = _memory_filename(tool_name, command)
    if filename is None:
        return
    path = workspace.path / filename
    if not path.exists():
        path.write_text(_TOOL_MEMORY_TEMPLATE, encoding="utf-8")


def workspace_files(workspace: Workspace) -> list[Path]:
    ignored = {".git", ".handoff", "__pycache__"}
    files: list[Path] = []
    for path in workspace.path.rglob("*"):
        if any(part in ignored for part in path.parts):
            continue
        if path.is_file():
            files.append(path)
    return sorted(files, key=lambda item: str(item.relative_to(workspace.path)).lower())


def preview_file(path: Path, limit: int = 8000) -> str:
    if not path.exists():
        return "File does not exist."
    if path.stat().st_size > limit:
        return path.read_text(encoding="utf-8", errors="replace")[:limit] + "\n\n[preview truncated]"
    return path.read_text(encoding="utf-8", errors="replace")
