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

## Known issues

- PowerShell/Windows Terminal may show extra dark space around the TUI layout. Do not optimize around this yet; test layout primarily in the target terminal and revisit Windows terminal rendering later.
