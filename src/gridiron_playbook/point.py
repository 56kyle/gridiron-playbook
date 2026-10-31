"""Module containing route point schemas for the gridiron_playbook package."""

from pydantic import Field

from gridiron_playbook.schema import GridironModel


class GridironPoint(GridironModel):
    """A point in a drawn route."""

    x: float = Field(alias="X_0")
    y: float = Field(alias="Y_0")
    z: float = Field(alias="Z_0")
