# handoff dual-mode design: ACP harness, then study graph

Status: approved direction, not yet implemented.
Audience: an implementing agent with this repo checked out.
Stack: Python 3.11+, Poetry, Textual TUI, Typer CLI. Entry: `handoff` → `handoff.cli:app`.

## Product

handoff is a **terminal workspace shell**. Open it in a directory. LAST.md / NEXT.md are waiting when you come back.

It is not a web chat, not an Obsidian companion, and not a launcher that `App.suspend()`s itself so Grok/Claude/Codex take over the terminal.

Two use cases, one tool:

| Mode | Workspace | When | Job |
|---|---|---|---|
| **Dev** | git repo (`workspace_type: code`) | **now** | Multi-agent harness. Grok, Codex, Claude Code run *inside* handoff as ACP sessions. One handoff ledger. |
| **Study** | notes dir (`workspace_type: regular`) | **later** | Learning notes plus a **local wiki-link graph** for lookup. Our graph, not Obsidian. |

Decisions already made:

- **No Obsidian** (no vault, plugin, or sync). Graph later, inside handoff.
- **ACP proxy, not nested PTYs.** Handoff draws the session. Provider CLIs run headless as agent servers. You keep their agents, tools, file edits, and logins — not their TUIs.
- **Portable terminal app.** Linux, macOS, SSH, WSL, any real terminal. Do not design around Windows console, ConPTY, or `wt.exe`.
- **File formats stay stable** (`.handoff/WORKSPACE.md`, `LAST.md`, `NEXT.md`, `DRAFT.md`, session/day/week logs). README already calls this a validation build.
- Conversations are ACP sessions in handoff, not HTTP calls to xAI/Anthropic/OpenAI APIs (that would drop CLI auth and tools).

## Current code (what you are changing)

Repo root: this repository. Package: `src/handoff/`. Tests: `tests/test_core.py`, `tests/test_workflows.py`.

| File | Role today |
|---|---|
| `src/handoff/tui.py` | Textual app `WorkspaceShell`. ~700 lines. **Do not dump the new agent UI in here.** |
| `src/handoff/tui.py` `action_launch_tool` | `suspend()` + `run_command` + finalize + **`action_handoff()`**. This is the blocker. |
| `src/handoff/launcher.py` | `run_command`, `codex_finalize_command`, `claude_finalize_command`. Keep `run_command` for the editor. Finalize-after-exit goes away on the in-app ACP path. |
| `src/handoff/workspace.py` | `Workspace`, `workspace_type` `code`/`regular`, `TOOL_MEMORY_FILES` (`claude`→`CLAUDE.md`, `codex`→`AGENTS.md`, `gemini`→`GEMINI.md`). `ensure_tool_file` only writes if missing. |
| `src/handoff/config.py` | Default tools `{"codex": "codex", "claude": "claude"}`. `REMOVED_DEFAULT_TOOLS = {"gemini"}`. User config `~/.handoff/config.yaml`. |
| `src/handoff/handoff.py` | `parse_draft_or_files`, `parse_last_sections`, `merge_next_text` via documents. Draft markers `## LAST.md` / `## NEXT.md`. |
| `src/handoff/workflows.py` | `save_workspace_handoff` writes LAST/NEXT, session log, day log, deletes DRAFT.md. |
| `src/handoff/tui_screens.py` | `HandoffScreen` modal. Keep it. |
| `src/handoff/ai.py` | Optional `ai_command` draft helper. Unrelated; leave it. |

Bindings today: `t` tool picker (markdown cheat sheet), `1–5` launch, `h` handoff, `q` quit, `s` logs, `e` edit.

Grok may already be on PATH (`grok`) but is not a configured tool. Grok already loads `AGENTS.md` and `CLAUDE.md` as project rules.

## Architecture (ACP)

```
handoff TUI  (ACP client + workspace shell)
  ├── files / LAST / NEXT / logs     (keep)
  └── agent tabs
        ├── grok    ← grok agent stdio
        ├── claude  ← ACP adapter, else claude -p --output-format stream-json
        └── codex   ← codex app-server or @agentclientprotocol/codex-acp
```

Handoff never calls provider HTTP APIs. Auth stays `grok login` / `claude` / `codex login`.

ACP is JSON-RPC 2.0 NDJSON over stdio. Typical lifecycle: `initialize` → `session/new` → `session/prompt` → `session/update` notifications → optional `session/request_permission` → `session/cancel` / process teardown.

Grok docs: `grok agent stdio`. Codex: `codex app-server` (VS Code extension path) and npm `@agentclientprotocol/codex-acp`. Claude: `@zed-industries/claude-code-acp` / `@agentclientprotocol/claude-agent-acp`, or stream-json until native ACP is the default.

**Rejected:** embedding native TUIs in a PTY widget (that is a multiplexer). Optional later if someone misses native chrome. Not this work.

## Target UI

```
┌──────── file tree ────────┬──────── right pane (tabs) ─────────────────┐
│ workspace files           │ Overview | Grok | Claude | Codex | +       │
│                           │ transcript (ACP stream)                    │
│                           │ tool calls / permission prompts            │
│                           │ ─────────────────────────────────────      │
│                           │ prompt input                               │
└───────────────────────────┴────────────────────────────────────────────┘
```

- `t` / `1–5` opens or focuses an agent tab (spawns ACP subprocess if needed). **No `suspend()`.**
- Several tabs can be live. Background tabs keep streaming.
- `h` is the human handoff at the end of *your* session, not after each agent turn.
- `q` with unsaved DRAFT.md / run snapshots offers handoff first.
- Agent-tab focus: typing goes to the prompt; `escape` back to files/overview. Global `h`, `q`, `s` still work.

## Implementation slices

Ship so the TUI still works after each slice. First vertical slice that matters: **Grok tab inside handoff, files and LAST/NEXT still visible, no `suspend()`.**

### 1. ACP client — `src/handoff/acp/`

Small stdio JSON-RPC client. No third-party ACP SDK required for v1.

Must cover: spawn, `initialize`, `session/new`, `session/prompt`, `session/update` (text, thought, tool calls), `session/request_permission`, `session/cancel`, teardown.

**Tests:** fake agent script on stdio. Do not require grok/claude/codex for unit tests.

### 2. Adapters — `src/handoff/agents.py`

```python
@dataclass(frozen=True)
class AgentAdapter:
    key: str                    # grok | claude | codex
    memory_file: str            # AGENTS.md or CLAUDE.md
    def matches(self, tool_name: str, command: str) -> bool: ...
    def spawn_command(self, executable: str) -> list[str]: ...
```

| Agent | Spawn | Memory file |
|---|---|---|
| grok | `grok agent stdio` | `AGENTS.md` |
| claude | ACP adapter if on PATH, else `claude -p --output-format stream-json --verbose` and `--resume` for later turns | `CLAUDE.md` |
| codex | `codex app-server` or `npx -y @agentclientprotocol/codex-acp` | `AGENTS.md` |

Unknown configured tools: no memory file, no ACP tab (or show “unsupported”). Missing binary: tab shows “not installed”.

Wire `ensure_tool_file` through this registry. Add `grok` → `AGENTS.md`. Keep “only create if missing”.

**Config:** default tools `{grok, codex, claude}`. If loaded `~/.handoff/config.yaml` tools are exactly the old default `{codex, claude}`, insert `grok`. Custom maps untouched.

In-app ACP path: drop post-exit finalize (`codex exec resume --last`, `claude --continue -p`). Memory files already tell agents to keep `.handoff/DRAFT.md` current. Optional “flush draft” prompt on tab close.

Keep `launcher.run_command` for `$EDITOR`.

### 3. Agent tab UI — `src/handoff/tui_agents.py`

New right-pane page (`TabbedContent` or ContentSwitcher + tab bar). **Not more code piled into `tui.py`.**

Per tab: transcript (RichLog or Markdown), tool-call summaries, permission modal, prompt input, status `idle | streaming | waiting-for-permission | dead`.

### 4. Session ledger (do not change file formats)

```python
@dataclass
class AgentRun:
    name: str
    command: str
    started_at: datetime
    ended_at: datetime | None
    status: str                  # ok | error | cancelled
    prompt_count: int
    draft_snapshot: Path | None
```

- Snapshot DRAFT.md to `.handoff/runs/<YYYY-MM-DD-HHMMSS>-<agent>.md` on tab close or before `h`, so one agent cannot wipe another’s bullets.
- `h` prefills from merged snapshots + current DRAFT.md + existing NEXT.md (`parse_last_sections`, `merge_next_text`, concatenate Completed/Open Issues, de-dupe).
- Session YAML `tools_launched` remains a derived list of names so old logs parse.
- Stop calling `action_handoff()` from launch.

### 5. Tests and docs

- ACP client vs fake stdio agent (handshake, prompt, stream, permission, cancel).
- Adapter command selection + missing binary.
- Config grok default + old-default migration.
- Two-agent DRAFT snapshot merge.
- README: dual-mode north star; agents run inside handoff via ACP; no native TUI chrome; study graph is later. Update the “Agent handoff integration” section that still describes suspend + finalize + auto-modal.

`poetry run pytest` must stay green.

## Suggested commit order

1. ACP stdio client + fake-agent tests.
2. Grok adapter + one working Grok tab (no suspend).
3. Permission prompts + DRAFT snapshot on tab close + do not auto-open handoff.
4. Claude + Codex adapters.
5. Multi-tab board, merge-on-`h`, quit-confirm, README.

Conventional commits (`type(scope): description`). No `Co-Authored-By`.

## Out of scope (do not build)

- Obsidian.
- Wiki-links / graph view (study follow-up).
- Nested PTY / ConPTY / `wt.exe`.
- Direct provider HTTP APIs.
- Headless jobs with no tab.
- Renaming `regular` → `study`.
- Stale NEXT.md items (public release, GitHub log persistence, lightsaber theme).
- Refactoring the whole TUI “for cleanliness” unless a slice requires it.

## Study follow-up (later session)

Notes workspace + `[[wiki links]]` + graph pane (`g`). Same LAST/NEXT spine. Separate design after the harness is usable.

## Draft format (unchanged)

`.handoff/DRAFT.md`:

```markdown
## LAST.md

### Summary

One or two sentences.

### Completed

- Item.

### Open Issues

- None

## NEXT.md

- Next action.
```

Memory-file template lives in `workspace.py` `_TOOL_MEMORY_TEMPLATE`. Do not overwrite existing `AGENTS.md` / `CLAUDE.md`.
