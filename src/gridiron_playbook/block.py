"""A blocking bar traced by ordinary saved waypoints, with the route continuing from its center."""

from collections.abc import Iterator
from collections.abc import Sequence
from math import hypot
from math import isfinite

from gridiron_playbook.point import GridironPoint
from gridiron_playbook.route import GridironRoute
from gridiron_playbook.route import path_length_yards


BLOCK_TOLERANCE_CM = 0.1


def _v2_sweep_offsets() -> Iterator[tuple[float, float]]:
    """Frozen Quickshare v2 template, in game centimeters."""
    side: float = -137.16
    for row in range(13):
        depth: float = 114.3 * (row / 12 - 0.5)
        yield side, depth
        side = -side
        yield side, depth
    yield side, 0.0
    yield 0.0, 0.0


V2_BLOCK_OFFSETS: tuple[tuple[float, float], ...] = tuple(_v2_sweep_offsets())
BLOCK_OFFSETS: tuple[tuple[float, float], ...] = V2_BLOCK_OFFSETS
_HALF_WIDTH: float = abs(BLOCK_OFFSETS[0][0])


def _approach(
    points: tuple[GridironPoint, ...], index: int, formation_start: tuple[float, float] | None
) -> tuple[float, float]:
    center: GridironPoint = points[index]
    for previous in reversed(points[:index]):
        if (previous.x, previous.y) != (center.x, center.y):
            return center.x - previous.x, center.y - previous.y
    if formation_start is not None and formation_start != (center.x, center.y):
        return center.x - formation_start[0], center.y - formation_start[1]
    for following in points[index + 1 :]:
        if (following.x, following.y) != (center.x, center.y):
            return following.x - center.x, following.y - center.y
    return 1.0, 0.0


def block_waypoints(
    points: tuple[GridironPoint, ...], index: int, formation_start: tuple[float, float] | None
) -> tuple[GridironPoint, ...]:
    """Generate the points to insert immediately after the designated route node."""
    if not 0 <= index < len(points):
        raise IndexError("Choose an existing route point for the block.")
    center: GridironPoint = points[index]
    dx, dy = _approach(points, index, formation_start)
    length: float = hypot(dx, dy)
    if not isfinite(length):
        raise ValueError("The route direction exceeds the numeric range for a block.")
    forward_x, forward_y = dx / length, dy / length
    stroke: tuple[GridironPoint, ...] = tuple(
        GridironPoint(
            X_0=center.x + (depth * forward_x - side * forward_y),
            Y_0=center.y + (depth * forward_y + side * forward_x),
            Z_0=center.z,
        )
        for side, depth in BLOCK_OFFSETS[:-1]
    )
    stamp: tuple[GridironPoint, ...] = (*stroke, center)
    if not ends_with_block((center, *stamp)):
        raise ValueError("The route coordinates do not have enough precision to draw a block.")
    return stamp


def ends_with_block(points: Sequence[GridironPoint]) -> bool:
    """Recognize a terminal blocking bar from the saved geometry in any field orientation."""
    if len(points) < len(BLOCK_OFFSETS) + 1:
        return False
    center: GridironPoint = points[-1]
    if points[-len(BLOCK_OFFSETS) - 1] != center or not isfinite(center.z):
        return False
    side_x: float = (points[-2].x - center.x) / _HALF_WIDTH
    side_y: float = (points[-2].y - center.y) / _HALF_WIDTH
    if abs(hypot(side_x, side_y) - 1.0) * _HALF_WIDTH > BLOCK_TOLERANCE_CM:
        return False
    return all(
        point.z == center.z
        and hypot(
            (point.x - center.x) - (side * side_x + depth * side_y),
            (point.y - center.y) - (side * side_y - depth * side_x),
        )
        <= BLOCK_TOLERANCE_CM
        for point, (side, depth) in zip(points[-len(BLOCK_OFFSETS) :], BLOCK_OFFSETS, strict=True)
    )


def route_yards_without_blocks(route: GridironRoute, start: tuple[float, float] | None) -> float:
    """Measure the route through each block's anchor, omitting the strokes that draw its bar."""
    path: list[GridironPoint] = []
    for point in route.points:
        path.append(point)
        if ends_with_block(path):
            del path[-len(BLOCK_OFFSETS) :]
    return path_length_yards(path, start)
