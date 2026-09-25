# Handoff: workspace shell and external agent sessions

## Product

Handoff keeps a directory's files, workspace context, and handoff notes available while the user works. Coding and Study workspaces share the same Markdown handoff format. Study workspaces also expose a local Markdown knowledge graph without interrupting external agent sessions.

Agents run as their ordinary interactive CLIs inside a terminal multiplexer. Handoff creates a window in that session and tracks the helper process. The user attaches with their own terminal, such as Alacritty, to give instructions, review output, and approve tool use.

## Decisions

- Keep Handoff running while agents run. Agent launches never suspend its TUI.
- Remove terminal emulation from the active app. Agent output never enters Handoff's rendering loop.
- Preserve native agent commands, authentication, tools, and interaction.
- Allow several sessions, including several instances of the same configured tool.
- Track processes, not model activity. A running process may be waiting for user input.
- Keep manual handoff saving and existing Markdown formats.
- Use psmux on Windows and tmux on other platforms for Claude, Codex, and other tools. On Windows, Grok launches in its own console (`CREATE_NEW_CONSOLE`) because psmux 3.3.8 cannot carry its keyboard protocol. That route does not require the multiplexer. Open focuses the visible console host, following a pseudoconsole handle to the owning terminal window when the configured host is Windows Terminal. Unsupported hosts for multiplexer tools are those without the multiplexer, and they never fall back to embedded PTYs.

## Architecture

```text
Handoff workspace TUI
  files / overview / handoff / logs
  session manager
    launch / open / stop / remove
        |
        +-- psmux or tmux session the terminal is attached to
              +-- window: HO: repository A
              +-- window: Codex: repository A
              +-- window: Claude: repository A
              +-- window: HO: repository B
              +-- window: Codex: repository B
```

Handoff must itself be running inside psmux or tmux to launch multiplexer tools. It names its current window `HO: <repository>`. For those tools, launch reads the attached session (`PSMUX_SESSION`, or `TMUX` plus `display-message`) and creates each agent as another window in it. Agent windows use `<Agent>: <repository>` and add a number for repeated launches. Open uses `switch-client` so this terminal moves to that agent window. On Windows, Grok skips that session lookup and starts `session_runner.py` in a new console. The helper's environment has `TMUX`, `TMUX_PANE`, and `PSMUX_*` removed, and the runner does not set `GROK_FORCE_LEGACY_CONSOLE` on that route. Open resolves the helper's console HWND to a visible terminal window before focusing it. Handoff does not nest a multiplexer inside the pane. The helper runs the native tool, waits for it, and records process metadata and exit status. Handoff only reads those small status records.

The multiplexer command returns as soon as the window exists, so it is not the agent's liveness signal. On Windows, Handoff retains a handle to the helper process. Elsewhere it checks that pid. Stop kills that helper and its descendants. It never kills the multiplexer server or processes by executable name. Open switches the attached client to that agent window.

Potentially blocking launch and stop work runs outside the TUI event loop. Status polling is bounded and does not redraw an unchanged session list.

## Interaction

| Control | Behavior |
|---|---|
| `1`-`5` | Launch another instance of the configured tool |
| `t` | Show the session manager |
| Select + Open / `Enter` | Switch this terminal to a multiplexer window, or focus a Grok console |
| Stop / `Ctrl+K` | Force-stop the selected session and its descendants |
| Remove | Remove an exited session from the list |
| `Ctrl+T` | Return to the workspace |
| `h` | Review and save the workspace handoff |

The session manager shows starting, running, exited, and failed states with the relevant PID, exit code, or error. It contains no agent prompt editor or transcript.

Quitting Handoff leaves multiplexer windows running. Tracking lasts for the current Handoff run; restarting the app does not rediscover earlier windows. The session manager explains this limit. A running entry cannot be removed without stopping it first.

## Workspace integration

Workspace front matter includes `workspace_mode: study` or `workspace_mode: coding`. `handoff init` accepts `--mode`; an existing workspace without a mode gets a one-time choice when opened. Study mode adds `g` for note search and local incoming/outgoing links. It indexes Markdown files while excluding metadata, dependency, build, and hidden directories. It resolves `[[wiki-links]]` and local Markdown links, reports unresolved targets, and keeps writing in the existing editor.

Before launch, Handoff creates the configured tool's memory file only if it is missing. Agents receive the existing instructions to read `.handoff/WORKSPACE.md` and maintain `.handoff/DRAFT.md`.

Handoff does not send prompts or finalize requests to external agents. The user drives each conversation and saves the shared workspace handoff when ready. Several agents in the same workspace share its files and draft; Handoff does not merge their conversations.

## Verification

Automated checks cover launch arguments, process tracking, window selection, the Windows Grok console route, targeted stop, errors, multiple sessions, and workspace navigation during slow backend operations. Multiplexer commands are mocked. Those tests do not establish a real psmux or tmux attach, native agent usability, or keyboard behavior inside Grok; those require an interactive check.

## Deferred

- Rediscovering multiplexer windows after Handoff restarts by listing the session.
- A direct model/tool loop or restoration of the legacy ACP board.
- Agent output capture, transcript rendering, and automatic agent commands.
- Removal of retired PTY/ACP modules and dependency cleanup.

The earlier ACP design is superseded by this external-session direction. Legacy ACP and PTY modules may remain in the repository, but neither is mounted in the workspace UI.
