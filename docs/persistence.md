# Keeping handoff notes across machines

Two ways to keep notes outside the repo. Use one, not both.

## Option 1: handoff syncs to your Nextcloud itself (WebDAV)

Handoff talks to your Nextcloud directly over WebDAV, so there is no desktop
client to install and handoff can wait for the sync to finish. This option has
only been exercised against a simulated server so far; report anything odd you
see against a real one.

### What you need

- A Nextcloud server you can reach from every machine, over HTTPS
  (for example `https://cloud.example.com`). The URL is the address you open in
  the browser, without `/index.php` or `/apps/...`. If Nextcloud lives in a
  subfolder, include it (`https://example.com/nextcloud`).
- A Nextcloud account. If it uses two-factor authentication (or you simply do
  not want to hand handoff your real password) you need an app password, so
  create one regardless.
- A valid TLS certificate. Self-signed certificates are not supported yet.

### Set up the first machine

1. In Nextcloud open **Settings > Security**, scroll to **Devices & sessions**,
   enter a name such as `handoff`, and press **Create new app password**. Copy
   it; Nextcloud shows it only once.
2. Run `handoff sync login`. It asks for the server URL, your username and the
   app password (typed hidden). Use `--folder` to change the remote folder name
   from the default `handoff`.
3. Handoff tests the connection. On success it saves the server, username and
   folder in `~/.handoff/config.yaml` and the app password in
   `~/.handoff/webdav.token` (or set `HANDOFF_WEBDAV_PASSWORD` instead).
4. Check it: `handoff sync status` shows the server, whether the password is
   set, and whether this repo has unsynced changes.
5. In a repo, run `handoff sync now`. You should see `Synced: N pushed, 0 pulled`.
   In the Nextcloud web UI a folder `handoff/<repo-id>/` now contains your
   `LAST.md`, `NEXT.md`, `WORKSPACE.md` and the `sessions/`, `days/` and
   `weeks/` folders. The repo id is the normalised git remote, for example
   `github.com__owner__repo`.

From now on, opening `handoff` in the repo pulls first, and saving a handoff
pushes.

### Add another machine

Install handoff there, run `handoff sync login` with the same server and app
password (or create a second app password, which lets you revoke machines
separately), then open `handoff` in a clone of the same repo. It prints
`Syncing handoff notes...` and pulls your existing notes. The repo id comes
from the git remote, so the clone can live at any path.

Repos with no `origin` remote use the folder name as the id, so two unrelated
folders with the same name would share notes. Add a remote or rename one.

### How syncing behaves

- Handoff pulls when it opens in a repo and pushes whenever you save a handoff
  or quit with unsynced changes. Run `handoff sync now` to force one.
- Saving or quitting shows a "Syncing" box that cannot be closed until the sync
  finishes or fails, so you do not leave a machine with unsynced notes.
- Offline (or the server unreachable): handoff does not block. It says so and
  syncs the next time it opens with a connection. Nothing is lost.
- Only notes are synced (`LAST/NEXT/WORKSPACE/WORKLOG.md`, `sessions/`, `days/`,
  `weeks/`), never `DRAFT.md`. Deletions are not propagated, so deleting a note
  locally does not delete it on the server (and it comes back on the next pull).
- Local state for the sync is in `.handoff/.sync-state.json`.

### Conflicts

If two machines changed the same file before syncing, nothing is overwritten.
The server's version is saved next to yours as `NEXT.conflict.md` (or the
matching name) and handoff reports it on every sync until you resolve it. To
resolve:

- **Keep the server's version:** copy the contents of the `.conflict.md` file
  over your file, then run `handoff sync now`. The two now match, so the
  conflict clears.
- **Keep your version:** delete that file in the Nextcloud web UI, then run
  `handoff sync now`. Your copy is uploaded as new.
- **Merge both:** edit your file into the merged text, delete the file in the
  Nextcloud web UI, then run `handoff sync now`. Merging alone is not enough
  yet, because the server copy still differs.

Finally delete the `.conflict.md` file; it is never uploaded.

### Troubleshooting

| What you see | Meaning and fix |
|---|---|
| `login rejected` | Wrong username or app password. Create a fresh app password; with 2FA your normal password never works. |
| `could not reach server` at login | Check the URL opens in a browser, includes any subfolder, and uses `https://`. |
| `Offline (...)` | The server is unreachable or its certificate is not trusted. The message includes the reason, for example `CERTIFICATE_VERIFY_FAILED` for a self-signed certificate. |
| `Authentication failed; run handoff sync login` | The app password was revoked or changed. Log in again. |
| `Sync timed out` | A sync took over 60 seconds. Run `handoff sync now` again; it resumes where it stopped. |
| A file keeps conflicting | Follow the conflict steps above. |
| Start over on one machine | Delete `.handoff/.sync-state.json`. The next sync compares contents again; identical files are adopted and differing ones become conflicts. |

### Turn it off or remove it

There is no `logout` command yet. Delete the `sync:` block from
`~/.handoff/config.yaml` and the file `~/.handoff/webdav.token`, and revoke the
app password in Nextcloud under **Settings > Security**. Notes already on the
server and on disk are left alone.

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
