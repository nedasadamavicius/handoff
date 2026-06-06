from __future__ import annotations

from dataclasses import dataclass
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

    def last_handoff(self) -> SessionFile | None:
        return read_handoff(self.last_file)


def current_directory_workspace(path: Path) -> Workspace:
    target = path.resolve()
    return Workspace(
        name=target.name or str(target),
        path=target,
        metadata_path=target / ".ws",
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
        "<!-- ws uses the workspace_type front matter to choose handoff templates. "
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




def workspace_files(workspace: Workspace) -> list[Path]:
    ignored = {".git", ".ws", "__pycache__"}
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
