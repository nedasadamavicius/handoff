# Development

## Dependency management

Poetry manages dependencies. `pipx` makes `handoff` available from any directory via an editable install, so code changes are picked up immediately without reinstalling.

To add a dependency:

```bash
poetry add <package>
pipx reinstall handoff
```

`pipx reinstall` is only needed when dependencies change, not on every code change.

## Running tests

```bash
poetry install
poetry run pytest
```

## Known issues

- PowerShell/Windows Terminal may show extra dark space around the TUI layout. Do not optimize around this yet; test layout primarily in the target terminal and revisit Windows terminal rendering later.
