"""Mouse-driven note graph drawn on a Braille dot canvas.

Every cell has one foreground colour, chosen by what matters most in it
(selected note > linked note > other note > highlighted link > link). Nodes live in
world coordinates so the view can pan, zoom and be rearranged by dragging without
re-running the layout.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from rich.color import Color, ColorParseError
from rich.style import Style
from rich.text import Text
from textual.message import Message
from textual.widget import Widget

from handoff.braille_canvas import DOTS_PER_CELL_X, DOTS_PER_CELL_Y, BrailleCanvas
from handoff.graph_layout import compute_node_positions

RGB = tuple[float, float, float]
Cell = tuple[str, Style]

MINIMUM_RENDER_WIDTH = 10
MINIMUM_RENDER_HEIGHT = 3
LABEL_RESERVED_PADDING_CELLS = 8
VERTICAL_FIT_PADDING_DOTS = 12
MAXIMUM_FIT_ZOOM = 3.0
NODE_HIT_PADDING_DOTS = 2
ZOOM_IN_FACTOR = 1.25
ZOOM_OUT_FACTOR = 0.8
LINK_BLEND_ALPHA = 0.4
NODE_BLEND_ALPHA = 0.8
UNLINKED_LABEL_BLEND_ALPHA = 0.6


class CellPriority(IntEnum):
    LINK = 1
    HOT_LINK = 2
    NODE = 3
    LINKED_NODE = 4
    SELECTED_NODE = 5


@dataclass(frozen=True)
class GraphColors:
    surface: RGB
    primary: RGB
    accent: RGB
    secondary: RGB
    foreground: RGB

    def priority_palette(self) -> dict[CellPriority, RGB]:
        return {
            CellPriority.LINK: _blend(self.surface, self.secondary, LINK_BLEND_ALPHA),
            CellPriority.HOT_LINK: self.primary,
            CellPriority.NODE: _blend(self.surface, self.secondary, NODE_BLEND_ALPHA),
            CellPriority.LINKED_NODE: self.accent,
            CellPriority.SELECTED_NODE: self.primary,
        }


@dataclass
class NodeDrag:
    path: Path
    grab_offset_dots: tuple[float, float]
    moved: bool = False


@dataclass
class PanDrag:
    start_cell: tuple[int, int]
    start_pan: tuple[float, float]
    moved: bool = False


def _blend(base: RGB, top: RGB, alpha: float) -> RGB:
    return tuple(base_channel + (top_channel - base_channel) * alpha for base_channel, top_channel in zip(base, top))


def _parse_rgb(value: str, fallback: RGB) -> RGB:
    try:
        triplet = Color.parse(value).get_truecolor()
    except ColorParseError:
        return fallback
    return (float(triplet.red), float(triplet.green), float(triplet.blue))


def _hex(color: RGB) -> str:
    red, green, blue = (max(0, min(255, round(channel))) for channel in color)
    return f"#{red:02x}{green:02x}{blue:02x}"


class GraphView(Widget):
    """Node-link diagram of the notes; click selects, drag moves, wheel zooms, empty-space drag pans."""

    DEFAULT_CSS = """
    GraphView {
        width: 50%;
        border: round $secondary;
        background: $surface;
    }
    """
    ALLOW_SELECT = False
    LABEL_WIDTH = 24
    MIN_ZOOM = 0.1
    MAX_ZOOM = 12.0

    class NodeSelected(Message):
        """Posted when a node is clicked."""

        def __init__(self, path: Path) -> None:
            super().__init__()
            self.path = path

    def __init__(self, index, selected_path: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.index = index
        self.selected_path = selected_path
        self.can_focus = False
        self.world: dict[Path, tuple[float, float]] = {}
        self.zoom = 1.0
        self.pan = (0.0, 0.0)
        self.dragged: set[Path] = set()
        self._laid_out_index = None
        self._fitted = False
        self._drag: NodeDrag | PanDrag | None = None
        self._style_cache: dict[tuple, Style] = {}
        self._hidden_labels: set[Path] = set()

    @property
    def _has_notes(self) -> bool:
        return bool(self.index and self.index.notes)

    @property
    def _is_large_enough(self) -> bool:
        return self.size.width >= MINIMUM_RENDER_WIDTH and self.size.height >= MINIMUM_RENDER_HEIGHT

    def _to_dots(self, world_x: float, world_y: float) -> tuple[float, float]:
        return (world_x - self.pan[0]) * self.zoom, (world_y - self.pan[1]) * self.zoom

    def _to_world(self, dot_x: float, dot_y: float) -> tuple[float, float]:
        return dot_x / self.zoom + self.pan[0], dot_y / self.zoom + self.pan[1]

    @staticmethod
    def _cell_center_in_dots(column: int, row: int) -> tuple[float, float]:
        return column * DOTS_PER_CELL_X + DOTS_PER_CELL_X / 2, row * DOTS_PER_CELL_Y + DOTS_PER_CELL_Y / 2

    def _radius(self, path: Path) -> float:
        """Disc radius in dots, growing with how many notes link here."""
        link_count = self.index.notes[path].link_count
        return max(1.2, min(6.0, (1.5 + 0.35 * link_count) * self.zoom**0.4))

    def _radius_cells(self, path: Path) -> int:
        return math.ceil(self._radius(path) / DOTS_PER_CELL_X)

    def _label(self, path: Path) -> str:
        return self.index.notes[path].title

    def _labelled_paths(self) -> set[Path]:
        return set(self.world) - self._hidden_labels

    @property
    def node_positions(self) -> dict[Path, tuple[int, int]]:
        """Left cell of each node's hit box (disc plus visible title), content-area relative."""
        self._ensure_layout()
        positions = {}
        for path, world_position in self.world.items():
            dot_x, dot_y = self._to_dots(*world_position)
            positions[path] = (
                round(dot_x / DOTS_PER_CELL_X) - self._radius_cells(path),
                round(dot_y / DOTS_PER_CELL_Y),
            )
        return positions

    def node_width(self, path: Path) -> int:
        width = 2 * self._radius_cells(path) + 1
        if path in self._labelled_paths():
            width += 1 + len(self._label(path))
        return width

    def select(self, path: Path | None) -> None:
        self.selected_path = path
        self.refresh()

    def _theme_color(self, name: str, fallback: RGB) -> RGB:
        value = self.app.theme_variables.get(name)
        return _parse_rgb(value, fallback) if value else fallback

    def _theme_colors(self) -> GraphColors:
        return GraphColors(
            surface=self._theme_color("surface", (23.0, 23.0, 23.0)),
            primary=self._theme_color("primary", (220.0, 20.0, 60.0)),
            accent=self._theme_color("accent", (192.0, 57.0, 43.0)),
            secondary=self._theme_color("secondary", (139.0, 0.0, 0.0)),
            foreground=self._theme_color("foreground", (232.0, 232.0, 232.0)),
        )

    def _ensure_layout(self) -> None:
        if not self._has_notes:
            self.world = {}
            return
        if self._laid_out_index is not self.index:
            self._laid_out_index = self.index
            self.world = compute_node_positions(self.index)
            self._fitted = False
        if not self._fitted and self._is_large_enough:
            self.fit()

    def fit(self) -> None:
        """Zoom and pan so every node (and its title, when shown) is visible."""
        if not self.world or not self._is_large_enough:
            return
        world_xs = [world_x for world_x, _ in self.world.values()]
        world_ys = [world_y for _, world_y in self.world.values()]
        world_width, world_height = max(world_xs) - min(world_xs), max(world_ys) - min(world_ys)
        longest_label = max((len(self._label(path)) for path in self.world), default=self.LABEL_WIDTH)
        label_cells = min(longest_label, max(self.LABEL_WIDTH, self.size.width // 2))
        label_dots = (label_cells + LABEL_RESERVED_PADDING_CELLS) * DOTS_PER_CELL_X
        canvas_width_dots = self.size.width * DOTS_PER_CELL_X
        canvas_height_dots = self.size.height * DOTS_PER_CELL_Y
        zoom_to_fit_width = (canvas_width_dots - label_dots) / world_width if world_width else self.MAX_ZOOM
        zoom_to_fit_height = (
            (canvas_height_dots - VERTICAL_FIT_PADDING_DOTS) / world_height if world_height else self.MAX_ZOOM
        )
        self.zoom = max(self.MIN_ZOOM, min(MAXIMUM_FIT_ZOOM, zoom_to_fit_width, zoom_to_fit_height))
        margin_x_dots = (canvas_width_dots - world_width * self.zoom - label_dots) / 2 + LABEL_RESERVED_PADDING_CELLS
        margin_y_dots = (canvas_height_dots - world_height * self.zoom) / 2
        self.pan = (min(world_xs) - margin_x_dots / self.zoom, min(world_ys) - margin_y_dots / self.zoom)
        self._fitted = True
        self.refresh()

    def render(self) -> Text:
        if not self._has_notes:
            return Text("No notes")
        if not self._is_large_enough:
            return Text("Graph too small")
        self._ensure_layout()

        colors = self._theme_colors()
        linked_paths = self._paths_linked_to_selection()
        centers = {path: self._to_dots(*world_position) for path, world_position in self.world.items()}
        canvas = self._draw_canvas(centers, linked_paths)
        rows = self._rows_from_canvas(canvas, colors)
        self._place_labels(rows, centers, linked_paths, colors)
        return self._text_from_rows(rows)

    def _paths_linked_to_selection(self) -> set[Path]:
        selected_note = self.index.notes.get(self.selected_path) if self.selected_path else None
        return set(selected_note.outgoing) | set(selected_note.incoming) if selected_note else set()

    def _draw_canvas(self, centers: dict[Path, tuple[float, float]], linked_paths: set[Path]) -> BrailleCanvas:
        canvas = BrailleCanvas(self.size.width, self.size.height)
        for path, note in self.index.notes.items():
            for target in note.outgoing:
                if target in centers:
                    touches_selection = self.selected_path in (path, target)
                    priority = CellPriority.HOT_LINK if touches_selection else CellPriority.LINK
                    canvas.draw_line(centers[path], centers[target], priority)
        for path, center in centers.items():
            canvas.draw_disc(center, self._radius(path), self._node_priority(path, linked_paths))
        return canvas

    def _node_priority(self, path: Path, linked_paths: set[Path]) -> CellPriority:
        if path == self.selected_path:
            return CellPriority.SELECTED_NODE
        return CellPriority.LINKED_NODE if path in linked_paths else CellPriority.NODE

    def _rows_from_canvas(self, canvas: BrailleCanvas, colors: GraphColors) -> list[list[Cell]]:
        blank_cell = (" ", self._style(None, colors.surface))
        palette = colors.priority_palette()
        rows = []
        for row in range(canvas.height_cells):
            cells = []
            for column in range(canvas.width_cells):
                glyph = canvas.glyph_at(column, row)
                if glyph is None:
                    cells.append(blank_cell)
                else:
                    color = palette[CellPriority(canvas.priority_at(column, row))]
                    cells.append((glyph, self._style(color, colors.surface)))
            rows.append(cells)
        return rows

    def _place_labels(
        self,
        rows: list[list[Cell]],
        centers: dict[Path, tuple[float, float]],
        linked_paths: set[Path],
        colors: GraphColors,
    ) -> None:
        """Write titles beside the discs, most important notes first; crowded ones are hidden."""
        occupied = self._cells_covered_by_discs(centers)
        self._hidden_labels = set()
        for path in self._paths_by_label_importance(centers, linked_paths):
            label = self._label(path)
            spot = self._find_label_spot(path, centers[path], len(label), occupied)
            if spot is None:
                self._hidden_labels.add(path)
                continue
            left_column, row, footprint = spot
            occupied |= footprint
            style = self._label_style(path, linked_paths, colors)
            for offset, character in enumerate(label):
                if 0 <= left_column + offset < self.size.width:
                    rows[row][left_column + offset] = (character, style)

    def _paths_by_label_importance(
        self, centers: dict[Path, tuple[float, float]], linked_paths: set[Path]
    ) -> list[Path]:
        return sorted(
            centers,
            key=lambda path: (
                path != self.selected_path,
                path not in linked_paths,
                -self.index.notes[path].link_count,
                str(path),
            ),
        )

    def _cells_covered_by_discs(self, centers: dict[Path, tuple[float, float]]) -> set[tuple[int, int]]:
        covered: set[tuple[int, int]] = set()
        for path, (dot_x, dot_y) in centers.items():
            radius = self._radius(path)
            for row in range(
                math.floor((dot_y - radius) / DOTS_PER_CELL_Y), math.floor((dot_y + radius) / DOTS_PER_CELL_Y) + 1
            ):
                covered.update(
                    (column, row)
                    for column in range(
                        math.floor((dot_x - radius) / DOTS_PER_CELL_X),
                        math.floor((dot_x + radius) / DOTS_PER_CELL_X) + 1,
                    )
                )
        return covered

    def _find_label_spot(
        self, path: Path, center: tuple[float, float], label_length: int, occupied: set[tuple[int, int]]
    ) -> tuple[int, int, set[tuple[int, int]]] | None:
        """Where a title fits as (left column, row, footprint): right of the disc first, else left; None if crowded."""
        center_column = round(center[0] / DOTS_PER_CELL_X)
        center_row = round(center[1] / DOTS_PER_CELL_Y)
        radius_cells = self._radius_cells(path)
        for left_column in (
            center_column + radius_cells + 1,
            center_column - radius_cells - label_length - 1,
        ):
            for row in (center_row, center_row + 1, center_row - 1):
                footprint = {(left_column + offset, row) for offset in range(-1, label_length + 1)}
                fits = (
                    0 <= left_column and left_column + label_length <= self.size.width and 0 <= row < self.size.height
                )
                if fits and not footprint & occupied:
                    return left_column, row, footprint
        return None

    def _label_style(self, path: Path, linked_paths: set[Path], colors: GraphColors) -> Style:
        if path == self.selected_path:
            return self._style(colors.primary, colors.surface, bold=True)
        if path in linked_paths:
            return self._style(colors.foreground, colors.surface, bold=True)
        faded = _blend(colors.surface, colors.foreground, UNLINKED_LABEL_BLEND_ALPHA)
        return self._style(faded, colors.surface, dim=True)

    @staticmethod
    def _text_from_rows(rows: list[list[Cell]]) -> Text:
        """One span per run of identical style keeps Rich's work, and the terminal output, small."""
        text = Text(no_wrap=True, overflow="crop", end="")
        for row_number, row in enumerate(rows):
            run_characters: list[str] = []
            run_style = row[0][1]
            for character, style in row:
                if style is not run_style:
                    text.append("".join(run_characters), run_style)
                    run_characters, run_style = [], style
                run_characters.append(character)
            text.append("".join(run_characters), run_style)
            if row_number < len(rows) - 1:
                text.append("\n")
        return text

    def _style(self, foreground: RGB | None, background: RGB, bold: bool = False, dim: bool = False) -> Style:
        key = (foreground, background, bold, dim)
        style = self._style_cache.get(key)
        if style is None:
            style = Style(
                color=_hex(foreground) if foreground else None,
                bgcolor=_hex(background),
                bold=bold or None,
                dim=dim or None,
            )
            self._style_cache[key] = style
        return style

    def _node_at(self, column: int, row: int) -> Path | None:
        for path, (left_column, node_row) in self.node_positions.items():
            if node_row == row and left_column <= column < left_column + self.node_width(path):
                return path
        click_x, click_y = self._cell_center_in_dots(column, row)
        for path, world_position in self.world.items():
            center_x, center_y = self._to_dots(*world_position)
            if math.hypot(click_x - center_x, click_y - center_y) <= self._radius(path) + NODE_HIT_PADDING_DOTS:
                return path
        return None

    def on_mouse_down(self, event) -> None:
        offset = event.get_content_offset(self)
        if offset is None:
            return
        path = self._node_at(offset.x, offset.y)
        if path is not None:
            node_x, node_y = self._to_dots(*self.world[path])
            click_x, click_y = self._cell_center_in_dots(offset.x, offset.y)
            self._drag = NodeDrag(path, (click_x - node_x, click_y - node_y))
        else:
            self._drag = PanDrag((offset.x, offset.y), self.pan)
        self.capture_mouse()
        event.stop()

    def on_mouse_move(self, event) -> None:
        if self._drag is None:
            return
        offset = event.get_content_offset_capture(self)
        if isinstance(self._drag, NodeDrag):
            self._move_dragged_node(self._drag, offset.x, offset.y)
        else:
            self._pan_to(self._drag, offset.x, offset.y)

    def _move_dragged_node(self, drag: NodeDrag, column: int, row: int) -> None:
        click_x, click_y = self._cell_center_in_dots(column, row)
        grab_x, grab_y = drag.grab_offset_dots
        new_position = self._to_world(click_x - grab_x, click_y - grab_y)
        if new_position != self.world[drag.path]:
            self.world[drag.path] = new_position
            self.dragged.add(drag.path)
            drag.moved = True
            self.refresh()

    def _pan_to(self, drag: PanDrag, column: int, row: int) -> None:
        start_column, start_row = drag.start_cell
        new_pan = (
            drag.start_pan[0] - (column - start_column) * DOTS_PER_CELL_X / self.zoom,
            drag.start_pan[1] - (row - start_row) * DOTS_PER_CELL_Y / self.zoom,
        )
        if new_pan != self.pan:
            self.pan = new_pan
            drag.moved = True
            self.refresh()

    def on_mouse_up(self, _event) -> None:
        drag, self._drag = self._drag, None
        if drag is None:
            return
        self.release_mouse()
        if isinstance(drag, NodeDrag) and not drag.moved:
            self.post_message(self.NodeSelected(drag.path))

    def _zoom_by(self, factor: float, event) -> None:
        offset = event.get_content_offset(self)
        if offset is not None:
            anchor_x, anchor_y = self._cell_center_in_dots(offset.x, offset.y)
        else:
            anchor_x, anchor_y = self.size.width * 1.0, self.size.height * 2.0
        world_x, world_y = self._to_world(anchor_x, anchor_y)
        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.zoom * factor))
        self.pan = (world_x - anchor_x / self.zoom, world_y - anchor_y / self.zoom)
        self.refresh()
        event.stop()

    def on_mouse_scroll_up(self, event) -> None:
        self._zoom_by(ZOOM_IN_FACTOR, event)

    def on_mouse_scroll_down(self, event) -> None:
        self._zoom_by(ZOOM_OUT_FACTOR, event)
