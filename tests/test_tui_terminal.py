from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from handoff.config import AppConfig
from handoff.tui_terminal import TerminalPane


def test_terminal_queries_receive_replies():
    from unittest.mock import Mock
    import pyte
    from handoff.tui_terminal import TerminalScreen

    session = Mock()
    screen = TerminalScreen(80, 24, session)
    stream = pyte.ByteStream(screen)
    stream.feed(b"\x1b[3;7H\x1b[6n\x1b[5n\x1b[c")
    assert [call.args[0] for call in session.write.call_args_list] == [
        b"\x1b[3;7R", b"\x1b[0n", b"\x1b[?6c"
    ]


def test_final_burst_is_rendered_after_child_goes_idle():
    import asyncio
    import pyte

    pane = TerminalPane(AppConfig(tools={}), Path.cwd())

    async def scenario():
        async with TerminalTestApp(pane).run_test() as pilot:
            pane._launched = pane._pty_running = True
            pane._screen = pyte.Screen(80, 24)
            stream = pyte.ByteStream(pane._screen)
            stream.feed(b"FIRST")
            pane._request_refresh()
            pane._refresh_from_reader()
            stream.feed(b"\rFINAL")
            pane._request_refresh()
            await pilot.pause(0.15)
            assert not pane._dirty.is_set()
            assert "FINAL" in pane.render_line(0).text

    asyncio.run(scenario())


def test_paste_is_forwarded_with_bracketed_paste_mode():
    from unittest.mock import Mock
    from textual.events import Paste
    import pyte

    pane = TerminalPane(AppConfig(tools={}), Path.cwd())
    pane._pty = Mock()
    pane._pty_running = True
    pane._screen = pyte.Screen(80, 24)
    pyte.ByteStream(pane._screen).feed(b"\x1b[?2004h")
    pane.on_paste(Paste("hello\nworld"))
    pane._pty.write.assert_called_once_with(b"\x1b[200~hello\nworld\x1b[201~")


class TerminalTestApp(App):
    """Simple app for testing TerminalPane."""

    def __init__(self, terminal_pane: TerminalPane, **kwargs):
        super().__init__(**kwargs)
        self.terminal_pane = terminal_pane

    def compose(self) -> ComposeResult:
        yield self.terminal_pane


def test_idle_render_shows_tools():
    """Before launch, render shows available tools."""
    config = AppConfig(
        tools={"echo": "echo", "grok": "grok"}
    )
    pane = TerminalPane(config, Path.cwd())

    async def _test():
        app = TerminalTestApp(pane)
        async with app.run_test() as pilot:
            text_content = pane.render().plain
            assert "echo" in text_content
            assert "grok" in text_content
            assert "select an agent" in text_content.lower()

    import asyncio
    asyncio.run(_test())


def test_launch_success():
    """launch() spawns the tool and returns True."""
    script = 'import sys; sys.stdout.write("READY\\n"); sys.stdout.flush(); import time; time.sleep(10)'
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(script)
        script_path = f.name

    try:
        cmd = f'{sys.executable} {script_path}'
        config = AppConfig(tools={"test": cmd})
        pane = TerminalPane(config, Path.cwd())

        async def _test():
            app = TerminalTestApp(pane)
            async with app.run_test() as pilot:
                result = pane.launch("test")
                assert result is True
                assert pane.is_running()

                import asyncio
                for _ in range(250):
                    await pilot.pause()
                    await asyncio.sleep(0.02)
                    if pane._screen is not None:
                        display_text = "".join(pane._screen.display)
                        if "READY" in display_text:
                            break

                assert pane._screen is not None
                display_text = "".join(pane._screen.display)
                assert "READY" in display_text
                pane.kill()

        import asyncio
        asyncio.run(_test())
    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass


def test_key_input_echo():
    """Input sent to terminal appears in output."""
    script = 'import sys; sys.stdout.write("READY\\n"); sys.stdout.flush(); line=sys.stdin.readline(); sys.stdout.write("GOT:"+line); sys.stdout.flush()'
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(script)
        script_path = f.name

    try:
        cmd = f'{sys.executable} {script_path}'
        config = AppConfig(tools={"echo": cmd})
        pane = TerminalPane(config, Path.cwd())

        async def _test():
            app = TerminalTestApp(pane)
            async with app.run_test() as pilot:
                pane.launch("echo")
                import asyncio
                for _ in range(250):
                    await pilot.pause()
                    await asyncio.sleep(0.02)
                    if pane._screen is not None and "READY" in "".join(pane._screen.display):
                        break

                pane.focus()
                await pilot.press("t", "e", "s", "t", "enter")

                for _ in range(250):
                    await pilot.pause()
                    await asyncio.sleep(0.02)
                    if pane._screen is not None:
                        display_text = "".join(pane._screen.display)
                        if "GOT:" in display_text:
                            break

                assert pane._screen is not None
                display_text = "".join(pane._screen.display)
                assert "GOT:" in display_text
                pane.kill()

        import asyncio
        asyncio.run(_test())
    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass


def test_shutdown():
    """shutdown() stops the process and joins the thread."""
    cmd = f'{sys.executable} -c "import time; time.sleep(10)"'
    config = AppConfig(tools={"sleep": cmd})
    pane = TerminalPane(config, Path.cwd())

    async def _test():
        app = TerminalTestApp(pane)
        async with app.run_test() as pilot:
            pane.launch("sleep")
            import asyncio
            await asyncio.sleep(0.1)
            assert pane.is_running()
            await pane.shutdown()
            assert not pane.is_running()

    import asyncio
    asyncio.run(_test())


def test_launch_twice_returns_false():
    """Launching while already running returns False."""
    cmd = f'{sys.executable} -c "import time; time.sleep(10)"'
    config = AppConfig(tools={"sleep": cmd})
    pane = TerminalPane(config, Path.cwd())

    async def _test():
        app = TerminalTestApp(pane)
        async with app.run_test() as pilot:
            result1 = pane.launch("sleep")
            assert result1 is True
            result2 = pane.launch("sleep")
            assert result2 is False
            pane.kill()

    import asyncio
    asyncio.run(_test())


def test_launch_invalid_tool_returns_false():
    """Launching a non-existent tool returns False."""
    config = AppConfig(tools={"existing": "echo"})
    pane = TerminalPane(config, Path.cwd())

    async def _test():
        app = TerminalTestApp(pane)
        async with app.run_test() as pilot:
            result = pane.launch("nonexistent")
            assert result is False
            assert not pane.is_running()

    import asyncio
    asyncio.run(_test())


def test_render_after_exit():
    """After killing, render shows ended message."""
    cmd = f'{sys.executable} -c "import time; time.sleep(10)"'
    config = AppConfig(tools={"sleep": cmd})
    pane = TerminalPane(config, Path.cwd())

    async def _test():
        app = TerminalTestApp(pane)
        async with app.run_test() as pilot:
            pane.launch("sleep")
            import asyncio
            await asyncio.sleep(0.2)
            assert pane.is_running()

            # Explicitly kill
            pane.kill()
            assert not pane.is_running()

            # After killing, should show ended message
            text_content = pane.render().plain
            assert "ended" in text_content.lower()

    import asyncio
    asyncio.run(_test())
