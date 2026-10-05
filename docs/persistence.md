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
   app password. The password is shown as you type, so you can see a paste worked;
   it is revocable in Nextcloud. To skip the prompt, set `HANDOFF_WEBDAV_PASSWORD`
   first or pass `--password`. Use `--folder` to change the remote folder name
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

From now on, opening `handoff` in the repo syncs, and saving a handoff syncs again.

### Add another machine

Install handoff there, run `handoff sync login` with the same server and app
password (or create a second app password, which lets you revoke machines
separately), then open `handoff` in a clone of the same repo. It prints
`New clone: fetching your handoff notes...` and pulls your existing notes. The repo id comes
from the git remote, so the clone can live at any path.

Repos with no `origin` remote use the folder name as the id, so two unrelated
folders with the same name would share notes. Add a remote or rename one.

### How syncing behaves

- Handoff syncs with the server in two situations: when the TUI opens (a
  "Syncing" box appears; it pulls, and also pushes anything left over from an
  offline save), and when you save a handoff. Quitting with `q` on its own never
  syncs; run `handoff sync now` to push other edits.
- The one exception is a brand-new clone with no `.handoff` yet. There handoff
  fetches your notes before the TUI starts, so it does not create default notes
  that would then have to be merged with yours.
- Saving a handoff shows a "Syncing" box that cannot be closed until the server
  confirms. If you chose to quit after saving, handoff exits only once it
  confirms, and prints `Handoff saved and synced (...)`.
- Offline (or the server unreachable): the handoff is still saved locally and
  handoff exits normally, telling you it will sync the next time it opens with a
  connection. Nothing is lost.
- A server error (for example a rejected login) keeps the TUI open so you can
  read the message instead of losing it; press `q` again to leave. The handoff
  is already saved locally.
- Only notes are synced (`LAST/NEXT/WORKSPACE/WORKLOG.md`, `sessions/`, `days/`,
  `weeks/`), never `DRAFT.md`. Deletions are not propagated, so deleting a note
  locally does not delete it on the server (and it comes back on the next pull).
- Local state for the sync is in `.handoff/.sync-state.json`.

### When two machines edited the same note

Nothing is ever silently overwritten, and you do not have to pick a winner up
front. Handoff combines the two versions into the file itself, pushes the
combined result so every machine ends up with the same text, and warns you:

```
- one
- two
<<<<<<< this machine
- from this machine
=======
- from the other machine
>>>>>>> from Nextcloud
```

Lines both versions share are kept once. If only one machine changed a note, its
version simply wins with no markers. When both changed the same stretch, both are
kept between the markers. Open the file, keep what you want, delete the three
marker lines, and save. The next sync pushes your cleaned-up version.

Handoff reminds you after every sync (`review markers in NEXT.md`, and a warning
inside the TUI) until no markers are left. Search for `<<<<<<<` to find them.

Because handoff does not keep the last shared copy, it cannot tell edits in
different parts of a note apart from edits to the same part, so it marks the whole
differing stretch. Expect the markers to be a little wider than strictly needed.

### Troubleshooting

| What you see | Meaning and fix |
|---|---|
| `login rejected` | Wrong username or app password. Create a fresh app password; with 2FA your normal password never works. |
| `could not reach server` at login | Check the URL opens in a browser, includes any subfolder, and uses `https://`. |
| `Offline (...)` | The server is unreachable or its certificate is not trusted. The message includes the reason, for example `CERTIFICATE_VERIFY_FAILED` for a self-signed certificate. |
| `Server refused the request (403)` | Not a login problem: something in front of Nextcloud (a firewall such as Cloudflare, or a reverse proxy rule) blocked the request. The message includes the server's reason. |
| `Server refused the request (403)` | Not a login problem: something in front of Nextcloud (a firewall such as Cloudflare, or a reverse proxy rule) blocked the request. The message includes the server's reason. |
| `Authentication failed; run handoff sync login` | The app password was revoked or changed. Log in again. |
| `Sync timed out` | A sync took over 60 seconds. Run `handoff sync now` again; it resumes where it stopped. |
| `review markers in ...` after every sync | A note still contains `<<<<<<<` markers. Resolve them as described above. |
| Start over on one machine | Delete `.handoff/.sync-state.json`. The next sync compares contents again; identical files are adopted and differing ones are combined with markers. |

### Known limitations

- **Open a new clone while online.** On a brand-new clone, handoff fetches your
  notes before creating any. If that first open happens offline, handoff creates
  default `LAST.md`, `NEXT.md` and `WORKSPACE.md` instead. The next sync then
  combines those defaults with your real notes and leaves merge markers in them.
  Resolve them by keeping your real text, or avoid it by making the first open of
  a new clone one with a connection.
- Merge markers cover the whole differing stretch of a note, not just the lines
  that actually clash (handoff does not keep the last shared copy).
- Self-signed certificates are not supported.
- There is no `logout` command (see below).

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
