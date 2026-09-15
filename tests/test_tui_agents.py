import asyncio
from pathlib import Path

from textual.widgets import ContentSwitcher, Input, RichLog

from handoff.agents import AgentAdapter, AgentLaunch
from handoff.config import AppConfig
from handoff.tui import WorkspaceShell
from handoff.tui_agents import PermissionScreen, QuitAgentScreen
from handoff.tui_screens import HandoffScreen
from handoff.workspace import current_directory_workspace


class FakeClient:
    instances = []

    def __init__(self, command, cwd, on_update=None, on_permission=None, on_error=None):
        self.on_update = on_update
        self.on_permission = on_permission
        self.on_error = on_error
        self.closed = False
        self.cancelled = False
        self.prompts = []
        self.__class__.instances.append(self)

    async def start(self):
        return self

    async def prompt(self, text):
        self.prompts.append(text)
        if self.on_update:
            await self.on_update({"update": {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "checking"}}})
            await self.on_update({"update": {"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "Read file", "status": "pending"}})
            await self.on_update({"update": {"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed"}})
            await self.on_update({"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Use `code` for the answer."}}})
        return {"stopReason": "end_turn"}

    async def cancel(self):
        self.cancelled = True

    async def close(self):
        self.closed = True


def make_app(tmp_path: Path) -> WorkspaceShell:
    path = tmp_path / "workspace"
    path.mkdir()
    workspace = current_directory_workspace(path)
    config = AppConfig(root=tmp_path / "config", tools={"fake": "fake"})
    return WorkspaceShell(config, workspace)


def install_fake(monkeypatch) -> None:
    adapter = AgentAdapter("fake", "AGENTS.md")
    monkeypatch.setattr("handoff.tui_agents.resolve_agent", lambda name, command: AgentLaunch(adapter, ["fake"], "acp"))
    monkeypatch.setattr("handoff.tui_agents.ACPClient", FakeClient)


def test_agent_tab_runs_in_shell_and_prompt_keeps_global_letters(tmp_path: Path, monkeypatch) -> None:
    install_fake(monkeypatch)
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.press("1")
            await pilot.pause()
            assert app.query_one("#right-switcher", ContentSwitcher).current == "agents-view"
            sid = next(iter(app.agent_board.sessions))
            field = app.query_one(f"#agent-input-{sid}", Input)
            assert field.has_focus
            await pilot.press("h", "q", "s")
            assert field.value == "hqs"
            await pilot.press("enter")
            await pilot.pause()
            assert FakeClient.instances[-1].prompts == ["hqs"]
            assert app.run_ledger.runs[0].prompt_count == 1
            log = app.query_one(f"#agent-log-{sid}", RichLog)
            pane = app.query_one(f"#agent-pane-{sid}")
            assert log.region.height > pane.region.height // 2, (
                pane.region,
                log.region,
                field.region,
                app.query_one(".agent-footer").region,
            )
            # Idle composer sends on Enter; the crimson Stop stays hidden until a run is live.
            assert not app.query_one(f"#agent-cancel-{sid}").display
            rendered = "\n".join(line.text for line in log.lines)
            assert all(label in rendered for label in ("❯ hqs", "think", "Read file", "◆ fake", "code"))
            code_segments = [
                segment
                for line in log.lines
                for segment in line._segments
                if "code" in segment.text
            ]
            assert code_segments and any(
                segment.style is not None and segment.style.bgcolor is not None
                for segment in code_segments
            )
            tool_entries = [entry for entry in app.agent_board.sessions[sid].transcript if entry.role == "tool"]
            assert len(tool_entries) == 1 and "completed" in tool_entries[0].text
            assert app.query_one(f"#agent-cancel-{sid}").disabled
            await pilot.press("escape")
            await pilot.pause()
            assert app.query_one("#right-switcher", ContentSwitcher).current == "overview-view"

    asyncio.run(scenario())


def test_two_instances_of_same_agent_run_side_by_side(tmp_path: Path, monkeypatch) -> None:
    install_fake(monkeypatch)
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.press("1")
            await pilot.pause()
            await pilot.press("ctrl+t")
            await pilot.pause()
            await pilot.press("1")
            await pilot.pause()
            sessions = list(app.agent_board.sessions.values())
            assert len(sessions) == 2
            assert [s.label for s in sessions] == ["fake", "fake 2"]
            # Each instance owns a distinct client and its own tab.
            assert app.query_one("#agent-tab-1")
            assert app.query_one("#agent-tab-2")

    asyncio.run(scenario())


def test_close_session_removes_its_tab(tmp_path: Path, monkeypatch) -> None:
    install_fake(monkeypatch)
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.press("1")
            await pilot.pause()
            sid = next(iter(app.agent_board.sessions))
            await app.agent_board.close_agent(sid)
            await pilot.pause()
            assert sid not in app.agent_board.sessions
            assert not app.query(f"#agent-tab-{sid}")
            assert FakeClient.instances[-1].closed

    asyncio.run(scenario())


def test_handoff_prefills_merged_agent_snapshot(tmp_path: Path, monkeypatch) -> None:
    install_fake(monkeypatch)
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.press("1")
            await pilot.pause()
            sid = next(iter(app.agent_board.sessions))
            await app.agent_board.submit(sid, "work")
            app.workspace.draft_file.write_text(
                "## LAST.md\n\n### Summary\n\nBuilt it.\n\n### Completed\n\n- Added board.\n\n### Open Issues\n\n- None\n\n## NEXT.md\n\n- Smoke test.\n",
                encoding="utf-8",
            )
            app.action_handoff()
            await pilot.pause()
            assert isinstance(app.screen, HandoffScreen)
            assert "Built it." in app.screen.summary
            assert "Added board." in app.screen.done

    asyncio.run(scenario())


def test_quit_with_live_agent_offers_handoff(tmp_path: Path, monkeypatch) -> None:
    install_fake(monkeypatch)
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.press("1")
            await pilot.pause()
            sid = next(iter(app.agent_board.sessions))
            await app.agent_board.submit(sid, "work")
            app.action_quit()
            await pilot.pause()
            assert isinstance(app.screen, QuitAgentScreen)

    asyncio.run(scenario())


def test_permission_modal_resolves_selected_option(tmp_path: Path, monkeypatch) -> None:
    install_fake(monkeypatch)
    app = make_app(tmp_path)

    async def scenario():
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.press("1")
            await pilot.pause()
            sid = next(iter(app.agent_board.sessions))
            request = asyncio.create_task(app.agent_board._request_permission(sid, {
                "message": "Allow read?",
                "options": [{"optionId": "allow-once", "name": "Allow once"}],
            }))
            await pilot.pause()
            assert isinstance(app.screen, PermissionScreen)
            await pilot.click("#permission-0")
            assert await request == "allow-once"

    asyncio.run(scenario())


def test_startup_failure_is_visible_and_can_be_retried(tmp_path: Path, monkeypatch) -> None:
    app = make_app(tmp_path)
    monkeypatch.setattr(
        "handoff.tui_agents.resolve_agent",
        lambda name, command: (_ for _ in ()).throw(RuntimeError("adapter missing")),
    )

    async def scenario():
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.press("1")
            await pilot.pause()
            sid = next(iter(app.agent_board.sessions))
            session = app.agent_board.sessions[sid]
            assert session.status == "dead" and session.client is None
            rendered = "\n".join(line.text for line in app.query_one(f"#agent-log-{sid}", RichLog).lines)
            assert "adapter missing" in rendered

    asyncio.run(scenario())
