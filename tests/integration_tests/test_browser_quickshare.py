"""Opt-in Quickshare round trips between independent browser sessions."""

import os
import re
from collections.abc import Iterator
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest

from gridiron_playbook.editor import PlaybookEditor
from gridiron_playbook.playbook import json_to_playbook
from gridiron_playbook.playbook import playbook_to_sav
from gridiron_playbook.playbook import sav_to_playbook


if TYPE_CHECKING:
    from playwright.sync_api import Browser
    from playwright.sync_api import Page

    from gridiron_playbook.play import GridironPlay
    from gridiron_playbook.playbook import GridironPlaybook


_EDITOR_URL: str = os.getenv("PLAYBOOK_EDITOR_TEST_URL", "")
_SHARE_URL: str = os.getenv("PLAYBOOK_QUICKSHARE_TEST_URL", "").rstrip("/")
_PLAY_COUNT = 121
pytestmark = pytest.mark.skipif(
    not _EDITOR_URL or not _SHARE_URL or find_spec("playwright") is None or find_spec("nicegui") is None,
    reason="Set PLAYBOOK_EDITOR_TEST_URL and PLAYBOOK_QUICKSHARE_TEST_URL and install the browser dependencies.",
)


@pytest.fixture(scope="module")
def browser() -> Iterator["Browser"]:
    from playwright.sync_api import sync_playwright

    for url in (_EDITOR_URL, _SHARE_URL):
        address = urlsplit(url)
        if address.scheme not in {"http", "https"} or address.hostname not in {"localhost", "127.0.0.1", "::1"}:
            pytest.fail("Quickshare browser tests must use local services.")
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(channel=os.getenv("PLAYBOOK_EDITOR_BROWSER_CHANNEL"))
        yield instance
        instance.close()


def _with_plays(document: "GridironPlaybook", plays: tuple["GridironPlay", ...]) -> "GridironPlaybook":
    properties = document.root.properties.model_copy(update={"custom_plays": plays})
    root = document.root.model_copy(update={"properties": properties})
    return document.model_copy(update={"root": root})


@pytest.fixture
def sender_file(custom_plays_json: str, tmp_path: Path) -> Path:
    editor = PlaybookEditor(json_to_playbook(custom_plays_json))
    editor.add_route_block(0, 1, len(editor.plays[0].routes[1].points) - 1)
    numbered = tuple(
        editor.plays[index % len(editor.plays)].model_copy(update={"play_name": f"Shared play {index + 1:03}"})
        for index in range(_PLAY_COUNT - 1)
    )
    last = editor.plays[0].model_copy(update={"play_name": "Shared finish"})
    document = _with_plays(editor.playbook, (*numbered, last))
    destination: Path = tmp_path / "sender.sav"
    _ = destination.write_bytes(playbook_to_sav(document))
    return destination


@pytest.fixture
def recipient_file(custom_plays_json: str, tmp_path: Path) -> Path:
    original = json_to_playbook(custom_plays_json)
    properties = original.root.properties.model_copy(
        update={"last_was_drawn": not original.root.properties.last_was_drawn}
    )
    recipient = original.model_copy(update={"root": original.root.model_copy(update={"properties": properties})})
    destination: Path = tmp_path / "recipient.sav"
    _ = destination.write_bytes(playbook_to_sav(recipient))
    return destination


def _check_copy_link(page: "Page", expected_url: str) -> None:
    from playwright.sync_api import expect

    assert page.evaluate("() => navigator.clipboard.writeText('Quickshare clipboard test')") is None
    page.get_by_role("button", name="Copy link", exact=True).click()
    expect(page.get_by_text("Link copied", exact=True)).to_be_visible()
    assert page.evaluate("async expected => (await navigator.clipboard.readText()) === expected", expected_url) is True


def _publish(page: "Page", source: Path, action: str) -> str:
    from playwright.sync_api import expect

    _ = page.goto(_EDITOR_URL)
    page.locator("input[type=file]").set_input_files(source)
    selected = page.get_by_role("button", name="Shared finish", exact=True)
    selected.click()
    expect(selected).to_have_attribute("aria-current", "true")
    page.get_by_role("button", name=action, exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="Create link", exact=True).click()
    link = dialog.get_by_role("textbox", name="Share link", exact=True)
    expect(link).to_have_value(re.compile(re.escape(_SHARE_URL) + r"/s/[A-Za-z0-9_-]{22}$"))
    url: str = link.input_value()
    _check_copy_link(page, url)
    return url


@pytest.mark.parametrize("action", ["Share play", "Share playbook"], ids=["selected-play", "121-play-book"])
def test_quickshare_round_trip(
    browser: "Browser", action: str, sender_file: Path, recipient_file: Path, tmp_path: Path
) -> None:
    from playwright.sync_api import expect

    source = sav_to_playbook(sender_file.read_bytes())
    original = sav_to_playbook(recipient_file.read_bytes())
    all_plays = source.root.properties.custom_plays
    shared = all_plays if action == "Share playbook" else (all_plays[-1],)
    with browser.new_context(permissions=["clipboard-read", "clipboard-write"]) as sender:
        url = _publish(sender.new_page(), sender_file, action)

    with browser.new_context(permissions=["clipboard-read", "clipboard-write"]) as spectator:
        preview = spectator.new_page()
        _ = preview.goto(url)
        field = preview.get_by_test_id("play-field")
        heading = preview.get_by_role("heading", level=1)
        expect(field).to_have_count(1)
        expect(heading).to_have_text(shared[0].play_name)
        if action == "Share playbook":
            search = preview.get_by_role("combobox")
            search.fill("Shared finish")
            preview.get_by_role("option", name=re.compile("Shared finish")).click()
        expect(heading).to_have_text("Shared finish")
        expect(field).to_have_count(1)
        expect(field).to_have_attribute("role", "img")
        expect(field.get_by_role("button")).to_have_count(0)
        expect(field.locator('[data-route-index="1"] polyline[marker-end]')).to_have_count(0)
        expect(preview.get_by_test_id("preview-yardage")).to_contain_text(["49 yds"])
        _check_copy_link(preview, url)

    with browser.new_context() as recipient:
        page = recipient.new_page()
        _ = page.goto(_EDITOR_URL)
        page.locator("input[type=file]").set_input_files(recipient_file)
        page.get_by_role("button", name="Import link", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_role("textbox", name="Share link", exact=True).fill(url)
        dialog.get_by_role("button", name="Import", exact=True).click()
        expect(dialog).to_have_count(0)
        last = page.get_by_role("button", name="Shared finish", exact=True)
        expect(last).to_be_visible()
        page.get_by_role("button", name="Undo", exact=True).click()
        expect(last).to_have_count(0)
        expect(page.get_by_role("button", name="Undo", exact=True)).to_be_disabled()
        page.get_by_role("button", name="Redo", exact=True).click()
        expect(last).to_be_visible()
        with page.expect_download() as transfer:
            page.get_by_role("button", name="Download .sav", exact=True).click()
        downloaded: Path = tmp_path / "imported.sav"
        transfer.value.save_as(downloaded)

    reopened = sav_to_playbook(downloaded.read_bytes())
    assert reopened == _with_plays(original, (*original.root.properties.custom_plays, *shared))
