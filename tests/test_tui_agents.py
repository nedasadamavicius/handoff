from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from textual.widgets import Button, ContentSwitcher, DataTable, DirectoryTree, Label

from handoff.config import AppConfig
from handoff.tui import WorkspaceShell
from handoff.tui_agents import QuitAgentScreen
from handoff.workspace import current_directory_workspace


class FakeManager:
    def __init__(self):
        self.sessions = []
        self.calls = []
        self.number = 0
        self.block_action = None
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fail_launch = False

    def _block(self, action):
        if self.block_action == action:
            self.entered.set()
            if not self.release.wait(5):
                raise RuntimeError("test operation timed out")

    def refresh(self):
        pass

    def launch(self, name, command):
        self._block("launch")
        if self.fail_launch:
            raise RuntimeError("missing executable")
        self.number += 1
        session = SimpleNamespace(name=name, ident=str(self.number), label=f"{name} #{self.number}",
                                  state="running", pid=self.number, exit_code=None, error=None)
        self.sessions.append(session)
        self.calls.append(("launch", session.ident))
        return session

    def open(self, session):
        self.calls.append(("open", session.ident))

    def stop(self, session):
        self._block("stop")
        self.calls.append(("stop", session.ident))
        session.state = "exited"

    def remove(self, session):
        if session.state in {"running", "starting"}:
            raise RuntimeError("Stop the session before removing it")
        self.sessions.remove(session)
        self.calls.append(("remove", session.ident))

    def shutdown(self):
        self.calls.append(("shutdown", None))


def make_app(tmp_path):
    path = tmp_path / "workspace"
    path.mkdir()
    app = WorkspaceShell(AppConfig(root=tmp_path / "config", tools={"codex": "codex", "claude": "claude"}), current_directory_workspace(path))
    app.session_manager = FakeManager()
    return app


async def until(pilot, predicate):
    for _ in range(60):
        if predicate():
            return
        await pilot.pause(0.02)
    assert predicate(), "condition did not complete"


async def finished(pilot, app):
    await until(pilot, lambda: app.session_widget._pending == 0)
    await pilot.pause()


def test_two_launches_open_stop_remove_and_selection(tmp_path):
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(115, 36)) as pilot:
            await pilot.press("1", "1")
            await finished(pilot, app)
            assert len(app.session_manager.sessions) == 2
            assert app.tools_launched == ["codex", "codex"]
            assert (app.workspace.path / "AGENTS.md").exists()
            assert not app.query("#terminal-pane")
            table = app.query_one(DataTable)
            assert table.has_focus
            await pilot.press("down", "enter")
            await finished(pilot, app)
            assert ("open", "2") in app.session_manager.calls
            await pilot.press("ctrl+k")
            await finished(pilot, app)
            assert ("stop", "2") in app.session_manager.calls
            assert app.session_manager.sessions[0].state == "running"
            await pilot.click("#session-remove")
            await finished(pilot, app)
            assert [session.ident for session in app.session_manager.sessions] == ["1"]
            await pilot.pause(0.4)
            await pilot.click("#session-remove")
            await finished(pilot, app)
            assert len(app.session_manager.sessions) == 1
            assert "Stop" in str(app.query_one("#session-status", Label).render())
            await pilot.click("#session-open")
            await finished(pilot, app)
            assert ("open", "1") in app.session_manager.calls
            await pilot.click("#session-stop")
            await finished(pilot, app)
            assert ("stop", "1") in app.session_manager.calls

    asyncio.run(scenario())


def test_single_click_selects_without_opening_double_click_opens(tmp_path):
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(115, 36)) as pilot:
            await pilot.press("1", "1")
            await finished(pilot, app)
            widget = app.session_widget
            # Second data row (header at y=0, rows at y=1, y=2) is session "2".
            await pilot.click("#sessions-table", offset=(5, 2))
            await finished(pilot, app)
            assert widget._selected_ident == "2"
            assert not any(action == "open" for action, _ in app.session_manager.calls)
            await pilot.double_click("#sessions-table", offset=(5, 2))
            await finished(pilot, app)
            assert ("open", "2") in app.session_manager.calls

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["launch", "stop"])
def test_slow_operations_keep_workspace_responsive_and_do_not_steal_focus(tmp_path, action):
    app = make_app(tmp_path)
    manager = app.session_manager

    async def scenario():
        async with app.run_test(size=(115, 36)) as pilot:
            if action == "stop":
                await pilot.press("1")
                await finished(pilot, app)
            manager.block_action = action
            try:
                await pilot.press("1" if action == "launch" else "ctrl+k")
                await until(pilot, manager.entered.is_set)
                await pilot.press("ctrl+t", "down", "r")
                assert app.query_one("#right-switcher", ContentSwitcher).current == "overview-view"
                assert isinstance(app.focused, DirectoryTree)
                assert not manager.release.is_set()
                manager.release.set()
                await finished(pilot, app)
                assert isinstance(app.focused, DirectoryTree)
                await pilot.press("t")
                assert app.query_one(DataTable).has_focus
            finally:
                manager.release.set()

    asyncio.run(scenario())


def test_queued_launches_are_not_dropped(tmp_path):
    app = make_app(tmp_path)
    manager = app.session_manager
    manager.block_action = "launch"

    async def scenario():
        async with app.run_test(size=(115, 36)) as pilot:
            try:
                await pilot.press("1", "2")
                await until(pilot, manager.entered.is_set)
                assert app.session_widget._pending == 2
                manager.release.set()
                await finished(pilot, app)
                assert app.tools_launched == ["codex", "claude"]
                assert len(manager.sessions) == 2
            finally:
                manager.release.set()

    asyncio.run(scenario())


def test_refresh_preserves_selection_and_does_not_redraw_unchanged_rows(tmp_path):
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(115, 36)) as pilot:
            await pilot.press("1", "2")
            await finished(pilot, app)
            await pilot.press("down")
            widget = app.session_widget
            table = widget.query_one(DataTable)
            assert widget._selected_ident == "2"
            with patch.object(table, "clear") as clear, patch.object(table, "update_cell") as update:
                await widget._refresh_worker()
                clear.assert_not_called()
                update.assert_not_called()
            app.session_manager.sessions[0].state = "exited"
            await widget._refresh_worker()
            await pilot.pause()
            assert widget._selected_ident == "2"
            await pilot.press("ctrl+t", "t")
            assert table.has_focus
            assert widget._selected_ident == "2"

    asyncio.run(scenario())


def test_failed_launch_not_recorded_and_buttons_safe_without_selection(tmp_path):
    app = make_app(tmp_path)
    app.session_manager.fail_launch = True

    async def scenario():
        async with app.run_test(size=(115, 36)) as pilot:
            await pilot.press("1")
            await finished(pilot, app)
            assert app.tools_launched == []
            assert "missing executable" in str(app.query_one("#session-status", Label).render())
            await pilot.click("#session-stop")
            await pilot.pause()
            assert not app.session_manager.sessions
            assert "Select" in str(app.query_one("#session-status", Label).render())

    asyncio.run(scenario())


def test_quit_and_unmount_release_tracking_without_stopping_agents(tmp_path):
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(115, 36)) as pilot:
            await pilot.press("1")
            await finished(pilot, app)
            app.action_quit()
            await pilot.pause()
            assert isinstance(app.screen, QuitAgentScreen)
            await pilot.click("#quit-discard")
        assert ("shutdown", None) in app.session_manager.calls
        assert not any(action == "stop" for action, _ in app.session_manager.calls)
        assert app.session_manager.sessions[0].state == "running"

    asyncio.run(scenario())


def test_normal_unmount_releases_tracking(tmp_path):
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.pause()
        assert app.session_manager.calls == [("shutdown", None)]

    asyncio.run(scenario())
