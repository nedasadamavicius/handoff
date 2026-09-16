from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Label, Static

from handoff.agent_runs import AgentRun, RunLedger
from handoff.external_sessions import SessionManager


class SessionManagerWidget(Static):
    DEFAULT_CSS = """
    SessionManagerWidget { width: 1fr; height: 1fr; padding: 1 2; }
    #session-help { height: auto; margin-bottom: 1; }
    #session-status { height: 2; color: $accent; }
    #sessions-table { height: 1fr; min-height: 3; }
    #session-controls { height: 3; }
    #session-controls Button { min-width: 8; width: auto; margin-right: 1; }
    """

    def __init__(self, manager: SessionManager, config, workspace, ledger: RunLedger | None = None, **kwargs):
        super().__init__("", **kwargs)
        self.manager, self.config = manager, config
        self._ledger = ledger
        self._pending = 0
        self._polling = False
        self._shutdown = False
        self._rows = {}
        self._session_runs: dict[str, AgentRun] = {}
        self._selected_ident = None
        self._operation_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        tools = "  ".join(f"{index} {name}" for index, name in enumerate(self.config.tools, 1))
        yield Label(
            "Interact with agents in their own windows. Quitting Handoff leaves them running; "
            "tracking is not restored after restart.\n"
            + tools + "\nEnter: Open | Ctrl+K: Stop | Ctrl+T: Workspace",
            id="session-help", markup=False,
        )
        yield Label("No sessions yet. Press a tool number to launch.", id="session-status", markup=False)
        yield DataTable(id="sessions-table", cursor_type="row")
        with Horizontal(id="session-controls"):
            yield Button("Open", id="session-open")
            yield Button("Stop", id="session-stop")
            yield Button("Remove", id="session-remove")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for title in ("Session", "State", "PID", "Exit / Error"):
            table.add_column(title, key=title)
        self._timer = self.set_interval(0.5, self._poll)
        self._poll()

    async def on_unmount(self) -> None:
        await self.shutdown_async()

    def _poll(self) -> None:
        if not self._shutdown and not self._pending and not self._polling:
            self._polling = True
            self.run_worker(self._refresh_worker(), exclusive=False)

    def _start(self, action, session=None, name=None) -> None:
        if self._shutdown:
            return
        if action != "launch" and session is None:
            self.query_one("#session-status", Label).update("Select a session first.")
            return
        self._pending += 1
        self.query_one("#session-status", Label).update(f"{action.capitalize()} queued...")
        self.run_worker(self._operation(action, session, name), exclusive=False)

    async def _refresh_worker(self):
        try:
            await asyncio.to_thread(self.manager.refresh)
            if not self._shutdown:
                self._render_table()
        except Exception as exc:
            if not self._shutdown:
                self.query_one("#session-status", Label).update(str(exc))
        finally:
            self._polling = False

    async def _operation(self, action, session=None, name=None):
        try:
            async with self._operation_lock:
                if self._shutdown:
                    return
                self.query_one("#session-status", Label).update(f"{action.capitalize()}...")
                if action == "launch":
                    result = await asyncio.to_thread(self.manager.launch, name, self.config.tools[name])
                    if result is not None and not self._shutdown:
                        self.app.tools_launched.append(name)
                        if self._ledger is not None:
                            self._session_runs[result.ident] = self._ledger.begin(name, self.config.tools[name])
                else:
                    await asyncio.to_thread(getattr(self.manager, action), session)
                if not self._shutdown:
                    self._render_table()
                    message = "Session launched; interact in its terminal window." if action == "launch" else f"{action.capitalize()} completed."
                    self.query_one("#session-status", Label).update(message)
        except Exception as exc:
            if not self._shutdown:
                self._render_table()
                self.query_one("#session-status", Label).update(str(exc))
                self.notify(str(exc), severity="error")
        finally:
            self._pending -= 1

    def _render_table(self) -> None:
        table = self.query_one(DataTable)
        rows = {
            session.ident: (session.label, session.state, str(session.pid or ""),
                            str(session.exit_code if session.exit_code is not None else session.error or ""))
            for session in self.manager.sessions
        }
        if rows == self._rows:
            return
        if self._ledger is not None:
            for ident, values in rows.items():
                old = self._rows.get(ident)
                old_state = old[1] if old else None
                new_state = values[1]
                if old_state in {"starting", "running"} and new_state not in {"starting", "running"}:
                    run = self._session_runs.pop(ident, None)
                    if run is not None:
                        self._ledger.finish(run, "error" if new_state == "error" else "ok")
        current = self._selected_ident
        previous_row = table.cursor_row
        with table.prevent(DataTable.RowHighlighted):
            for ident in self._rows.keys() - rows.keys():
                table.remove_row(ident)
            for ident, values in rows.items():
                if ident not in self._rows:
                    table.add_row(*values, key=ident)
                elif self._rows[ident] != values:
                    for column, value in zip(("Session", "State", "PID", "Exit / Error"), values):
                        table.update_cell(ident, column, value, update_width=True)
            self._rows = rows
            if rows:
                keys = list(rows)
                index = keys.index(current) if current in rows else min(previous_row, len(keys) - 1)
                self._selected_ident = keys[index]
                table.move_cursor(row=index, animate=False)
            else:
                self._selected_ident = None

    def _selected(self):
        return next((session for session in self.manager.sessions if session.ident == self._selected_ident), None)

    def stop_selected(self) -> None:
        self._start("stop", self._selected())

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None:
            self._selected_ident = str(event.row_key.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._selected_ident = str(event.row_key.value)
        self._start("open", self._selected())
        event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action = {"session-open": "open", "session-stop": "stop", "session-remove": "remove"}.get(event.button.id)
        if action:
            self._start(action, self._selected())
            event.stop()

    def launch_background(self, name: str) -> None:
        self._start("launch", name=name)

    async def shutdown_async(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._timer.stop()
        await asyncio.to_thread(self.manager.shutdown)
