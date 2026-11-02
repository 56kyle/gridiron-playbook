"""Fixtures used in unit tests."""

import pytest

from gridiron_playbook.editor import PlaybookEditor
from gridiron_playbook.playbook import GridironPlaybook


@pytest.fixture
def editor(custom_plays_json: str) -> PlaybookEditor:
    return PlaybookEditor(GridironPlaybook.model_validate_json(custom_plays_json))
