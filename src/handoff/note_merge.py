"""Combine two edited versions of a note so a person can review the result.

Lines both versions share at the start and end are kept once. When only one version
changed the middle, that change is taken as-is. When both changed it, both versions
are kept between git-style markers for the user to resolve by hand.
"""

from __future__ import annotations

LOCAL_MARKER = "<<<<<<< this machine"
SEPARATOR_MARKER = "======="
REMOTE_MARKER = ">>>>>>> from Nextcloud"


def combine_versions(local_text: str, remote_text: str) -> str:
    local_lines = local_text.splitlines()
    remote_lines = remote_text.splitlines()
    shared_start = _shared_prefix_length(local_lines, remote_lines)
    shared_end = _shared_suffix_length(local_lines[shared_start:], remote_lines[shared_start:])
    local_middle = local_lines[shared_start : len(local_lines) - shared_end]
    remote_middle = remote_lines[shared_start : len(remote_lines) - shared_end]

    if local_middle and remote_middle:
        middle = [LOCAL_MARKER, *local_middle, SEPARATOR_MARKER, *remote_middle, REMOTE_MARKER]
    else:
        middle = local_middle or remote_middle
    merged_lines = local_lines[:shared_start] + middle + local_lines[len(local_lines) - shared_end :]
    return "\n".join(merged_lines) + "\n"


def has_merge_markers(text: str) -> bool:
    return any(line.startswith(LOCAL_MARKER) for line in text.splitlines())


def _shared_prefix_length(first: list[str], second: list[str]) -> int:
    length = 0
    while length < min(len(first), len(second)) and first[length] == second[length]:
        length += 1
    return length


def _shared_suffix_length(first: list[str], second: list[str]) -> int:
    length = 0
    while length < min(len(first), len(second)) and first[-1 - length] == second[-1 - length]:
        length += 1
    return length
