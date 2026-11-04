"""Module containing playbook save schemas for the gridiron_playbook package."""

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import FilePath
from pydantic import validate_call

from gridiron_playbook.constants import DEFAULT_PYDANTIC_CONFIG
from gridiron_playbook.constants import USER_CACHE_FOLDER
from gridiron_playbook.game import get_gridiron_playbook_path
from gridiron_playbook.play import GridironLastDrawnPlay
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.playbook_document import GridironPlaybook
from gridiron_playbook.playbook_document import GridironPlaybookProperties
from gridiron_playbook.playbook_document import GridironSaveRoot
from gridiron_playbook.playbook_document import json_to_playbook as json_to_playbook
from gridiron_playbook.playbook_document import playbook_to_json as playbook_to_json
from gridiron_playbook.playbook_document import playbook_to_sav as playbook_to_sav
from gridiron_playbook.playbook_document import sav_to_playbook as sav_to_playbook
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


if TYPE_CHECKING:
    from gridiron_playbook.game_playbook import GamePlaybookStore


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


def export_playbook(export_path: Path) -> None:
    """Export the current playbook to the given path as a json."""
    if export_path.is_dir():
        export_path = export_path / "GridironCustomPlays.json"
    export_path = export_path.with_suffix(".json")

    playbook_save_path: Path = get_gridiron_playbook_path()
    playbook: GridironPlaybook = read_sav_to_playbook(path=playbook_save_path)

    write_playbook_to_json(playbook=playbook, path=export_path)


@validate_call(config=DEFAULT_PYDANTIC_CONFIG)
def import_playbook(import_path: FilePath) -> None:
    """Import the playbook from the given path to be the current one, while backing up the original."""
    playbook: GridironPlaybook
    if import_path.suffix == ".json":
        playbook = read_json_to_playbook(path=import_path)
    elif import_path.suffix == ".sav":
        playbook = read_sav_to_playbook(path=import_path)
    else:
        raise ValueError(f"Invalid path suffix provided: {import_path.suffix}, please provide a .json or a .sav file.")
    store: GamePlaybookStore = _game_playbook_store()
    _ = store.apply(store.prepare_install(playbook))


def save_backup_playbook() -> Path:
    """Save a verified, unique backup in the application's local data folder."""
    return _game_playbook_store().backup_current()


def load_backup_playbook() -> None:
    """Restore the most recent different backup while preserving the current save."""
    store: GamePlaybookStore = _game_playbook_store()
    _ = store.apply(store.prepare_restore())


def _game_playbook_store() -> "GamePlaybookStore":
    from gridiron_playbook.game_playbook import GAME_PLAYBOOK_BACKUP_DIRECTORY
    from gridiron_playbook.game_playbook import GamePlaybookStore

    return GamePlaybookStore(
        get_gridiron_playbook_path(), GAME_PLAYBOOK_BACKUP_DIRECTORY, legacy_backup_directory=USER_CACHE_FOLDER
    )


def _ensure_path_suffix(path: Path, suffix: str) -> None:
    """Raises a ValueError if the provided path does not end with the given suffix."""
    if path.suffix != suffix:
        raise ValueError(f"Invalid path suffix provided: {path.suffix}, please provide a {suffix}")


def write_playbook_to_sav(playbook: GridironPlaybook, path: Path) -> None:
    """Writes the provided playbook to a .sav file at the path provided."""
    _ensure_path_suffix(path=path, suffix=".sav")
    playbook_sav: bytes = playbook_to_sav(playbook=playbook)
    _ = path.write_bytes(playbook_sav)


def write_playbook_to_json(playbook: GridironPlaybook, path: Path) -> None:
    """Writes the provided playbook to a .json file at the path provided."""
    _ensure_path_suffix(path=path, suffix=".json")
    playbook_json: str = playbook_to_json(playbook=playbook)
    _ = path.write_text(playbook_json)


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


if __name__ == "__main__":
    path: Path = Path.cwd()
    load_backup_playbook()
