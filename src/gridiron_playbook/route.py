"""Module containing route schemas for the gridiron_playbook package."""

from collections.abc import Iterable
from math import dist

from pydantic import Field

from gridiron_playbook.point import GridironPoint
from gridiron_playbook.schema import GridironModel


CENTIMETERS_PER_YARD: float = 91.44


def path_length_yards(points: Iterable[GridironPoint], start: tuple[float, float] | None) -> float:
    """Measure an ordered path in the field plane from its known start or first waypoint."""
    previous: tuple[float, float] | None = start
    yards: float = 0.0
    for point in points:
        current: tuple[float, float] = (point.x, point.y)
        if previous is not None:
            yards += dist(previous, current) / CENTIMETERS_PER_YARD
        previous = current
    return yards


class GridironRoute(GridironModel):
    """A player's slot and ordered route points."""

    slot: int = Field(alias="Slot_0")
    points: tuple[GridironPoint, ...] = Field(alias="Points_0")

    def length_yards(self, start: tuple[float, float] | None) -> float:
        """Measure the ground path through every saved waypoint, including block strokes."""
        return path_length_yards(self.points, start)
