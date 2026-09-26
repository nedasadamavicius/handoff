from __future__ import annotations

import shlex
import shutil
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


NEXT_AUDIT_PROMPT = (
    "Audit and clean up .handoff/NEXT.md for this repository. "
    "Read .handoff/NEXT.md, then use git history and diffs (git log, git diff, git show, git status) "
    "to judge which entries are obsolete: already shipped or committed, duplicated, or no longer relevant. "
    "Rewrite .handoff/NEXT.md keeping only durable, still-open next actions, in priority order. "
    "Preserve the '# Next' heading and use '- ' bullets; write plain human-readable Markdown, not diff notation. "
    "Remove duplicates, junk lines, and anything the git history shows is already done. "
    "Do not edit any file other than .handoff/NEXT.md, and make no code changes."
)

NEXT_AUDIT_ALLOWED_TOOLS = (
    "Read,Bash(git log:*),Bash(git diff:*),Bash(git status:*),Bash(git show:*),"
    "Edit(.handoff/NEXT.md),Write(.handoff/NEXT.md)"
)


def next_audit_command(config: AppConfig) -> list[str]:
    """Build a headless Sonnet command that audits and rewrites .handoff/NEXT.md."""
    template = config.tools.get("claude")
    if not template:
        raise KeyError("Claude tool is not configured; cannot run the Next audit.")
    parts = format_command(template)
    executable = parts[0] if parts else "claude"
    return [
        executable, "-p", NEXT_AUDIT_PROMPT,
        "--model", "sonnet",
        "--allowedTools", NEXT_AUDIT_ALLOWED_TOOLS,
    ]


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


TERMINAL_EDITORS = frozenset({
    "nvim", "vim", "vi", "hx", "helix", "nano", "micro", "kak", "ne", "joe", "mcedit",
})


def is_terminal_editor(command: list[str]) -> bool:
    """True when the editor runs inside this terminal and the TUI must hand it the screen."""
    if not command:
        return False
    name = Path(command[0]).stem.lower()
    if name in {"emacs", "emacsclient"}:
        return any(arg in {"-nw", "-t", "--tty", "--no-window-system"} for arg in command[1:])
    return name in TERMINAL_EDITORS


def spawn_detached(command: list[str], cwd: Path) -> None:
    """Start a GUI editor without blocking or taking over the terminal."""
    command = [arg for arg in command if arg not in {"--wait", "-w"}]
    executable = shutil.which(command[0]) if command else None
    resolved = [executable, *command[1:]] if executable else command
    kwargs: dict = {
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(resolved, **kwargs)
    except (FileNotFoundError, OSError) as exc:
        raise LaunchError(f"Could not launch editor: {command[0] if command else command}") from exc


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
    resolved_command = command
    if isinstance(command, list) and command:
        executable = shutil.which(command[0])
        if executable is not None:
            resolved_command = [executable, *command[1:]]
    try:
        return subprocess.call(resolved_command, cwd=str(cwd), shell=shell)
    except FileNotFoundError as exc:
        executable = command[0] if isinstance(command, list) and command else str(command)
        raise LaunchError(f"Could not find executable: {executable}") from exc
