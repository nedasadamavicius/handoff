# 02: Provider registry and configuration

## Outcome
Grok, Claude, and Codex resolve to appropriate headless backends; defaults include Grok and memory files remain intact.

## Context and decisions
ACPClient cannot speak Codex app-server or Claude stream-json directly. Keep shell execution out of agent spawn. Authentication is pre-existing CLI login. Preserve legacy launcher helpers for compatibility but do not use finalizers in the new UI.

## Scope
Own src/handoff/agents.py, src/handoff/claude_stream.py, src/handoff/config.py, workspace.py memory registry portion only, tests/test_agents.py, tests/test_claude_stream.py and config assertion/migration tests in tests/test_core.py. No TUI or ledger changes.

## Requirements
- Frozen AgentAdapter with key, memory_file, matches(tool_name, command), spawn_command(executable) -> list[str]. Export get_adapter(name, command) -> adapter or None; resolve_agent(name, command) -> AgentLaunch with adapter, command list, backend ('acp' or 'claude-stream'). Raise actionable AgentUnavailable for missing/unsupported executable.
- Parse configured commands with shlex, match known provider executable basenames and exact tool aliases, avoid arbitrary substring false matches. Support executable paths and already-configured adapter commands. Do not silently discard custom flags: preserve compatible server arguments or reject native-TUI flags with actionable explanation.
- Grok: executable + agent stdio. Codex: prefer installed codex-acp, else npx -y @agentclientprotocol/codex-acp; no direct app-server ACP. Claude: prefer claude-agent-acp or claude-code-acp on PATH; otherwise claude stream backend with -p --output-format stream-json --verbose --include-partial-messages and --resume session ID for later prompts. Missing dependencies produce actionable install/login messages; no install during implementation.
- ClaudeStreamClient exposes the same start/prompt/cancel/close shape and update/permission callbacks as ACPClient. Each prompt starts a headless CLI turn with text argument, cwd, retained session ID; translate stream_event text/thinking deltas, assistant/tool summaries, result/errors to session/update dictionaries, avoid duplicate final assistant text when partial chunks were delivered. No auto-approval/bypass flags; native denied tools remain denied and are reported. Cancellation terminates the active process with bounded cleanup. start verifies availability without creating a paid turn.
- Default tools order grok, codex, claude. Migrate raw tools only when exactly {codex: codex, claude: claude}; preserve custom maps and existing removed-gemini behavior. No config file rewrite needed.
- Wire ensure_tool_file through registry for Grok/Codex AGENTS.md and Claude CLAUDE.md, keep legacy Gemini memory behavior and only-create-if-missing semantics.

## Acceptance criteria
Mock PATH selection/missing binaries; cover aliases/custom command errors, all adapter choices, old-default migration/custom preservation, Grok memory creation and existing file preservation. Fake Claude stream validates first/resumed turns, text/tool/error, cancellation.

## Verification
python -m pytest tests/test_agents.py tests/test_claude_stream.py tests/test_core.py using available environment. No provider/network calls.

## Dependencies
None; match client interface fixed in 01, do not edit that module.

## Out of scope
ACP transport, TUI, ledger, README, provider installation or live prompts.
