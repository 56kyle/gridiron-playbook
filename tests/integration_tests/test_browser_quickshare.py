"""Opt-in Quickshare round trips between independent browser sessions."""

import os
from base64 import urlsafe_b64decode
from collections.abc import Iterator
from importlib.util import find_spec
from math import cos
from math import sin
from pathlib import Path
from struct import pack
from typing import TYPE_CHECKING
from typing import Literal
from urllib.parse import urljoin
from urllib.parse import urlsplit
from zlib import decompress

import pytest

from gridiron_playbook.block import block_waypoints
from gridiron_playbook.editor import PlaybookEditor
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.playbook import json_to_playbook
from gridiron_playbook.playbook import playbook_to_sav
from gridiron_playbook.playbook import sav_to_playbook
from gridiron_playbook.point import GridironPoint
from gridiron_playbook.quickshare.codec import Precision
from gridiron_playbook.quickshare.codec import encode_share
from gridiron_playbook.quickshare.links import decode_link
from gridiron_playbook.quickshare.links import make_link
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.route import GridironRoute


if TYPE_CHECKING:
    from playwright.sync_api import Browser
    from playwright.sync_api import Page

    from gridiron_playbook.playbook import GridironPlaybook


_EDITOR_URL: str = os.getenv("PLAYBOOK_EDITOR_TEST_URL", "")
_SHARE_URL: str = os.getenv("PLAYBOOK_QUICKSHARE_TEST_URL", urljoin(_EDITOR_URL, "quickshare/"))
_PLAY_COUNT = 121
# Produced by the v1 encoder for a one-yard QB route with a terminal block.
_V1_BLOCK_FRAGMENT = (
    "eNpzDwxmZGDkDinPzCtWCMpMzyhhZODySU1PTK5USEosAsrJasb0H_p6ov4AAypo8HhYJbJubeOB1teBO-RUEw_g"
    "EHeAiYusc39YlUhQHG4OyBh3UYLicHNAxoicbCAkDjenGmRxDUFxBxR_GRAUh5sDCzcC4nBzDn_ViOk3ICgONwdk"
    "jMaMOkLicHO-AY059L-WkDjcHJAxMekExR1Q_HWuhpD4ARR_mREUdyAUbrjSJwD70_iX"
)
pytestmark = pytest.mark.skipif(
    not _EDITOR_URL or find_spec("playwright") is None or find_spec("nicegui") is None,
    reason="Set PLAYBOOK_EDITOR_TEST_URL and install the browser dependencies.",
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


@pytest.fixture
def workspace_files(custom_plays_json: str, tmp_path: Path) -> tuple[Path, Path]:
    template = json_to_playbook(custom_plays_json)
    paths: list[Path] = []
    for prefix, count in (("Source", 4), ("Destination", 2)):
        plays = tuple(
            template.root.properties.custom_plays[index % len(template.root.properties.custom_plays)].model_copy(
                update={"play_name": f"{prefix} {index}"}
            )
            for index in range(count)
        )
        path = tmp_path / f"{prefix}.sav"
        _ = path.write_bytes(playbook_to_sav(_with_plays(template, plays)))
        paths.append(path)
    return paths[0], paths[1]


def _open_workspace(page: "Page", paths: tuple[Path, Path]) -> None:
    from playwright.sync_api import expect

    _ = page.goto(_EDITOR_URL)
    page.locator("input[type=file]").set_input_files(paths[0])
    page.get_by_role("button", name="Open playbook", exact=True).click()
    page.get_by_role("dialog").locator("input[type=file]").set_input_files(paths[1])
    expect(page.get_by_role("tab")).to_have_count(2)
    page.get_by_role("tab", name=paths[0].name, exact=True).click()
    expect(page.locator(".pb-play-button")).to_have_text([f"Source {i}" for i in range(4)])


@pytest.mark.parametrize("action", ["Copy to", "Move to"])
def test_workspace_transfer(
    browser: "Browser", workspace_files: tuple[Path, Path], tmp_path: Path, action: str
) -> None:
    from playwright.sync_api import expect

    source, destination = workspace_files
    original_source = sav_to_playbook(source.read_bytes())
    original_destination = sav_to_playbook(destination.read_bytes())
    chosen = (original_source.root.properties.custom_plays[1], original_source.root.properties.custom_plays[3])
    with browser.new_context() as context:
        page = context.new_page()
        _open_workspace(page, workspace_files)
        page.get_by_role("button", name="Source 1", exact=True).click()
        page.get_by_role("button", name="Source 3", exact=True).click(modifiers=["Control"])
        page.get_by_role("tab", name=destination.name, exact=True).click()
        page.get_by_role("tab", name=source.name, exact=True).click()
        expect(page.get_by_role("checkbox", name="Select Source 1", exact=True)).to_be_checked()
        expect(page.get_by_role("checkbox", name="Select Source 3", exact=True)).to_be_checked()
        page.get_by_role("button", name=action, exact=True).click()
        page.get_by_role("menuitem", name=destination.name, exact=True).click()
        expect(page.get_by_role("tab", name=destination.name, exact=True)).to_have_attribute("aria-selected", "true")
        expect(page.locator(".pb-play-button")).to_have_text(["Source 1", "Source 3", "Destination 0", "Destination 1"])
        with page.expect_download() as transfer:
            page.get_by_role("button", name="Download .sav", exact=True).click()
        saved = tmp_path / "combined.sav"
        transfer.value.save_as(saved)
        assert sav_to_playbook(saved.read_bytes()) == _with_plays(
            original_destination, (*chosen, *original_destination.root.properties.custom_plays)
        )
        page.get_by_role("tab", name=source.name, exact=True).click()
        expected_source = ["Source 0", "Source 2"] if action == "Move to" else [f"Source {i}" for i in range(4)]
        expect(page.locator(".pb-play-button")).to_have_text(expected_source)
        page.get_by_role("button", name="Undo", exact=True).click()
        page.get_by_role("tab", name=source.name, exact=True).click()
        expect(page.locator(".pb-play-button")).to_have_text([f"Source {i}" for i in range(4)])
        page.get_by_role("tab", name=destination.name, exact=True).click()
        expect(page.locator(".pb-play-button")).to_have_text(["Destination 0", "Destination 1"])


def test_workspace_reorder_and_merge(browser: "Browser", workspace_files: tuple[Path, Path]) -> None:
    from playwright.sync_api import expect

    source, destination = workspace_files
    with browser.new_context() as context:
        page = context.new_page()
        _open_workspace(page, workspace_files)
        page.get_by_role("button", name="Source 1", exact=True).click()
        page.get_by_role("button", name="Source 2", exact=True).click(modifiers=["Shift"])
        page.get_by_role("button", name="Move to top", exact=True).click()
        reordered = ["Source 1", "Source 2", "Source 0", "Source 3"]
        expect(page.locator(".pb-play-button")).to_have_text(reordered)
        page.get_by_role("button", name=f"Playbook actions for {source.name}", exact=True).click()
        page.get_by_role("menuitem", name="Merge into", exact=True).click()
        page.get_by_role("menuitem", name=destination.name, exact=True).click()
        expect(page.locator(".pb-play-button")).to_have_text([*reordered, "Destination 0", "Destination 1"])
        page.get_by_role("tab", name=source.name, exact=True).click()
        expect(page.locator(".pb-play-button")).to_have_text(reordered)


def test_workspace_drag_between_books(browser: "Browser", workspace_files: tuple[Path, Path]) -> None:
    from playwright.sync_api import expect

    source, destination = workspace_files
    with browser.new_context() as context:
        page = context.new_page()
        _open_workspace(page, workspace_files)
        page.locator('[aria-label="Drag Source 3"]').drag_to(
            page.locator('[data-play-index="0"]'), target_position={"x": 15, "y": 2}
        )
        expect(page.locator(".pb-play-button")).to_have_text(["Source 3", "Source 0", "Source 1", "Source 2"])
        page.locator('[aria-label="Drag Source 3"]').drag_to(page.get_by_role("tab", name=destination.name, exact=True))
        expect(page.locator(".pb-play-button")).to_have_text(["Source 3", "Destination 0", "Destination 1"])
        page.get_by_role("tab", name=source.name, exact=True).click()
        expect(page.locator(".pb-play-button")).to_have_text(["Source 0", "Source 1", "Source 2"])


def test_workspace_new_and_close(browser: "Browser", workspace_files: tuple[Path, Path]) -> None:
    from playwright.sync_api import expect

    source, _ = workspace_files
    with browser.new_context() as context:
        page = context.new_page()
        _open_workspace(page, workspace_files)
        page.get_by_role("button", name="New playbook", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_role("textbox", name="Playbook name", exact=True).fill("New.sav")
        dialog.get_by_role("button", name="Create playbook", exact=True).click()
        expect(page.get_by_role("tab", name="New.sav", exact=True)).to_have_attribute("aria-selected", "true")
        expect(page.locator(".pb-play-button")).to_have_count(0)
        page.get_by_role("button", name="New play", exact=True).click()
        dialog.get_by_role("textbox", name="Formation", exact=True).fill("Twins Right")
        dialog.get_by_role("textbox", name="Play name", exact=True).fill("New play")
        dialog.get_by_role("button", name="Create play", exact=True).click()
        expect(page.locator(".pb-play-button")).to_have_text(["New play"])
        page.get_by_role("tab", name=source.name, exact=True).click()
        expect(page.locator(".pb-play-button")).to_have_text([f"Source {i}" for i in range(4)])
        page.get_by_role("tab", name="New.sav", exact=True).click()
        page.get_by_role("button", name="Close New.sav", exact=True).click()
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        expect(page.get_by_role("tab", name="New.sav", exact=True)).to_have_count(1)
        expect(page.locator(".pb-play-button")).to_have_text(["New play"])
        page.get_by_role("button", name="Close New.sav", exact=True).click()
        dialog.get_by_role("button", name="Close without downloading", exact=True).click()
        expect(page.get_by_role("tab", name="New.sav", exact=True)).to_have_count(0)
        expect(page.get_by_role("tab")).to_have_count(2)


def _check_copy_link(page: "Page", expected_url: str, warning: str | None = None) -> None:
    from playwright.sync_api import expect

    assert page.evaluate("() => navigator.clipboard.writeText('Quickshare clipboard test')") is None
    page.get_by_role("button", name="Copy link", exact=True).click()
    if warning is not None:
        popup = page.get_by_role("dialog").filter(has_text=warning).last
        expect(popup.get_by_text(warning, exact=True)).to_be_visible()
        popup.get_by_role("button", name="Cancel", exact=True).click()
        expect(popup).to_have_count(0)
        assert page.evaluate("() => navigator.clipboard.readText()") == "Quickshare clipboard test"
        page.get_by_role("button", name="Copy link", exact=True).click()
        popup.get_by_role("button", name="Copy anyway", exact=True).click()
    expect(page.get_by_text("Link copied", exact=True).last).to_be_visible()
    assert page.evaluate("async expected => (await navigator.clipboard.readText()) === expected", expected_url) is True


def _select_precision(page: "Page", label: str) -> None:
    page.get_by_role("dialog").get_by_role("combobox").click()
    page.get_by_role("option", name=label, exact=True).click()


def _check_length(page: "Page", url: str) -> None:
    from playwright.sync_api import expect

    expect(page.get_by_test_id("share-length")).to_have_text(f"{len(url):,} characters")


@pytest.mark.parametrize("action", ["Share play", "Share playbook"], ids=["selected-play", "121-play-book"])
def test_quickshare_round_trip(
    browser: "Browser", action: str, sender_file: Path, recipient_file: Path, tmp_path: Path
) -> None:
    from playwright.sync_api import expect

    source = sav_to_playbook(sender_file.read_bytes())
    all_plays = source.root.properties.custom_plays
    is_book: bool = action == "Share playbook"
    shared = all_plays if is_book else (all_plays[-1],)
    snapshot = ShareSnapshot(version=1, kind="playbook" if is_book else "play", plays=shared)
    exact_url: str = make_link(_SHARE_URL, encode_share(snapshot))
    artifacts: list[tuple[str | Path, tuple["GridironPlay", ...]]] = []
    with browser.new_context(permissions=["clipboard-read", "clipboard-write"]) as sender:
        page = sender.new_page()
        _ = page.goto(_EDITOR_URL)
        page.locator("input[type=file]").set_input_files(sender_file)
        selected = page.get_by_role("button", name="Shared finish", exact=True)
        selected.click()
        expect(selected).to_have_attribute("aria-current", "true")
        page.get_by_role("button", name=action, exact=True).click()
        _check_length(page, exact_url)
        if is_book:
            assert len(exact_url) > 4000
            _check_copy_link(page, exact_url, "Discord Nitro limit exceeded")
        else:
            assert len(exact_url) <= 2000
            _check_copy_link(page, exact_url)
        for precision, label in [(Precision.MILLIMETER, "1 mm"), (Precision.CENTIMETER, "1 cm")]:
            _select_precision(page, label)
            _check_length(page, make_link(_SHARE_URL, encode_share(snapshot, precision)))
        url: str = make_link(_SHARE_URL, encode_share(snapshot, Precision.CENTIMETER))
        rounded = decode_link(url).plays
        assert rounded != snapshot.plays
        if is_book:
            for label, filename, plays in [
                ("Download share file", "compact.gridironshare", rounded),
                ("Download exact file", "exact.gridironshare", shared),
            ]:
                with page.expect_download() as transfer:
                    page.get_by_role("button", name=label, exact=True).click()
                assert transfer.value.suggested_filename.endswith(".gridironshare")
                path = tmp_path / filename
                transfer.value.save_as(path)
                artifacts.append((path, plays))
        else:
            _check_copy_link(page, url)
            artifacts.append((url, rounded))

    for artifact, expected in artifacts:
        _check_preview(browser, artifact, expected[0].play_name)
        _check_import(browser, artifact, recipient_file, expected, tmp_path / "imported.sav", snapshot.kind)


def _check_preview(browser: "Browser", artifact: str | Path, first_name: str) -> None:
    from playwright.sync_api import expect

    with browser.new_context() as spectator:
        preview = spectator.new_page()
        _ = preview.goto(_SHARE_URL if isinstance(artifact, Path) else artifact)
        spectator.set_offline(True)
        if isinstance(artifact, Path):
            preview.locator("input[type=file]").set_input_files(artifact)
        field = preview.get_by_test_id("play-field")
        heading = preview.get_by_role("heading", level=1)
        expect(field).to_have_count(1)
        expect(heading).to_have_text(first_name)
        if isinstance(artifact, Path):
            search = preview.get_by_role("searchbox", name="Find a play")
            search.fill("Shared finish")
            expect(preview.get_by_role("combobox", name="Select play").get_by_role("option")).to_have_count(1)
        expect(heading).to_have_text("Shared finish")
        expect(field).to_have_count(1)
        expect(field).to_have_attribute("role", "img")
        expect(field.get_by_role("button")).to_have_count(0)
        expect(field.locator('[data-route-index="1"] polyline[marker-end]')).to_have_count(0)
        expect(preview.get_by_test_id("preview-yardage")).to_contain_text(["49 yds"])


def _check_import(
    browser: "Browser",
    artifact: str | Path,
    recipient_file: Path,
    plays: tuple["GridironPlay", ...],
    downloaded: Path,
    kind: Literal["play", "playbook"] = "play",
) -> None:
    from playwright.sync_api import expect

    original = sav_to_playbook(recipient_file.read_bytes())
    with browser.new_context() as recipient:
        page = recipient.new_page()
        _ = page.goto(_EDITOR_URL)
        page.locator("input[type=file]").set_input_files(recipient_file)
        page.get_by_role("button", name="Import share", exact=True).click()
        dialog = page.get_by_role("dialog")
        if isinstance(artifact, Path):
            dialog.locator(".pb-uploader input[type=file]").set_input_files(artifact)
        else:
            dialog.get_by_role("textbox", name="Share link", exact=True).fill(artifact)
        dialog.get_by_role("button", name="Import", exact=True).click()
        expect(dialog).to_have_count(0)
        combined = plays if kind == "playbook" else (*plays, *original.root.properties.custom_plays)
        ordered_names = [play.play_name for play in combined]
        expect(page.locator(".pb-play-button")).to_have_text(ordered_names)
        first = page.get_by_role("button", name=plays[0].play_name, exact=True)
        expect(first).to_have_attribute("aria-current", "true")
        last = page.get_by_role("button", name=plays[-1].play_name, exact=True)
        expect(last).to_be_visible()
        if kind == "playbook":
            expect(page.get_by_role("tab")).to_have_count(2)
            expect(page.get_by_role("button", name="Undo", exact=True)).to_be_disabled()
            page.get_by_role("tab", name=recipient_file.name, exact=True).click()
            expect(page.locator(".pb-play-button")).to_have_text(
                [play.play_name for play in original.root.properties.custom_plays]
            )
            page.get_by_role("tab").last.click()
            expect(page.locator(".pb-play-button")).to_have_text(ordered_names)
        else:
            page.get_by_role("button", name="Undo", exact=True).click()
            expect(last).to_have_count(0)
            expect(page.get_by_role("button", name="Undo", exact=True)).to_be_disabled()
            page.get_by_role("button", name="Redo", exact=True).click()
            expect(last).to_be_visible()
        with page.expect_download() as transfer:
            page.get_by_role("button", name="Download .sav", exact=True).click()
        transfer.value.save_as(downloaded)

    reopened = sav_to_playbook(downloaded.read_bytes())
    assert reopened == _with_plays(original, combined)


@pytest.mark.parametrize("as_file", [False, True], ids=["v1-link", "v1-file"])
def test_quickshare_round_trip_with_v1_block(
    browser: "Browser", recipient_file: Path, tmp_path: Path, as_file: bool
) -> None:
    from playwright.sync_api import expect

    link: str = _SHARE_URL + "#v1/" + _V1_BLOCK_FRAGMENT
    artifact: str | Path = link
    if as_file:
        artifact = tmp_path / "legacy.gridironshare"
        _ = artifact.write_bytes(urlsafe_b64decode(_V1_BLOCK_FRAGMENT + "=" * (-len(_V1_BLOCK_FRAGMENT) % 4)))
    with browser.new_context() as spectator:
        page = spectator.new_page()
        _ = page.goto(_SHARE_URL if isinstance(artifact, Path) else artifact)
        if isinstance(artifact, Path):
            page.locator("input[type=file]").set_input_files(artifact)
        expect(page.get_by_role("heading", name="Legacy bar")).to_be_visible()
        expect(page.get_by_test_id("preview-yardage")).to_have_text("1 yd")
        expect(page.locator('[data-route-index="0"] polyline[marker-end]')).to_have_count(0)
    _check_import(browser, artifact, recipient_file, decode_link(link).plays, tmp_path / "legacy-import.sav")


def test_decode_share_with_exact_block_vectors(browser: "Browser") -> None:
    anchor = GridironPoint(X_0=20.125, Y_0=-13.25, Z_0=-0.0)
    before = GridironPoint(X_0=17.125, Y_0=-17.25, Z_0=2.0)
    after = GridironPoint(X_0=-28.875, Y_0=90.125, Z_0=0.0)
    incoming = block_waypoints((before, anchor), 1, None)
    outgoing = block_waypoints((anchor, after), 0, None)
    routes = (
        GridironRoute(Slot_0=2, Points_0=(before, anchor, *incoming)),
        GridironRoute(Slot_0=4, Points_0=(anchor, *outgoing, after)),
    )
    play = GridironPlay(FormationName_0="Custom", PlayName_0="Two directions", Routes_0=routes)
    data: bytes = encode_share(ShareSnapshot(version=1, kind="play", plays=(play,)))
    assert len(decompress(data)) < 16 * len(incoming)
    expected: str = b"".join(pack("<ddd", p.x, p.y, p.z) for route in routes for p in route.points).hex()
    with browser.new_context() as spectator:
        page = spectator.new_page()
        _ = page.goto(_SHARE_URL)
        assert (
            page.evaluate(
                """async hex => {
                const {decodeShare} = await import(new URL('decode.js', document.baseURI).href);
                const bytes = Uint8Array.from(hex.match(/../g), pair => parseInt(pair, 16));
                const share = await decodeShare(bytes);
                const points = share.plays[0].routes.flatMap(route => route.points);
                const bits = new DataView(new ArrayBuffer(points.length * 24));
                points.forEach((p, i) => [p.x, p.y, p.z].forEach((v, j) => bits.setFloat64(i*24+j*8, v, true)));
                return Array.from(new Uint8Array(bits.buffer), b => b.toString(16).padStart(2, '0')).join('');
            }""",
                data.hex(),
            )
            == expected
        )


def test_copy_link_with_standard_discord_warning(browser: "Browser", custom_plays_json: str, tmp_path: Path) -> None:
    source = json_to_playbook(custom_plays_json)
    points = tuple(GridironPoint(X_0=400 * sin(i), Y_0=300 * cos(i), Z_0=0.0) for i in range(135))
    route = GridironRoute(Slot_0=0, Points_0=points)
    play = source.root.properties.custom_plays[0].model_copy(update={"routes": (route,)})
    snapshot = ShareSnapshot(version=1, kind="play", plays=(play,))
    url = make_link(_SHARE_URL, encode_share(snapshot))
    assert 2000 < len(url) <= 4000
    path: Path = tmp_path / "standard-warning.sav"
    _ = path.write_bytes(playbook_to_sav(_with_plays(source, (play,))))
    with browser.new_context(permissions=["clipboard-read", "clipboard-write"]) as sender:
        page = sender.new_page()
        _ = page.goto(_EDITOR_URL)
        page.locator("input[type=file]").set_input_files(path)
        page.get_by_role("button", name="Share play", exact=True).click()
        _check_length(page, url)
        _check_copy_link(page, url, "Discord message limit exceeded")


def test_import_link_exceeding_socket_message_limit(browser: "Browser", recipient_file: Path) -> None:
    from playwright.sync_api import expect

    original = sav_to_playbook(recipient_file.read_bytes()).root.properties.custom_plays[0]
    plays: list["GridironPlay"] = []
    for index in range(4):
        points = tuple(
            GridironPoint(X_0=400 * sin(i), Y_0=300 * cos(i), Z_0=0)
            for i in range(index * 16_000, (index + 1) * 16_000)
        )
        route = GridironRoute(Slot_0=0, Points_0=points)
        plays.append(original.model_copy(update={"routes": (route,), "play_name": f"Long-link play {index + 1}"}))
    snapshot = ShareSnapshot(version=1, kind="playbook", plays=tuple(plays))
    link = make_link(_SHARE_URL, encode_share(snapshot))
    assert len(link) > 1_000_000
    with browser.new_context(permissions=["clipboard-read", "clipboard-write"]) as recipient:
        page = recipient.new_page()
        _ = page.goto(_EDITOR_URL)
        page.locator("input[type=file]").set_input_files(recipient_file)
        page.get_by_role("button", name="Import share", exact=True).click()
        dialog = page.get_by_role("dialog")
        assert page.evaluate("link => navigator.clipboard.writeText(link)", link) is None
        dialog.get_by_role("textbox", name="Share link", exact=True).press("ControlOrMeta+v")
        dialog.get_by_role("button", name="Import", exact=True).click()
        imported = page.get_by_role("button", name="Long-link play 4", exact=True)
        expect(imported).to_be_visible(timeout=30_000)
        expect(page.get_by_role("tab")).to_have_count(2)
        page.get_by_role("tab", name=recipient_file.name, exact=True).click()
        expect(imported).to_have_count(0)
        expect(page.locator(".pb-play-button").first).to_have_text(original.play_name)
