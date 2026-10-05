from __future__ import annotations

from pathlib import Path

from handoff.launcher import split_command
from handoff.workspace import Workspace

TOOL_MEMORY_FILES: dict[str, str] = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
}

_LEGACY_MEMORY_TEMPLATE = """\
Read `.handoff/WORKSPACE.md` to understand this workspace - its goals, context, and constraints.

## Git

Use conventional commit messages (`type(scope): description`). Use only ASCII characters in commit messages. Never add a `Co-Authored-By` trailer to commits.

During the session, keep `.handoff/DRAFT.md` current when you make material progress. Treat it as the live handoff ledger, not only an exit note. After meaningful code or content changes, update the draft's LAST.md section with:

- what was done and **why** it was done
- only the files that matter — not a full `git diff` dump, just the relevant changed files and what changed in them
- unresolved questions or blockers

The Completed section must describe shipped changes, decisions, fixes, or artifacts created. Do not list agent process steps such as reading, re-reading, inspecting, reviewing, searching, opening files, or running tests. Mention only the concrete outcome those steps produced.

**Keep it tight.** Each bullet should be one concise line. No walls of text. If a reader wouldn't need a piece of information to pick up where you left off, cut it. Err heavily on the side of brevity — document what's important and why, not every detail.

Before handing control back to the user after material work, make sure `.handoff/DRAFT.md` reflects the latest completed work and evidence. Do this even if the user did not say the session is ending.

Do not spend time expanding the NEXT.md section during ordinary progress updates. Fill or revise NEXT.md only when the agent session is ending or when the next action is already clear and durable. When updating NEXT.md, actively remove any items that have already been completed — do not let stale tasks accumulate.

Before ending any session, make sure `.handoff/DRAFT.md` uses this exact format:

Write normal human-readable Markdown. Do not write patch or diff notation in `.handoff/DRAFT.md`; bullets should start with `- `, never `+- ` or `-- `.

## LAST.md

### Summary

One or two sentences describing what was accomplished.

### Completed

- List of completed items.

### Open Issues

- Unresolved questions or blockers (use "- None" if there are none).

## NEXT.md

- Next action items for the following session.
"""


_SOURCE_TAGS_MEMORY_TEMPLATE = """\
Read `.handoff/WORKSPACE.md` to understand this workspace - its goals, context, and constraints.

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
"""


def memory_template(source_tags: bool = True) -> str:
    return _SOURCE_TAGS_MEMORY_TEMPLATE if source_tags else _LEGACY_MEMORY_TEMPLATE


def _memory_filename(tool_name: str, command: str) -> str | None:
    parts = split_command(command)
    names = {tool_name.lower()}
    if parts:
        names.add(Path(parts[0].strip('"')).name.lower())
    aliases = {"openai": "codex", "xai": "grok"}
    for name in names:
        key = aliases.get(name, name)
        if key in TOOL_MEMORY_FILES:
            return TOOL_MEMORY_FILES[key]
    return None


def ensure_tool_files(workspace: Workspace, tools: dict[str, str], source_tags: bool = True) -> None:
    for name, command in tools.items():
        ensure_tool_file(workspace, name, command, source_tags)


def ensure_tool_file(workspace: Workspace, tool_name: str, command: str, source_tags: bool = True) -> None:
    filename = _memory_filename(tool_name, command)
    if filename is None:
        return
    path = workspace.path / filename
    if not path.exists():
        path.write_text(memory_template(source_tags), encoding="utf-8")


def memory_file_migration(workspace: Workspace, tool_name: str, command: str) -> tuple[Path, str] | None:
    """Return (path, new_text) if an untouched legacy instruction file can be upgraded.

    Only files that exactly match the legacy template are offered; customised
    files are never rewritten. Callers must ask the user before writing.
    """
    filename = _memory_filename(tool_name, command)
    if filename is None:
        return None
    path = workspace.path / filename
    if not path.exists() or path.read_text(encoding="utf-8") != _LEGACY_MEMORY_TEMPLATE:
        return None
    return path, _SOURCE_TAGS_MEMORY_TEMPLATE


def auto_migrate_memory_files(workspace: Workspace, tools: dict[str, str]) -> list[Path]:
    migrated: list[Path] = []
    for name, command in tools.items():
        migration = memory_file_migration(workspace, name, command)
        if migration is None:
            continue
        path, text = migration
        path.write_text(text, encoding="utf-8")
        migrated.append(path)
    return migrated
