from itertools import pairwise

import pytest

from gridiron_playbook.block import block_waypoints
from gridiron_playbook.block import ends_with_block
from gridiron_playbook.block import route_yards_without_blocks
from gridiron_playbook.point import GridironPoint
from gridiron_playbook.route import GridironRoute


def test_block_waypoints_with_duplicate_approach() -> None:
    start = GridironPoint(X_0=-400, Y_0=25, Z_0=0)
    at = GridironPoint(X_0=100, Y_0=25, Z_0=8)
    stamp: tuple[GridironPoint, ...] = block_waypoints((start, at, at), 2, None)

    assert all(p.z == at.z for p in stamp)
    assert stamp[-1] == at
    assert stamp[-2].x == pytest.approx(at.x)
    assert abs(stamp[-2].y - at.y) == pytest.approx(1.5 * 91.44)
    sweeps: list[float] = sorted(
        a.x for a, b in pairwise(stamp) if a.x == b.x and abs(a.y - b.y) == pytest.approx(3 * 91.44)
    )
    assert sweeps[-1] - sweeps[0] == pytest.approx(1.25 * 91.44)
    assert all(high - low <= 10 for low, high in pairwise(sweeps))


@pytest.mark.parametrize(
    ("start", "next_y", "expected_side"),
    [((-40, 0), 100, (0, 1)), (None, 75, (1, 0)), (None, 0, (0, 1))],
    ids=["from-formation", "from-next-leg", "entirely-coincident"],
)
def test_block_waypoints_at_first_saved_node(
    start: tuple[float, float] | None, next_y: float, expected_side: tuple[float, float]
) -> None:
    at = GridironPoint(X_0=0, Y_0=0, Z_0=8)
    following = GridironPoint(X_0=0, Y_0=next_y, Z_0=8)
    stamp: tuple[GridironPoint, ...] = block_waypoints((at, following), 0, start)

    side = (abs(stamp[-2].x) / (1.5 * 91.44), abs(stamp[-2].y) / (1.5 * 91.44))
    assert side == pytest.approx(expected_side)


def test_ends_with_block_after_waypoint_edits() -> None:
    at = GridironPoint(X_0=75, Y_0=-138, Z_0=1)
    before = GridironPoint(X_0=31, Y_0=88, Z_0=7)
    stamp: tuple[GridironPoint, ...] = block_waypoints((before, at), 1, None)

    assert ends_with_block((at, *stamp))
    assert not ends_with_block((at, *stamp, before))
    assert not ends_with_block((at, stamp[0], before, *stamp[2:]))


@pytest.mark.parametrize("nested", [False, True], ids=["adjacent", "nested"])
@pytest.mark.parametrize(("start", "expected"), [((0, 0), 15.0), (None, 5.0)], ids=["formation-start", "unknown-start"])
def test_route_yards_without_blocks_with_multiple_blocks(
    nested: bool, start: tuple[float, float] | None, expected: float
) -> None:
    anchor = GridironPoint(X_0=914.4, Y_0=0, Z_0=5)
    end = GridironPoint(X_0=914.4, Y_0=457.2, Z_0=0)
    first_block = block_waypoints((anchor, end), 0, start)
    points = (anchor, *first_block, end)
    second_anchor: int = 1 if nested else len(first_block)
    second_block = block_waypoints(points, second_anchor, start)
    after: int = second_anchor + 1
    route = GridironRoute(Slot_0=0, Points_0=(*points[:after], *second_block, *points[after:]))

    assert route_yards_without_blocks(route, start) == pytest.approx(expected)


def test_route_yards_without_blocks_with_edited_block() -> None:
    anchor = GridironPoint(X_0=145, Y_0=-360, Z_0=0)
    stamp = block_waypoints((anchor,), 0, None)
    moved = stamp[1].model_copy(update={"x": stamp[1].x + 15.0})
    route = GridironRoute(Slot_0=0, Points_0=(anchor, stamp[0], moved, *stamp[2:]))

    assert route_yards_without_blocks(route, None) == pytest.approx(route.length_yards(None))
