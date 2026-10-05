"""A dot canvas drawn with Braille glyphs.

Each terminal cell is a 2x4 grid of dots, four times the resolution of block glyphs.
Every dot carries an integer priority; a cell shows the highest priority drawn into it.
"""

from __future__ import annotations

import math

DOTS_PER_CELL_X = 2
DOTS_PER_CELL_Y = 4
BRAILLE_BLANK = 0x2800
BRAILLE_BITS_BY_DOT_ROW_AND_COLUMN = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))

DotPosition = tuple[float, float]


class BrailleCanvas:
    def __init__(self, width_cells: int, height_cells: int) -> None:
        self.width_cells = width_cells
        self.height_cells = height_cells
        self._dot_bits = [[0] * width_cells for _ in range(height_cells)]
        self._priorities = [[0] * width_cells for _ in range(height_cells)]

    def plot(self, dot_x: int, dot_y: int, priority: int) -> None:
        column, row = dot_x // DOTS_PER_CELL_X, dot_y // DOTS_PER_CELL_Y
        if not (0 <= column < self.width_cells and 0 <= row < self.height_cells):
            return
        dot_column, dot_row = dot_x % DOTS_PER_CELL_X, dot_y % DOTS_PER_CELL_Y
        self._dot_bits[row][column] |= BRAILLE_BITS_BY_DOT_ROW_AND_COLUMN[dot_row][dot_column]
        self._priorities[row][column] = max(self._priorities[row][column], priority)

    def draw_line(self, start: DotPosition, end: DotPosition, priority: int) -> None:
        start_x, start_y = start
        end_x, end_y = end
        step_count = max(1, math.ceil(max(abs(end_x - start_x), abs(end_y - start_y))))
        for step in range(step_count + 1):
            progress = step / step_count
            self.plot(
                math.floor(start_x + (end_x - start_x) * progress),
                math.floor(start_y + (end_y - start_y) * progress),
                priority,
            )

    def draw_disc(self, center: DotPosition, radius: float, priority: int) -> None:
        center_x, center_y = center
        for dot_y in range(math.floor(center_y - radius), math.ceil(center_y + radius) + 1):
            for dot_x in range(math.floor(center_x - radius), math.ceil(center_x + radius) + 1):
                if math.hypot(dot_x + 0.5 - center_x, dot_y + 0.5 - center_y) <= radius:
                    self.plot(dot_x, dot_y, priority)

    def glyph_at(self, column: int, row: int) -> str | None:
        """The Braille glyph for a cell, or None when nothing was drawn there."""
        bits = self._dot_bits[row][column]
        return chr(BRAILLE_BLANK + bits) if bits else None

    def priority_at(self, column: int, row: int) -> int:
        return self._priorities[row][column]
