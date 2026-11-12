# External agent sessions

## Outcome

Handoff stays responsive while native agent CLIs run in separate interactive Windows terminal windows. Users launch, select, open, stop, and remove sessions from Handoff, and type into each agent's own terminal.

## Context and decisions

- User approved external terminal sessions instead of embedded PTYs and explicitly requested a plan followed by Luna implementation. This spec is the implementation plan; proceed without another approval round.
- Repository: D:/handoff. Read AGENTS.md and .handoff/WORKSPACE.md. Existing uncommitted changes belong to the user; preserve unrelated work.
- First release supports Windows. Other platforms report external terminal launching unsupported; never suspend Handoff or fall back to PTY/ACP.
- Multiple sessions, including repeated launches of the same tool, are allowed. Session tracking lasts for the current Handoff app run. Quitting Handoff leaves external agent sessions alive; restart recovery is deferred and must be stated in UI help.
- No agent output capture, prompt editor, command forwarding, transcript rendering, automatic agent requests, or embedded terminal.
- Handoff retains workspace memory files and manual handoff saving. Existing ACP modules remain unmounted and unchanged.

## Scope

Following an incomplete first pass, completion is split by ownership: the backend worker owns src/handoff/external_sessions.py, src/handoff/session_runner.py, and tests/test_external_sessions.py. The UI worker implements 02-ui-completion.md and owns src/handoff/tui_sessions.py, src/handoff/tui.py, and tests/test_tui_agents.py. Manager owns README.md, DESIGN.md, .handoff/DRAFT.md, specification files, and integration review. Do not edit manager-owned files or dependency manifests. Leave retired PTY files/tests intact but ensure the active app no longer imports them.

## Requirements

### External process backend

1. Use standard-library subprocess and Windows ctypes APIs; no new runtime dependencies. Keep platform-specific functions isolated and imports safe on other platforms.
2. Prefer Windows Terminal (wt.exe resolved with shutil.which) with a unique named window per session. Launch an external Python helper via wt -w <unique-name> new-tab --title <label> --suppressApplicationTitle --startingDirectory <workspace> <python> <absolute-helper-script> <request-path>. Use subprocess argument lists, never concatenate untrusted values into shell commands. Suppress inherited Handoff stdio for the terminal launcher. Windows Terminal launcher exit is NOT agent exit.
3. If wt is unavailable, launch the same helper with CREATE_NEW_CONSOLE and no inherited redirected stdio, so it has its own real terminal. The helper runs the configured native tool with inherited console I/O, waits for it, records exit, and exits. It writes initial metadata (PID and console window handle) and final exit status atomically to per-session files under .handoff/external-sessions/. A random session identifier names each request/status file. Do not persist secrets or environment variables. No automatic session recovery from these records in this release.
4. Requests carry the argument vector, workspace, status path, and display label as JSON; do not serialize executable code. Resolve the executable with shutil.which or a verified file path before launching. Parse configured Windows commands with support for quoted executable paths and arguments; strip wrapping quotes correctly. Native .exe and npm .cmd/.bat shims must work. For shims, use a Windows-appropriate invocation that preserves literal arguments and fails clearly if unsupported; test spaces and metacharacters. Do not pipe native child stdout/stderr.
5. Track the helper process, not wt.exe. Open and retain a Windows process handle when its PID is reported, using SYNCHRONIZE and PROCESS_QUERY_LIMITED_INFORMATION. Poll its exit state without waiting. Retaining the handle prevents acting on a recycled PID. A status file reports child exit code or startup failure. If the user closes the window and no final file exists, report exited (unknown code), not perpetually running. Starting can be a separate state. Give startup a bounded timeout (e.g. 15 seconds); surface errors rather than claiming success. Handle missing/malformed/temporarily unavailable status files without blocking/crashing the UI.
6. Open selects an existing session window: verify helper liveness, then for wt invoke wt -w <unique-name> focus-tab --target 0 (no new-tab); retain the backend/path chosen at launch rather than redetecting it. For the fallback, verify the recorded HWND is visible and valid, restore with ShowWindowAsync and foreground with SetForegroundWindow. If focus is denied/unavailable, report that the user must switch using the taskbar; do not silently launch another agent or claim focus succeeded. GetConsoleWindow may return a non-visible window in pseudoconsole hosts: https://learn.microsoft.com/en-us/windows/console/getconsolewindow . Check visibility. Windows Terminal arguments: https://learn.microsoft.com/en-us/windows/terminal/command-line-arguments .
7. Stop is an explicit force-stop action for the selected live session and its descendants only. Verify the retained process handle is still live immediately before taskkill /PID <helper-pid> /T /F. Run taskkill with CREATE_NO_WINDOW, capture its small diagnostic output, check the result, and impose a timeout. Never taskkill by executable/image name. A failed stop is an error, not an exited session. Starting sessions without a known helper PID cannot be stopped safely yet; show a clear message. Live session handles stay owned until process exit or manager shutdown.
8. Launch, open, and stop operations that may wait must run off the Textual UI thread (asyncio.to_thread or equivalent). Polling is low-frequency (~500ms), bounded metadata work; no redraw when nothing changed. Closing Handoff releases bookkeeping handles but does not terminate sessions.

### UI and shell

1. Replace the mounted TerminalPane with a native session manager using standard Textual widgets (DataTable or ListView plus buttons/status/help). No new visual design system. Show session name/unique number, state, PID when available, and exit code/error when relevant. Empty state explains numbered launch shortcuts and that interaction happens in separate windows.
2. 1-5 launches configured tools; repeated presses launch distinct sessions. t opens the session manager. Selecting a row and Open (or Enter) focuses its terminal window. Stop / Ctrl+K stops the selected session. Remove removes only an exited/error row; it cannot abandon a live process silently. Ctrl+T returns to workspace. There is no embedded input forwarding.
3. Manager table/list must own arrow/Enter navigation while focused. Existing app bindings must not steal manager selection keys. Buttons remain keyboard accessible. Ctrl+Q and handoff actions continue working. During slow launch/stop, workspace navigation stays usable and state/error is visible. Catch backend exceptions and notify without crashing the app.
4. Continue ensure_tool_file immediately before launching a configured agent. Record successfully started launches for handoff metadata. Quitting with a live session may retain the existing handoff prompt, but clearly state in the session pane that quitting Handoff leaves windows running and tracking is not restored after restart. Shutdown never kills them. No automatic finalize prompts.

## Acceptance criteria

- Active WorkspaceShell imports/creates no TerminalPane/PtySession and never suspends for agent launch.
- Two launches produce two tracked sessions; wt launcher exit does not mark the agent exited.
- A fake slow backend does not block navigation. Reopening the manager preserves selection/sessions.
- Open targets existing window identity. Stop targets only the selected tracked helper PID and handles failure/exit races. Remove rejects live entries.
- Failed launch, missing binary, unsupported OS, terminal closed manually, and normal exit have accurate observable states.
- Quit releases manager resources and leaves live external processes untouched.
- Quoted executable paths, arguments with spaces, and .cmd shims have focused tests. No test opens a visible terminal or invokes a real provider.

## Verification

- Use D:/handoff/.venv/Scripts/python -m pytest tests/test_external_sessions.py tests/test_tui_agents.py -q -p no:cacheprovider --basetemp=D:/handoff/.test-tmp-external-<unique>.
- Add meaningful headless runner tests using short Python fixture scripts where practical; mock Windows GUI/process APIs for window-specific operations.
- Run git diff --check. Report exact commands/results, owned files changed, and limitations. Do not claim interactive Windows Terminal/agent usability was verified by mocks.

## Dependencies

- Backend and UI completion can run independently using the fixed synchronous API in 02-ui-completion.md; the manager reviews the integrated result. Backend methods serialize access internally with an RLock because UI operations use worker threads.

### Clarification during implementation

- Native executables preserve quoted paths and spaced/literal metacharacter arguments. For .cmd/.bat only, reject unsupported shell metacharacters (% ! & | < > ^ embedded quotes/newlines) with a clear error rather than permit cmd expansion. Ordinary shim paths and arguments with spaces must work. Test both the positive case and rejection.

## Out of scope

- Linux/macOS terminal launch, restart recovery, transcript capture, LLM harness, ACP restoration, dependency cleanup, handoff file format changes, automatic agent interaction, commits/pushes, and real provider launches during automated verification.
