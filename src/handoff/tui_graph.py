"""Mouse-driven note graph drawn on a Braille dot canvas.

Each terminal cell is a 2x4 grid of Braille dots, four times the resolution of
block glyphs, so links are thin smooth lines and nodes are round dot discs.
Every cell has one foreground colour, chosen by what matters most in it
(selected note > linked note > other note > highlighted link > link). Nodes
live in world coordinates so the view can pan, zoom and be rearranged by
dragging without re-running the layout.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

from rich.color import Color
from rich.style import Style
from rich.text import Text
from textual.message import Message
from textual.widget import Widget

RGB = tuple[float, float, float]
BRAILLE_BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))  # [dot row][dot column]
LAYOUT_SPACING = 1.8  # multiplier on the ideal node distance; higher spreads clusters out
LAYOUT_GRAVITY = 0.15  # pull towards the centre; keeps unlinked notes on a tidy outer ring
LAYOUT_BUDGET_SECONDS = 0.4  # keep `g` responsive on big vaults; the layout just stops early

# Colour priority for a cell that holds several things.
_LINK, _HOT_LINK, _NODE, _LINKED_NODE, _SELECTED_NODE = 1, 2, 3, 4, 5


def _mix(base: RGB, top: RGB, alpha: float) -> RGB:
    return tuple(b + (t - b) * alpha for b, t in zip(base, top))


def _rgb(value: str, fallback: RGB) -> RGB:
    try:
        triplet = Color.parse(value).get_truecolor()
    except Exception:
        return fallback
    return (float(triplet.red), float(triplet.green), float(triplet.blue))


def _hex(color: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, round(c))) for c in color))


class GraphView(Widget):
    """Node-link diagram of the notes; click selects, drag moves, wheel zooms, empty-space drag pans."""

    DEFAULT_CSS = """
    GraphView {
        width: 50%;
        border: round $secondary;
        background: $surface;
    }
    """
    ALLOW_SELECT = False  # dragging pans or moves nodes; it must not start a text selection
    LABEL_WIDTH = 18
    MIN_ZOOM = 0.1  # dots per world unit
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
        self.pan = (0.0, 0.0)  # world coordinates at the canvas's top-left dot
        self.dragged: set[Path] = set()
        self._laid_out_for = None
        self._fitted = False
        self._drag: list | None = None
        self._style_cache: dict[tuple, Style] = {}
        self._hidden_labels: set[Path] = set()

    # ---- coordinates -------------------------------------------------
    # World units map to Braille dots; a cell is 2 dots wide and 4 dots tall, and a dot is
    # roughly square on screen, so both axes share one zoom factor.
    def _to_dots(self, wx: float, wy: float) -> tuple[float, float]:
        return (wx - self.pan[0]) * self.zoom, (wy - self.pan[1]) * self.zoom

    def _to_world(self, dx: float, dy: float) -> tuple[float, float]:
        return dx / self.zoom + self.pan[0], dy / self.zoom + self.pan[1]

    @staticmethod
    def _cell_to_dots(x: int, y: int) -> tuple[float, float]:
        return x * 2 + 1.0, y * 4 + 2.0

    def _radius(self, path: Path) -> float:
        """Disc radius in dots, growing with how many notes link here."""
        note = self.index.notes[path]
        degree = len(note.outgoing) + len(note.incoming)
        return max(1.2, min(6.0, (1.5 + 0.35 * degree) * self.zoom ** 0.4))

    def _radius_cells(self, path: Path) -> int:
        return math.ceil(self._radius(path) / 2)

    def _label(self, path: Path) -> str:
        return self.index.notes[path].title[: self.LABEL_WIDTH]

    def _labelled(self) -> set[Path]:
        """Nodes whose title is drawn: every node, unless the last render had no room for it."""
        return set(self.world) - self._hidden_labels

    @property
    def node_positions(self) -> dict[Path, tuple[int, int]]:
        """Left cell of each node's hit box (disc plus visible title), content-area relative."""
        self._ensure_layout()
        result = {}
        for path, place in self.world.items():
            dx, dy = self._to_dots(*place)
            result[path] = (round(dx / 2) - self._radius_cells(path), round(dy / 4))
        return result

    def _node_width(self, path: Path) -> int:
        width = 2 * self._radius_cells(path) + 1
        if path in self._labelled():
            width += 1 + len(self._label(path))
        return width

    def _color(self, name: str, fallback: RGB) -> RGB:
        try:
            value = self.app.theme_variables.get(name)
        except Exception:
            value = None
        return _rgb(value, fallback) if value else fallback

    def select(self, path: Path | None) -> None:
        self.selected_path = path
        self.refresh()

    # ---- layout ------------------------------------------------------
    def _ensure_layout(self) -> None:
        if not self.index or not self.index.notes:
            self.world = {}
            return
        if self._laid_out_for is not self.index:
            self._laid_out_for = self.index
            self._compute_world()
            self._fitted = False
        if not self._fitted and self.size.width >= 10 and self.size.height >= 3:
            self.fit()

    def _compute_world(self) -> None:
        """Force-directed layout (Fruchterman-Reingold) inside a circular boundary.

        Linked notes pull together, every note pushes apart, and stragglers settle on an
        outer ring instead of piling up against straight walls.
        """
        paths = sorted(self.index.notes, key=lambda p: str(p).lower())
        n = len(paths)
        span = max(80.0, math.sqrt(n) * 40)
        self.world = {}
        if n == 1:
            self.world[paths[0]] = (span / 2, span / 2)
            return
        pos = {}
        for i, path in enumerate(paths):  # deterministic golden-angle spiral start
            angle = i * 2.399963
            radius = math.sqrt((i + 0.5) / n) * span / 2
            pos[path] = [span / 2 + math.cos(angle) * radius, span / 2 + math.sin(angle) * radius]
        edges = [(a, b) for a, note in self.index.notes.items() for b in note.outgoing]
        degree = {p: len(self.index.notes[p].outgoing) + len(self.index.notes[p].incoming) for p in paths}
        k = math.sqrt(span * span / n) * LAYOUT_SPACING
        temperature = span / 8
        started = time.monotonic()
        for _ in range(max(20, min(150, 30000 // n))):
            if time.monotonic() - started > LAYOUT_BUDGET_SECONDS:
                break
            force = {path: [0.0, 0.0] for path in paths}
            for i, a in enumerate(paths):
                for b in paths[i + 1:]:
                    dx = pos[a][0] - pos[b][0]
                    dy = pos[a][1] - pos[b][1]
                    dist = max(0.01, math.hypot(dx, dy))
                    push = k * k / dist
                    force[a][0] += dx / dist * push
                    force[a][1] += dy / dist * push
                    force[b][0] -= dx / dist * push
                    force[b][1] -= dy / dist * push
            for a, b in edges:
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                dist = max(0.01, math.hypot(dx, dy))
                # Hubs pull each neighbour less, so well-linked notes do not collapse onto them.
                pull = dist * dist / k / math.sqrt(1 + max(degree[a], degree[b]) / 2)
                force[a][0] -= dx / dist * pull
                force[a][1] -= dy / dist * pull
                force[b][0] += dx / dist * pull
                force[b][1] += dy / dist * pull
            for path in paths:
                force[path][0] += (span / 2 - pos[path][0]) * LAYOUT_GRAVITY
                force[path][1] += (span / 2 - pos[path][1]) * LAYOUT_GRAVITY
                fx, fy = force[path]
                length = max(0.01, math.hypot(fx, fy))
                step = min(length, temperature)
                nx = pos[path][0] + fx / length * step
                ny = pos[path][1] + fy / length * step
                off = math.hypot(nx - span / 2, ny - span / 2)
                if off > span / 2:  # circular boundary
                    nx = span / 2 + (nx - span / 2) * (span / 2) / off
                    ny = span / 2 + (ny - span / 2) * (span / 2) / off
                pos[path] = [nx, ny]
            temperature *= 0.95
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        scale = span / max(1.0, max(xs) - min(xs), max(ys) - min(ys))
        self.world = {path: ((pos[path][0] - min(xs)) * scale, (pos[path][1] - min(ys)) * scale) for path in paths}

    def fit(self) -> None:
        """Zoom and pan so every node (and its title, when shown) is visible."""
        if not self.world or self.size.width < 10 or self.size.height < 3:
            return
        xs = [x for x, _ in self.world.values()]
        ys = [y for _, y in self.world.values()]
        span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
        label_dots = (self.LABEL_WIDTH + 8) * 2
        width_dots, height_dots = self.size.width * 2, self.size.height * 4
        fit_x = (width_dots - label_dots) / span_x if span_x else self.MAX_ZOOM
        fit_y = (height_dots - 12) / span_y if span_y else self.MAX_ZOOM
        self.zoom = max(self.MIN_ZOOM, min(3.0, fit_x, fit_y))
        margin_x = (width_dots - span_x * self.zoom - label_dots) / 2 + 8
        margin_y = (height_dots - span_y * self.zoom) / 2
        self.pan = (min(xs) - margin_x / self.zoom, min(ys) - margin_y / self.zoom)
        self._fitted = True
        self.refresh()

    # ---- drawing -----------------------------------------------------
    def render(self) -> Text:
        width, height = self.size.width, self.size.height
        if not self.index or not self.index.notes:
            return Text("No notes")
        if width < 10 or height < 3:
            return Text("Graph too small")
        self._ensure_layout()

        surface = self._color("surface", (23.0, 23.0, 23.0))
        primary = self._color("primary", (220.0, 20.0, 60.0))
        accent = self._color("accent", (192.0, 57.0, 43.0))
        secondary = self._color("secondary", (139.0, 0.0, 0.0))
        foreground = self._color("foreground", (232.0, 232.0, 232.0))
        palette = {
            _LINK: _mix(surface, secondary, 0.4),
            _HOT_LINK: primary,
            _NODE: _mix(surface, secondary, 0.8),
            _LINKED_NODE: accent,
            _SELECTED_NODE: primary,
        }
        selected = self.index.notes.get(self.selected_path) if self.selected_path else None
        linked = set(selected.outgoing) | set(selected.incoming) if selected else set()

        bits = [[0] * width for _ in range(height)]
        rank = [[0] * width for _ in range(height)]
        centers = {path: self._to_dots(*place) for path, place in self.world.items()}

        def plot(dx: int, dy: int, level: int) -> None:
            cx, cy = dx >> 1, dy >> 2
            if 0 <= cx < width and 0 <= cy < height:
                bits[cy][cx] |= BRAILLE_BITS[dy & 3][dx & 1]
                if level > rank[cy][cx]:
                    rank[cy][cx] = level

        for path, note in self.index.notes.items():
            for target in note.outgoing:
                if target in centers:
                    hot = self.selected_path in (path, target)
                    self._draw_line(plot, centers[path], centers[target], _HOT_LINK if hot else _LINK)
        for path, center in centers.items():
            level = _SELECTED_NODE if path == self.selected_path else _LINKED_NODE if path in linked else _NODE
            self._draw_disc(plot, center, self._radius(path), level)

        cells: list[list[tuple[str, Style]]] = []
        blank = self._style(None, surface)
        for y in range(height):
            row = []
            for x in range(width):
                if bits[y][x]:
                    row.append((chr(0x2800 + bits[y][x]), self._style(palette[rank[y][x]], surface)))
                else:
                    row.append((" ", blank))
            cells.append(row)

        # Titles beside the discs: important notes first, then the best connected; crowded ones are skipped.
        taken: set[tuple[int, int]] = set()
        for path, (dx, dy) in centers.items():
            r = self._radius(path)
            for row in range(math.floor((dy - r) / 4), math.floor((dy + r) / 4) + 1):
                taken.update((col, row) for col in range(math.floor((dx - r) / 2), math.floor((dx + r) / 2) + 1))
        degree = {p: len(self.index.notes[p].outgoing) + len(self.index.notes[p].incoming) for p in centers}
        order = sorted(centers, key=lambda p: (p != self.selected_path, p not in linked, -degree[p], str(p)))
        self._hidden_labels = set()
        for path in order:
            dx, dy = centers[path]
            x = round(dx / 2) + self._radius_cells(path) + 1
            y = round(dy / 4)
            label = self._label(path)
            for row in (y, y + 1, y - 1):  # fall back to the rows beside the disc when crowded
                span = {(x + i, row) for i in range(-1, len(label) + 1)}
                if 0 <= row < height and not span & taken:
                    y = row
                    break
            else:
                self._hidden_labels.add(path)
                continue
            taken |= span
            if path == self.selected_path:
                style = self._style(primary, surface, bold=True)
            elif path in linked:
                style = self._style(foreground, surface, bold=True)
            else:
                style = self._style(_mix(surface, foreground, 0.6), surface)
            for i, ch in enumerate(label):
                if 0 <= x + i < width:
                    cells[y][x + i] = (ch, style)

        # One span per run of identical style keeps Rich's work (and the terminal output) small.
        text = Text(no_wrap=True, overflow="crop", end="")
        for y, row in enumerate(cells):
            run: list[str] = []
            run_style = row[0][1]
            for ch, style in row:
                if style is not run_style:
                    text.append("".join(run), run_style)
                    run, run_style = [], style
                run.append(ch)
            text.append("".join(run), run_style)
            if y < height - 1:
                text.append("\n")
        return text

    def _style(self, fg: RGB | None, bg: RGB, bold: bool = False) -> Style:
        key = (fg, bg, bold)
        style = self._style_cache.get(key)
        if style is None:
            style = Style(color=_hex(fg) if fg else None, bgcolor=_hex(bg), bold=bold or None)
            self._style_cache[key] = style
        return style

    @staticmethod
    def _draw_line(plot, start, end, level: int) -> None:
        """One-dot-wide line between two dot positions."""
        x0, y0 = start
        x1, y1 = end
        steps = max(1, math.ceil(max(abs(x1 - x0), abs(y1 - y0))))
        for i in range(steps + 1):
            t = i / steps
            plot(math.floor(x0 + (x1 - x0) * t), math.floor(y0 + (y1 - y0) * t), level)

    @staticmethod
    def _draw_disc(plot, center, radius: float, level: int) -> None:
        cx, cy = center
        for y in range(math.floor(cy - radius), math.ceil(cy + radius) + 1):
            for x in range(math.floor(cx - radius), math.ceil(cx + radius) + 1):
                if math.hypot(x + 0.5 - cx, y + 0.5 - cy) <= radius:
                    plot(x, y, level)

    # ---- mouse -------------------------------------------------------
    def _node_at(self, x: int, y: int) -> Path | None:
        for path, (nx, ny) in self.node_positions.items():
            if ny == y and nx <= x < nx + self._node_width(path):
                return path
        dx, dy = self._cell_to_dots(x, y)
        for path, place in self.world.items():  # the disc itself may span several rows
            cx, cy = self._to_dots(*place)
            if math.hypot(dx - cx, dy - cy) <= self._radius(path) + 2:
                return path
        return None

    def on_mouse_down(self, event) -> None:
        offset = event.get_content_offset(self)
        if offset is None:
            return
        path = self._node_at(offset.x, offset.y)
        if path is not None:
            nx, ny = self._to_dots(*self.world[path])
            dx, dy = self._cell_to_dots(offset.x, offset.y)
            self._drag = ["node", path, dx - nx, dy - ny, False]
        else:
            self._drag = ["pan", offset.x, offset.y, self.pan, False]
        self.capture_mouse()
        event.stop()

    def on_mouse_move(self, event) -> None:
        if self._drag is None:
            return  # no hover effects: a redraw per mouse move is far too costly on Windows pseudo-consoles
        offset = event.get_content_offset_capture(self)
        if self._drag[0] == "node":
            _, path, grab_x, grab_y, _ = self._drag
            dx, dy = self._cell_to_dots(offset.x, offset.y)
            place = self._to_world(dx - grab_x, dy - grab_y)
            if place != self.world[path]:
                self.world[path] = place
                self.dragged.add(path)
                self._drag[4] = True
                self.refresh()
        else:
            _, start_x, start_y, pan0, _ = self._drag
            pan = (pan0[0] - (offset.x - start_x) * 2 / self.zoom, pan0[1] - (offset.y - start_y) * 4 / self.zoom)
            if pan != self.pan:
                self.pan = pan
                self._drag[4] = True
                self.refresh()

    def on_mouse_up(self, event) -> None:
        if self._drag is None:
            return
        kind, target, moved = self._drag[0], self._drag[1], self._drag[4]
        self._drag = None
        self.release_mouse()
        if kind == "node" and not moved:
            self.post_message(self.NodeSelected(target))

    def _zoom_by(self, factor: float, event) -> None:
        offset = event.get_content_offset(self)
        if offset is not None:
            cx, cy = self._cell_to_dots(offset.x, offset.y)
        else:
            cx, cy = self.size.width * 1.0, self.size.height * 2.0
        wx, wy = self._to_world(cx, cy)
        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.zoom * factor))
        self.pan = (wx - cx / self.zoom, wy - cy / self.zoom)
        self.refresh()
        event.stop()

    def on_mouse_scroll_up(self, event) -> None:
        self._zoom_by(1.25, event)

    def on_mouse_scroll_down(self, event) -> None:
        self._zoom_by(0.8, event)
