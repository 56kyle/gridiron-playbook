"""Module containing logic for logging used throughout the gridiron_playbook package."""

from pathlib import Path

from loguru import logger

from gridiron_playbook.constants import APP_START_TIME
from gridiron_playbook.constants import FILE_SAFE_DATETIME_FORMAT
from gridiron_playbook.constants import USER_LOG_FOLDER


FILE_SAFE_DATETIME_SLUG: str = APP_START_TIME.strftime(FILE_SAFE_DATETIME_FORMAT)

LOG_PATH: Path = USER_LOG_FOLDER / f"log_{FILE_SAFE_DATETIME_SLUG}.log"


LOG_HANDLER_ID: int = logger.add(LOG_PATH, serialize=True)
