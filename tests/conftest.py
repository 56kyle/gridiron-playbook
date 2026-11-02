"""Fixtures used in all tests."""

from pathlib import Path

import pytest


@pytest.fixture
def custom_plays_json() -> str:
    source: Path = Path(__file__).parents[1] / "data" / "GridIronCustomPlays.json"
    return source.read_text(encoding="utf-8")
