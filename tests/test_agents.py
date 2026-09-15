from pathlib import Path

from handoff.agents import AgentUnavailable, get_adapter, resolve_agent


def test_adapter_aliases_and_memory_files():
    assert get_adapter("grok", "grok").memory_file == "AGENTS.md"
    assert get_adapter("claude", "claude").memory_file == "CLAUDE.md"
    assert get_adapter("codex", r"C:\bin\codex.exe") is not None


def test_unsupported_command_is_actionable():
    try:
        resolve_agent("custom", "unknown-agent")
    except AgentUnavailable as exc:
        assert "Unsupported" in str(exc)
    else:
        raise AssertionError("expected AgentUnavailable")


def test_claude_stream_fallback(monkeypatch):
    monkeypatch.setattr("handoff.agents._available", lambda name: "C:/bin/claude.exe" if name == "claude" else None)
    launch = resolve_agent("claude", "claude")
    assert launch.backend == "claude-stream"
    assert "stream-json" in launch.command


def test_grok_plain_command_adds_agent_stdio(monkeypatch):
    monkeypatch.setattr("handoff.agents._available", lambda name: "C:/bin/grok.exe" if name == "grok" else None)
    launch = resolve_agent("grok", "grok")
    assert launch.command == ["C:/bin/grok.exe", "agent", "stdio"]


def test_missing_claude_is_actionable(monkeypatch):
    monkeypatch.setattr("handoff.agents._available", lambda name: None)
    try:
        resolve_agent("claude", "claude")
    except AgentUnavailable as exc:
        assert "unavailable" in str(exc)
    else:
        raise AssertionError("expected AgentUnavailable")


def test_codex_prefers_adapter_then_npx(monkeypatch):
    monkeypatch.setattr("handoff.agents._available", lambda name: "C:/bin/codex-acp.exe" if name == "codex-acp" else None)
    assert resolve_agent("codex", "codex").command == ["C:/bin/codex-acp.exe"]
    monkeypatch.setattr("handoff.agents._available", lambda name: "C:/bin/npx.cmd" if name == "npx" else None)
    assert resolve_agent("codex", "codex").command == ["C:/bin/npx.cmd", "-y", "@agentclientprotocol/codex-acp"]


def test_native_tui_flags_are_rejected(monkeypatch):
    monkeypatch.setattr("handoff.agents._available", lambda name: f"C:/bin/{name}.exe")
    for name, command in (("grok", "grok chat"), ("claude", "claude --dangerously-skip-permissions"), ("codex", "codex --full-auto")):
        try:
            resolve_agent(name, command)
        except AgentUnavailable as exc:
            assert "cannot" in str(exc)
        else:
            raise AssertionError(f"expected rejection for {command}")
