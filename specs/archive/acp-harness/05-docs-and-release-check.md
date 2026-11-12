# 05: Documentation and integrated verification

## Outcome
README accurately explains the working harness, provider setup, shortcuts and validation limits.

## Context and decisions
Preserve existing user README edits and DESIGN.md. Validation build, study graph later. Providers retain CLI credentials/tools but native terminal chrome is not embedded.

## Scope
Own targeted README.md sections only. Manager owns integrated checks, narrow integration fixes, specification status and .handoff/DRAFT.md.

## Requirements
- Replace suspend/finalize/auto-modal descriptions with agent tabs, permissions, cancel/close, snapshots and h/quit workflow.
- Document Grok agent stdio, Codex ACP adapter/npm dependency, preferred Claude adapter and stream-json fallback limits (CLI-controlled permission denials, no ACP permission modal in fallback), unknown/missing providers and login prerequisites.
- Explain defaults/old-default migration, prompt-safe shortcuts and retained editor behavior, no HTTP provider integration.
- Keep dual-mode north star; graph/wiki links deferred.

## Acceptance criteria
Instructions match delivered commands/UI and do not promise untested live provider compatibility or graph support.

## Verification
Full poetry run pytest or documented environment equivalent. Manager reviews docs against implementation and runs deterministic fake-provider integration checks; report live smoke testing separately.

## Dependencies
04 complete.

## Out of scope
Publishing, commits, installations, graph implementation.
