"""Module containing playbook documents and codecs for the gridiron_playbook package."""

from pydantic import Field

from gridiron_playbook._native import json_to_sav
from gridiron_playbook.play import GridironLastDrawnPlay
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.property_schema import GridironSchemaRegistry
from gridiron_playbook.save import sav_to_json
from gridiron_playbook.save_header import GridironSaveHeader
from gridiron_playbook.schema import GridironModel


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


def sav_to_playbook(save_bytes: bytes) -> GridironPlaybook:
    """Return the playbook encoded by the provided save bytes."""
    playbook_json: str = sav_to_json(save_bytes=save_bytes)
    return json_to_playbook(json_text=playbook_json)


def json_to_playbook(json_text: str) -> GridironPlaybook:
    """Return the playbook encoded by the provided JSON text."""
    return GridironPlaybook.model_validate_json(json_text)


def playbook_to_sav(playbook: GridironPlaybook) -> bytes:
    """Return the bytes for the provided playbook as a .sav file."""
    playbook_json: str = playbook_to_json(playbook=playbook)
    return json_to_sav(json_text=playbook_json)


def playbook_to_json(playbook: GridironPlaybook) -> str:
    """Return the provided playbook as JSON text."""
    return playbook.model_dump_json(indent=4, by_alias=True, exclude_unset=True)
