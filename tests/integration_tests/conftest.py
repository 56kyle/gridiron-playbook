"""Fixtures used in integration tests."""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from loguru import logger

import gridiron_playbook
from gridiron_playbook import constants


@pytest.fixture
def temporary_log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    module_name: str = "gridiron_playbook.log"
    with monkeypatch.context() as context:
        context.setattr(constants, "USER_LOG_FOLDER", tmp_path)
        context.delitem(sys.modules, module_name, raising=False)
        context.delattr(gridiron_playbook, "log", raising=False)

        from gridiron_playbook import log

        try:
            logger.info("logging contract")
            yield log.LOG_PATH
        finally:
            logger.remove(log.LOG_HANDLER_ID)
            _ = sys.modules.pop(module_name, None)
            delattr(gridiron_playbook, "log")
