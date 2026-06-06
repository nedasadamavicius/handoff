# handoff

Local-first terminal workspace shell for Markdown workspaces and short session handoffs.

## Install for development

```bash
poetry install
poetry run ws init my-notes
cd my-notes
poetry run ws
```

You can also use an existing repository directly:

```bash
cd path/to/existing-repo
poetry run ws
```

On first run in a directory, `ws` creates local metadata in `.ws/` and opens that directory as the active workspace.

## Example use case: learning notes

Use `ws` as a lightweight study handoff tool:

```bash
poetry run ws init learning
cd learning
poetry run ws
```

During a study session, create or edit notes in the directory. When you are done, press `h` to open the handoff draft and fill in:

- `LAST.md`: what you studied, added, understood, or decided this session.
- `NEXT.md`: what you should study or continue with next time.

When you return later:

```bash
cd learning
poetry run ws
```

The overview shows what happened last session and what to do next, without needing a long session history.

Configure external tools only after they are installed and available on `PATH`:

```yaml
tools:
  codex: "codex"
  helix: "hx ."
```

## Product shape

`ws` opens a terminal UI for the current directory, previewing files, launching configured editors/tools, and saving handoff summaries.

Workspace metadata lives in readable files inside the current directory:

```text
.ws/
  WORKSPACE.md
  LAST.md
  NEXT.md
```

The Python implementation is a validation build. File formats and the `ws` entrypoint should stay stable so the tool can be rewritten later without migrating user data.

## Agent handoff integration

When you open a configured agent tool from `ws`, such as `claude` or `codex`, `ws` generates that tool's memory file (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, etc.) in the workspace root. These files are not created when the app itself opens. The file instructs the agent to:

1. Read `.ws/WORKSPACE.md` at session start to understand the workspace context.
2. Treat `.ws/DRAFT.md` as a live handoff ledger and keep the LAST.md section current after material work, including affected files and relevant `git diff` details.
3. Save NEXT.md updates for the end of the agent session unless the next action is already clear and durable.

Agents are also instructed to refresh `.ws/DRAFT.md` before handing control back after material work, even if you did not say the session is ending.

When you press `h` to open the handoff modal, `ws` checks for `.ws/DRAFT.md` and pre-populates the fields from the agent's draft. NEXT.md items from the existing handoff are merged with draft NEXT.md items so unfinished carryover stays visible unless you remove it in the modal. You review, edit if needed, and save. The draft is deleted after saving.

After a Codex tool session exits, `ws` asks the most recent Codex session to refresh `.ws/DRAFT.md` before opening the handoff modal by running `codex exec resume --last` with a focused draft-finalization prompt.

The tool file is only created if it does not already exist, so your edits are never overwritten.

**Supported tools** (matched by configured tool name or command):

| Tool | File created |
|---|---|
| claude | `CLAUDE.md` |
| codex | `AGENTS.md` |
| gemini | `GEMINI.md` |

To add a tool, configure it in `~/.ws/config.yaml`:

```yaml
tools:
  claude: "claude"
```

Then open that tool from `ws`. The matching memory file is created only for the tool being opened, just before it starts.

**Draft format** (`.ws/DRAFT.md`):

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

`ws` ships with the `graphite-crimson` theme by default. You can switch to any built-in Textual theme or create your own.

**Switch theme** — add a `theme` key to `~/.ws/config.yaml`:

```yaml
theme: textual-dark
```

**Create a custom theme** — drop a YAML file in `~/.ws/themes/`:

```yaml
# ~/.ws/themes/my-theme.yaml
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

Then set `theme: my-theme` in your config. The file is discovered automatically on next launch — no restart of any service needed.

A copy of `graphite-crimson.yaml` is written to `~/.ws/themes/` on first run as a starting point to copy and edit.

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

## Known issues

- PowerShell/Windows Terminal may show extra dark space around the TUI layout. Do not optimize around this yet; test layout primarily in the target terminal and revisit Windows terminal rendering later.
