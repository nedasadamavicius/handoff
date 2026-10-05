from __future__ import annotations

from pathlib import Path
import sys

import typer

from handoff.config import DEFAULT_ROOT, ensure_config
from handoff.workspace import (
    WORKSPACE_MODES,
    current_directory_workspace,
    auto_migrate_memory_files,
    initialize_directory_workspace,
    memory_file_migration,
)

app = typer.Typer(help="Local-first terminal workspace shell.")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    from handoff.tui import WorkspaceShell

    config = ensure_config()
    workspace = initialize_directory_workspace(Path.cwd(), workspace_mode_value=None)
    if config.source_tags:
        for path in auto_migrate_memory_files(workspace, config.tools):
            typer.echo(f"Upgraded {path.name} to source-tag handoff instructions.")
    WorkspaceShell(config, workspace).run()


@app.command()
def init(
    directory: Path = typer.Argument(..., help="Directory workspace to create."),
    root: Path = typer.Option(DEFAULT_ROOT, "--root", help="User config root.", hidden=True),
    mode: str | None = typer.Option(None, "--mode", help="Workspace mode: study or coding."),
) -> None:
    """Create a directory workspace."""
    if mode is not None and mode not in WORKSPACE_MODES:
        raise typer.BadParameter("must be 'study' or 'coding'", param_hint="--mode")
    if mode is None and sys.stdin.isatty():
        mode = typer.prompt("Workspace mode (study/coding)", default="coding")
        if mode not in WORKSPACE_MODES:
            raise typer.BadParameter("must be 'study' or 'coding'")
    ensure_config(root)
    workspace = initialize_directory_workspace(directory, workspace_mode_value=mode or "coding")
    typer.echo(f"Initialized directory workspace: {workspace.path}")


@app.command("migrate-instructions")
def migrate_instructions(
    directory: Path = typer.Argument(Path("."), help="Workspace directory."),
    root: Path = typer.Option(DEFAULT_ROOT, "--root", help="User config root.", hidden=True),
    yes: bool = typer.Option(False, "--yes", help="Apply without asking."),
) -> None:
    """Upgrade untouched CLAUDE.md / AGENTS.md handoff instructions to source-tag bullets."""
    config = ensure_config(root)
    workspace = current_directory_workspace(directory)
    found = False
    for name, command in config.tools.items():
        migration = memory_file_migration(workspace, name, command)
        if migration is None:
            continue
        path, text = migration
        found = True
        typer.echo(f"{path.name} matches the previous handoff template and can be upgraded.")
        if yes or typer.confirm(f"Overwrite {path.name} with the source-tag instructions?", default=False):
            path.write_text(text, encoding="utf-8")
            typer.echo(f"Updated {path}")
    if not found:
        typer.echo("Nothing to migrate. Customised instruction files are never rewritten; merge the new "
                   "'Handoff' block by hand (see _SOURCE_TAGS_MEMORY_TEMPLATE in workspace.py).")


if __name__ == "__main__":
    app()
