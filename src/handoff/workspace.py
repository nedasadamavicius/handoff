from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from handoff.session import SessionFile, read_handoff


WORKSPACE_TYPES = {"code", "regular"}
WORKSPACE_MODES = {"study", "coding"}


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


def initialize_directory_workspace(path: Path, workspace_mode_value: str | None = "coding") -> Workspace:
    target = path.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    workspace = current_directory_workspace(target)
    ensure_workspace_files(
        workspace, workspace_kind=infer_workspace_type(workspace), workspace_mode=workspace_mode_value
    )
    return workspace


def ensure_workspace_files(
    workspace: Workspace, workspace_kind: str = "regular", workspace_mode: str | None = None
) -> None:
    if workspace_kind not in WORKSPACE_TYPES:
        workspace_kind = "regular"
    workspace.meta.mkdir(parents=True, exist_ok=True)
    if not workspace.workspace_file.exists():
        workspace.workspace_file.write_text(
            render_workspace_file(workspace, workspace_kind, workspace_mode), encoding="utf-8"
        )
    elif workspace_type(workspace) is None:
        existing = workspace.workspace_file.read_text(encoding="utf-8")
        workspace.workspace_file.write_text(render_workspace_header(workspace_kind) + existing, encoding="utf-8")
    if workspace_mode in WORKSPACE_MODES and workspace_mode_fn(workspace) is None:
        set_workspace_mode(workspace, workspace_mode)
    if not workspace.last_file.exists():
        workspace.last_file.write_text("# Last Session\n\nNo previous session recorded.\n", encoding="utf-8")
    if not workspace.next_file.exists():
        workspace.next_file.write_text("# Next\n\n- Define the next action.\n", encoding="utf-8")
    if not workspace.draft_file.exists():
        workspace.draft_file.write_text(
            "## LAST.md\n\n### Summary\n\n### Completed\n\n### Open Issues\n\n## NEXT.md\n\n",
            encoding="utf-8",
        )


def render_workspace_file(workspace: Workspace, workspace_type: str, workspace_mode: str | None = None) -> str:
    description = (
        "Code repository workspace. Handoff templates may include development evidence such as tools launched, "
        "files opened, and git status."
        if workspace_type == "code"
        else "Regular workspace for notes, learning, content, or general files."
    )
    return render_workspace_header(workspace_type, workspace_mode) + f"# {workspace.name}\n\n{description}\n"


def render_workspace_header(workspace_type: str, workspace_mode: str | None = None) -> str:
    data = {"workspace_type": workspace_type}
    if workspace_mode in WORKSPACE_MODES:
        data["workspace_mode"] = workspace_mode
    frontmatter = yaml.safe_dump(data, sort_keys=False).strip()
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


def workspace_mode(workspace: Workspace) -> str | None:
    if not workspace.workspace_file.exists():
        return None
    text = workspace.workspace_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    try:
        _, frontmatter, _ = text.split("---\n", 2)
        value = (yaml.safe_load(frontmatter) or {}).get("workspace_mode")
    except (ValueError, yaml.YAMLError):
        return None
    return value if value in WORKSPACE_MODES else None


# Internal alias keeps the ``workspace_mode`` parameter name readable above.
workspace_mode_fn = workspace_mode


def set_workspace_mode(workspace: Workspace, mode: str) -> None:
    if mode not in WORKSPACE_MODES:
        raise ValueError(f"Unknown workspace mode: {mode}")
    text = workspace.workspace_file.read_text(encoding="utf-8") if workspace.workspace_file.exists() else ""
    if text.startswith("---\n"):
        try:
            _, frontmatter, body = text.split("---\n", 2)
            data = yaml.safe_load(frontmatter) or {}
        except (ValueError, yaml.YAMLError):
            data = {"workspace_type": infer_workspace_type(workspace)}
            body = text
    else:
        data = {"workspace_type": workspace_type(workspace) or infer_workspace_type(workspace)}
        body = text
    data["workspace_mode"] = mode
    workspace.workspace_file.write_text(
        f"---\n{yaml.safe_dump(data, sort_keys=False).strip()}\n---\n\n{body.lstrip()}", encoding="utf-8"
    )


def infer_workspace_type(workspace: Workspace) -> str:
    return "code" if (workspace.path / ".git").is_dir() else "regular"




TOOL_MEMORY_FILES: dict[str, str] = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
    "gemini": "GEMINI.md",
}

_TOOL_MEMORY_TEMPLATE = """\
Read `.handoff/WORKSPACE.md` to understand this workspace - its goals, context, and constraints.

## Git

Use conventional commit messages (`type(scope): description`). Use only ASCII characters in commit messages. Never add a `Co-Authored-By` trailer to commits.

During the session, keep `.handoff/DRAFT.md` current when you make material progress. Treat it as the live handoff ledger, not only an exit note. After meaningful code or content changes, update the draft's LAST.md section with:

- what was done and **why** it was done
- only the files that matter — not a full `git diff` dump, just the relevant changed files and what changed in them
- unresolved questions or blockers

The Completed section must describe shipped changes, decisions, fixes, or artifacts created. Do not list agent process steps such as reading, re-reading, inspecting, reviewing, searching, opening files, or running tests. Mention only the concrete outcome those steps produced.

**Keep it tight.** Each bullet should be one concise line. No walls of text. If a reader wouldn't need a piece of information to pick up where you left off, cut it. Err heavily on the side of brevity — document what's important and why, not every detail.

Before handing control back to the user after material work, make sure `.handoff/DRAFT.md` reflects the latest completed work and evidence. Do this even if the user did not say the session is ending.

Do not spend time expanding the NEXT.md section during ordinary progress updates. Fill or revise NEXT.md only when the agent session is ending or when the next action is already clear and durable. When updating NEXT.md, actively remove any items that have already been completed — do not let stale tasks accumulate.

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
    import shlex
    parts = shlex.split(command, posix=False)
    names = {tool_name.lower()}
    if parts:
        names.add(Path(parts[0].strip('"')).name.lower())
    aliases = {"openai": "codex", "xai": "grok"}
    for name in names:
        key = aliases.get(name, name)
        if key in TOOL_MEMORY_FILES:
            return TOOL_MEMORY_FILES[key]
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


def preview_file(path: Path, limit: int | None = None) -> str:
    if not path.exists():
        return "File does not exist."
    text = path.read_text(encoding="utf-8", errors="replace")
    if limit is not None and len(text) > limit:
        return text[:limit] + "\n\n[preview truncated]"
    return text
