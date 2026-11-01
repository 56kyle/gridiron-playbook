"""Module containing playbook save schemas for the gridiron_playbook package."""
from pathlib import Path

from pydantic import Field

from gridiron_playbook.game import get_gridiron_playbook_path
from gridiron_playbook.play import GridironLastDrawnPlay
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.point import GridironPoint
from gridiron_playbook.property_schema import GridironArrayPropertySchema
from gridiron_playbook.property_schema import GridironBytePropertySchema
from gridiron_playbook.property_schema import GridironOtherPropertySchema
from gridiron_playbook.property_schema import GridironPropertyData
from gridiron_playbook.property_schema import GridironPropertySchema
from gridiron_playbook.property_schema import GridironSchemaRegistry
from gridiron_playbook.property_schema import GridironStructDescriptor
from gridiron_playbook.property_schema import GridironStructPropertySchema
from gridiron_playbook.property_schema import GridironStructType
from gridiron_playbook.route import GridironRoute
from gridiron_playbook.save_header import GridironCustomVersion
from gridiron_playbook.save_header import GridironPackageVersion
from gridiron_playbook.save_header import GridironSaveHeader
from gridiron_playbook.schema import GridironModel


__all__: list[str] = [
    "GridironArrayPropertySchema",
    "GridironBytePropertySchema",
    "GridironCustomVersion",
    "GridironLastDrawnPlay",
    "GridironOtherPropertySchema",
    "GridironPackageVersion",
    "GridironPlay",
    "GridironPlaybook",
    "GridironPlaybookProperties",
    "GridironPoint",
    "GridironPropertyData",
    "GridironPropertySchema",
    "GridironRoute",
    "GridironSaveHeader",
    "GridironSaveRoot",
    "GridironSchemaRegistry",
    "GridironStructDescriptor",
    "GridironStructPropertySchema",
    "GridironStructType",
]


class GridironPlaybookProperties(GridironModel):
    """The plays and drawing state stored in the save root."""

    custom_plays: tuple[GridironPlay, ...] = Field(alias="CustomPlays_0")
    last_formation: str = Field(alias="LastFormation_0")
    last_was_drawn: bool = Field(alias="bLastWasDrawn_0")
    last_drawn_play: GridironLastDrawnPlay = Field(alias="LastDrawnPlay_0")


class GridironSaveRoot(GridironModel):
    """The Unreal save class and its stored properties."""

    save_game_type: str
    properties: GridironPlaybookProperties


class GridironPlaybook(GridironModel):
    """A complete GridIron custom plays JSON document."""

    header: GridironSaveHeader
    schemas: GridironSchemaRegistry
    root: GridironSaveRoot
    extra: tuple[int, ...]


def export_playbook(path: Path) -> None:
    """Export the playbook to the given path."""


