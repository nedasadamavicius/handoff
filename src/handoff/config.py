from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_ROOT = Path.home() / ".handoff"
REMOVED_DEFAULT_TOOLS = {"gemini"}


@dataclass(frozen=True)
class EditorConfig:
    default: str = "code"
    options: dict[str, str] = field(
        default_factory=lambda: {
            "nvim": "nvim {file}",
            "helix": "hx {file}",
            "vim": "vim {file}",
            "code": "code --wait {file}",
        }
    )


@dataclass(frozen=True)
class AppConfig:
    root: Path = DEFAULT_ROOT
    editor: EditorConfig = field(default_factory=EditorConfig)
    tools: dict[str, str] = field(default_factory=lambda: {"codex": "codex", "claude": "claude"})
    ai_command: str | None = None
    theme: str = "graphite-crimson"

    @property
    def workspaces_dir(self) -> Path:
        return self.root / "workspaces"

    @property
    def themes_dir(self) -> Path:
        return self.root / "themes"


def config_path(root: Path = DEFAULT_ROOT) -> Path:
    return root / "config.yaml"


def default_config_data(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    editor = EditorConfig()
    return {
        "root": str(root),
        "editor": {
            "default": editor.default,
            "options": editor.options,
        },
        "tools": {"codex": "codex", "claude": "claude"},
        "ai_command": None,
        "theme": "graphite-crimson",
    }


def ensure_config(root: Path = DEFAULT_ROOT) -> AppConfig:
    root.mkdir(parents=True, exist_ok=True)
    (root / "workspaces").mkdir(parents=True, exist_ok=True)
    path = config_path(root)
    if not path.exists():
        path.write_text(yaml.safe_dump(default_config_data(root), sort_keys=False), encoding="utf-8")
    return load_config(root)


def load_config(root: Path = DEFAULT_ROOT) -> AppConfig:
    path = config_path(root)
    if not path.exists():
        return AppConfig(root=root)

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    configured_root = Path(raw.get("root") or root).expanduser()
    editor_raw = raw.get("editor") or {}
    editor = EditorConfig(
        default=editor_raw.get("default") or "nvim",
        options=dict(editor_raw.get("options") or EditorConfig().options),
    )
    tools = {
        name: command
        for name, command in dict(raw.get("tools") or AppConfig().tools).items()
        if name.lower() not in REMOVED_DEFAULT_TOOLS
    }
    return AppConfig(
        root=configured_root,
        editor=editor,
        tools=tools,
        ai_command=raw.get("ai_command"),
        theme=raw.get("theme") or "graphite-crimson",
    )
