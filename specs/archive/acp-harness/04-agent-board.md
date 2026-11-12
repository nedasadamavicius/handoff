# 04: In-app agent board and shell integration

## Outcome
Multiple agent tabs run inside the existing workspace shell with visible file tree, access to LAST/NEXT, streamed conversations and human handoff on demand.

## Context and decisions
Retain existing ContentSwitcher/overview/preview IDs and navigation. Build new widgets in tui_agents.py; tui.py only composition/wiring. Use client and ledger interfaces from 01-03. Normal text input must allow literal h/q/s; expose global actions via Ctrl+h/Ctrl+q/Ctrl+s when input focused, existing bare keys outside input. Escape returns file focus/overview. This resolves the design's conflict between typing and global single-letter keys.

## Scope
Own src/handoff/tui_agents.py, targeted src/handoff/tui.py integration, tests/test_tui_agents.py. May add new screens in tui_agents.py; leave existing HandoffScreen intact.

## Requirements
- Visible tab bar with Overview, configured agent tabs and + picker; t opens picker, 1-5 open/focus corresponding agent regardless of picker state outside text input. Spawning is lazy, only once per live tab. Unsupported/missing agents show recoverable actionable status.
- AgentBoard accepts config/workspace/ledger, uses resolve_agent and corresponding client, streams background tabs independently with Textual async workers. Per pane transcript RichLog (plain provider strings, no markup injection), tool summaries/status, Input or TextArea prompt, Send/Cancel/Close controls; idle/streaming/waiting-for-permission/dead status; prevent duplicate submits while starting/streaming.
- Prompt submission increments AgentRun count, displays user message; initialization errors and exits surface in tab. Permissions use modal with supplied option IDs and explicit cancel; serialize simultaneous permissions or ensure each modal/future is resolved separately. Closing/cancel resolves outstanding permission cancelled, tears down client, snapshots run, allows reopen as new run.
- Keep LAST/NEXT visibly available through Overview tab; file previews and editor keep working. Launch removes suspend/run_command/finalizer/automatic action_handoff; editor retains suspend/run_command.
- Before h snapshot all active runs; merge via ledger and existing NEXT; save tools_launched from ledger; consume pending only after successful save. Cancelled handoff retains pending snapshots.
- q offers Save handoff / Quit without saving / Cancel if draft or pending snapshots exist; running agents must be captured/closed on confirmed quit, never on cancelled quit. Save then quit only after actual successful save; cancel/empty/error keeps app open. Shutdown tears down all processes even through app unmount.
- Bare h/q/s shortcuts must not hijack prompt text, Ctrl variants operate when prompt focused. Escape restores overview/tree. Existing navigation/forms/logs preserved.

## Acceptance criteria
Textual headless pilot with fake backend validates open/focus/reopen, text containing h/q/s, streamed background tab, permission selected/cancel, cancellation and shutdown cleanup, no suspend/finalizer/autohandoff during launch, merged h prefill and guarded quit. Existing tests remain green.

## Verification
python -m pytest tests/test_tui_agents.py tests/test_core.py tests/test_workflows.py and foundation tests. Use asyncio.run+app.run_test; no providers.

## Dependencies
01, 02, 03 implemented and their interfaces reviewed before starting.

## Out of scope
Docs, study graph, native PTYs, whole-TUI redesign, provider installation.
