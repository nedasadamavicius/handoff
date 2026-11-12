# 01: ACP stdio client

## Outcome
An asynchronous client runs a fake or real ACP server and supports interactive multi-turn sessions without blocking Textual.

## Context and decisions
Use Python asyncio subprocess pipes, JSON-RPC 2.0 NDJSON, no SDK. ACP protocolVersion 1, clientCapabilities {}, clientInfo name handoff/version 0.1.0. Providers perform their own tools. Follow the reference lifecycle in the index.

## Scope
Own src/handoff/acp/ and tests/test_acp.py plus tests/fixtures/fake_acp_agent.py only.

## Requirements
- Export ACPClient and ACPError from handoff.acp. Constructor: ACPClient(command: list[str], cwd: Path, on_update: async callback accepting params dict, on_permission: async callback accepting params dict and returning ACP permission result dict).
- async start() spawns, initializes, validates version, calls session/new with absolute cwd and mcpServers [], stores session_id. async prompt(text) sends text content and returns result dict; reject overlapping turns. async cancel() sends session/cancel notification and resolves pending permissions cancelled. async close() idempotently cancels and terminates/waits/kills with bounded teardown.
- Separate stdout reader from callback/request handlers so a permission wait does not block prompt responses or cancel. Correlate request IDs; lock writes; do not timeout normal long prompts. Bound handshake waits.
- Forward session/update params unchanged, including text/thought/tool updates. Permission response shape: {outcome: {outcome: selected, optionId: ...}} or {outcome: {outcome: cancelled}}. Validate selection against supplied options; default cancelled when callback missing/fails.
- Unknown server requests get -32601. Surface JSON-RPC errors, malformed data, EOF and process death; settle pending futures and drain stderr with bounded retained diagnostics. Cleanup also on failed initialization and cancellation.
- Do not advertise unimplemented filesystem/terminal capabilities.

## Acceptance criteria
Fake server verifies exact handshake, two turns, streamed text/tool/thought events, selected/cancelled permissions, cancellation while permission waits, RPC failure, process death, and idempotent close without leaked pending tasks.

## Verification
Run python -m pytest tests/test_acp.py in available repository environment; use asyncio.run inside tests (no pytest-asyncio dependency). Fake process uses sys.executable and no installed providers.

## Dependencies
None. Interface is consumed by 04.

## Out of scope
Adapters, TUI, configuration, ledger, docs, live provider operations.
