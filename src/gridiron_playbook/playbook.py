"""Module containing playbook save schemas for the gridiron_playbook package."""
import json
from pathlib import Path
from uuid import uuid4

from pydantic import Field
from pydantic import FilePath
from pydantic import validate_call

from gridiron_playbook._native import json_to_sav
from gridiron_playbook.constants import DEFAULT_PYDANTIC_CONFIG
from gridiron_playbook.constants import USER_CACHE_FOLDER
from gridiron_playbook.game import get_gridiron_playbook_path
from gridiron_playbook.log import FILE_SAFE_DATETIME_SLUG
from gridiron_playbook.log import logger
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
from gridiron_playbook.save import sav_to_json
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


GRIDIRON_PLAYBOOK_CACHE: Path = USER_CACHE_FOLDER / "playbooks"


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


def export_playbook(export_path: Path) -> None:
    """Export the current playbook to the given path as a json."""
    if export_path.is_dir():
        export_path: Path = export_path / "GridironCustomPlays.json"
    export_path: Path = export_path.with_suffix(".json")

    playbook_save_path: Path = get_gridiron_playbook_path()
    playbook: GridironPlaybook = read_sav_to_playbook(path=playbook_save_path)

    write_playbook_to_json(playbook=playbook, path=export_path)


@validate_call(config=DEFAULT_PYDANTIC_CONFIG)
def import_playbook(import_path: FilePath) -> None:
    """Import the playbook from the given path to be the current one, while backing up the original."""
    playbook_save_path: Path = get_gridiron_playbook_path()
    if import_path.suffix == ".json":
        playbook: GridironPlaybook = read_json_to_playbook(path=import_path)
    elif import_path.suffix == ".sav":
        playbook: GridironPlaybook = read_sav_to_playbook(path=import_path)
    else:
        raise ValueError(f"Invalid path suffix provided: {path.suffix}, please provide a .json or a .sav file.")

    save_backup_playbook()

    playbook_sav: bytes = playbook_to_sav(playbook=playbook)
    playbook_save_path.write_bytes(playbook_sav)


def save_backup_playbook() -> Path:
    """Saves the current playbook to a backup location in user cache."""
    backup_name: str = f"{FILE_SAFE_DATETIME_SLUG}.sav"
    backup_path: Path = USER_CACHE_FOLDER / backup_name

    original_playbook_path: Path = get_gridiron_playbook_path()
    original_bytes: bytes = original_playbook_path.read_bytes()

    logger.info(f"Saving backup from {original_playbook_path} to {backup_path}")
    backup_path.write_bytes(original_bytes)
    return backup_path


def load_backup_playbook() -> None:
    """Loads the latest playbook backup in user cache."""
    newest_backup_path: Path | None = None
    highest_value: int = 0
    for path in USER_CACHE_FOLDER.rglob("*.sav"):
        value: int = int(path.stem.replace("_", "").replace("-", ""))
        if value > highest_value:
            highest_value = value
            newest_backup_path: Path = path

    if newest_backup_path is None:
        raise FileNotFoundError(f"Failed to find a backup playbook.")

    backup_bytes: bytes = newest_backup_path.read_bytes()

    current_playbook_path: Path = get_gridiron_playbook_path()
    current_playbook_path.write_bytes(backup_bytes)


def _ensure_path_suffix(path: Path, suffix: str) -> None:
    """Raises a ValueError if the provided path does not end with the given suffix."""
    if path.suffix != suffix:
        raise ValueError(f"Invalid path suffix provided: {path.suffix}, please provide a {suffix}")


def write_playbook_to_sav(playbook: GridironPlaybook, path: Path) -> None:
    """Writes the provided playbook to a .sav file at the path provided."""
    _ensure_path_suffix(path=path, suffix=".sav")
    playbook_sav: bytes = playbook_to_sav(playbook=playbook)
    path.write_bytes(playbook_sav)


def write_playbook_to_json(playbook, path: Path) -> None:
    """Writes the provided playbook to a .json file at the path provided."""
    _ensure_path_suffix(path=path, suffix=".json")
    playbook_json: str = playbook_to_json(playbook=playbook)
    path.write_text(playbook_json)


def read_sav_to_playbook(path: Path) -> GridironPlaybook:
    """Reads the provided .sav file as a playbook."""
    playbook_sav: bytes = path.read_bytes()
    playbook: GridironPlaybook = sav_to_playbook(save_bytes=playbook_sav)
    return playbook


def read_json_to_playbook(path: Path) -> GridironPlaybook:
    """Reads the provided .json file as a playbook."""
    _ensure_path_suffix(path=path, suffix=".json")
    playbook_json: str = path.read_text()
    return json_to_playbook(json_text=playbook_json)


def sav_to_playbook(save_bytes: bytes) -> GridironPlaybook:
    """Returns the playbook from the bytes provided."""
    playbook_json: str = sav_to_json(save_bytes=save_bytes)
    playbook: GridironPlaybook = json_to_playbook(json_text=playbook_json)
    return playbook


def json_to_playbook(json_text: str) -> GridironPlaybook:
    """Returns the playbook encoded by the provided JSON text."""
    return GridironPlaybook.model_validate_json(json_text)


def playbook_to_sav(playbook: GridironPlaybook) -> bytes:
    """Returns the bytes for the provided playbook as a .sav file."""
    playbook_json: str = playbook_to_json(playbook=playbook)
    return json_to_sav(json_text=playbook_json)


def playbook_to_json(playbook: GridironPlaybook) -> str:
    """Returns the provided playbook as a JSON str."""
    return playbook.model_dump_json(indent=4, by_alias=True, exclude_unset=True)


if __name__ == "__main__":
    path: Path = Path.cwd()
    load_backup_playbook()
