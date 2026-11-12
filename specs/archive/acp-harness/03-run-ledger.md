# 03: Run snapshots and merged handoff

## Outcome
Agent draft snapshots survive tab closures and prefill a single human handoff without losing another agent's completed bullets.

## Context and decisions
Do not change LAST/NEXT/DRAFT or session YAML formats. Keep historical snapshots; do not replay consumed snapshots on the next handoff. Agent attribution of a shared draft cannot be guaranteed; snapshots preserve contents observed at capture time.

## Scope
Own src/handoff/agent_runs.py and tests/test_agent_runs.py only. UI uses the exported interface; no workspace/workflows/TUI edits.

## Requirements
- AgentRun dataclass: name, command, started_at, ended_at None, status ('ok'|'error'|'cancelled'), prompt_count 0, draft_snapshot Path|None.
- RunLedger(workspace) owns runs and pending snapshot paths. begin(name, command) -> AgentRun; snapshot(run) -> Path|None reads current draft, creates collision-free sanitized timestamp-agent filename under workspace.meta/runs, records it pending, no draft deletion. finish(run, status) timestamps and snapshots.
- merged_draft(next_text: str) -> HandoffDraft merges pending snapshots chronologically then current draft using parse_draft_or_files, parse_last_sections and merge_next_text. Unique summaries concatenate, Completed/Open Issues bullets deduplicate preserving order; remove blank placeholder and None if real issues exist; output structured ### Summary/Completed/Open Issues. Preserve existing NEXT and merge additions.
- consume() clears current pending inputs (historical files remain). tools_launched property derives names from runs preserving launch order for legacy session metadata. has_pending property indicates unconsumed snapshots; current DRAFT handled by UI.
- Do not import snapshots from prior sessions automatically; no new persisted schema. Keep current working ledger independent of old archived files.

## Acceptance criteria
Two agents capture different drafts with shared bullets; merge retains both unique outcomes, deduplicates shared entries and NEXT, suppresses None placeholders, avoids filename collisions; consume stops historical replay; absent draft safe.

## Verification
python -m pytest tests/test_agent_runs.py; tests use tmp_path and existing document parsers.

## Dependencies
None. 04 owns calls before h/on close and consume after successful save.

## Out of scope
TUI, workspace/workflow format changes, transport, provider adapters, historical deletion.
