# Workspaces and study mode

User-level preferences live under `~/.handoff/`:

```text
~/.handoff/
  config.yaml
  themes/
  workspaces/
```

Workspace state lives under the active directory's `.handoff/` folder.

## Product shape

See [DESIGN.md](DESIGN.md) for the external-session manager and workspace direction.

`handoff` opens a terminal UI for the current directory, previewing files, launching configured editors/tools, and saving handoff summaries.

The product has two modes on one stable handoff spine: Coding and Study. Both retain workspace context, handoff notes, and external AI agent sessions. Study workspaces additionally expose the local Markdown knowledge lookup with `g`.

Workspace metadata lives in readable files inside the current directory:

```text
.handoff/
  WORKSPACE.md
  LAST.md
  NEXT.md
```

The Python implementation is a validation build. File formats and the `handoff` entrypoint should stay stable so the tool can be rewritten later without migrating user data.

## Example: learning notes

Use `handoff` as a lightweight study handoff tool:

```bash
handoff init learning --mode study
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

The overview shows what happened last session and what to do next, without needing a long session history. In a Study workspace, press `g` to browse the local knowledge graph: a read-only note preview on the left and a node-link graph of all notes on the right. Notes are dots sized by how linked they are; the selected note and its links are highlighted. Click a node to preview it, drag a node to rearrange it, drag empty space to pan, scroll to zoom, and press `e` to open the note in your configured editor. Handoff understands `[[wiki-links]]` and local Markdown links; the graph stays on disk-free, local repository data.
