"""Textual agent board used by the workspace shell.

The board deliberately keeps provider details behind the small client
interfaces.  This also makes it straightforward to exercise with fake
clients in headless tests.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.binding import Binding
from textual.widgets import (
    Button,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widget import Widget
from rich.console import Group
from rich.markdown import Markdown
from rich.padding import Padding
from rich.text import Text

from handoff.acp.client import ACPClient
from handoff.agents import AgentUnavailable, resolve_agent
from handoff.agent_runs import AgentRun, RunLedger
from handoff.claude_stream import ClaudeStreamClient
from handoff.config import AppConfig
from handoff.workspace import Workspace


class PermissionScreen(ModalScreen[str | None]):
    """Small, explicit permission chooser; closing the modal means cancel."""
    CSS = "PermissionScreen { align: center middle; } #permission { width: 70; height: auto; padding: 1 2; background: $surface; }"

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__()
        self.params = params
        self.option_ids: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="permission"):
            yield Label(str(self.params.get("message") or self.params.get("description") or "Permission requested"))
            for index, option in enumerate(self.params.get("options", [])):
                self.option_ids.append(str(option.get("optionId")))
                yield Button(str(option.get("name") or option.get("optionId")), id=f"permission-{index}")
            yield Button("Cancel", id="permission-cancel", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "permission-cancel":
            self.dismiss(None)
            return
        index = int((event.button.id or "").removeprefix("permission-"))
        self.dismiss(self.option_ids[index])


class QuitAgentScreen(ModalScreen[str]):
    """Choose how to leave a workspace with an unfinished handoff."""

    CSS = "QuitAgentScreen { align: center middle; } #quit-agent { width: 62; height: auto; padding: 1 2; background: $surface; }"
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="quit-agent"):
            yield Label("This workspace has an unsaved draft or agent run.")
            yield Button("Save handoff", id="quit-handoff", variant="primary")
            yield Button("Quit without saving", id="quit-discard", variant="error")
            yield Button("Cancel", id="quit-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss((event.button.id or "quit-cancel").removeprefix("quit-"))

    def action_cancel(self) -> None:
        self.dismiss("cancel")


@dataclass
class TranscriptEntry:
    role: str
    text: str
    key: str | None = None


@dataclass
class AgentSession:
    """One live agent instance, owning its own tab, client, and transcript."""
    sid: int
    agent: str
    command: str
    label: str
    client: Any = None
    run: AgentRun | None = None
    status: str = "idle"
    task: asyncio.Task | None = None
    received_output: bool = False
    transcript: list[TranscriptEntry] = field(default_factory=list)
    tool_titles: dict[str, str] = field(default_factory=dict)


class AgentBoard(Widget):
    """Session-oriented agent board: pick a model, open as many tabs as you like."""

    CSS = """
    AgentBoard, AgentBoard > Vertical, #agent-tabs, TabPane, .agent-pane {
        height: 1fr;
    }
    #agent-status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    .agent-log {
        height: 1fr;
        padding: 1 2;
        background: $background;
        scrollbar-size-vertical: 1;
    }
    .agent-input {
        height: 3;
        width: 1fr;
        margin: 0;
        border: tall $panel-lighten-2;
    }
    .agent-input:focus { border: tall $accent; }
    .agent-prompt-row { height: 3; padding: 0 1; }
    .agent-prompt-mark {
        width: 3;
        height: 3;
        padding: 1 0 0 1;
        color: $accent;
        text-style: bold;
    }
    .agent-footer {
        height: 3;
        padding: 0 1;
    }
    .agent-hint {
        width: 1fr;
        height: 3;
        content-align: left middle;
    }
    .agent-stop {
        width: auto;
        min-width: 10;
        height: 3;
        margin: 0;
    }
    .launcher { padding: 1 2; height: 1fr; }
    .launch-title { text-style: bold; padding: 0 0 1 0; }
    .launch-help { color: $text-muted; padding: 1 0 0 0; }
    #agent-launcher {
        height: auto;
        border: none;
        background: $background;
    }
    #agent-launcher > ListItem {
        padding: 0 1;
        background: $background;
    }
    #agent-launcher > ListItem.-highlight {
        background: $accent 25%;
    }
    .launch-card { height: 3; content-align: left middle; }
    """
    BINDINGS = [
        Binding("escape", "workspace", "Workspace", show=False),
        Binding("ctrl+w", "close_session", "Close session", show=False, priority=True),
    ]

    TITLES = {"claude": "Claude Code", "grok": "Grok", "codex": "Codex"}
    VENDORS = {"claude": "anthropic", "grok": "xAI", "codex": "OpenAI"}

    def __init__(self, config: AppConfig, workspace: Workspace, ledger: RunLedger, *, id: str = "agent-board") -> None:
        super().__init__(id=id)
        self.config, self.workspace, self.ledger = config, workspace, ledger
        self.agents = dict(config.tools)
        self.sessions: dict[int, AgentSession] = {}
        self._counter = 0
        self._permission_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        count = len(self.agents)
        keys = f"1–{count}" if count > 1 else "1"
        with Vertical():
            yield Static(
                f"{keys} new session   ·   ctrl+w close   ·   esc workspace",
                id="agent-status",
            )
            with TabbedContent(id="agent-tabs"):
                yield TabPane("＋ New", self._launcher(), id="agent-overview")

    # ----- launcher ---------------------------------------------------------

    def _launcher(self) -> Widget:
        items = []
        for index, name in enumerate(self.agents, start=1):
            card = Static(self._card_text(index, name), classes="launch-card")
            items.append(ListItem(card, id=f"agent-launch-{name}"))
        return Vertical(
            Static("New session", classes="launch-title"),
            Static("Pick a model. Each opens its own tab — open one twice to run two.", classes="launch-help"),
            ListView(*items, id="agent-launcher"),
            classes="launcher",
        )

    def _card_text(self, index: int, name: str) -> Text:
        title = self.TITLES.get(name, name)
        vendor = self.VENDORS.get(name, "")
        text = Text()
        text.append(f"{index}", style="bold #FF3355")
        text.append(f"   {title}", style="bold")
        if vendor:
            text.append(f"    {vendor}", style="grey50")
        return text

    def show_launcher(self) -> None:
        try:
            self.query_one("#agent-tabs", TabbedContent).active = "agent-overview"
        except Exception:
            pass
        try:
            self.query_one("#agent-launcher", ListView).focus()
        except Exception:
            self.focus()

    # ----- session pane -----------------------------------------------------

    def _session_pane(self, session: AgentSession) -> Widget:
        sid = session.sid
        log = RichLog(
            id=f"agent-log-{sid}",
            classes="agent-log",
            wrap=True,
            highlight=False,
            markup=False,
        )
        log.styles.height = "1fr"
        prompt = Input(placeholder=f"message {session.agent}…", id=f"agent-input-{sid}", classes="agent-input")
        prompt.styles.height = 3
        prompt_row = Horizontal(
            Label("❯", classes="agent-prompt-mark"),
            prompt,
            classes="agent-prompt-row",
        )
        prompt_row.styles.height = 3
        hint = Static(self._hint(session), id=f"agent-hint-{sid}", classes="agent-hint")
        stop = Button("■ Stop", id=f"agent-cancel-{sid}", classes="agent-stop", variant="error")
        stop.styles.display = "none"
        stop.disabled = True
        stop.styles.width = "auto"
        stop.styles.min_width = 10
        stop.styles.height = 3
        footer = Horizontal(hint, stop, classes="agent-footer")
        footer.styles.height = 3
        return Vertical(
            log,
            prompt_row,
            footer,
            id=f"agent-pane-{sid}",
            classes="agent-pane",
        )

    def _hint(self, session: AgentSession) -> Text:
        """A single status-plus-keys line under the composer.

        Idle shows the two keys that matter; a live run replaces them with a
        working indicator, since the crimson Stop is the only action then.
        """
        name = session.agent
        keycap = "bold #FF3355"
        muted = "grey50"
        line = Text()
        if session.status == "waiting-for-permission":
            line.append("◐ ", style="bold #DC143C")
            line.append(f"{name} needs your approval", style="#DC143C")
            return line
        if session.status == "streaming":
            line.append("◐ ", style="bold #FF3355")
            line.append(f"{name} is working…", style="#FF3355")
            return line
        if session.status == "dead":
            line.append("● ", style="bold #8B0000")
            line.append("session ended", style=muted)
        else:
            line.append("● ", style="grey37")
            line.append("ready", style=muted)
        line.append("      ")
        line.append("↵", style=keycap)
        line.append(" send", style=muted)
        line.append("      ")
        line.append("^w", style=keycap)
        line.append(" close session", style=muted)
        return line

    # ----- transcript -------------------------------------------------------

    def _session(self, sid: int) -> AgentSession | None:
        return self.sessions.get(sid)

    def _log(
        self,
        sid: int,
        role: str,
        text: str,
        *,
        append: bool = False,
        key: str | None = None,
    ) -> None:
        session = self._session(sid)
        if session is None:
            return
        keyed = next((entry for entry in session.transcript if key and entry.key == key), None)
        if keyed is not None:
            keyed.role = role
            keyed.text = text
        elif append and session.transcript and session.transcript[-1].role == role:
            session.transcript[-1].text += text
        else:
            session.transcript.append(TranscriptEntry(role, text, key))
        self._render_transcript(sid)

    def _render_transcript(self, sid: int) -> None:
        session = self._session(sid)
        if session is None:
            return
        try:
            log = self.query_one(f"#agent-log-{sid}", RichLog)
        except Exception:
            return
        log.clear()
        for entry in session.transcript:
            if entry.role == "user":
                line = Text("❯ ", style="bold cyan")
                line.append(entry.text, style="bold")
                log.write(line)
            elif entry.role == "assistant":
                header = Text(f"◆ {session.agent}", style="bold green")
                try:
                    body = Markdown(
                        entry.text,
                        code_theme="monokai",
                        inline_code_lexer="text",
                        inline_code_theme="monokai",
                    )
                    log.write(Group(header, Padding(body, (0, 0, 1, 2))))
                except Exception:
                    fallback = Text(entry.text)
                    log.write(Group(header, Padding(fallback, (0, 0, 1, 2))))
            elif entry.role == "thought":
                line = Text("· think  ", style="italic dim")
                line.append(entry.text.replace("\n", " "), style="dim")
                log.write(line)
            elif entry.role == "tool":
                line = Text("$ ", style="bold yellow")
                line.append(entry.text)
                log.write(line)
            elif entry.role == "error":
                line = Text("! error  ", style="bold red")
                line.append(entry.text, style="red")
                log.write(line)
            else:
                line = Text("· ", style="dim")
                line.append(entry.text, style="dim")
                log.write(line)

    def _set_status(self, session: AgentSession, status: str) -> None:
        session.status = status
        sid = session.sid
        try:
            self.query_one(f"#agent-hint-{sid}", Static).update(self._hint(session))
        except Exception:
            pass
        try:
            busy = status in {"streaming", "waiting-for-permission"}
            stop = self.query_one(f"#agent-cancel-{sid}", Button)
            stop.disabled = not busy
            stop.styles.display = "block" if busy else "none"
        except Exception:
            pass

    # ----- lifecycle --------------------------------------------------------

    def _label_for(self, agent: str) -> str:
        used = {session.label for session in self.sessions.values() if session.agent == agent}
        if agent not in used:
            return agent
        index = 2
        while f"{agent} {index}" in used:
            index += 1
        return f"{agent} {index}"

    async def new_session(self, agent: str) -> AgentSession | None:
        if agent not in self.agents:
            return None
        self._counter += 1
        sid = self._counter
        session = AgentSession(
            sid=sid,
            agent=agent,
            command=self.agents[agent],
            label=self._label_for(agent),
        )
        self.sessions[sid] = session
        tabs = self.query_one("#agent-tabs", TabbedContent)
        await tabs.add_pane(TabPane(session.label, self._session_pane(session), id=f"agent-tab-{sid}"))
        tabs.active = f"agent-tab-{sid}"
        await self._start(session)
        return session

    async def _start(self, session: AgentSession) -> None:
        sid = session.sid
        try:
            launch = resolve_agent(session.agent, session.command)
            callback = lambda event: self._on_update(sid, event)
            permission = lambda params: self._request_permission(sid, params)
            cls = ACPClient if launch.backend == "acp" else ClaudeStreamClient
            options = {"on_update": callback, "on_permission": permission}
            if cls is ACPClient:
                options["on_error"] = lambda error: self._on_client_error(sid, error)
            session.client = cls(launch.command, self.workspace.path, **options)
            await session.client.start()
            self._set_status(session, "idle")
            self._log(sid, "system", "Session ready.")
            self.query_one(f"#agent-input-{sid}", Input).focus()
        except Exception as exc:
            session.client = None
            self._set_status(session, "dead")
            self._log(sid, "error", f"Could not start session: {exc}")

    async def submit(self, sid: int, prompt: str) -> None:
        session = self._session(sid)
        if session is None or not prompt.strip():
            return
        if session.client is None:
            await self._start(session)
            if session.client is None:
                return
        if (session.task is not None and not session.task.done()) or session.status in {"streaming", "waiting-for-permission"}:
            return
        self._log(sid, "user", prompt)
        if session.run is None:
            session.run = self.ledger.begin(session.agent, session.command)
        session.run.prompt_count += 1
        session.received_output = False
        self._set_status(session, "streaming")
        session.task = asyncio.create_task(self._prompt(session, prompt))
        await session.task

    async def _prompt(self, session: AgentSession, prompt: str) -> None:
        try:
            result = await session.client.prompt(prompt)
            if not session.received_output and isinstance(result, dict):
                fallback = result.get("result") or result.get("message")
                if isinstance(fallback, str) and fallback:
                    self._log(session.sid, "assistant", fallback)
            self._set_status(session, "idle")
        except asyncio.CancelledError:
            self._set_status(session, "idle")
        except Exception as exc:
            process = getattr(session.client, "process", None)
            dead = process is not None and getattr(process, "returncode", None) is not None
            self._set_status(session, "dead" if dead else "idle")
            self._log(session.sid, "error", str(exc))
        finally:
            session.task = None

    async def _on_update(self, sid: int, event: dict) -> None:
        session = self._session(sid)
        if session is None:
            return
        update = event.get("update", event)
        if not isinstance(update, dict):
            return
        kind = update.get("sessionUpdate") or update.get("type") or "status"
        # A tool call carries `content` as a *list* of content blocks; only a
        # message/thought chunk carries text (directly or under a dict content).
        text = update.get("text")
        if not text:
            content = update.get("content")
            if isinstance(content, dict):
                text = content.get("text")
        if text and kind not in {"tool_call", "tool_call_update"}:
            if kind == "agent_message_chunk":
                session.received_output = True
                self._log(sid, "assistant", str(text), append=True)
            elif kind in {"agent_thought_chunk", "thought_chunk"}:
                self._log(sid, "thought", str(text), append=True)
            else:
                self._log(sid, "system", str(text))
            return
        if kind in {"available_commands_update", "usage_update", "current_mode_update", "config_options_update"}:
            return
        if kind in {"tool_call", "tool_call_update"}:
            tool_id = str(update.get("toolCallId") or "")
            if kind == "tool_call" and update.get("title") and tool_id:
                session.tool_titles[tool_id] = str(update["title"])
            detail = update.get("title") or session.tool_titles.get(tool_id) or "Tool activity"
            status = update.get("status")
            suffix = f" · {status}" if status else ""
            self._log(sid, "tool", f"{detail}{suffix}", key=f"tool:{tool_id}" if tool_id else None)
            return
        if kind not in {"agent_message_chunk", "agent_thought_chunk", "thought_chunk"}:
            detail = update.get("title") or update.get("status") or kind.replace("_", " ")
            self._log(sid, "system", str(detail))

    async def _on_client_error(self, sid: int, error: Exception) -> None:
        self._log(sid, "error", str(error))

    async def _request_permission(self, sid: int, params: dict) -> object:
        session = self._session(sid)
        if session is None:
            return None
        async with self._permission_lock:
            self._set_status(session, "waiting-for-permission")
            future = asyncio.get_running_loop().create_future()

            def resolve(result: str | None) -> None:
                if not future.done():
                    future.set_result(result)

            self.app.push_screen(PermissionScreen(params), resolve)
            result = await future
            self._set_status(session, "streaming")
            return result

    async def cancel(self, sid: int) -> None:
        session = self._session(sid)
        if session is None:
            return
        if session.client:
            await session.client.cancel()
        if session.task and not session.task.done():
            session.task.cancel()
        if session.run and session.run.ended_at is None:
            self.ledger.finish(session.run, "cancelled")
        self._set_status(session, "idle")

    async def close_agent(self, sid: int) -> None:
        session = self._session(sid)
        if session is None:
            return
        if session.task and not session.task.done():
            await self.cancel(sid)
        elif session.run and session.run.ended_at is None:
            self.ledger.finish(session.run, "ok")
        if session.client:
            await session.client.close()
        self.sessions.pop(sid, None)
        try:
            tabs = self.query_one("#agent-tabs", TabbedContent)
            await tabs.remove_pane(f"agent-tab-{sid}")
            if not self.sessions:
                self.show_launcher()
        except Exception:
            pass

    async def shutdown(self) -> None:
        async def _close(session: AgentSession) -> None:
            if session.task and not session.task.done():
                await self.cancel(session.sid)
            elif session.run and session.run.ended_at is None:
                self.ledger.finish(session.run, "ok")
            if session.client:
                await session.client.close()

        await asyncio.gather(*(_close(session) for session in list(self.sessions.values())), return_exceptions=True)

    # ----- events -----------------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "agent-launcher":
            return
        agent = (event.item.id or "").removeprefix("agent-launch-")
        if agent in self.agents:
            self.run_worker(self.new_session(agent), exclusive=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        ident = event.button.id or ""
        if ident.startswith("agent-cancel-"):
            try:
                sid = int(ident.removeprefix("agent-cancel-"))
            except ValueError:
                return
            self.run_worker(self.cancel(sid), exclusive=False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        ident = event.input.id or ""
        if not ident.startswith("agent-input-"):
            return
        try:
            sid = int(ident.removeprefix("agent-input-"))
        except ValueError:
            return
        session = self._session(sid)
        if session is None or session.status in {"streaming", "waiting-for-permission"}:
            return
        prompt = event.value
        event.input.value = ""
        self.run_worker(self.submit(sid, prompt), exclusive=False)

    # ----- handoff / quit hooks --------------------------------------------

    def snapshot_active(self) -> None:
        for session in self.sessions.values():
            if session.run is not None and session.run.ended_at is None:
                self.ledger.snapshot(session.run)

    @property
    def has_live_runs(self) -> bool:
        return any(session.run is not None and session.run.ended_at is None for session in self.sessions.values())

    # ----- actions ----------------------------------------------------------

    def _active_sid(self) -> int | None:
        try:
            active = self.query_one("#agent-tabs", TabbedContent).active
        except Exception:
            return None
        if active and active.startswith("agent-tab-"):
            try:
                return int(active.removeprefix("agent-tab-"))
            except ValueError:
                return None
        return None

    def action_close_session(self) -> None:
        sid = self._active_sid()
        if sid is not None:
            self.run_worker(self.close_agent(sid), exclusive=False)

    def action_workspace(self) -> None:
        self.app.show_workspace_overview()
