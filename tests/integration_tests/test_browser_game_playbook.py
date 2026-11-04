"""Opt-in browser checks for reversible deployment to isolated game saves."""

import os
from collections.abc import Iterator
from importlib.util import find_spec
from pathlib import Path
from tempfile import gettempdir
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest

from gridiron_playbook.game_playbook import GamePlaybookStore
from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.playbook import playbook_to_sav
from gridiron_playbook.workspace import document_with_plays


if TYPE_CHECKING:
    from playwright.sync_api import Browser
    from playwright.sync_api import Locator
    from playwright.sync_api import Page


_EDITOR_URL = os.getenv("PLAYBOOK_EDITOR_TEST_URL", "")
_BACKUP_DIRECTORY = os.getenv("GRIDIRON_GAME_BACKUP_DIRECTORY", "")
pytestmark = pytest.mark.skipif(
    not _EDITOR_URL or not _BACKUP_DIRECTORY or find_spec("playwright") is None or find_spec("nicegui") is None,
    reason="Set local editor and isolated game-backup test locations, and install browser dependencies.",
)


@pytest.fixture(scope="module")
def browser() -> Iterator["Browser"]:
    from playwright.sync_api import sync_playwright

    address = urlsplit(_EDITOR_URL)
    if address.scheme not in {"http", "https"} or address.hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Game-save browser tests require a local editor.")
    if not Path(_BACKUP_DIRECTORY).resolve().is_relative_to(Path(gettempdir()).resolve()):
        pytest.fail("Game-save browser tests require a backup directory inside the temporary folder.")
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(channel=os.getenv("PLAYBOOK_EDITOR_BROWSER_CHANNEL"))
        yield instance
        instance.close()


@pytest.fixture
def game_files(tmp_path: Path, custom_plays_json: str) -> tuple[Path, Path]:
    template = GridironPlaybook.model_validate_json(custom_plays_json)
    first = template.root.properties.custom_plays[0]
    game = document_with_plays(template, (first.model_copy(update={"play_name": "Game original"}),))
    chosen = document_with_plays(template, (first.model_copy(update={"play_name": "Chosen in editor"}),))
    target = tmp_path / "GridironCustomPlays.sav"
    uploaded = tmp_path / "Chosen.sav"
    _ = target.write_bytes(playbook_to_sav(game))
    _ = uploaded.write_bytes(playbook_to_sav(chosen))
    return target, uploaded


def _review_target(page: "Page", target: Path) -> "Locator":
    from playwright.sync_api import expect

    dialog = page.get_by_role("dialog")
    location = dialog.get_by_role("textbox", name="Game save", exact=True)
    expect(location).to_be_visible()
    location.fill(str(target))
    dialog.get_by_role("button", name="Review", exact=True).click()
    expect(dialog.get_by_role("checkbox", name="Gridiron is closed", exact=True)).to_be_visible()
    expect(dialog.get_by_text(str(target.resolve()), exact=True)).to_be_visible()
    return dialog


def test_game_playbook_with_reversible_browser_restore(browser: "Browser", game_files: tuple[Path, Path]) -> None:
    from playwright.sync_api import expect

    target, uploaded = game_files
    original = target.read_bytes()
    chosen = uploaded.read_bytes()
    store = GamePlaybookStore(target, Path(_BACKUP_DIRECTORY))
    with browser.new_context() as context:
        page = context.new_page()
        _ = page.goto(_EDITOR_URL)
        page.locator("input[type=file]").set_input_files(uploaded)
        expect(page.get_by_role("tab", name=uploaded.name, exact=True)).to_have_attribute("aria-selected", "true")
        page.get_by_role("button", name="Use in game", exact=True).click()
        dialog = _review_target(page, target)
        expect(dialog.get_by_role("button", name="Use in game", exact=True)).to_be_disabled()
        assert target.read_bytes() == original
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        expect(dialog).to_have_count(0)
        assert target.read_bytes() == original
        page.get_by_role("button", name="Use in game", exact=True).click()
        dialog = _review_target(page, target)
        closed = dialog.get_by_role("checkbox", name="Gridiron is closed", exact=True)
        closed.click()
        expect(closed).to_be_checked()
        dialog.get_by_role("button", name="Use in game", exact=True).click()
        expect(dialog).to_have_count(0)
        assert target.read_bytes() == chosen
        assert store.prepare_restore().replacement == original
        page.get_by_role("button", name=f"Close {uploaded.name}", exact=True).click()
        expect(page.get_by_role("tab")).to_have_count(0)
        for expected in (original, chosen):
            page.get_by_role("button", name="Restore previous playbook", exact=True).click()
            dialog = _review_target(page, target)
            closed = dialog.get_by_role("checkbox", name="Gridiron is closed", exact=True)
            closed.click()
            expect(closed).to_be_checked()
            dialog.get_by_role("button", name="Restore previous playbook", exact=True).click()
            expect(dialog).to_have_count(0)
            assert target.read_bytes() == expected
        assert uploaded.read_bytes() == chosen
