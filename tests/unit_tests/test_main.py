"""Test cases for the __main__ module."""

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from gridiron_playbook import __main__


if TYPE_CHECKING:
    from typer.testing import Result


@pytest.fixture
def runner() -> CliRunner:
    """Fixture for invoking command-line interfaces."""
    return CliRunner()


def test_main_succeeds(runner: CliRunner) -> None:
    """It exits with a status code of zero."""
    result: Result = runner.invoke(__main__.app)
    assert result.exit_code == 0
