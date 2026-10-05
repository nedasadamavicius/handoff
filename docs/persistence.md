# Keeping handoff notes across machines

Two ways to keep notes outside the repo. Use one, not both.

## Option 1: handoff syncs to your Nextcloud itself (WebDAV)

1. In Nextcloud: Settings > Security > create an **app password**.
2. Run `handoff sync login` and enter your server URL (for example
   `https://cloud.example.com`), username and the app password.
3. That is it. Notes live in `<repo>/.handoff` and are stored remotely under
   `handoff/<repo-id>/`.

- Handoff pulls when it opens in a repo and pushes whenever you save a handoff.
- Saving or quitting shows a "Syncing" box that cannot be closed until the sync
  finishes or fails, so you never leave a machine with unsynced notes.
- Offline: handoff does not block. It says so and syncs the next time it opens
  with a connection.
- Only notes are synced (`LAST/NEXT/WORKSPACE/WORKLOG.md`, `sessions/`, `days/`,
  `weeks/`), never `DRAFT.md`. Deletions are not propagated. If two machines
  changed the same file, the remote copy is saved as `<name>.conflict.md` and
  nothing is overwritten.
- `handoff sync now` and `handoff sync status` run or inspect a sync.
- The app password is stored in `~/.handoff/webdav.token` (or set
  `HANDOFF_WEBDAV_PASSWORD`). Revoke it in Nextcloud at any time.

## Option 2: a folder you sync yourself (junction/symlink)

By default handoff stores notes in `<repo>/.handoff/`. That folder is not meant
to be committed, and other people working on the same repo have their own.
To carry your notes between your own machines, point handoff at a folder that
**you** sync, outside the repo. Handoff links each repo's `.handoff` to
`<state_root>/<repo-id>/`, so nothing is ever added to the repository.

### Setup with your own Nextcloud client

1. Install the Nextcloud desktop client on every machine and sign in to your
   own server (for example `https://cloud.example.com`).
2. Sync a folder, e.g. `~/Nextcloud/handoff`. Wait for the first sync to finish.
3. On each machine run: `handoff state set ~/Nextcloud/handoff`
4. Open handoff in a repo. It links `.handoff` to the synced folder. If the repo
   already has notes it asks before moving them (the old copy is kept as
   `.handoff.local-backup`). `handoff state link` does the same on demand.

Any other synced folder works the same way (Syncthing, Dropbox, a network share).
Check the result with `handoff state status`; undo with `handoff state unset`.

## How it works

- **Repo id** is the normalised `origin` URL (`github.com__owner__repo`), so
  every machine you own resolves to the same folder regardless of local path.
  Repos without a remote use the folder name.
- **Per user:** the store lives in your account, so collaborators never see or
  overwrite your notes.
- **Links:** a directory junction on Windows, a symlink elsewhere.

## Caveats

- Let the sync finish before switching machines. If both machines edit
  `DRAFT.md`, `LAST.md` or `NEXT.md` before syncing, Nextcloud creates a
  "conflict" copy; handoff warns when it finds one at startup.
- If the synced folder is missing at startup, handoff warns and falls back to
  a local `.handoff`.
- If both the repo's `.handoff` and the store already hold notes, handoff
  refuses to merge them; combine by hand and re-run.
- Make sure `.handoff/` is in the repo's `.gitignore` (or your global ignore).
