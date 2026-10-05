# Development

## Setup

Poetry manages dependencies and builds. Install it once with `pipx install poetry`, then:

```bash
poetry install                 # creates the virtualenv with runtime and dev dependencies
poetry run handoff             # run from source
pipx install --editable .      # optional: a global `handoff` that follows your working copy
```

To add a dependency:

```bash
poetry add <package>           # or: poetry add --group dev <package>
pipx reinstall handoff         # only if you use the global editable install
```

Commit `poetry.lock` with every dependency change. After editing `pyproject.toml` by hand, run `poetry lock`.

## Building and releasing

```bash
poetry build                   # writes dist/*.whl and dist/*.tar.gz
```

Test a build before sharing it: install the wheel into a fresh virtualenv outside the repo and run `handoff --help`.

Bump `version` in `pyproject.toml`, add a line to [CHANGELOG](CHANGELOG.md), and tag the commit (`git tag v0.2.0`). Anyone can then install that exact version with `pipx install git+https://github.com/nedasadamavicius/handoff.git@v0.2.0`.

## Running tests

```bash
poetry install
poetry run pytest
```

## Code standards

Formatting and linting are configured in `pyproject.toml`.

```bash
poetry run isort src tests
poetry run black src tests
poetry run pylint src/handoff
```

- On Windows set `PYTHONUTF8=1` first, or isort skips files containing non-ASCII characters.
- Line length is 120; `black` and `isort` own formatting, so do not hand-format.
- Names are words, not abbreviations. Variables, arguments and attributes need at least three characters (`x` and `y` are allowed for coordinates). Pylint enforces this.
- Write code that reads without comments. Keep a comment only for a non-obvious reason (an OS or library quirk), never to say what the next line does.
- Shared behavior lives in one place: frontmatter and bullet helpers in `documents.py`, unique paths in `paths.py`, dialog styling in `DialogScreen` (`tui_forms.py`).
- Pylint complexity checks (branches, statements, arguments) are on. A few older functions still exceed them; do not add new ones.

## Persistence

See [Keeping handoff notes across machines](persistence.md) for the Nextcloud sync and synced-folder options.

## Known issues

- PowerShell/Windows Terminal may show extra dark space around the TUI layout. Do not optimize around this yet; test layout primarily in the target terminal and revisit Windows terminal rendering later.
