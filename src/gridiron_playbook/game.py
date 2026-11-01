"""Module containing logic used for interacting with Gridiron files."""
from pathlib import Path

from srctools.steam import AppInfo
from srctools.steam import find_app


GRIDIRON_REMASTERED_APP_ID: int = 1234567
GRIDIRON_REMASTERED_PLAYTEST_APP_ID: int = 5011360


def get_newest_gridiron_app_info() -> AppInfo:
    """Returns the remastered game's app info, or its playtest if that is not available."""
    try:
        app_info: AppInfo = find_app(app_id=GRIDIRON_REMASTERED_APP_ID)
    except KeyError:
        app_info: AppInfo = find_app(app_id=GRIDIRON_REMASTERED_PLAYTEST_APP_ID)
    return app_info


def get_gridiron_saved_content_folder() -> Path:
    """Returns the path to the Gridiron saved content folder."""
    gridiron_app_info: AppInfo = get_newest_gridiron_app_info()
    gridiron_path: Path = gridiron_app_info.path
    return gridiron_path / "Gridiron" / "Saved"


def get_gridiron_playbook_path() -> Path:
    """Returns the path to the Gridiron playbook save file."""
    gridiron_saved_content_folder: Path = get_gridiron_saved_content_folder()
    return gridiron_saved_content_folder / "SaveGames" / "GridironCustomPlays.sav"
