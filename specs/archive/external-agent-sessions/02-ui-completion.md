# Complete external session UI

## Outcome

Complete the UI integration and its tests for 01-session-manager.md. Existing partial UI is incomplete and must be corrected.

## Context and decisions

The user authorized a plan followed by Luna implementation. All product decisions from 01-session-manager.md remain. Backend completion runs independently with the API below; do not edit backend files. Preserve unrelated edits. You are not alone in this repository.

## Scope

Own ONLY src/handoff/tui_sessions.py, src/handoff/tui.py, tests/test_tui_agents.py. The backend worker owns external_sessions.py, session_runner.py, and tests/test_external_sessions.py. Manager owns docs and draft.

## Requirements

- Backend API remains synchronous: SessionManager(workspace), sessions list of ExternalSession(name, command, workspace, ident, state, pid, exit_code, error, hwnd), launch(name, command)->ExternalSession, refresh()->None, open(session), stop(session), remove(session), shutdown(). Backend methods may block and serialize internally. Do not invoke them on UI thread, including refresh and shutdown.
- Replace the current partial widget with properly sized Textual DataTable, help/empty status, operation status, and Open/Stop/Remove buttons. Numbered tools and instructions must be visible in help. No embedded terminal or prompt input.
- Launch/open/stop/remove/refresh/shutdown use asyncio.to_thread in Textual async workers, never block the message handler. Use app.run_worker/widget.run_worker to start coroutines, returning from key events immediately. Avoid thread-based call_from_thread callbacks. Poll every 500ms with at most one refresh worker pending. Catch errors, notify, and clear operation/poll busy state in finally. Operations must not block workspace navigation. Poll snapshots may safely be read after backend.refresh completes; keep changes to table on UI thread.
- Maintain selected identity across refreshes and remove. Do not clear/redraw unchanged rows. While launch is pending show status; new session row appears when backend returns. Failures visible. Append app.tools_launched only when launch succeeds, never before.
- t shows table and focuses it after refresh/layout; 1-5 launches another session, Ctrl+T returns to workspace, Ctrl+K invokes selected Stop, row-selected/Enter invokes Open. Button operations use same async pathway. Buttons keyboard accessible. No stale handoff suppression for SessionManagerWidget. DataTable navigation must not be stolen by app bindings.
- Quit with live sessions still offers handoff; shutdown closes bookkeeping only and never stops agents. Ensure normal unmount cleanup also invokes manager shutdown safely; prevent polling after shutdown and late callbacks accessing unmounted widgets. Avoid app exit waiting on long stop operation on the UI thread.
- Remove only exited/error sessions; backend rejects live ones. Ensure Delete/Remove behavior actually connected.

## Acceptance criteria

Create and run replacement tests/test_tui_agents.py with fake synchronous SessionManager and controlled asyncio/thread events. Cover: two launches, launch failure not logged as success, slow launch responsiveness (Ctrl+T + workspace navigation while fake blocks), slow stop responsiveness, reopen table selection preserved, Enter and button Open, Ctrl+K and button Stop, remove and live-remove refusal, no redraw on unchanged refresh, quit leaves sessions alive/only shutdown, no TerminalPane mounted. No visible window/provider launch. Do not claim missing tests are a blocker: creating tests is assigned work.

## Verification

Run .venv/Scripts/python -m pytest tests/test_tui_agents.py -q -p no:cacheprovider --basetemp=D:/handoff/.test-tmp-session-ui-<unique> and git diff --check. Fix failures before returning. Return changed files, exact results, and remaining limitations. Do not hand back partial implementation as complete.

## Dependencies

Backend API above is frozen; use fakes, so implementation and verification can run independently of backend completion.

## Out of scope

Backend files, real agent/window launches, docs, DRAFT, dependency manifests, commits, and platform design changes.
