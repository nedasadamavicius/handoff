from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.app import App
from textual.widgets import DataTable, Label

from handoff.tui_screens import KnowledgeScreen


@pytest.mark.parametrize("has_outgoing,has_incoming", [(False, False), (True, False), (False, True), (True, True)])
def test_graph_shows_none_only_for_empty_link_directions(tmp_path: Path, has_outgoing: bool, has_incoming: bool) -> None:
    (tmp_path / "selected.md").write_text(
        "# Selected\n" + ("[[target]]" if has_outgoing else ""), encoding="utf-8"
    )
    (tmp_path / "target.md").write_text("# Target", encoding="utf-8")
    (tmp_path / "source.md").write_text(
        "# Source\n" + ("[Selected](selected.md)" if has_incoming else ""), encoding="utf-8"
    )
    app = App()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            screen = KnowledgeScreen(tmp_path, tmp_path / "selected.md")
            await app.push_screen(screen)
            await pilot.pause()
            graph = str(screen.query_one("#knowledge-graph", Label).content)
            outgoing, incoming = graph.split("Links to:\n", 1)[1].split("\n\nLinked from:\n")
            assert outgoing == ("  → Target  (target.md)" if has_outgoing else "  (none)")
            assert incoming == ("  ← Source  (source.md)" if has_incoming else "  (none)")

    asyncio.run(scenario())


def test_search_renders_note_text_without_interpreting_markup(tmp_path: Path) -> None:
    folder = tmp_path / "[bold]"
    folder.mkdir()
    note_path = folder / "note.md"
    note_path.write_text("# Arrays [/index]\n\n[[missing[/link]]]", encoding="utf-8")
    app = App()

    async def scenario() -> None:
        async with app.run_test(size=(115, 36)) as pilot:
            screen = KnowledgeScreen(tmp_path)
            await app.push_screen(screen)
            await pilot.pause()
            await pilot.press("a", "r", "r", "a", "y", "s")
            await pilot.pause()
            table = screen.query_one("#knowledge-results", DataTable)
            assert table.row_count == 1
            title, path = table.get_row_at(0)
            assert title.plain == "Arrays [/index]"
            assert path.plain == str(note_path.relative_to(tmp_path))
            graph = screen.query_one("#knowledge-graph", Label)
            assert "Arrays [/index]" in str(graph.content)
            assert "missing[/link" in str(graph.content)
            await pilot.press("tab", "enter")
            await pilot.pause()
            assert screen.selected == note_path.relative_to(tmp_path)
            await pilot.press("escape")
            await pilot.pause()
            assert screen not in app.screen_stack

    asyncio.run(scenario())
