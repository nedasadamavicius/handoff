# handoff

Handoff is for people who work in the terminal and regularly switch between projects or other ongoing work without wanting to lose context each time they stop. It was made for anyone comfortable in a terminal who needs a lightweight way to leave clear notes for their future self about what they were doing, what changed, and what to do next.

The main use cases are study sessions and project work in GitHub repos, but the broader purpose is the same: make terminal-based work easier to resume after interruption. Instead of relying on memory, scattered notes, or long session history, Handoff keeps a small local handoff so you can return to work with context already waiting for you.

## Install

```bash
pipx install --editable .
```

Then run `handoff` from any directory:

```bash
handoff init my-notes
cd my-notes
handoff
```

You can also open an existing repository directly:

```bash
cd path/to/existing-repo
handoff
```

On first run in a directory, `handoff` creates local metadata in `.handoff/` and opens that directory as the active workspace.


## Example use case: learning notes

Use `handoff` as a lightweight study handoff tool:

```bash
handoff init learning
cd learning
handoff
```

During a study session, create or edit notes in the directory. When you are done, press `h` to open the handoff draft and fill in:

- `LAST.md`: what you studied, added, understood, or decided this session.
- `NEXT.md`: what you should study or continue with next time.

When you return later:

```bash
cd learning
handoff
```

The overview shows what happened last session and what to do next, without needing a long session history.

The default tool launcher includes `grok`, `codex`, and `claude`. They must be installed, logged in, and available on `PATH` before launching them from the TUI. Handoff runs providers inside its own agent tabs over stdio; it does not embed their native terminal UI or call provider HTTP APIs.

Existing user configuration with the old default `{codex, claude}` is migrated by adding `grok`; custom tool maps are kept as configured.

User-level preferences live under `~/.handoff/`:

```text
~/.handoff/
  config.yaml
  themes/
  workspaces/
```

Workspace state lives under the active directory's `.handoff/` folder.

## Product shape

See [DESIGN.md](DESIGN.md) for the ACP harness and dual-mode direction.

`handoff` opens a terminal UI for the current directory, previewing files, launching configured editors/tools, and saving handoff summaries.

The product has two modes on one stable handoff spine: a dev mode for a code repository (the current ACP multi-agent harness) and a regular/study mode for notes. The local wiki-link graph is a later study feature; graph support is not part of this validation build.

Workspace metadata lives in readable files inside the current directory:

```text
.handoff/
  WORKSPACE.md
  LAST.md
  NEXT.md
```

The Python implementation is a validation build. File formats and the `handoff` entrypoint should stay stable so the tool can be rewritten later without migrating user data.

## Agent handoff integration

When you open a configured agent tool from `handoff`, such as `grok`, `claude`, or `codex`, `handoff` opens an agent tab in the right pane and generates that tool's memory file (`AGENTS.md` or `CLAUDE.md`) in the workspace root. These files are not created when the app itself opens. The file instructs the agent to:

1. Read `.handoff/WORKSPACE.md` at session start to understand the workspace context.
2. Treat `.handoff/DRAFT.md` as a live handoff ledger and keep the LAST.md section current after material work, including affected files and relevant `git diff` details.
3. Save NEXT.md updates for the end of the agent session unless the next action is already clear and durable.

Agents are also instructed to refresh `.handoff/DRAFT.md` before handing control back after material work, even if you did not say the session is ending.

When you press `h` to open the handoff modal, `handoff` snapshots active agent drafts and pre-populates the fields from the current draft plus run snapshots. NEXT.md items from the existing handoff are merged with draft NEXT.md items so unfinished carryover stays visible unless you remove it in the modal. You review, edit if needed, and save. The draft is deleted after saving.

The tool file is only created if it does not already exist, so your edits are never overwritten.

### Providers and setup

The Grok adapter starts `grok agent stdio`. Codex uses a native ACP executable when configured, or the `@agentclientprotocol/codex-acp` npm package through `npx`; configure the adapter and complete `codex login` first. Claude prefers a `claude-agent-acp` or `claude-code-acp` executable. If neither is installed, it falls back to `claude -p --output-format stream-json --verbose --include-partial-messages`; later turns use `--resume`. This fallback is CLI-controlled: permission denials are reported by Claude, and it does not provide Handoff's ACP permission modal.

Unknown configured commands are unsupported and missing provider binaries are reported in the agent tab. Provider compatibility depends on the installed CLI/adapter and login state; this documentation does not promise live-provider compatibility testing.

### Agent tabs and shortcuts

Use `t` to show the agent board and `1`–`5` to open or focus configured agent tabs. Each tab has a transcript, prompt field, status, permission controls where ACP supports them, and Send/Cancel/Close controls. Closing a tab or pressing `h` snapshots its draft under `.handoff/runs/`; `h` is the human handoff workflow, not an automatic modal after every agent turn. Press `q` to quit; when a draft or live run is pending, choose Save handoff, Quit without saving, or Cancel.

While an agent prompt field is focused, typing remains in the prompt editor. The global prompt-safe shortcuts `Ctrl+h`, `Ctrl+q`, and `Ctrl+s` still open handoff, quit, and logs. Existing editor shortcuts and `$EDITOR` behavior remain available. `s` opens logs, `e` edits the selected file, and `h` saves the handoff.

**Agent memory files** (matched by configured tool name or command):

| Tool | File created |
|---|---|
| grok | `AGENTS.md` |
| claude | `CLAUDE.md` |
| codex | `AGENTS.md` |
| gemini (legacy memory-file support; no agent tab) | `GEMINI.md` |

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

## Themes

`handoff` ships with the `graphite-crimson` theme by default. Custom themes are global user preferences stored in `~/.handoff/themes/`.

```yaml
# ~/.handoff/themes/my-theme.yaml
name: my-theme
dark: true
primary: "#DC143C"
secondary: "#8B0000"
accent: "#C0392B"
warning: "#DC143C"
success: "#8B0000"
error: "#FF3333"
background: "#0d0d0d"
surface: "#171717"
panel: "#222222"
foreground: "#e8e8e8"
```

A copy of `graphite-crimson.yaml` is written to `~/.handoff/themes/` on first run as a starting point to copy and edit.

Color roles:
| Key | Used for |
|---|---|
| `primary` | Focus ring on the file pane, app title |
| `accent` | Focus ring on the preview pane |
| `success` | Last Session panel border and header |
| `warning` | What's Next panel border and header |
| `background` | App background |
| `surface` | Widget backgrounds |
| `panel` | Panel backgrounds, unfocused borders |
| `foreground` | Primary text |
| `secondary` / `error` | Secondary elements, error notifications |

## Dependency management

Poetry manages dependencies. `pipx` makes `handoff` available from any directory via an editable install, so code changes are picked up immediately without reinstalling.

To add a dependency:

```bash
poetry add <package>
pipx reinstall handoff
```

`pipx reinstall` is only needed when dependencies change, not on every code change.

### Running tests

```bash
poetry install
poetry run pytest
```

## Known issues

- PowerShell/Windows Terminal may show extra dark space around the TUI layout. Do not optimize around this yet; test layout primarily in the target terminal and revisit Windows terminal rendering later.
