# ACP harness implementation specs

Authorization: DESIGN.md records an approved direction; the user requested specifications and multiple lower-cost implementation agents on 2026-09-15.

Execute 01, 02, and 03 in parallel with disjoint ownership. Execute 04 after those interfaces are ready. Execute 05 after integration. Manager owns integration, this index, and the live handoff ledger. No commits or external writes.

Preserve existing README edits, DESIGN.md, memory files, and file formats. Study graph, PTYs, direct provider APIs, and whole-shell refactoring are excluded.

Protocol decisions: ACP v1 NDJSON; advertise no client filesystem or terminal capabilities (providers retain their own tools). Codex app-server is not ACP: use its ACP adapter. Claude stream-json fallback needs a distinct session backend, never pass that stream to the ACP parser. Reject unknown methods explicitly. Authentication stays with provider CLI login.

References: https://agentclientprotocol.com/protocol/v1/initialization ; https://agentclientprotocol.com/protocol/v1/prompt-turn ; https://github.com/agentclientprotocol/codex-acp ; https://github.com/agentclientprotocol/claude-agent-acp .

Verification target: poetry run pytest. If Poetry/environment is unavailable, use a workspace-local virtual environment and python -m pytest; report the substitution. No live provider prompts required for automated checks.

Implementation status (2026-09-15): specs 01-05 complete. The deterministic suite and a live Grok initialize/session/new/teardown smoke check pass; Codex and Claude live adapters remain untested.
