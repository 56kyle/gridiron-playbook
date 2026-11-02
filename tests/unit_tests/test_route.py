import pytest

from gridiron_playbook.point import GridironPoint
from gridiron_playbook.route import GridironRoute


@pytest.mark.parametrize(
    ("start", "expected"),
    [((30, -40), 13.25), (None, 8.25)],
    ids=["formation-start", "unknown-start"],
)
def test_length_yards(start: tuple[float, float] | None, expected: float) -> None:
    route = GridironRoute(
        Slot_0=5,
        Points_0=(
            GridironPoint(X_0=30 + 3 * 91.44, Y_0=-40 + 4 * 91.44, Z_0=950),
            GridironPoint(X_0=30 + 3 * 91.44, Y_0=-40 - 4.25 * 91.44, Z_0=0),
        ),
    )

    assert route.length_yards(start) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("start", "points"),
    [((35, -53), ()), (None, ()), (None, (GridironPoint(X_0=80, Y_0=-60, Z_0=20),))],
)
def test_length_yards_with_no_segments(start: tuple[float, float] | None, points: tuple[GridironPoint, ...]) -> None:
    route = GridironRoute(Slot_0=5, Points_0=points)

    assert route.length_yards(start) == 0
