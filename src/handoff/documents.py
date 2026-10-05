from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

import yaml

MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkdn"}


FRONTMATTER_DELIMITER = "---\n"
BULLET_PREFIXES = ("- ", "* ")
EMPTY_BULLET_MARKERS = {"-", "*", "- None", "* None", "None"}


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (metadata, body); ({}, text) when the frontmatter is absent or malformed."""
    if not text.startswith(FRONTMATTER_DELIMITER):
        return {}, text
    try:
        _, raw_metadata, body = text.split(FRONTMATTER_DELIMITER, 2)
        metadata = yaml.safe_load(raw_metadata) or {}
    except (ValueError, yaml.YAMLError):
        return {}, text
    return (metadata if isinstance(metadata, dict) else {}), body.lstrip()


def render_frontmatter(metadata: dict) -> str:
    return f"{FRONTMATTER_DELIMITER}{yaml.safe_dump(metadata, sort_keys=False).strip()}\n---\n\n"


def is_bullet(line: str) -> bool:
    return line.strip().startswith(BULLET_PREFIXES)


def strip_bullet_prefix(line: str) -> str:
    stripped = line.strip()
    return stripped[2:].strip() if is_bullet(stripped) else stripped


def render_bullets(items: Iterable[str], empty: str = "- None") -> str:
    bullets = [f"- {item}" for item in items]
    return "\n".join(bullets) if bullets else empty


def first_occurrences(items: Iterable[str], key: Callable[[str], str] = str.casefold) -> list[str]:
    """Drop later items whose key was already seen, keeping the original order."""
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        item_key = key(item)
        if item_key not in seen:
            seen.add(item_key)
            unique.append(item)
    return unique


def parse_body_sections(markdown: str) -> dict[str, str]:
    """Sections of a log body, ignoring its H1 title."""
    without_title = "\n".join(line for line in markdown.splitlines() if not line.startswith("# "))
    return parse_markdown_sections(without_title, heading_prefixes=("## ", "### "))


def parse_markdown_sections(
    markdown: str,
    *,
    heading_prefixes: tuple[str, ...] = ("## ",),
) -> dict[str, str]:
    """Collect content under the requested Markdown heading levels."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in markdown.splitlines():
        if line.startswith(heading_prefixes):
            current = line.lstrip("#").strip().lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def strip_yaml_frontmatter(text: str) -> str:
    """Return Markdown content without a leading YAML frontmatter block."""
    return split_frontmatter(text)[1]


def strip_handoff_frontmatter(path: Path) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    body = strip_yaml_frontmatter(text)
    if body != text:
        path.write_text(body, encoding="utf-8")


def is_markdown_file(path: Path) -> bool:
    return path.suffix.lower() in MARKDOWN_SUFFIXES


def strip_first_heading(markdown: str) -> str:
    lines = markdown.splitlines()
    if lines and lines[0].startswith("# "):
        return "\n".join(lines[1:]).lstrip()
    return markdown


def strip_first_subheading(markdown: str) -> str:
    lines = markdown.splitlines()
    if lines and lines[0].startswith("## "):
        return "\n".join(lines[1:]).lstrip()
    return markdown


def render_last_markdown(fields: Mapping[str, str]) -> str:
    parts = ["# Current Session Summary"]
    parts.append("## Summary\n\n" + (fields["summary"].strip() or "Not recorded."))
    parts.append("## Completed\n\n" + normalize_list_text(fields["done"]))
    parts.append("## Open Issues\n\n" + normalize_list_text(fields["open"]))
    if fields.get("evidence", "").strip():
        parts.append("## Evidence\n\n```text\n" + fields["evidence"].strip() + "\n```")
    return "\n\n".join(parts)


def render_next_markdown(text: str) -> str:
    return "# Next\n\n" + normalize_list_text(text)


def normalize_list_text(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return "- None"
    lines = []
    for line in cleaned.splitlines():
        item = line.strip()
        if not item:
            continue
        lines.append(item if item.startswith(("-", "*")) else f"- {item}")
    return "\n".join(lines) or "- None"


def strip_next_heading(markdown: str) -> str:
    lines = markdown.splitlines()
    if lines and lines[0].strip().lower() in {"# next", "## next.md"}:
        return "\n".join(lines[1:]).lstrip()
    return strip_first_heading(markdown)


def deduplicate_next_lines(text: str) -> str:
    kept_lines: list[str] = []
    seen_lines: set[str] = set()
    for line in text.splitlines():
        normalized = line.strip()
        if not normalized:
            if kept_lines and kept_lines[-1] != "":
                kept_lines.append("")
            continue
        if normalized.lower() in seen_lines:
            continue
        seen_lines.add(normalized.lower())
        kept_lines.append(line)
    while kept_lines and not kept_lines[-1].strip():
        kept_lines.pop()
    return "\n".join(kept_lines)


def merge_next_text(existing: str, incoming: str) -> str:
    existing_body = strip_next_heading(existing).strip()
    incoming_body = strip_next_heading(incoming).strip()
    if not incoming_body:
        return existing_body
    if not existing_body or existing_body == "- Define the next action.":
        return deduplicate_next_lines(incoming_body)

    return deduplicate_next_lines(existing_body + "\n" + incoming_body)
