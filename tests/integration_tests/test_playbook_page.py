from __future__ import annotations

import asyncio
from importlib.util import find_spec
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from typing_extensions import override


if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path

    from nicegui.testing import User


if find_spec("nicegui") is None:
    pytest.skip("Install the web extra to exercise NiceGUI page interactions.", allow_module_level=True)
pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]


@pytest.fixture(autouse=True)
def working_copy_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GRIDIRON_WORKING_COPY_PATH", str(tmp_path / "working.sqlite3"))


async def _initialize_recovery(user: User) -> None:
    from gridiron_playbook.web.recovery import RecoveryBridge

    _ = user.find(RecoveryBridge).trigger("ready", {"workspace_id": uuid4().hex, "source_id": None})
    await user.should_see("Open your playbook")


def _simulate_editor() -> AbstractAsyncContextManager[User]:
    # NiceGUI leaves the optional main_file parameter partly untyped; we supply only a page builder.
    from nicegui.testing import user_simulation  # pyright: ignore[reportUnknownVariableType]

    from gridiron_playbook.web.playbook_page import playbook_page

    return user_simulation(playbook_page)


async def _upload(user: User, name: str, data: bytes) -> None:
    from nicegui import ui

    (uploader,) = user.find(ui.upload).elements
    await uploader.handle_uploads([ui.upload.SmallFileUpload(name, "application/json", data)])


async def test_playbook_page_with_invalid_replacement(custom_plays_json: str) -> None:
    async with _simulate_editor() as user:
        _ = await user.open("/")
        await _initialize_recovery(user)
        await _upload(user, "original.json", custom_plays_json.encode())
        await user.should_see("original.json")
        _ = user.find("Open playbook").click()
        await _upload(user, "broken.json", b"{")
        await user.should_see("Could not open playbook")
        _ = user.find("Cancel").click()
        await user.should_see("original.json")
        await user.should_see("Download .sav")


async def test_playbook_page_with_separate_tabs(custom_plays_json: str) -> None:
    from nicegui import testing

    async with _simulate_editor() as first:
        _ = await first.open("/")
        await _initialize_recovery(first)
        await _upload(first, "first-tab.json", custom_plays_json.encode())
        await first.should_see("first-tab.json")

        second: testing.User = testing.User(first.http_client)
        _ = await second.open("/")
        await _initialize_recovery(second)
        await second.should_see("Open your playbook")
        await second.should_not_see("first-tab.json")
        await first.should_see("first-tab.json")


async def test_playbook_page_with_custom_formation_and_slot(custom_plays_json: str) -> None:
    from nicegui import ui

    from gridiron_playbook.web.play_diagram import PlayDiagram

    async with _simulate_editor() as user:
        _ = await user.open("/")
        await _initialize_recovery(user)
        await _upload(user, "original.json", custom_plays_json.encode())
        await user.should_see("original.json")
        _ = user.find(marker="new-play").click()
        _ = user.find(kind=ui.input, content="Formation").type("Custom spread")
        _ = user.find(kind=ui.input, content="Play name").type("Flat")
        _ = user.find("Create play").click()
        await user.should_see("Custom spread")

        _ = user.find("Draw route").click()
        _ = user.find("Custom slot").click()
        _ = user.find(kind=ui.input, content="Player slot").type("255")
        _ = user.find("Start drawing").click()
        _ = user.find(PlayDiagram).trigger("route_finish", {"points": [{"x": 100, "y": 200}, {"x": 140, "y": 240}]})

        await user.should_see(kind=ui.label, content="Slot 255")


@pytest.mark.parametrize("cancel", [True, False], ids=["cancelled", "superseded"])
async def test_playbook_page_with_obsolete_upload(custom_plays_json: str, cancel: bool) -> None:
    from nicegui import ui
    from nicegui.elements.upload_files import SmallFileUpload

    started: asyncio.Event = asyncio.Event()
    release: asyncio.Event = asyncio.Event()
    settled: asyncio.Event = asyncio.Event()

    class PausedUpload(SmallFileUpload):
        @override
        async def read(self) -> bytes:
            handler: asyncio.Future[object] | None = asyncio.current_task()
            assert handler is not None
            handler.add_done_callback(lambda _: settled.set())
            started.set()
            _ = await release.wait()
            return await super().read()

    data: bytes = custom_plays_json.encode()
    async with _simulate_editor() as user:
        _ = await user.open("/")
        await _initialize_recovery(user)
        await _upload(user, "opened.json", data)
        await user.should_see("opened.json")
        _ = user.find("Open playbook").click()
        (chooser,) = user.find(ui.upload).elements
        await chooser.handle_uploads([PausedUpload("late.json", "application/json", data)])
        try:
            _ = await asyncio.wait_for(started.wait(), timeout=5)
            if cancel:
                _ = user.find("Cancel").click()
            else:
                await _upload(user, "latest.json", data)
                await user.should_see("latest.json")
        finally:
            release.set()
            _ = await asyncio.wait_for(settled.wait(), timeout=5)

        await user.should_see("opened.json" if cancel else "latest.json")
        await user.should_not_see("late.json")
