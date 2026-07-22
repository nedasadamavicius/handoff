from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkdn"}


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
    if not text.startswith("---\n"):
        return text
    try:
        _, _frontmatter, body = text.split("---\n", 2)
    except ValueError:
        return text
    return body.lstrip()


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
    merged: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        normalized = line.strip()
        if not normalized:
            if merged and merged[-1] != "":
                merged.append("")
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(line)
    while merged and not merged[-1].strip():
        merged.pop()
    return "\n".join(merged)


def merge_next_text(existing: str, incoming: str) -> str:
    existing_body = strip_next_heading(existing).strip()
    incoming_body = strip_next_heading(incoming).strip()
    if not incoming_body:
        return existing_body
    if not existing_body or existing_body == "- Define the next action.":
        return deduplicate_next_lines(incoming_body)

    return deduplicate_next_lines(existing_body + "\n" + incoming_body)
