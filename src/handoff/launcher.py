from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from handoff.config import AppConfig


class LaunchError(RuntimeError):
    """Raised when an external editor or tool cannot be launched."""


def format_command(template: str, file: Path | None = None) -> list[str]:
    value = template
    if file is not None:
        value = value.replace("{file}", str(file))
    return shlex.split(value, posix=False)


def editor_command(config: AppConfig, file: Path, editor_name: str | None = None) -> list[str]:
    name = editor_name or config.editor.default
    template = config.editor.options.get(name)
    if template is None:
        raise KeyError(f"Editor is not configured: {name}")
    return format_command(template, file=file)


def tool_command(config: AppConfig, tool_name: str) -> str:
    template = config.tools.get(tool_name)
    if template is None:
        raise KeyError(f"Tool is not configured: {tool_name}")
    return template


def run_command(command: list[str] | str, cwd: Path, *, shell: bool = False) -> int:
    try:
        return subprocess.call(command, cwd=str(cwd), shell=shell)
    except FileNotFoundError as exc:
        executable = command[0] if isinstance(command, list) and command else str(command)
        raise LaunchError(f"Could not find executable: {executable}") from exc
