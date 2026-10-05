Read `.handoff/WORKSPACE.md` to understand this workspace - its goals, context, and constraints.

## Priority

Handle this before other work, without waiting to be asked. Remove this section once it ships.

- Include committed work in the handoff's changed-files list. The Evidence "Files changed" list is built only from `git status` (`changed_files_from_status` in `src/handoff/git.py`), so files a session already committed are missing. Their path source tags then get dropped as "not in changed files", leaving Completed bullets untagged. Also list the files changed by commits made since the session started (for example `git diff --name-only <session-start commit>..HEAD`, or `git log --since=<session start> --name-only`), merge them with uncommitted files, and number them together. Add tests.

## Git

Use conventional commit messages (`type(scope): description`). Use only ASCII characters in commit messages. Never add a `Co-Authored-By` trailer to commits.

## Handoff

During the session, keep `.handoff/DRAFT.md` current when you make material progress. Treat it as the live handoff ledger, not only an exit note. After meaningful code or content changes, update the draft's LAST.md section with:

- what was done and **why** it was done, at the conceptual level
- unresolved questions or blockers

The Completed section must describe shipped changes, decisions, fixes, or artifacts created. Do not list agent process steps such as reading, re-reading, inspecting, reviewing, searching, opening files, or running tests. Mention only the concrete outcome those steps produced.

**One-liners, concept over detail.** The reader wants a semi-high-level picture of what happened last time, not a changelog of files. Each Completed bullet is a single brief, concrete, informative line stating the idea and outcome (e.g. "Progression now keyed per workout slot, so sharing across weeks works"). Do not name files, functions, or how each was changed in the bullet text; use source tags to point at files instead. No sub-bullets, no multi-sentence bullets. Prefer fewer bullets: merge related changes into one line. Rewrite the Completed section on each update instead of appending, merging or dropping bullets that no longer matter, so the draft stays short as the session grows.

**Source tags.** Do not write a file list in the draft; the handoff tool generates the numbered changed-files list. End a Completed bullet with the repo-relative path of each file it affected in square brackets, using forward slashes, e.g. `[src/foo.ts][src/bar.ts]`. Tag by path, never by number: the tool converts paths to list numbers when the handoff is rendered. Only tag files that actually changed in git. Omit tags on bullets that touch no files (decisions, rationale).

**Keep it tight.** If a reader wouldn't need a piece of information to pick up where you left off, cut it. Err heavily on the side of brevity.

Before handing control back to the user after material work, make sure `.handoff/DRAFT.md` reflects the latest completed work and evidence. Do this even if the user did not say the session is ending.

Do not spend time expanding the NEXT.md section during ordinary progress updates. Fill or revise NEXT.md only when the agent session is ending or when the next action is already clear and durable. When updating NEXT.md, actively remove any items that have already been completed. Do not let stale tasks accumulate.

Before ending any session, make sure `.handoff/DRAFT.md` uses this exact format:

Write normal human-readable Markdown. Do not write patch or diff notation in `.handoff/DRAFT.md`; bullets should start with `- `, never `+- ` or `-- `.

## LAST.md

### Summary

One or two sentences describing what was accomplished.

### Completed

- One-line conceptual item, ends with path tags like [src/foo.ts][src/bar.ts].

### Open Issues

- Unresolved questions or blockers (use "- None" if there are none).

## NEXT.md

- Next action items for the following session.
