"""Module containing play schemas for the gridiron_playbook package."""

from pydantic import Field

from gridiron_playbook.route import GridironRoute
from gridiron_playbook.schema import GridironModel


class GridironPlay(GridironModel):
    """A completed play with its formation, name, and routes."""

    formation_name: str = Field(alias="FormationName_0")
    play_name: str = Field(alias="PlayName_0")
    routes: tuple[GridironRoute, ...] = Field(alias="Routes_0")


class GridironLastDrawnPlay(GridironModel):
    """A saved drawing whose name and routes can be absent."""

    formation_name: str = Field(alias="FormationName_0")
    play_name: str = Field(default="", alias="PlayName_0")
    routes: tuple[GridironRoute, ...] = Field(default=(), alias="Routes_0")
