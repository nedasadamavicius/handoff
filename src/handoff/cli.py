from __future__ import annotations

from pathlib import Path

import typer

from handoff.config import DEFAULT_ROOT, ensure_config
from handoff.workspace import initialize_directory_workspace

app = typer.Typer(help="Local-first terminal workspace shell.")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    from handoff.tui import WorkspaceShell
    from handoff.workspace import current_directory_workspace

    WorkspaceShell(ensure_config(), current_directory_workspace(Path.cwd())).run()


@app.command()
def init(
    directory: Path = typer.Argument(..., help="Directory workspace to create."),
    root: Path = typer.Option(DEFAULT_ROOT, "--root", help="Workspace system root.", hidden=True),
) -> None:
    """Create a directory workspace."""
    ensure_config(root)
    workspace = initialize_directory_workspace(directory)
    typer.echo(f"Initialized directory workspace: {workspace.path}")


if __name__ == "__main__":
    app()
