# handoff

Handoff is a terminal UI for people who switch between projects and don't want to lose context each time they stop. It keeps a small, local handoff in your directory: what you did last session and what to do next.

Open any directory (a GitHub repo, a study folder) with `handoff`, work, then press `h` to save a handoff. When you come back, the overview shows the last session and the next steps, with no long session history to dig through. Notes are plain Markdown in `.handoff/`, so they are easy to read, edit, and version.

It also launches external AI agents (`claude`, `codex`, `grok`) in the workspace and points them at the same handoff notes. Two modes share one spine: Coding and Study (which adds a local Markdown knowledge graph).

## Install

```bash
pipx install --editable .
```

## Quick start

```bash
handoff init my-notes   # or: cd existing-repo
cd my-notes
handoff
```

On first run in a directory, `handoff` creates `.handoff/` with `WORKSPACE.md`, `LAST.md`, and `NEXT.md`. Press `h` to write the handoff for the session.

## Additional documentation

- [Workspaces and study mode](docs/workspace.md): workspace layout, user config, learning-notes workflow
- [Agent integration and sessions](docs/agent-sessions.md): launching agents, memory files, draft format, psmux/tmux shortcuts
- [Themes](docs/themes.md): customizing colors
- [Development](docs/development.md): dependencies, tests, known issues
- [Design](docs/DESIGN.md): external-session manager and workspace direction
- [Changelog](docs/CHANGELOG.md): release history
