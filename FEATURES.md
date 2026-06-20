# handoff — Features

`handoff` is a local-first terminal workspace shell for maintaining continuity between AI coding sessions (Claude Code, Codex) and human work sessions. The core loop: work → handoff → next session picks up exactly where you left off.

---

## Current Features

### TUI Shell
- Split-pane terminal UI (Textual): file browser on the left, content viewer on the right
- Overview panel on launch: "Last Session" summary and "What's Next" side by side
- Independently scrollable overview panels with keyboard focus navigation
- Markdown rendering and plain-text preview modes for workspace files
- Filtered directory tree (hides `.git`, `.handoff`, `__pycache__`, `.claude`, etc.)
- Full keyboard-driven navigation — no mouse required

### Workspace Management
- `handoff init <dir>` — initialize a directory workspace with scaffold files
- Running `handoff` in any directory auto-detects or creates a workspace
- Two workspace types: **code** (git repo, inferred from `.git/`) and **regular**
- Per-workspace metadata in `.handoff/`: `WORKSPACE.md`, `LAST.md`, `NEXT.md`, `DRAFT.md`

### Session Handoff Modal
- Press `h` to open the paginated handoff form
- Four editable fields: Summary, Completed, Open Issues, Next Session
- Read-only Evidence page for code workspaces (changed files, tools launched, `git status`)
- Ctrl+Left/Right to page through fields; Ctrl+S to save; Esc to cancel
- Pre-fills from `DRAFT.md` if agents updated it during the session
- Normalizes diff/patch notation artifacts written by agents (`+- `, `-- ` bullets)
- Filters "low-value" completed items (reading, searching, reviewing, running tests)

### Session & Day Logging
- Every saved handoff writes a timestamped session file to `.handoff/sessions/`
- Session files have YAML frontmatter (workspace, start/end timestamps, tools launched, files opened)
- Day log aggregated per date in `.handoff/days/` — merges completed items and open issues across sessions
- Duplicate-safe merging: re-running handoffs on the same day appends, does not clobber

### Log Browser
- Press `s` to browse session, day, and week logs without leaving the TUI
- Ctrl+Left/Right switches between Sessions, Days, and Weeks
- Enter explicitly loads the highlighted log; list navigation does not replace the existing preview
- Left/Right moves focus between the list and preview while preserving preview content and scroll position
- `e` opens the highlighted log in the configured editor; Esc closes the browser

### Weekly Reviews & Worklog
- Detects completed weeks that have day logs but have not been finalized
- Generates `.handoff/weeks/YYYY-W##.md` review drafts from aggregated day logs
- Press `W` to review Summary, Highlights, and Carry-forwards in a modal
- Approved reviews are appended reverse-chronologically to `.handoff/WORKLOG.md`
- Supports multiple pending weeks, presented oldest-first

### Tool Launcher
- Configure up to 5 external tools in `~/.handoff/config.yaml`
- Press `t` to show the tool picker, then `1`–`5` to launch
- Default tools: **claude** and **codex**
- After a Claude session, automatically runs `claude --continue -p <finalize-prompt>` to flush `DRAFT.md`
- After a Codex session, automatically runs `codex exec resume --last <finalize-prompt>` to flush `DRAFT.md`
- Auto-creates `CLAUDE.md` / `AGENTS.md` in the workspace with handoff format instructions on first launch

### DRAFT.md Live Ledger
- `CLAUDE.md` / `AGENTS.md` instruct AI agents to write to `.handoff/DRAFT.md` during work (not just at end)
- Handoff modal reads `DRAFT.md` on open to pre-fill all fields — no manual copy-paste
- NEXT.md items are merged (deduped) from both the draft and the existing file

### Editor Integration
- Press `e` to open the selected file in your configured editor
- `w` / `l` / `n` shortcuts open `WORKSPACE.md`, `LAST.md`, `NEXT.md` directly
- Configurable editors: nvim (default), helix, vim, VS Code
- VS Code launches with `--wait`; configured editor commands run correctly on Windows

### Git Integration
- Captures `git status --short` at handoff time for code workspaces
- Parses changed file list shown in the Evidence panel
- Workspace type auto-inferred from presence of `.git/`

### Theme System
- Built-in `graphite-crimson` dark theme (charcoal + crimson red)
- User-definable YAML themes in `~/.handoff/themes/`
- Theme applied at startup from `config.yaml`

### File Management
- `c` key opens a "New File" modal — creates a file in the currently selected directory
- File path relative to workspace root tracked in session log when previewed

---

## Suggestions — What Could Be Added

### High value / low effort
- **Workspace switcher** — the `workspaces_dir` path exists in config but the TUI has no way to switch between workspaces
- **NEXT.md task toggle** — press `x` on a `- [ ]` / `- ` line in the NEXT panel to tick it off without opening an editor
- **Delete file** — the browser supports create but not delete; `d` with a confirmation prompt would round out basic file management
- **Config editor shortcut** — a `C` binding that opens `~/.handoff/config.yaml` in the editor, same as the `w`/`l`/`n` shortcuts

### Medium value
- **Full-text search** — `ctrl+f` or `/` to search across workspace files and session logs by keyword; essential once sessions accumulate
- **Session duration tracking** — already stores `started_at` / `ended_at` but the TUI never displays it; show duration in the overview or session list
- **Statistics view** — press `S` to see: sessions this week, avg session length, most-opened files, streak of daily work
- **Workspace rename / re-type** — no in-app way to change `workspace_type` or the display name without editing YAML directly
- **NEXT.md ordering** — drag-to-reorder or `j`/`k`+`shift` to move items up/down in the Next panel

### Lower priority / larger scope
- **Multiple panes / tabs** — open two workspaces side by side for cross-project reference
- **Export** — `handoff export --json` or `--csv` to dump session data for dashboards or time tracking tools
- **Webhook / notification** — post a Slack or Discord message when a handoff is saved (useful for team-shared workspaces)
- **Gemini finalization** — `GEMINI.md` was stubbed and then removed; restoring it would extend the auto-handoff pattern to Gemini CLI users

---

## Is it enough feature-wise?

For a personal solo tool focused on AI session continuity: **yes, the core loop is solid.** The handoff modal, DRAFT.md ledger, auto-finalization, session/day/week logging, historical log browser, and weekly worklog cover the essential workflow.

The most impactful remaining additions would be a **NEXT.md task toggle** and **full-text search** across workspace files and historical logs.
