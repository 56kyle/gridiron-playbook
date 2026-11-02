from __future__ import annotations

import asyncio
from importlib.util import find_spec
from typing import TYPE_CHECKING

import pytest
from typing_extensions import override


if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from nicegui.testing import User


if find_spec("nicegui") is None:
    pytest.skip("Install the web extra to exercise NiceGUI page interactions.", allow_module_level=True)
pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]


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
        await _upload(first, "first-tab.json", custom_plays_json.encode())
        await first.should_see("first-tab.json")

        second: testing.User = testing.User(first.http_client)
        _ = await second.open("/")
        await second.should_see("Open your playbook")
        await second.should_not_see("first-tab.json")
        await first.should_see("first-tab.json")


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
