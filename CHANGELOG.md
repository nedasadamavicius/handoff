# Changelog

## 2026-06-06

- Added the first local workspace TUI prototype with a current-directory workflow.
- Switched workspace metadata to `.ws/WORKSPACE.md`, `.ws/LAST.md`, and `.ws/NEXT.md`.
- Added code-vs-regular workspace detection based on `.git/`.
- Added editor/tool launching, including Claude/Codex-style command launchers.
- Added a right-pane IA with last-session and next-session panels.
- Added scrollable file previews with pane focus routing.
- Added direct metadata editing shortcuts for `WORKSPACE.md`, `LAST.md`, and `NEXT.md`.
- Reworked manual handoff into an in-app modal with focused fields and generated Markdown output.
- Added local Git evidence for code handoffs.
- Added basic tests for core workspace, config, handoff, launcher, and Git behavior.
