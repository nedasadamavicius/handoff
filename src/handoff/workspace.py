from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from handoff.documents import render_frontmatter, split_frontmatter
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
    ensure_workspace_files(workspace, workspace_kind=infer_workspace_type(workspace), initial_mode=workspace_mode_value)
    return workspace


def ensure_workspace_files(
    workspace: Workspace, workspace_kind: str = "regular", initial_mode: str | None = None
) -> None:
    if workspace_kind not in WORKSPACE_TYPES:
        workspace_kind = "regular"
    workspace.meta.mkdir(parents=True, exist_ok=True)
    if not workspace.workspace_file.exists():
        workspace.workspace_file.write_text(
            render_workspace_file(workspace, workspace_kind, initial_mode), encoding="utf-8"
        )
    elif workspace_type(workspace) is None:
        existing = workspace.workspace_file.read_text(encoding="utf-8")
        workspace.workspace_file.write_text(render_workspace_header(workspace_kind) + existing, encoding="utf-8")
    if initial_mode in WORKSPACE_MODES and workspace_mode(workspace) is None:
        set_workspace_mode(workspace, initial_mode)
    if not workspace.last_file.exists():
        workspace.last_file.write_text("# Last Session\n\nNo previous session recorded.\n", encoding="utf-8")
    if not workspace.next_file.exists():
        workspace.next_file.write_text("# Next\n\n- Define the next action.\n", encoding="utf-8")
    if not workspace.draft_file.exists():
        workspace.draft_file.write_text(
            "## LAST.md\n\n### Summary\n\n### Completed\n\n### Open Issues\n\n## NEXT.md\n\n",
            encoding="utf-8",
        )


def render_workspace_file(workspace: Workspace, kind: str, mode: str | None = None) -> str:
    description = (
        "Code repository workspace. Handoff templates may include development evidence such as tools launched, "
        "files opened, and git status."
        if kind == "code"
        else "Regular workspace for notes, learning, content, or general files."
    )
    return render_workspace_header(kind, mode) + f"# {workspace.name}\n\n{description}\n"


def render_workspace_header(kind: str, mode: str | None = None) -> str:
    metadata = {"workspace_type": kind}
    if mode in WORKSPACE_MODES:
        metadata["workspace_mode"] = mode
    return (
        render_frontmatter(metadata) + "<!-- handoff uses the workspace_type front matter to choose handoff templates. "
        "Do not remove it unless you intentionally change the workspace type. -->\n\n"
    )


def workspace_frontmatter(workspace: Workspace) -> dict:
    if not workspace.workspace_file.exists():
        return {}
    return split_frontmatter(workspace.workspace_file.read_text(encoding="utf-8"))[0]


def workspace_type(workspace: Workspace) -> str | None:
    value = workspace_frontmatter(workspace).get("workspace_type")
    return value if value in WORKSPACE_TYPES else None


def workspace_mode(workspace: Workspace) -> str | None:
    value = workspace_frontmatter(workspace).get("workspace_mode")
    return value if value in WORKSPACE_MODES else None


def set_workspace_mode(workspace: Workspace, mode: str) -> None:
    if mode not in WORKSPACE_MODES:
        raise ValueError(f"Unknown workspace mode: {mode}")
    existing_text = workspace.workspace_file.read_text(encoding="utf-8") if workspace.workspace_file.exists() else ""
    metadata, body = split_frontmatter(existing_text)
    if not metadata:
        metadata = {"workspace_type": workspace_type(workspace) or infer_workspace_type(workspace)}
    metadata["workspace_mode"] = mode
    workspace.workspace_file.write_text(render_frontmatter(metadata) + body.lstrip(), encoding="utf-8")


def infer_workspace_type(workspace: Workspace) -> str:
    return "code" if (workspace.path / ".git").is_dir() else "regular"


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
