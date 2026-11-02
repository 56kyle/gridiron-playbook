"""Opt-in pointer-to-save integration check against a running local editor."""

import os
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest
from pydantic import TypeAdapter

from gridiron_playbook.editor import PlaybookEditor
from gridiron_playbook.playbook import playbook_to_sav
from gridiron_playbook.playbook import sav_to_playbook


if TYPE_CHECKING:
    from gridiron_playbook.playbook import GridironPlaybook
    from gridiron_playbook.point import GridironPoint


_FIXTURE: Path = Path(__file__).parents[2] / "data" / "GridIronCustomPlays.sav"
_EDITOR_URL: str = os.environ.get("PLAYBOOK_EDITOR_TEST_URL", "")
pytestmark = pytest.mark.skipif(
    not _EDITOR_URL or find_spec("playwright") is None or find_spec("nicegui") is None,
    reason="Set PLAYBOOK_EDITOR_TEST_URL and install the web and browser test dependencies.",
)


def test_move_route_point_with_browser_drag(tmp_path: Path) -> None:
    address = urlsplit(_EDITOR_URL)
    if address.scheme not in {"http", "https"} or address.hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("PLAYBOOK_EDITOR_TEST_URL must point to a local editor.")

    from playwright.sync_api import expect
    from playwright.sync_api import sync_playwright

    from gridiron_playbook.web.play_diagram import FieldTransform

    source: bytes = _FIXTURE.read_bytes()
    original: GridironPlaybook = sav_to_playbook(source)
    play = original.root.properties.custom_plays[0]
    point: GridironPoint = play.routes[0].points[1]
    downloaded: Path = tmp_path / "dragged.sav"
    dx, dy = 32, -16

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYBOOK_EDITOR_BROWSER_CHANNEL"))
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        _ = page.goto(_EDITOR_URL)
        page.locator("input[type=file]").set_input_files(_FIXTURE)
        field = page.get_by_test_id("play-field")
        expect(field.locator("[data-lineup-slot]")).to_have_count(7)
        expect(field.locator('[data-lineup-slot="1"]')).to_be_visible()
        field.locator('[data-route-index="0"]').focus()
        page.keyboard.press("Enter")
        expect(field.locator("[data-point-index]")).to_have_count(len(play.routes[0].points))
        handle = field.locator('[data-point-index="1"]')
        expect(handle).to_be_visible()
        handle.scroll_into_view_if_needed()
        box = handle.bounding_box()
        assert box is not None
        svg_scale: float = TypeAdapter(float).validate_python(field.evaluate("svg => svg.getScreenCTM().a"))
        assert svg_scale > 0
        start_x: int = round(box["x"] + box["width"] / 2)
        start_y: int = round(box["y"] + box["height"] / 2)
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        page.mouse.move(start_x + dx, start_y + dy, steps=4)
        page.mouse.up()
        expect(page.get_by_role("button", name="Undo", exact=True)).to_be_enabled()
        with page.expect_download() as transfer:
            page.get_by_role("button", name="Download .sav", exact=True).click()
        transfer.value.save_as(downloaded)
        browser.close()

    reopened: GridironPlaybook = sav_to_playbook(downloaded.read_bytes())
    moved: GridironPoint = reopened.root.properties.custom_plays[0].routes[0].points[1]
    pixels_per_game_unit: float = svg_scale * FieldTransform.for_play(play).scale
    assert (moved.x, moved.y) == pytest.approx(
        (point.x - dy / pixels_per_game_unit, point.y + dx / pixels_per_game_unit)
    )
    assert moved.z == point.z
    restored: PlaybookEditor = PlaybookEditor(reopened)
    restored.move_route_point(0, 0, 1, point.x, point.y)
    assert playbook_to_sav(restored.playbook) == source
