Read `.handoff/WORKSPACE.md` to understand this workspace - its goals, context, and constraints.

# Project rules

## Ownership
- The person who initiated the work is its only owner.
- Never add AI co-authorship, co-signing or attribution anywhere: no `Co-Authored-By` trailers, no "Generated with"
  lines, no AI mentions in commit messages, PR descriptions, code comments, docs or release notes.

## Plain ASCII
- Use only plain ASCII characters (0x00-0x7F) in everything you generate: code, comments, docs, commit messages and
  PR text.
- No em or en dashes, curly quotes, arrows, multiplication signs, ellipsis characters, box-drawing characters or
  emoji. Use `-`, `"`, `'`, `->`, `x`, `...` and `|--` / `` `-- `` instead.
- Exception: content the user wrote, or data that requires non-ASCII (e.g. translations), stays as it is.

## Conventional commits
- Every commit message follows Conventional Commits: `<type>(<optional scope>): <description>`.
- Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert. Mark breaking changes with `!`
  or a `BREAKING CHANGE:` footer.
- One logical change per commit, so history stays easy to trace.

## Enforcement
- These rules are enforced by git hooks in `.githooks/` and by the `rules` CI workflow.
- After cloning, run `git config core.hooksPath .githooks` once to turn on the local hooks.
- Never bypass the checks (`--no-verify`, disabling the workflow). If a check is wrong, fix the check in a
  separate commit.
- Paths that legitimately need non-ASCII (e.g. translations) go in `.asciiignore`, one glob per line.

# Software rules

## Specs and traceability
- **Spec or commits only.** Before starting work, decide and say which, and why. If unsure, ask.
  - Write a spec if there is a real decision to make, unknowns that need a prototype, no obvious "done", several
    commits serving one goal, or risk (data, security, public API, migrations).
  - Otherwise commits are enough, and the commit body says why, not only what.
  - If a small change hits a decision halfway, stop and write a spec.
- **Where specs live.** `specs/NNN-short-name.md`, copied from `specs/_template.md`. One goal per spec. Specs
  that are done, superseded or dropped move to `specs/archive/`; they are never deleted.
- **Traceability.** Commits for a spec carry the footers `Spec: NNN` and `Task: T1`. Tests name the acceptance
  criterion they check. Each PR links its spec.
- **Execution.** While a spec is in progress, make no new decisions. If something isn't covered, park the spec:
  record the gap as an open question, set the status back to `draft`, and stop. The gap is resolved in a
  separate planning session, never by switching the current session to planning.
- **Decisions are human.** AI drafts specs and code; the owner decides. Where a decision, assumption or open
  question comes up, present options and a recommendation, and let the owner decide.

## Development roles
- **Only in development sessions:** one `ready` spec per session. Planning and writing specs happen in separate
  engineering sessions, and small commit-only changes have no fixed roles.
- **Orchestrator (main session):** hands tasks to the roles below, reviews their results against the spec, and
  commits each task with the `Spec:` and `Task:` footers. Doesn't write the code itself.
- **Test writer:** writes tests from the acceptance criteria before the code exists.
- **Implementer:** makes those tests pass. Never edits tests; reports a wrong test or a gap instead.
- **Validator** (when the spec has a Validation section): checks results against inputs outside the
  implementation. Reports findings; the owner decides.
- In Claude Code these are the sub-agents in `.claude/agents/`. In other tools, run each role as a separate
  agent or session with the same instructions.

# Project specifics

## Build and test
- Python 3.11+, managed with Poetry. `poetry install` sets up the virtualenv; `poetry run handoff` runs from source.
- Tests: `poetry run pytest`. Every change keeps the full suite green.
- Format and lint before committing: `poetry run isort src tests`, `poetry run black src tests`,
  `poetry run pylint src/handoff`. On Windows set `PYTHONUTF8=1` first, or isort skips files with non-ASCII.
- Dependency changes go through `poetry add` and are committed together with `poetry.lock`.
- Releases: bump `version` in `pyproject.toml`, add a line to `docs/CHANGELOG.md`, tag `vX.Y.Z`. Details in
  `docs/development.md`.

## Code conventions
- Line length 120; black and isort own formatting, never hand-format.
- Names are full words; variables, arguments and attributes have at least three characters (`x`, `y` allowed).
- Code reads without comments; keep a comment only for a non-obvious reason (OS or library quirk).
- Shared behavior lives in one place: frontmatter and bullets in `documents.py`, unique paths in `paths.py`,
  dialog styling in `DialogScreen` (`tui_forms.py`).
- Pylint complexity checks are on. Some older functions exceed them; never add new ones.
- TUI glyphs (key symbols, em dashes in labels) are intentional and allowed in `src/` and `docs/` via
  `.asciiignore`.

## Product decisions
- The TUI stays in the red (crimson) family. "Effects" means same-hue glow, never new colors. Palette changes
  are mirrored in the user theme `graphite-crimson.yaml` (see `docs/themes.md`).
- No in-app editing or IDE features: editing is delegated to the user's configured editor.
- No embedded terminals: terminal editors and agents open full screen with handoff suspended or in a
  multiplexer (tmux/psmux). Embedding via PTY froze on Windows; don't retry.
- Overview panels (LAST/NEXT) are read-only handoff artifacts, updated at handoff time only; no mid-session task
  management.
- Customised `CLAUDE.md`/`AGENTS.md` files are never rewritten by handoff; only untouched templates are migrated.

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

Write normal human-readable Markdown. Do not write patch or diff notation in `.handoff/DRAFT.md`; bullets should start with `- `, never `+- ` or `-- `. Leave a blank line between bullets.

## LAST.md

### Summary

One or two sentences describing what was accomplished.

### Completed

- One-line conceptual item, ends with path tags like [src/foo.ts][src/bar.ts].

### Open Issues

- Unresolved questions or blockers (use "- None" if there are none).

## NEXT.md

- Next action items for the following session.
