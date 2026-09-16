from __future__ import annotations

from pathlib import Path
import sys

import typer

from handoff.config import DEFAULT_ROOT, ensure_config
from handoff.workspace import WORKSPACE_MODES, initialize_directory_workspace

app = typer.Typer(help="Local-first terminal workspace shell.")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    from handoff.tui import WorkspaceShell

    WorkspaceShell(ensure_config(), initialize_directory_workspace(Path.cwd(), workspace_mode_value=None)).run()


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


if __name__ == "__main__":
    app()
