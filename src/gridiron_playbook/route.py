"""Module containing route schemas for the gridiron_playbook package."""

from pydantic import Field

from gridiron_playbook.point import GridironPoint
from gridiron_playbook.schema import GridironModel


class GridironRoute(GridironModel):
    """A player's slot and ordered route points."""

    slot: int = Field(alias="Slot_0")
    points: tuple[GridironPoint, ...] = Field(alias="Points_0")
