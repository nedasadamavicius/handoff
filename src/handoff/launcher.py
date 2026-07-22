from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from handoff.config import AppConfig


class LaunchError(RuntimeError):
    """Raised when an external editor or tool cannot be launched."""


CODEX_FINALIZE_PROMPT = (
    "Update .handoff/DRAFT.md from the work completed in this Codex session. "
    "Use the required handoff format from AGENTS.md. "
    "Write normal human-readable Markdown, not patch or diff notation; never prefix bullets with '+-' or '--'. "
    "Complete LAST.md with what changed, affected files, relevant git diff details, and open issues. "
    "In Completed, include shipped changes, decisions, fixes, or artifacts created. "
    "Do not list agent process steps like reading, re-reading, inspecting, reviewing, searching, or opening files; mention only the concrete outcome those steps produced. "
    "Keep NEXT.md concise and include only durable next actions. "
    "Do not make unrelated code changes."
)

CLAUDE_FINALIZE_PROMPT = (
    "Update .handoff/DRAFT.md from the work completed in this Claude session. "
    "Use the required handoff format from CLAUDE.md. "
    "Write normal human-readable Markdown, not patch or diff notation; never prefix bullets with '+-' or '--'. "
    "Complete LAST.md with what changed, affected files, relevant git diff details, and open issues. "
    "In Completed, include shipped changes, decisions, fixes, or artifacts created. "
    "Do not list agent process steps like reading, re-reading, inspecting, reviewing, searching, or opening files; mention only the concrete outcome those steps produced. "
    "Keep NEXT.md concise and include only durable next actions. "
    "Do not make unrelated code changes."
)


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


def codex_finalize_command(tool_name: str, command: str) -> str | None:
    combined = (tool_name + " " + command).lower()
    if "codex" not in combined:
        return None
    parts = format_command(command)
    if not parts:
        return None
    executable = parts[0]
    if "codex" not in Path(executable).name.lower():
        return None
    return subprocess.list2cmdline([executable, "exec", "resume", "--last", CODEX_FINALIZE_PROMPT])


def claude_finalize_command(tool_name: str, command: str) -> str | None:
    combined = (tool_name + " " + command).lower()
    if "claude" not in combined:
        return None
    parts = format_command(command)
    if not parts:
        return None
    executable = parts[0]
    if "claude" not in Path(executable).name.lower():
        return None
    return subprocess.list2cmdline([
        executable, "--continue", "-p", CLAUDE_FINALIZE_PROMPT,
        "--allowedTools", "Write(.handoff/*),Edit(.handoff/*)",
    ])


def run_command(command: list[str] | str, cwd: Path, *, shell: bool = False) -> int:
    try:
        return subprocess.call(command, cwd=str(cwd), shell=shell)
    except FileNotFoundError as exc:
        executable = command[0] if isinstance(command, list) and command else str(command)
        raise LaunchError(f"Could not find executable: {executable}") from exc
