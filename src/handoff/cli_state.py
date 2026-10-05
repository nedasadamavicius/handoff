from __future__ import annotations

import sys
from pathlib import Path

import typer

from handoff.cli_common import ConfigRoot, RepositoryDirectory
from handoff.config import DEFAULT_ROOT, ensure_config, update_config_value
from handoff.git import repository_id
from handoff.state import BACKUP_DIRECTORY_NAME, LinkStatus, conflict_files, link_state

state_app = typer.Typer(help="Keep handoff notes outside the repo in a folder you sync (e.g. Nextcloud).")


def link_repository_state(repo: Path, state_root: Path | None, *, interactive: bool) -> None:
    result = link_state(repo, state_root)
    if result.status is LinkStatus.NEEDS_MIGRATION:
        if interactive and sys.stdin.isatty() and typer.confirm(result.message, default=False):
            result = link_state(repo, state_root, migrate=True)
            typer.echo(f"Moved .handoff to {result.target} (old copy kept as {BACKUP_DIRECTORY_NAME}).")
        else:
            typer.echo("Existing .handoff not moved; run `handoff state link` to migrate.")
    elif result.status is LinkStatus.LINKED:
        typer.echo(f".handoff now stored in {result.target}")
    elif result.status in {LinkStatus.CONFLICT, LinkStatus.UNAVAILABLE}:
        typer.echo(f"warning: {result.message}", err=True)
    if result.target and result.status in {LinkStatus.LINKED, LinkStatus.ALREADY_LINKED}:
        for path in conflict_files(result.target):
            typer.echo(f"warning: sync conflict file {path}", err=True)


@state_app.command("set")
def state_set(
    path: Path = typer.Argument(..., help="Synced folder, e.g. ~/Nextcloud/handoff."),
    root: ConfigRoot = DEFAULT_ROOT,
) -> None:
    """Choose the folder that stores handoff notes for all your repos."""
    state_root = path.expanduser().resolve()
    state_root.mkdir(parents=True, exist_ok=True)
    ensure_config(root)
    update_config_value(root, "state_root", str(state_root))
    typer.echo(f"state_root set to {state_root}. Open handoff in a repo (or run `handoff state link`) to link it.")


@state_app.command("unset")
def state_unset(root: ConfigRoot = DEFAULT_ROOT) -> None:
    """Stop using an external state folder (existing links are left untouched)."""
    ensure_config(root)
    update_config_value(root, "state_root", None)
    typer.echo("state_root cleared.")


@state_app.command("link")
def state_link(directory: RepositoryDirectory = Path("."), root: ConfigRoot = DEFAULT_ROOT) -> None:
    """Link this repo's .handoff to the state folder, offering to migrate existing notes."""
    config = ensure_config(root)
    if config.state_root is None:
        raise typer.BadParameter("no state_root configured; run `handoff state set <folder>` first")
    link_repository_state(directory.resolve(), config.state_root, interactive=True)


@state_app.command("status")
def state_status(directory: RepositoryDirectory = Path("."), root: ConfigRoot = DEFAULT_ROOT) -> None:
    """Show where this repo's handoff notes are stored."""
    config = ensure_config(root)
    link = directory.resolve() / ".handoff"
    typer.echo(f"state_root: {config.state_root or '(not set; notes stay in the repo .handoff)'}")
    typer.echo(f"repo id:    {repository_id(directory.resolve())}")
    typer.echo(f".handoff:   {link.resolve() if link.exists() else '(missing)'}")
