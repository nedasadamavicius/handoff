"""Local Markdown knowledge graph used by study workspaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from handoff.documents import MARKDOWN_SUFFIXES


IGNORED_DIRECTORIES = {
    ".git", ".handoff", ".pytest_cache", "__pycache__", "node_modules",
    "vendor", "venv", ".venv", "dist", "build", "target",
}
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"!?(?:\[[^\]]*\])\(([^)#\s]+)(?:#[^)]+)?\)")


@dataclass
class Note:
    path: Path
    title: str
    content: str
    outgoing: list[Path] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    incoming: list[Path] = field(default_factory=list)


@dataclass
class KnowledgeIndex:
    root: Path
    notes: dict[Path, Note]

    @classmethod
    def build(cls, root: Path) -> "KnowledgeIndex":
        root = root.resolve()
        notes: dict[Path, Note] = {}
        for path in _markdown_files(root):
            relative = path.relative_to(root)
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            heading = next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), "")
            notes[relative] = Note(path=relative, title=heading or path.stem, content=content)

        by_name: dict[str, list[Path]] = {}
        for path in notes:
            by_name.setdefault(path.name.lower(), []).append(path)
            by_name.setdefault(path.stem.lower(), []).append(path)
        for note in notes.values():
            link_source = re.sub(r"```.*?```", "", note.content, flags=re.DOTALL)
            link_source = re.sub(r"`[^`]*`", "", link_source)
            targets = [*WIKILINK_RE.findall(link_source), *MARKDOWN_LINK_RE.findall(link_source)]
            for raw in targets:
                if _is_external(raw):
                    continue
                target = _resolve_target(note.path, raw, notes, by_name)
                if target is None:
                    note.unresolved.append(raw)
                elif target not in note.outgoing:
                    note.outgoing.append(target)
        for note in notes.values():
            for target in note.outgoing:
                notes[target].incoming.append(note.path)
        return cls(root, notes)

    def search(self, query: str) -> list[Note]:
        query = query.strip().lower()
        values = list(self.notes.values())
        if not query:
            return sorted(values, key=lambda item: str(item.path).lower())
        def score(note: Note) -> tuple[int, str]:
            title = note.title.lower()
            path = str(note.path).lower()
            if title == query:
                rank = 0
            elif title.startswith(query):
                rank = 1
            elif query in title:
                rank = 2
            elif query in path:
                rank = 3
            elif query in note.content.lower():
                rank = 4
            else:
                rank = 99
            return rank, path
        return sorted((note for note in values if score(note)[0] < 99), key=score)

    def neighbors(self, path: Path) -> tuple[list[Note], list[Note]]:
        note = self.notes[path]
        return ([self.notes[item] for item in note.outgoing], [self.notes[item] for item in note.incoming])


def _markdown_files(root: Path) -> list[Path]:
    result: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in MARKDOWN_SUFFIXES:
            relative_parts = path.relative_to(root).parts
            if not any(part in IGNORED_DIRECTORIES or part.startswith(".") for part in relative_parts):
                result.append(path)
    return sorted(result, key=lambda item: str(item).lower())


def _resolve_target(source: Path, raw: str, notes: dict[Path, Note], by_name: dict[str, list[Path]]) -> Path | None:
    raw = raw.split("|", 1)[0].strip().replace("\\", "/")
    if not raw:
        return None
    candidate = Path(raw)
    candidates = []
    if candidate.suffix.lower() in MARKDOWN_SUFFIXES:
        candidates.append(candidate)
    else:
        candidates.extend((candidate.with_suffix(suffix) for suffix in (".md", ".markdown")))
    source_dir = source.parent
    for item in candidates:
        for resolved in (source_dir / item, item):
            normalized = Path(str(resolved).replace("\\", "/"))
            if normalized in notes:
                return normalized
    matches = by_name.get(candidate.name.lower(), []) + by_name.get(candidate.stem.lower(), [])
    unique = list(dict.fromkeys(matches))
    return unique[0] if len(unique) == 1 else None


def _is_external(raw: str) -> bool:
    target = raw.split("|", 1)[0].strip().lower()
    return not target or "://" in target or target.startswith(("mailto:", "#", "/"))
