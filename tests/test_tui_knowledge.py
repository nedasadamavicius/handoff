from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.app import App

from handoff.tui_screens import KnowledgeScreen, GraphView


def test_preview_empty_on_open(tmp_path: Path) -> None:
    """Test that the preview is empty when the screen opens."""
    (tmp_path / "note.md").write_text("# Note", encoding="utf-8")
    app = App()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            screen = KnowledgeScreen(tmp_path)
            await app.push_screen(screen)
            await pilot.pause()

            # Should show placeholder text
            assert "Select a note from the graph" in screen.preview_source

    asyncio.run(scenario())


def test_clicking_node_loads_preview(tmp_path: Path) -> None:
    """Test that clicking a graph node loads the note in the preview."""
    (tmp_path / "note.md").write_text("# Test Note\n\nContent here", encoding="utf-8")
    app = App()

    async def scenario() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            screen = KnowledgeScreen(tmp_path)
            await app.push_screen(screen)
            await pilot.pause()

            # The note should be in the graph
            graph = screen.query_one("#knowledge-graph", GraphView)
            assert Path("note.md") in graph.node_positions

            # Simulate a click by posting the NodeSelected message
            graph.post_message(GraphView.NodeSelected(Path("note.md")))
            await pilot.pause()

            # Preview should now show the content
            assert "Test Note" in screen.preview_source
            assert "Content here" in screen.preview_source
            assert screen.selected == Path("note.md")

    asyncio.run(scenario())


def test_markup_renders_safely(tmp_path: Path) -> None:
    """Test that special characters like [/index] render safely."""
    folder = tmp_path / "[bold]"
    folder.mkdir()
    note_path = folder / "note.md"
    note_path.write_text("# Arrays [/index]\n\n[[missing[/link]]]", encoding="utf-8")
    app = App()

    async def scenario() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            screen = KnowledgeScreen(tmp_path)
            await app.push_screen(screen)
            await pilot.pause()

            # The note should appear in the graph
            graph = screen.query_one("#knowledge-graph", GraphView)
            assert note_path.relative_to(tmp_path) in graph.node_positions

            # Simulate a click
            graph.post_message(GraphView.NodeSelected(note_path.relative_to(tmp_path)))
            await pilot.pause()

            # Check that the content appears safely (not interpreted as markup)
            assert "Arrays [/index]" in screen.preview_source
            assert "missing[/link]" in screen.preview_source

            await pilot.press("escape")
            await pilot.pause()
            assert screen not in app.screen_stack

    asyncio.run(scenario())


def test_initial_path_loads_preview(tmp_path: Path) -> None:
    """Test that passing initial_path loads that note on open."""
    (tmp_path / "a.md").write_text("# A\n\n[[b]]", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n\nContent", encoding="utf-8")
    app = App()

    async def scenario() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            screen = KnowledgeScreen(tmp_path, tmp_path / "b.md")
            await app.push_screen(screen)
            await pilot.pause()

            # B should be selected and loaded
            assert screen.selected == Path("b.md")
            assert "B" in screen.preview_source
            assert "Content" in screen.preview_source

    asyncio.run(scenario())


def test_pressing_e_dismisses_with_path(tmp_path: Path) -> None:
    """Test that pressing 'e' dismisses the screen and returns the note path."""
    note_path = tmp_path / "note.md"
    note_path.write_text("# Note", encoding="utf-8")
    app = App()

    async def scenario() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            screen = KnowledgeScreen(tmp_path)
            await app.push_screen(screen)
            await pilot.pause()

            # Select the note
            graph = screen.query_one("#knowledge-graph", GraphView)
            graph.post_message(GraphView.NodeSelected(Path("note.md")))
            await pilot.pause()

            # Press 'e' to edit
            await pilot.press("e")
            await pilot.pause()

            # Screen should be dismissed with the path
            assert screen not in app.screen_stack

    asyncio.run(scenario())


def test_pressing_esc_dismisses_without_path(tmp_path: Path) -> None:
    """Test that pressing Esc dismisses the screen with None."""
    note_path = tmp_path / "note.md"
    note_path.write_text("# Note", encoding="utf-8")
    app = App()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            screen = KnowledgeScreen(tmp_path)
            await app.push_screen(screen)
            await pilot.pause()

            # Press Escape to close
            await pilot.press("escape")
            await pilot.pause()

            # Screen should be dismissed with None
            assert screen not in app.screen_stack

    asyncio.run(scenario())


def _widget_offset(graph: GraphView, path: Path, dx: int = 0) -> tuple[int, int]:
    """Widget-relative coordinates of a node, including the border the widget draws inside."""
    x, y = graph.node_positions[path]
    return x + dx + graph.content_region.x - graph.region.x, y + graph.content_region.y - graph.region.y


def test_real_mouse_click_on_node_opens_it(tmp_path: Path) -> None:
    (tmp_path / "alpha.md").write_text("# Alpha\n\n[[beta]]", encoding="utf-8")
    (tmp_path / "beta.md").write_text("# Beta\n\nBody", encoding="utf-8")
    app = App()

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            screen = KnowledgeScreen(tmp_path)
            await app.push_screen(screen)
            await pilot.pause()
            graph = screen.query_one("#knowledge-graph", GraphView)
            graph.render()  # lay out nodes for the current size
            await pilot.click(GraphView, offset=_widget_offset(graph, Path("beta.md"), 1))
            await pilot.pause()
            assert screen.selected == Path("beta.md")

    asyncio.run(scenario())


def test_dragging_a_node_moves_it_without_selecting(tmp_path: Path) -> None:
    (tmp_path / "alpha.md").write_text("# Alpha\n\n[[beta]]", encoding="utf-8")
    (tmp_path / "beta.md").write_text("# Beta", encoding="utf-8")
    app = App()

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            screen = KnowledgeScreen(tmp_path)
            await app.push_screen(screen)
            await pilot.pause()
            graph = screen.query_one("#knowledge-graph", GraphView)
            graph.render()
            path = Path("beta.md")
            start = _widget_offset(graph, path, 1)
            before = graph.node_positions[path]
            target = (start[0] + 0, 3 if before[1] > 6 else 12)
            await pilot.mouse_down(GraphView, offset=start)
            await pilot.hover(GraphView, offset=target)
            await pilot.mouse_up(GraphView, offset=target)
            await pilot.pause()
            assert graph.node_positions[path] != before
            assert path in graph.dragged
            assert screen.selected is None

    asyncio.run(scenario())


def _graph_app_scenario(tmp_path: Path):
    for name in ("alpha", "beta", "gamma"):
        (tmp_path / f"{name}.md").write_text(f"# {name.title()}\n\n[[alpha]]", encoding="utf-8")
    return App()


def test_dragging_empty_space_pans_the_graph(tmp_path: Path) -> None:
    app = _graph_app_scenario(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            screen = KnowledgeScreen(tmp_path)
            await app.push_screen(screen)
            await pilot.pause()
            graph = screen.query_one("#knowledge-graph", GraphView)
            graph.render()
            taken = {(x + i, y) for p, (x, y) in graph.node_positions.items() for i in range(graph._node_width(p))}
            width, height = graph.content_region.width, graph.content_region.height
            empty = next((x, y) for y in range(height - 1, -1, -1) for x in range(width) if (x, y) not in taken)
            ox, oy = graph.content_region.x - graph.region.x, graph.content_region.y - graph.region.y
            start = (empty[0] + ox, empty[1] + oy)
            before = graph.pan
            await pilot.mouse_down(GraphView, offset=start)
            await pilot.hover(GraphView, offset=(start[0] + 3, start[1]))
            await pilot.mouse_up(GraphView, offset=(start[0] + 3, start[1]))
            await pilot.pause()
            assert graph.pan != before
            assert screen.selected is None

    asyncio.run(scenario())


def test_mouse_wheel_zooms_the_graph(tmp_path: Path) -> None:
    app = _graph_app_scenario(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            screen = KnowledgeScreen(tmp_path)
            await app.push_screen(screen)
            await pilot.pause()
            graph = screen.query_one("#knowledge-graph", GraphView)
            graph.render()
            before = graph.zoom
            graph.on_mouse_scroll_up(_FakeWheel())
            assert graph.zoom > before
            graph.on_mouse_scroll_down(_FakeWheel())
            graph.on_mouse_scroll_down(_FakeWheel())
            assert graph.zoom < before

    asyncio.run(scenario())


class _FakeWheel:
    def get_content_offset(self, widget):
        return None

    def stop(self) -> None:
        pass


def test_graph_starts_fitted_so_every_node_is_visible(tmp_path: Path) -> None:
    app = _graph_app_scenario(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            screen = KnowledgeScreen(tmp_path)
            await app.push_screen(screen)
            await pilot.pause()
            graph = screen.query_one("#knowledge-graph", GraphView)
            graph.render()
            for path, (x, y) in graph.node_positions.items():
                assert 0 <= x and x + graph._node_width(path) <= graph.size.width, path
                assert 0 <= y < graph.size.height, path

    asyncio.run(scenario())
