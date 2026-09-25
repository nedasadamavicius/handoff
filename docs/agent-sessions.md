# Agent integration and sessions

When you launch a configured agent tool from `handoff`, such as `grok`, `claude`, or `codex`, Handoff starts it in the workspace directory and generates that tool's memory file (`AGENTS.md` or `CLAUDE.md`) in the workspace root. Claude and Codex are new windows in the psmux or tmux session this terminal is already attached to. On Windows, Grok is a separate console. These files are not created when the app itself opens. The file instructs the agent to:

1. Read `.handoff/WORKSPACE.md` at session start to understand the workspace context.
2. Treat `.handoff/DRAFT.md` as a live handoff ledger and keep the LAST.md section current after material work, including affected files and relevant `git diff` details.
3. Save NEXT.md updates for the end of the agent session unless the next action is already clear and durable.

Agents are also instructed to refresh `.handoff/DRAFT.md` before handing control back after material work, even if you did not say the session is ending.

When you press `h` to open the handoff modal, Handoff pre-populates the fields from the workspace draft and any pending run snapshots. NEXT.md items from the existing handoff are merged with draft NEXT.md items so unfinished carryover stays visible unless you remove them in the modal. You review, edit if needed, and save. The draft is deleted after saving. External sessions share the workspace draft; Handoff does not capture their conversations or send them automatic finalize requests.

The tool file is only created if it does not already exist, so your edits are never overwritten.

## Default tools

The default tool launcher includes `grok`, `codex`, and `claude`. They must be installed, logged in, and available on `PATH` before launching them from the TUI. Start Handoff from inside `psmux` on Windows or `tmux` elsewhere. Claude and Codex stay as windows in that session. On Windows, Grok opens in its own console so its keyboard talks to that console directly.

Existing user configuration with the old default `{codex, claude}` is migrated by adding `grok`; custom tool maps are kept as configured.

## Providers and setup

Configure the ordinary interactive command you would run yourself, such as `codex` or `claude`. Authentication, prompts, tool approvals, and agent output stay in that tool's own terminal. Custom executable commands are supported; no ACP adapter is required for this launch path.

Claude and Codex require Handoff to be running inside `psmux` on Windows or `tmux` on Linux and macOS, and they stay in that session. A launch of those tools from a plain shell is refused. On Windows, Grok starts in a new console. Handoff clears inherited `TMUX`, `TMUX_PANE`, and `PSMUX_*` variables for that process, and Open focuses the visible console window. When Windows Terminal is the console host, the helper's console handle is a hidden pseudoconsole, and Open follows it to the terminal window that owns it. Missing executables and launch failures are reported in Handoff. The workspace and handoff features remain available without the multiplexer.

## Agent sessions and shortcuts

The grouping for Handoff, Claude, and Codex is: **Alacritty → one session → windows for each repository**. Handoff names its window `HO: <repository>`. Agent windows use `<Agent>: <repository>`, with a number for repeated launches. Prefix then `w` lists every workspace and agent window; prefix then `n`/`p` moves between them. Grok on Windows opens beside that session, in the console host Windows is configured to use.

On Windows, Alacritty can start psmux automatically with this setting in its Windows configuration:

```toml
[terminal]
shell = { program = "psmux", args = ["new-session", "-A", "-s", "main"] }
```

Keep any existing `-f` configuration-file arguments when adjusting your setup. From that session, open each repository as its own window and run `handoff` there. The default prefix is `Ctrl+B`; with a custom `M-q` prefix, use `Alt+Q` instead.

Use `t` to show the session manager and `1`–`5` to launch configured tools. Claude and Codex each add a window to the current psmux or tmux session. Grok on Windows opens a separate console. Select a session and press Open to switch this terminal to a multiplexer window, or to focus a Grok console. Stop ends that session. Exited sessions can be removed from the list. Handoff reports process state; it cannot tell whether an agent is thinking or waiting for your input.

Press `Enter` on a selected session to open it, `Ctrl+K` to force-stop it and its child processes, or `Ctrl+T` to return to the workspace. `s` opens logs, `e` edits the selected file, and `h` saves the handoff.

Quitting Handoff leaves multiplexer windows running. Tracking covers the current Handoff run only: restarting Handoff does not rediscover those windows. Close them from the multiplexer when you are finished. The app still offers to save a handoff when a draft or live session is pending.

**Agent memory files** (matched by configured tool name or command):

| Tool | File created |
|---|---|
| grok | `AGENTS.md` |
| claude | `CLAUDE.md` |
| codex | `AGENTS.md` |

The matching memory file is created only for the tool being opened, just before it starts.

**Draft format** (`.handoff/DRAFT.md`):

```markdown
## LAST.md

### Summary

What was accomplished this session.

### Completed

- Item one.
- Item two.

### Open Issues

- Anything unresolved.

## NEXT.md

- Next action items.
```
