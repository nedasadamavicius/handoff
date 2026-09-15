from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path


class AgentUnavailable(RuntimeError):
    """A configured provider cannot be started."""


@dataclass(frozen=True)
class AgentAdapter:
    key: str
    memory_file: str

    def matches(self, tool_name: str, command: str) -> bool:
        parts = shlex.split(command, posix=False)
        if not parts:
            return False
        names = {_executable_name(parts[0]), tool_name.lower()}
        return any(self._aliases(n) for n in names)

    def _aliases(self, name: str) -> bool:
        return name == self.key

    def spawn_command(self, executable: str) -> list[str]:
        return [executable]


class _Grok(AgentAdapter):
    def _aliases(self, name: str) -> bool:
        return name in {"grok", "xai"}

    def spawn_command(self, executable: str) -> list[str]:
        return [executable, "agent", "stdio"]


class _Codex(AgentAdapter):
    def _aliases(self, name: str) -> bool:
        return name in {"codex", "codex-acp"}

    def spawn_command(self, executable: str) -> list[str]:
        return [executable]


class _Claude(AgentAdapter):
    def _aliases(self, name: str) -> bool:
        return name in {"claude", "claude-agent-acp", "claude-code-acp"}


ADAPTERS = (_Grok("grok", "AGENTS.md"), _Codex("codex", "AGENTS.md"), _Claude("claude", "CLAUDE.md"))


def get_adapter(name: str, command: str) -> AgentAdapter | None:
    for adapter in ADAPTERS:
        if adapter.matches(name, command):
            return adapter
    return None


@dataclass(frozen=True)
class AgentLaunch:
    adapter: AgentAdapter
    command: list[str]
    backend: str


def _available(name: str) -> str | None:
    return shutil.which(name)


def _executable_name(value: str) -> str:
    name = Path(value.strip('"')).name.lower()
    return name.removesuffix(".exe").removesuffix(".cmd").removesuffix(".bat")


def _resolve_executable(value: str) -> str | None:
    path = Path(value)
    if path.exists():
        return str(path)
    return _available(value)


def resolve_agent(name: str, command: str) -> AgentLaunch:
    adapter = get_adapter(name, command)
    if adapter is None:
        raise AgentUnavailable(f"Unsupported agent command for {name!r}: {command!r}")
    parts = shlex.split(command, posix=False)
    executable = parts[0].strip('"') if parts else ""
    executable_name = _executable_name(executable) if executable else ""
    if adapter.key == "codex" and executable_name == "codex":
        if len(parts) > 1:
            raise AgentUnavailable("Codex native CLI flags cannot be forwarded to codex-acp; configure codex-acp directly.")
        found = _available("codex-acp")
        if found:
            return AgentLaunch(adapter, [found], "acp")
        npx = _available("npx")
        if npx:
            return AgentLaunch(adapter, [npx, "-y", "@agentclientprotocol/codex-acp"], "acp")
        raise AgentUnavailable("Codex ACP is unavailable; install codex-acp or Node.js (npx), then log in.")
    if adapter.key == "codex":
        found = _resolve_executable(executable)
        if not found:
            raise AgentUnavailable(f"Codex ACP adapter is unavailable: {executable!r}; install it and log in.")
        return AgentLaunch(adapter, [found, *parts[1:]], "acp")
    if adapter.key == "claude":
        if executable_name in {"claude-agent-acp", "claude-code-acp"}:
            found = _resolve_executable(executable)
            if not found:
                raise AgentUnavailable(f"Claude ACP adapter is unavailable: {executable!r}; install it and log in.")
            return AgentLaunch(adapter, [found, *parts[1:]], "acp")
        if len(parts) > 1:
            raise AgentUnavailable("Claude native TUI flags cannot be forwarded to the headless stream backend; configure an ACP adapter directly.")
        for candidate in ("claude-agent-acp", "claude-code-acp"):
            found = _available(candidate)
            if found:
                return AgentLaunch(adapter, [found], "acp")
        found = _resolve_executable(executable)
        if not found:
            raise AgentUnavailable("Claude Code is unavailable; install claude or a Claude ACP adapter, then log in.")
        return AgentLaunch(adapter, [found, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages"], "claude-stream")
    if not executable or (Path(executable).name != executable and not Path(executable).exists()):
        raise AgentUnavailable(f"Grok executable is unavailable: {executable!r}; install it and log in.")
    if not Path(executable).exists() and not _available(executable):
        raise AgentUnavailable(f"Grok executable is unavailable: {executable!r}; install it and log in.")
    found = _resolve_executable(executable)
    if not found:
        raise AgentUnavailable(f"Grok executable is unavailable: {executable!r}; install it and log in.")
    if parts[1:3] == ["agent", "stdio"]:
        command_parts = [found, *parts[1:]]
    elif len(parts) == 1:
        command_parts = adapter.spawn_command(found)
    else:
        raise AgentUnavailable("Grok native CLI flags cannot be used for an ACP tab; configure 'grok agent stdio' instead.")
    return AgentLaunch(adapter, command_parts, "acp")
