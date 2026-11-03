"""Recognition and reconstruction of the frozen Quickshare v2 block pattern."""

import math
import struct
from collections.abc import Iterator
from collections.abc import Sequence
from dataclasses import dataclass

from gridiron_playbook.block import BLOCK_TOLERANCE_CM
from gridiron_playbook.block import V2_BLOCK_OFFSETS
from gridiron_playbook.block import ends_with_block
from gridiron_playbook.point import GridironPoint


Direction = tuple[float, float]
BLOCK_POINTS = len(V2_BLOCK_OFFSETS)
_HEADING_COUNT = 65_536
_ANGLE_STEP = math.tau / _HEADING_COUNT
_XYZ = struct.Struct("<ddd")
_UNIT_TOLERANCE = 1e-12
_SWEEP_WIDTH = V2_BLOCK_OFFSETS[1][0] - V2_BLOCK_OFFSETS[0][0]
_SWEEP_STEP = V2_BLOCK_OFFSETS[2][1] - V2_BLOCK_OFFSETS[1][1]
_SWEEP_TOLERANCE = 4 * BLOCK_TOLERANCE_CM


@dataclass(frozen=True)
class RouteBlock:
    """An insertion immediately after a literal route node."""

    anchor: int
    direction: Direction


def compact_heading(direction: Direction) -> int:
    """Quantize a forward direction to the v2 unsigned 16-bit turn."""
    return round(math.atan2(direction[1], direction[0]) / _ANGLE_STEP) % _HEADING_COUNT


def heading_direction(heading: int) -> Direction:
    """Reconstruct the v2 direction used to draw a compact block."""
    angle: float = heading * _ANGLE_STEP
    return math.cos(angle), math.sin(angle)


def check_direction(direction: Direction) -> None:
    """Require a finite unit vector for a v2 block."""
    if not abs(math.hypot(*direction) - 1.0) <= _UNIT_TOLERANCE:
        raise ValueError("Invalid Quickshare block direction.")


def inferred_direction(points: Sequence[GridironPoint], anchor: int) -> Direction | None:
    """Use the preceding literal with the same binary64 operations in both decoders."""
    if anchor == 0:
        return None
    before, at = points[anchor - 1], points[anchor]
    dx, dy = at.x - before.x, at.y - before.y
    length: float = math.sqrt(dx * dx + dy * dy)
    if not length or not math.isfinite(length):
        return None
    direction: Direction = (dx / length, dy / length)
    return direction if abs(math.hypot(*direction) - 1.0) <= _UNIT_TOLERANCE else None


def _coordinates(anchor: GridironPoint, direction: Direction) -> Iterator[tuple[float, float, float]]:
    ux, uy = direction
    for side, depth in V2_BLOCK_OFFSETS[:-1]:
        yield anchor.x + (depth * ux - side * uy), anchor.y + (depth * uy + side * ux), anchor.z
    yield anchor.x, anchor.y, anchor.z


def expand_blocks(points: list[GridironPoint], blocks: list[RouteBlock]) -> list[GridironPoint]:
    """Insert the v2 strokes in route order, including blocks that share an anchor."""
    expanded: list[GridironPoint] = []
    block_index: int = 0
    for index, point in enumerate(points):
        expanded.append(point)
        while block_index < len(blocks) and blocks[block_index].anchor == index:
            expanded.extend(
                GridironPoint(X_0=x, Y_0=y, Z_0=z) for x, y, z in _coordinates(point, blocks[block_index].direction)
            )
            block_index += 1
    return expanded


def _candidate_directions(
    points: tuple[GridironPoint, ...], index: int, previous: tuple[float, float] | None
) -> Iterator[Direction]:
    center: GridironPoint = points[index]
    dx, dy = 1.0, 0.0
    if previous is not None and previous != (center.x, center.y):
        dx, dy = center.x - previous[0], center.y - previous[1]
    else:
        for j in range(index + BLOCK_POINTS + 1, len(points)):
            following: GridironPoint = points[j]
            if (following.x, following.y) != (center.x, center.y):
                dx, dy = following.x - center.x, following.y - center.y
                break
    length: float = math.hypot(dx, dy)
    if length and math.isfinite(length):
        yield dx / length, dy / length
    # The preceding leg may have been moved after stamping the block.
    side, _ = V2_BLOCK_OFFSETS[-2]
    edge: GridironPoint = points[index + BLOCK_POINTS - 1]
    measured: Direction = ((edge.y - center.y) / side, (center.x - edge.x) / side)
    yield measured
    yield heading_direction(compact_heading(measured))


def _matching_direction(
    points: tuple[GridironPoint, ...], index: int, previous: tuple[float, float] | None
) -> Direction | None:
    end: int = index + BLOCK_POINTS
    if end >= len(points) or points[end] != points[index]:
        return None
    span: tuple[GridironPoint, ...] = points[index : end + 1]
    if not ends_with_block(span):
        return None
    stored: bytes = b"".join(_XYZ.pack(p.x, p.y, p.z) for p in span[1:])
    for direction in _candidate_directions(points, index, previous):
        if abs(math.hypot(*direction) - 1.0) <= _UNIT_TOLERANCE:
            generated: bytes = b"".join(_XYZ.pack(*xyz) for xyz in _coordinates(points[index], direction))
            if generated == stored:
                return direction
    return None


def split_blocks(
    points: tuple[GridironPoint, ...], formation_start: tuple[float, float] | None
) -> tuple[list[GridironPoint], list[RouteBlock]]:
    """Replace only complete, bitwise reproducible spans with block instructions."""
    literals: list[GridironPoint] = []
    blocks: list[RouteBlock] = []
    previous: tuple[float, float] | None = formation_start
    index: int = 0
    while index < len(points):
        current: GridironPoint = points[index]
        if index:
            prior: GridironPoint = points[index - 1]
            if (prior.x, prior.y) != (current.x, current.y):
                previous = (prior.x, prior.y)
        literals.append(current)
        while (direction := _matching_direction(points, index, previous)) is not None:
            blocks.append(RouteBlock(len(literals) - 1, direction))
            index += BLOCK_POINTS
            edge: GridironPoint = points[index - 1]
            previous = (edge.x, edge.y)
        index += 1
    return literals, blocks


def has_block_strokes(points: Sequence[GridironPoint]) -> bool:
    """Recognize a pair of adjacent sweeps even when other nodes of the block were edited."""
    for end in range(3, len(points)):
        a, b, c, d = points[end - 3], points[end - 2], points[end - 1], points[end]
        ux, uy = b.x - a.x, b.y - a.y
        if abs(math.hypot(ux, uy) - _SWEEP_WIDTH) > _SWEEP_TOLERANCE:
            continue
        gap_x, gap_y = c.x - b.x, c.y - b.y
        if abs(math.hypot(gap_x, gap_y) - _SWEEP_STEP) > _SWEEP_TOLERANCE:
            continue
        along_sweep: float = (gap_x * ux + gap_y * uy) / _SWEEP_WIDTH
        reverse_error: float = math.hypot((d.x - c.x) + ux, (d.y - c.y) + uy)
        if abs(along_sweep) <= _SWEEP_TOLERANCE and reverse_error <= _SWEEP_TOLERANCE:
            return True
    return False
