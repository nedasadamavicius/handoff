from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Label
from textual.widgets._footer import FooterKey

from handoff.tui import WorkspaceShell
from handoff.tui_footer import ResponsiveFooter, pack_rows


class _FooterApp(App):
    BINDINGS = WorkspaceShell.BINDINGS

    def compose(self) -> ComposeResult:
        yield Label("body")
        yield ResponsiveFooter()


def _shown(app: App) -> tuple[int, bool, set[str]]:
    footer = app.query_one(ResponsiveFooter)
    keys = [key for key in footer.query(FooterKey) if "-command-palette" not in key.classes]
    visible = {
        key.description
        for key in keys
        if key.region.width and key.region.right <= app.size.width and key.region.bottom <= app.size.height
    }
    return footer.region.height, footer.compact, visible


def test_pack_rows_wraps_greedily() -> None:
    assert pack_rows([5, 5, 5], 10) == [2, 1]
    assert pack_rows([12], 10) == [1]
    assert pack_rows([], 10) == [0]


def test_footer_shows_every_key_at_any_width() -> None:
    expected = {binding.description for binding in WorkspaceShell.BINDINGS if binding.show}

    async def run() -> None:
        app = _FooterApp()
        async with app.run_test(size=(220, 20)) as pilot:
            await pilot.pause()
            height, compact, visible = _shown(app)
            assert (height, compact, visible) == (1, False, expected)

            for width in (160, 120, 80):
                await pilot.resize_terminal(width, 20)
                await pilot.pause()
                await pilot.pause()
                height, compact, visible = _shown(app)
                assert compact and height > 1, width
                assert visible == expected, width

            await pilot.resize_terminal(220, 20)
            await pilot.pause()
            await pilot.pause()
            assert _shown(app) == (1, False, expected)

    asyncio.run(run())


def test_browser_gives_up_width_before_the_overview() -> None:
    from handoff.tui import browser_width

    assert browser_width(220) == 40
    assert browser_width(140) == 40
    assert browser_width(120) == 20
    assert browser_width(80) == 20


def test_browser_shrinks_with_the_terminal(tmp_path) -> None:
    from test_tui_agents import make_app

    app = make_app(tmp_path)

    async def run() -> None:
        async with app.run_test(size=(200, 30)) as pilot:
            await pilot.pause()
            browser = app.query_one("#browser")
            last = app.query_one("#last-container")
            assert browser.region.width == 40
            await pilot.resize_terminal(115, 30)
            await pilot.pause()
            assert browser.region.width == 20
            assert last.region.width > 40

    asyncio.run(run())
