"""Source tags: agents tag Completed bullets by path, the tool resolves them to [n].

Agents write ``[src/foo.py]``; at handoff render time each path tag is replaced
by ``[n]``, the 1-based index of that path in the numbered changed-files list
shown alongside it. Numbers are only ever produced from the list in hand, so
they cannot point at the wrong file. Unknown paths and bare numeric tags are
dropped rather than guessed.
"""

from __future__ import annotations

import re


_TAG = re.compile(r"([ 	]*)\[([^\[\]\s()]+)\](?!\()")
_TRAILING_NUMERIC = re.compile(r"(?:\[\d+\])+\s*$")


def _norm(path: str) -> str:
    path = path.strip().strip("\"'").replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def number_files(files: list[str]) -> list[str]:
    """Deterministic, de-duplicated order so numbering is stable for a given set."""
    return sorted({_norm(item) for item in files if _norm(item)}, key=str.lower)


def format_numbered(files: list[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(files, 1))


def _lookup(path: str, files: list[str]) -> int | None:
    key = _norm(path)
    for index, item in enumerate(files, 1):
        if item == key:
            return index
    for index, item in enumerate(files, 1):
        # Untracked directories appear in git status as "dir/".
        if item.endswith("/") and key.startswith(item):
            return index
    return None


def _looks_like_path(token: str) -> bool:
    return "/" in token or "\\" in token or "." in token


def resolve_source_tags(text: str, files: list[str]) -> tuple[str, list[str]]:
    """Replace path tags with [n]. Returns (text, dropped_tags).

    ``files`` must be the already-numbered list (see ``number_files``).
    """
    dropped: list[str] = []

    def replace(match: re.Match[str]) -> str:
        lead, token = match.group(1), match.group(2)
        if token.isdigit():
            dropped.append(token)  # agents must not guess numbers
            return ""
        if not _looks_like_path(token):
            return match.group(0)  # e.g. a [x] checkbox
        index = _lookup(token, files)
        if index is None:
            dropped.append(token)
            return ""
        return f"{lead}[{index}]"

    return _TAG.sub(replace, text), dropped


def strip_numeric_tags(text: str) -> str:
    """Remove trailing [n] tags; used where bullets leave their session's file list."""
    return "\n".join(_TRAILING_NUMERIC.sub("", line).rstrip() for line in text.splitlines())
