"""Opt-in diagram interactions against a running local editor."""

import os
from collections.abc import Iterator
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
    from playwright.sync_api import Locator
    from playwright.sync_api import Page

    from gridiron_playbook.playbook import GridironPlaybook
    from gridiron_playbook.point import GridironPoint


_FIXTURE: Path = Path(__file__).parents[2] / "data" / "GridIronCustomPlays.sav"
_EDITOR_URL: str = os.environ.get("PLAYBOOK_EDITOR_TEST_URL", "")
pytestmark = pytest.mark.skipif(
    not _EDITOR_URL or find_spec("playwright") is None or find_spec("nicegui") is None,
    reason="Set PLAYBOOK_EDITOR_TEST_URL and install the web and browser test dependencies.",
)


@pytest.fixture
def editor_page() -> Iterator["Page"]:
    address = urlsplit(_EDITOR_URL)
    if address.scheme not in {"http", "https"} or address.hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("PLAYBOOK_EDITOR_TEST_URL must point to a local editor.")

    from playwright.sync_api import expect
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYBOOK_EDITOR_BROWSER_CHANNEL"))
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        _ = page.goto(_EDITOR_URL)
        page.locator("input[type=file]").set_input_files(_FIXTURE)
        field = page.get_by_test_id("play-field")
        expect(field.locator("[data-lineup-slot]")).to_have_count(7)
        yield page
        browser.close()


def test_move_route_point_with_browser_drag(editor_page: "Page", tmp_path: Path) -> None:
    from playwright.sync_api import expect

    from gridiron_playbook.web.play_diagram import FieldTransform

    source: bytes = _FIXTURE.read_bytes()
    original: GridironPlaybook = sav_to_playbook(source)
    play = original.root.properties.custom_plays[0]
    point: GridironPoint = play.routes[0].points[1]
    downloaded: Path = tmp_path / "dragged.sav"
    dx, dy = 32, -16

    field = editor_page.get_by_test_id("play-field")
    expect(field.locator('[data-lineup-slot="1"]')).to_be_visible()
    field.locator('[data-route-index="0"]').focus()
    editor_page.keyboard.press("Enter")
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
    editor_page.mouse.move(start_x, start_y)
    editor_page.mouse.down()
    editor_page.mouse.move(start_x + dx, start_y + dy, steps=4)
    editor_page.mouse.up()
    expect(editor_page.get_by_role("button", name="Undo", exact=True)).to_be_enabled()
    with editor_page.expect_download() as transfer:
        editor_page.get_by_role("button", name="Download .sav", exact=True).click()
    transfer.value.save_as(downloaded)

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


def test_lineup_with_game_route_yardage(editor_page: "Page") -> None:
    from playwright.sync_api import expect

    for index, yards in enumerate((12, 49, 14, 31, 64)):
        expect(editor_page.get_by_test_id(f"route-{index}")).to_contain_text(f"{yards} yds")

    field = editor_page.get_by_test_id("play-field")
    for slot, side in [(5, "WR-R"), (6, "WR-L")]:
        marker = field.get_by_role("button", name=f"Select {side} route, slot {slot}", exact=True)
        expect(marker.locator("text")).to_have_text("WR")


def test_cancel_drag_after_typing_in_search(editor_page: "Page") -> None:
    from playwright.sync_api import expect

    editor_page.get_by_test_id("route-0").click()
    handle = editor_page.get_by_test_id("play-field").locator('[data-point-index="1"]')
    expect(handle).to_be_visible()
    search = editor_page.get_by_placeholder("Find a play")
    search.fill("SWRT")
    handle.hover()
    origin = handle.get_attribute("transform")
    box = handle.bounding_box()
    assert origin is not None
    assert box is not None
    expect(search).to_be_focused()
    editor_page.mouse.down()
    editor_page.mouse.move(box["x"] + 45, box["y"] - 20)
    expect(handle).not_to_have_attribute("transform", origin)
    editor_page.keyboard.press("Escape")
    editor_page.mouse.up()
    expect(handle).to_have_attribute("transform", origin)
    expect(editor_page.get_by_role("button", name="Undo", exact=True)).to_be_disabled()


def _preview_end(line: "Locator") -> str:
    return f"{line.get_attribute('x2')},{line.get_attribute('y2')}"


def test_draw_route_with_working_copy_refresh(editor_page: "Page", tmp_path: Path) -> None:
    from playwright.sync_api import expect

    field = editor_page.get_by_test_id("play-field")
    field.locator('[data-lineup-slot="1"]').click()
    expect(editor_page.get_by_role("button", name="Finish route", exact=True)).to_be_visible()
    draft_count = editor_page.locator(".pb-draft-tools strong")
    expect(draft_count).to_contain_text(" · 0 points")
    bridge = editor_page.locator("[data-recovery-revision]")
    expect(bridge).to_have_attribute("data-recovery-status", "ready")
    revision = bridge.get_attribute("data-recovery-revision")
    assert revision is not None
    field.click(position={"x": 70, "y": 80})
    expect(draft_count).to_contain_text(" · 1 point")
    _ = editor_page.wait_for_function(
        """revision => {
            const recovery = document.querySelector('[data-recovery-revision]');
            return recovery?.dataset.recoveryStatus === 'ready' && Number(recovery.dataset.recoveryRevision) > revision;
        }""",
        arg=int(revision),
    )
    revision = bridge.get_attribute("data-recovery-revision")
    assert revision is not None
    field.click(position={"x": 120, "y": 60})
    expect(draft_count).to_contain_text(" · 2 points")
    path = field.locator("[data-draft-path]")
    original_points = path.get_attribute("points")
    assert original_points is not None
    _ = editor_page.wait_for_function(
        """revision => {
            const recovery = document.querySelector('[data-recovery-revision]');
            return recovery?.dataset.recoveryStatus === 'ready' && Number(recovery.dataset.recoveryRevision) > revision;
        }""",
        arg=int(revision),
    )
    _ = editor_page.reload()
    expect(editor_page.get_by_role("button", name="Finish route", exact=True)).to_be_enabled()
    expect(draft_count).to_contain_text(" · 2 points")
    restored = path.get_attribute("points")
    assert restored is not None
    assert [float(axis) for point in restored.split() for axis in point.split(",")] == pytest.approx(
        [float(axis) for point in original_points.split() for axis in point.split(",")]
    )
    editor_page.get_by_role("button", name="Finish route", exact=True).click()
    expect(path).to_have_count(0)
    with editor_page.expect_download() as transfer:
        editor_page.get_by_role("button", name="Download .sav", exact=True).click()
    downloaded = tmp_path / "recovered-draft.sav"
    transfer.value.save_as(downloaded)
    route = sav_to_playbook(downloaded.read_bytes()).root.properties.custom_plays[0].routes[-1]
    assert route.slot == 1
    assert len(route.points) == 2


def test_draw_route_with_pointer_preview_and_shortcuts(editor_page: "Page", tmp_path: Path) -> None:
    from playwright.sync_api import expect

    from gridiron_playbook.web.play_diagram import FieldTransform

    field = editor_page.get_by_test_id("play-field")
    center = field.locator('[data-lineup-slot="1"]')
    center.click()
    preview = field.locator("[data-draft-preview]")
    path = field.locator("[data-draft-path]")
    expect(path).to_have_count(1)
    field.hover(position={"x": 70, "y": 80})
    expect(preview).to_be_visible()
    anchor = f"{preview.get_attribute('x1')},{preview.get_attribute('y1')}"
    expect(path).to_have_attribute("points", anchor)
    first = _preview_end(preview)
    field.click(position={"x": 70, "y": 80})
    expect(path).to_have_attribute("points", f"{anchor} {first}")

    field.hover(position={"x": 120, "y": 60})
    expect(preview).to_be_visible()
    assert f"{preview.get_attribute('x1')},{preview.get_attribute('y1')}" == first
    second = _preview_end(preview)
    assert second != first
    editor_page.get_by_role("button", name="Finish route", exact=True).hover()
    expect(preview).to_have_count(0)
    field.click(position={"x": 120, "y": 60})
    expect(path).to_have_attribute("points", f"{anchor} {first} {second}")

    editor_page.keyboard.press("Control+z")
    expect(path).to_have_attribute("points", f"{anchor} {first}")
    editor_page.keyboard.press("Control+Shift+z")
    expect(path).to_have_attribute("points", f"{anchor} {first} {second}")
    editor_page.keyboard.press("Backspace")
    expect(path).to_have_attribute("points", f"{anchor} {first}")
    field.hover(position={"x": 240, "y": 160})
    expect(preview).to_be_visible()
    editor_page.keyboard.press("Enter")
    expect(field.locator("[data-point-index]")).to_have_count(1)

    downloaded: Path = tmp_path / "drawn.sav"
    with editor_page.expect_download() as transfer:
        editor_page.get_by_role("button", name="Download .sav", exact=True).click()
    transfer.value.save_as(downloaded)
    saved = sav_to_playbook(downloaded.read_bytes()).root.properties.custom_plays[0].routes[-1]
    assert saved.slot == 1
    (committed,) = saved.points
    original = sav_to_playbook(_FIXTURE.read_bytes()).root.properties.custom_plays[0]
    x, y = (float(axis) for axis in first.split(","))
    assert (committed.x, committed.y) == pytest.approx(FieldTransform.for_play(original).field_to_game(x, y))


def test_keyboard_history_with_inputs_dialogs_and_cancelled_draft(editor_page: "Page") -> None:
    from playwright.sync_api import expect

    field = editor_page.get_by_test_id("play-field")
    draw = editor_page.get_by_role("button", name="Draw route for C, slot 1", exact=True)
    draw.click()
    expect(field.locator("[data-draft-path]")).to_have_count(1)
    field.click(position={"x": 40, "y": 70})
    editor_page.keyboard.press("Enter")
    expect(draw).to_have_count(0)
    editor_page.keyboard.press("Control+z")
    expect(draw).to_be_visible()
    editor_page.keyboard.press("Control+y")
    expect(draw).to_have_count(0)

    search = editor_page.get_by_placeholder("Find a play")
    search.press_sequentially("S")
    search.press("Control+z")
    expect(search).to_have_value("")
    expect(draw).to_have_count(0)
    editor_page.get_by_role("button", name="Rename", exact=True).click()
    dialog = editor_page.get_by_role("dialog")
    cancel = dialog.get_by_role("button", name="Cancel", exact=True)
    cancel.focus()
    cancel.press("Control+z")
    cancel.click()
    expect(dialog).to_have_count(0)
    expect(draw).to_have_count(0)

    editor_page.keyboard.press("Control+z")
    draw.click()
    expect(field.locator("[data-draft-path]")).to_have_count(1)
    field.click(position={"x": 95, "y": 70})
    editor_page.keyboard.press("Escape")
    expect(field.locator("[data-draft-path]")).to_have_count(0)
    expect(draw).to_be_visible()
    editor_page.keyboard.press("Control+y")
    expect(draw).to_have_count(0)


def _download_save(page: "Page", destination: Path) -> None:
    with page.expect_download() as transfer:
        page.get_by_role("button", name="Download .sav", exact=True).click()
    transfer.value.save_as(destination)


def test_edit_existing_route_nodes(editor_page: "Page", tmp_path: Path) -> None:
    from playwright.sync_api import expect

    editor_page.get_by_test_id("route-1").click()
    field = editor_page.get_by_test_id("play-field")
    handles = field.locator("[data-point-index]")
    line = field.locator('[data-route-index="1"] polyline[marker-end]')
    add_node = editor_page.get_by_role("button", name="Add node", exact=True)
    original = sav_to_playbook(_FIXTURE.read_bytes()).root.properties.custom_plays[0].routes[1]
    expect(handles).to_have_count(len(original.points))
    original_path = line.get_attribute("points")
    assert original_path is not None
    vertices: list[str] = original_path.split()

    add_node.click()
    x, y = TypeAdapter(tuple[float, float]).validate_python(
        line.evaluate("""line => {
            const a = line.points.getItem(1), b = line.points.getItem(2);
            const p = new DOMPoint((a.x + b.x) / 2, (a.y + b.y) / 2).matrixTransform(line.getScreenCTM());
            return [p.x, p.y];
        }""")
    )
    editor_page.mouse.click(x, y)
    expect(handles).to_have_count(len(original.points) + 1)
    inserted_path = line.get_attribute("points")
    assert inserted_path is not None
    inserted: list[str] = inserted_path.split()
    assert [*inserted[:2], *inserted[3:]] == vertices

    handles.nth(1).click()
    editor_page.keyboard.press("Delete")
    expect(line).to_have_attribute("points", original_path)

    add_node.click()
    field.click(position={"x": 25, "y": 25})
    expect(handles).to_have_count(len(original.points) + 1)
    downloaded: Path = tmp_path / "extended.sav"
    _download_save(editor_page, downloaded)
    extended = sav_to_playbook(downloaded.read_bytes()).root.properties.custom_plays[0].routes[1]
    assert extended.points[:-1] == original.points
    assert extended.points[-1] not in original.points


@pytest.mark.parametrize("terminal", [False, True], ids=["mid-route", "route-end"])
def test_add_route_block_with_save_and_reopen(editor_page: "Page", tmp_path: Path, terminal: bool) -> None:
    from playwright.sync_api import expect

    lineup_row = editor_page.get_by_test_id("route-1")
    lineup_row.click()
    field = editor_page.get_by_test_id("play-field")
    route = field.locator('[data-route-index="1"]')
    arrow = route.locator("polyline[marker-end]")
    original = sav_to_playbook(_FIXTURE.read_bytes()).root.properties.custom_plays[0].routes[1]
    expect(arrow).to_have_count(1)
    original_path = arrow.get_attribute("points")
    assert original_path is not None
    if not terminal:
        field.locator('[data-point-index="1"]').click()
    editor_page.get_by_role("button", name="Add block", exact=True).click()
    line = route.locator("polyline").last
    expect(line).not_to_have_attribute("points", original_path)
    block_path = line.get_attribute("points")
    assert block_path is not None
    expect(arrow).to_have_count(0 if terminal else 1)
    expect(lineup_row).to_contain_text("49 yds")

    editor_page.get_by_role("button", name="Undo", exact=True).click()
    expect(arrow).to_have_attribute("points", original_path)
    editor_page.get_by_role("button", name="Redo", exact=True).click()
    expect(line).to_have_attribute("points", block_path)

    downloaded: Path = tmp_path / "blocked.sav"
    _download_save(editor_page, downloaded)
    saved = sav_to_playbook(downloaded.read_bytes()).root.properties.custom_plays[0].routes[1]
    anchor: int = len(original.points) - 1 if terminal else 1
    added: int = len(saved.points) - len(original.points)
    assert added > 1
    assert saved.points[anchor + added] == original.points[anchor]
    assert saved.points[: anchor + 1] + saved.points[anchor + added + 1 :] == original.points
    assert saved.length_yards(None) == pytest.approx(original.length_yards(None) + 44)

    editor_page.get_by_role("button", name="Open playbook", exact=True).click()
    editor_page.get_by_role("dialog").locator("input[type=file]").set_input_files(downloaded)
    expect(editor_page.get_by_text(downloaded.name, exact=True)).to_be_visible()
    expect(arrow).to_have_count(0 if terminal else 1)
    expect(lineup_row).to_contain_text("49 yds")
    reopened_path = line.get_attribute("points")
    assert reopened_path is not None
    coordinates = tuple(map(float, reopened_path.replace(",", " ").split()))
    assert coordinates == pytest.approx(tuple(map(float, block_path.replace(",", " ").split())))
