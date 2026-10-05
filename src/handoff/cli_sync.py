from __future__ import annotations

from pathlib import Path

import typer

from handoff.cli_common import ConfigRoot, RepositoryDirectory
from handoff.config import DEFAULT_ROOT, AppConfig, ensure_config, update_config_value
from handoff.note_sync import has_unsynced, sync_for_repo
from handoff.webdav import (
    PASSWORD_ENVIRONMENT_VARIABLE,
    AuthError,
    OfflineError,
    SyncError,
    SyncSettings,
    WebDAVClient,
    load_password,
    save_password,
)

sync_app = typer.Typer(help="Sync handoff notes with your Nextcloud (WebDAV).")


def run_sync(config: AppConfig, repo: Path, *, report_when_unconfigured: bool = False) -> bool:
    """Sync with friendly output; True when a sync completed."""
    try:
        report = sync_for_repo(config.root, config.sync, repo, None)
    except OfflineError as error:
        typer.echo(f"Offline ({error}); notes will sync next time handoff opens with a connection.", err=True)
        return False
    except SyncError as error:
        typer.echo(f"Sync error: {error}", err=True)
        return False
    if report is None:
        if report_when_unconfigured:
            typer.echo("Sync is not set up; run `handoff sync login`.", err=True)
        return False
    typer.echo(f"Synced: {report.summary()}")
    return True


def pull_on_open(config: AppConfig, repo: Path) -> None:
    if config.sync is not None and load_password(config.root):
        typer.echo("Syncing handoff notes...")
        run_sync(config, repo)


@sync_app.command("login")
def sync_login(
    server: str = typer.Option(..., prompt="Nextcloud URL (e.g. https://cloud.example.com)"),
    username: str = typer.Option(..., prompt=True),
    password: str = typer.Option(
        ...,
        prompt="App password (visible as you type; it is revocable in Nextcloud)",
        envvar=PASSWORD_ENVIRONMENT_VARIABLE,
    ),
    folder: str = typer.Option("handoff", help="Remote folder holding all repos."),
    root: ConfigRoot = DEFAULT_ROOT,
) -> None:
    """Store credentials (use a Nextcloud app password) and test the connection."""
    settings = SyncSettings(server.rstrip("/"), username, folder.strip("/") or "handoff")
    try:
        WebDAVClient(settings, password).list_directory("")
    except AuthError as error:
        raise typer.BadParameter("login rejected; create an app password in Nextcloud Settings > Security") from error
    except SyncError as error:
        raise typer.BadParameter(f"could not reach server: {error}") from error
    ensure_config(root)
    update_config_value(root, "sync", {"server": settings.server, "username": username, "folder": settings.folder})
    save_password(root, password)
    typer.echo("Sync configured. Notes now sync when you open handoff and whenever a handoff is saved.")


@sync_app.command("now")
def sync_now(directory: RepositoryDirectory = Path("."), root: ConfigRoot = DEFAULT_ROOT) -> None:
    """Sync this repo's notes immediately."""
    if not run_sync(ensure_config(root), directory.resolve(), report_when_unconfigured=True):
        raise typer.Exit(1)


@sync_app.command("status")
def sync_status(directory: RepositoryDirectory = Path("."), root: ConfigRoot = DEFAULT_ROOT) -> None:
    """Show sync configuration and whether local notes are unsynced."""
    config = ensure_config(root)
    if config.sync is None:
        typer.echo("Sync not configured (run `handoff sync login`).")
        return
    typer.echo(f"server: {config.sync.server}  user: {config.sync.username}  folder: {config.sync.folder}")
    typer.echo(f"password: {'set' if load_password(config.root) else 'MISSING'}")
    typer.echo(f"unsynced local changes: {'yes' if has_unsynced(directory.resolve() / '.handoff') else 'no'}")
