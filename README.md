# handoff

Handoff is a terminal UI for people who switch between projects and don't want to lose context each time they stop. It keeps a small, local handoff in your directory: what you did last session and what to do next.

Open any directory (a GitHub repo, a study folder) with `handoff`, work, then press `h` to save a handoff. When you come back, the overview shows the last session and the next steps, with no long session history to dig through. Notes are plain Markdown in `.handoff/`, so they are easy to read, edit, and version.

It also launches external AI agents (`claude`, `codex`, `grok`) in the workspace and points them at the same handoff notes. Two modes share one spine: Coding and Study (which adds a local Markdown knowledge graph).

## Install

Requires Python 3.11 or newer. Works on Windows, macOS and Linux.

```bash
pipx install git+https://github.com/nedasadamavicius/handoff.git
```

[pipx](https://pipx.pypa.io) puts the `handoff` command on your PATH in its own environment. Upgrade with `pipx upgrade handoff`. Plain `pip install git+https://github.com/nedasadamavicius/handoff.git` also works inside a virtualenv.

Launching agents inside the workspace needs a terminal multiplexer: `tmux` on macOS and Linux, `psmux` on Windows. See [agent sessions](docs/agent-sessions.md).

### Build from source

```bash
git clone https://github.com/nedasadamavicius/handoff.git
cd handoff
pipx install .                 # for your user only
sudo pipx install --global .   # for every user on macOS/Linux (pipx 1.5 or newer)
```

On Windows `pipx install .` already puts `handoff` on your PATH for your user; run it from an elevated shell with `--global` if every account on the machine needs it. Avoid `sudo pip install .`: modern macOS and Linux Python refuse it (PEP 668), and it can break system packages.

To update, `git pull` and run `pipx install --force .` again. To work on handoff itself, see [Development](docs/development.md).

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
- [Development](docs/development.md): dependencies, tests, code standards, known issues
- [Persistence](docs/persistence.md): keep notes across machines with your own Nextcloud
- [Design](docs/DESIGN.md): external-session manager and workspace direction
- [Changelog](docs/CHANGELOG.md): release history
