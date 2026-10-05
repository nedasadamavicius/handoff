from __future__ import annotations

from pathlib import Path


def unique_path(directory: Path, stem: str, suffix: str = ".md") -> Path:
    """First of ``stem``, ``stem-2``, ``stem-3``... that does not exist yet in ``directory``."""
    candidate = directory / f"{stem}{suffix}"
    attempt = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{attempt}{suffix}"
        attempt += 1
    return candidate
