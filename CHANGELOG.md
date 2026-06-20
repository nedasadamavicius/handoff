# Changelog

## 2026-06-20

- Added Claude auto-handoff prefill
- Added weekly worklog feature: auto-detects unfinalized past weeks on TUI launch, auto-generates `.handoff/weeks/YYYY-W##.md` drafts from day logs, prompts user to review via `W` key, and appends approved entries to `.handoff/WORKLOG.md` (reverse chronological).
- Added `WeeklyReviewScreen` modal with Summary, Highlights, and Carry-forwards fields.
- Added `weekly.py` with ISO week utilities, day-log aggregation, draft rendering, and worklog append logic.
- Added workspace properties: `weeks_dir`, `week_file()`, `worklog_file`.
- Added 8 new tests covering weekly aggregation, pending detection, draft lifecycle, and worklog append.

## 2026-06-06

- Added the first local workspace TUI prototype with a current-directory workflow.
- Switched workspace metadata to `.handoff/WORKSPACE.md`, `.handoff/LAST.md`, and `.handoff/NEXT.md`.
- Added code-vs-regular workspace detection based on `.git/`.
- Added editor/tool launching, including Claude/Codex-style command launchers.
- Added a right-pane IA with last-session and next-session panels.
- Added scrollable file previews with pane focus routing.
- Added direct metadata editing shortcuts for `WORKSPACE.md`, `LAST.md`, and `NEXT.md`.
- Reworked manual handoff into an in-app modal with focused fields and generated Markdown output.
- Added local Git evidence for code handoffs.
- Added basic tests for core workspace, config, handoff, launcher, and Git behavior.
