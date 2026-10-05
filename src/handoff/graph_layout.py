"""Force-directed (Fruchterman-Reingold) layout of a note graph inside a circular boundary.

Linked notes pull together. Notes with no links are kept out of the main cluster and
placed on a quiet outer ring so they read as standalone notes.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

from handoff.knowledge import KnowledgeIndex

WorldPosition = tuple[float, float]

SPACING_MULTIPLIER = 1.8
GRAVITY = 0.15
TIME_BUDGET_SECONDS = 0.4
GOLDEN_ANGLE_RADIANS = 2.399963
MINIMUM_SPAN = 80.0
SPAN_PER_SQRT_NOTE = 40
OUTER_RING_RADIUS_RATIO = 0.72
FINAL_SCALE_RATIO = 0.58
COOLING_RATE = 0.95
MINIMUM_DISTANCE = 0.01
MINIMUM_ITERATIONS = 20
MAXIMUM_ITERATIONS = 150
ITERATION_WORK_BUDGET = 30000


def compute_node_positions(index: KnowledgeIndex) -> dict[Path, WorldPosition]:
    paths = sorted(index.notes, key=lambda path: str(path).lower())
    link_counts = {path: index.notes[path].link_count for path in paths}
    unlinked_paths = [path for path in paths if link_counts[path] == 0]
    layout_paths = [path for path in paths if link_counts[path] > 0] or paths
    span = max(MINIMUM_SPAN, math.sqrt(len(layout_paths)) * SPAN_PER_SQRT_NOTE)

    laid_out = set(layout_paths)
    if len(layout_paths) == 1:
        positions = {layout_paths[0]: (span / 2, span / 2)}
    else:
        links = [
            (source, target)
            for source, note in index.notes.items()
            for target in note.outgoing
            if source in laid_out and target in laid_out
        ]
        positions = _settle(layout_paths, links, link_counts, span)

    positions.update(_outer_ring(unlinked_paths, span))
    return positions


def _spiral_start(paths: list[Path], span: float) -> dict[Path, list[float]]:
    """Deterministic golden-angle spiral, so the same vault always lays out the same way."""
    centre = span / 2
    positions = {}
    for number, path in enumerate(paths):
        angle = number * GOLDEN_ANGLE_RADIANS
        radius = math.sqrt((number + 0.5) / len(paths)) * centre
        positions[path] = [centre + math.cos(angle) * radius, centre + math.sin(angle) * radius]
    return positions


def _offset(positions: dict[Path, list[float]], first: Path, second: Path) -> tuple[float, float, float]:
    offset_x = positions[first][0] - positions[second][0]
    offset_y = positions[first][1] - positions[second][1]
    return offset_x, offset_y, max(MINIMUM_DISTANCE, math.hypot(offset_x, offset_y))


def _push_pair(
    forces: dict[Path, list[float]], first: Path, second: Path, offset: tuple[float, float, float], strength: float
) -> None:
    """Push ``first`` away from ``second`` by ``strength`` (negative strength pulls them together)."""
    offset_x, offset_y, distance = offset
    forces[first][0] += offset_x / distance * strength
    forces[first][1] += offset_y / distance * strength
    forces[second][0] -= offset_x / distance * strength
    forces[second][1] -= offset_y / distance * strength


def _compute_forces(
    paths: list[Path],
    links: list[tuple[Path, Path]],
    link_counts: dict[Path, int],
    positions: dict[Path, list[float]],
    ideal_distance: float,
) -> dict[Path, list[float]]:
    forces = {path: [0.0, 0.0] for path in paths}
    for number, first in enumerate(paths):
        for second in paths[number + 1 :]:
            offset = _offset(positions, first, second)
            _push_pair(forces, first, second, offset, ideal_distance * ideal_distance / offset[2])
    for source, target in links:
        offset = _offset(positions, source, target)
        hub_damping = math.sqrt(1 + max(link_counts[source], link_counts[target]) / 2)
        _push_pair(forces, source, target, offset, -(offset[2] * offset[2] / ideal_distance / hub_damping))
    return forces


def _settle(
    paths: list[Path], links: list[tuple[Path, Path]], link_counts: dict[Path, int], span: float
) -> dict[Path, WorldPosition]:
    centre = span / 2
    positions = _spiral_start(paths, span)
    ideal_distance = math.sqrt(span * span / len(paths)) * SPACING_MULTIPLIER
    temperature = span / 8
    started_at = time.monotonic()
    iterations = max(MINIMUM_ITERATIONS, min(MAXIMUM_ITERATIONS, ITERATION_WORK_BUDGET // len(paths)))

    for _ in range(iterations):
        if time.monotonic() - started_at > TIME_BUDGET_SECONDS:
            break
        forces = _compute_forces(paths, links, link_counts, positions, ideal_distance)
        for path in paths:
            positions[path] = _step_towards_force(positions[path], forces[path], centre, temperature)
        temperature *= COOLING_RATE

    return _recentre_and_scale(positions, span)


def _step_towards_force(position: list[float], force: list[float], centre: float, step_limit: float) -> list[float]:
    force_x = force[0] + (centre - position[0]) * GRAVITY
    force_y = force[1] + (centre - position[1]) * GRAVITY
    force_length = max(MINIMUM_DISTANCE, math.hypot(force_x, force_y))
    step = min(force_length, step_limit)
    next_x = position[0] + force_x / force_length * step
    next_y = position[1] + force_y / force_length * step
    distance_from_centre = math.hypot(next_x - centre, next_y - centre)
    if distance_from_centre > centre:
        next_x = centre + (next_x - centre) * centre / distance_from_centre
        next_y = centre + (next_y - centre) * centre / distance_from_centre
    return [next_x, next_y]


def _recentre_and_scale(positions: dict[Path, list[float]], span: float) -> dict[Path, WorldPosition]:
    all_x = [position[0] for position in positions.values()]
    all_y = [position[1] for position in positions.values()]
    scale = (span * FINAL_SCALE_RATIO) / max(1.0, max(all_x) - min(all_x), max(all_y) - min(all_y))
    mean_x, mean_y = sum(all_x) / len(all_x), sum(all_y) / len(all_y)
    centre = span / 2
    return {
        path: (centre + (position[0] - mean_x) * scale, centre + (position[1] - mean_y) * scale)
        for path, position in positions.items()
    }


def _outer_ring(paths: list[Path], span: float) -> dict[Path, WorldPosition]:
    centre = span / 2
    radius = span * OUTER_RING_RADIUS_RATIO
    return {
        path: (
            centre + math.cos(-math.pi / 2 + number * 2 * math.pi / len(paths)) * radius,
            centre + math.sin(-math.pi / 2 + number * 2 * math.pi / len(paths)) * radius,
        )
        for number, path in enumerate(paths)
    }
