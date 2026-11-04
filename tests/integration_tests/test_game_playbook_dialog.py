"""Game-save confirmation dialogs use isolated real saves and archives."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from importlib.util import find_spec
from typing import TYPE_CHECKING

import pytest

from gridiron_playbook.editor import PlaybookEditor
from gridiron_playbook.game_playbook import GamePlaybookStore
from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.playbook import playbook_to_sav
from gridiron_playbook.playbook import sav_to_playbook


if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path

    from nicegui.testing import User


if find_spec("nicegui") is None:
    pytest.skip("Install the web extra to test game-save confirmations.", allow_module_level=True)

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]


@dataclass(frozen=True)
class GameFiles:
    target: Path
    backups: Path
    original: bytes
    replacement: GridironPlaybook


@pytest.fixture
def game_files(tmp_path: Path, custom_plays_json: str, monkeypatch: pytest.MonkeyPatch) -> GameFiles:
    original = GridironPlaybook.model_validate_json(custom_plays_json)
    editor = PlaybookEditor(original)
    editor.rename_play(0, "Chosen in editor")
    target = tmp_path / "GridironCustomPlays.sav"
    contents = playbook_to_sav(original)
    _ = target.write_bytes(contents)
    backups = tmp_path / "backups"
    monkeypatch.setenv("GRIDIRON_GAME_SAVE_PATH", str(target))
    monkeypatch.setenv("GRIDIRON_GAME_BACKUP_DIRECTORY", str(backups))
    monkeypatch.setenv("GRIDIRON_WORKING_COPY_PATH", str(tmp_path / "working.sqlite3"))
    return GameFiles(target, backups, contents, editor.playbook)


def _simulate_dialogs(files: GameFiles, is_current: Callable[[], bool]) -> AbstractAsyncContextManager[User]:
    from nicegui import ui
    from nicegui.testing import user_simulation  # pyright: ignore[reportUnknownVariableType]

    from gridiron_playbook.web.game_playbook_dialog import install_game_dialog
    from gridiron_playbook.web.game_playbook_dialog import restore_game_dialog

    def page() -> None:
        _ = ui.button("Open install", on_click=lambda: install_game_dialog(files.replacement, "Chosen.sav", is_current))
        _ = ui.button("Open restore", on_click=lambda: restore_game_dialog(is_current))

    return user_simulation(page)


async def test_install_game_dialog_with_confirmation(game_files: GameFiles) -> None:
    from nicegui import ui

    async with _simulate_dialogs(game_files, lambda: True) as user:
        _ = await user.open("/")
        _ = user.find("Open install").click()
        await user.should_see(marker="game-apply")
        (apply,) = user.find(marker="game-apply").elements
        assert isinstance(apply, ui.button)
        assert not apply.enabled
        assert game_files.target.read_bytes() == game_files.original
        assert not game_files.backups.exists()
        _ = user.find(marker="game-closed").click()
        _ = user.find(marker="game-apply").click()
        await user.should_see("Playbook is ready to use in Gridiron.")
        assert game_files.target.read_bytes() == playbook_to_sav(game_files.replacement)
        assert [path.read_bytes() for path in game_files.backups.rglob("*.sav")] == [game_files.original]


async def test_install_game_dialog_with_cancel(game_files: GameFiles) -> None:
    from nicegui import ui

    async with _simulate_dialogs(game_files, lambda: True) as user:
        _ = await user.open("/")
        _ = user.find("Open install").click()
        await user.should_see(marker="game-apply")
        (dialog,) = user.find(ui.dialog).elements
        assert isinstance(dialog, ui.dialog)
        _ = user.find("Cancel").click()
        assert not dialog.value
        assert game_files.target.read_bytes() == game_files.original
        assert not game_files.backups.exists()


async def test_install_game_dialog_with_stale_editor(game_files: GameFiles) -> None:
    from nicegui import ui

    current = [True]
    checked = asyncio.Event()

    def is_current() -> bool:
        if not current[0]:
            checked.set()
        return current[0]

    async with _simulate_dialogs(game_files, is_current) as user:
        _ = await user.open("/")
        _ = user.find("Open install").click()
        await user.should_see(marker="game-apply")
        (dialog,) = user.find(ui.dialog).elements
        assert isinstance(dialog, ui.dialog)
        current[0] = False
        _ = user.find(marker="game-closed").click()
        _ = user.find(marker="game-apply").click()
        _ = await asyncio.wait_for(checked.wait(), timeout=5)
        assert not dialog.value
        assert game_files.target.read_bytes() == game_files.original
        assert not game_files.backups.exists()


async def test_install_game_dialog_with_changed_game_save(game_files: GameFiles) -> None:
    async with _simulate_dialogs(game_files, lambda: True) as user:
        _ = await user.open("/")
        _ = user.find("Open install").click()
        await user.should_see(marker="game-apply")
        _ = game_files.target.write_bytes(b"newer game save")
        _ = user.find(marker="game-closed").click()
        _ = user.find(marker="game-apply").click()
        await user.should_see(marker="game-save-path")
        assert game_files.target.read_bytes() == b"newer game save"
        assert not list(game_files.backups.rglob("*.sav"))


async def test_install_game_dialog_with_manual_location(game_files: GameFiles, monkeypatch: pytest.MonkeyPatch) -> None:
    from nicegui import ui

    monkeypatch.setenv("GRIDIRON_GAME_SAVE_PATH", str(game_files.target.with_name("missing.sav")))
    async with _simulate_dialogs(game_files, lambda: True) as user:
        _ = await user.open("/")
        _ = user.find("Open install").click()
        await user.should_see(marker="game-save-path")
        (location,) = user.find(marker="game-save-path").elements
        assert isinstance(location, ui.input)
        location.value = str(game_files.target)
        _ = user.find(marker="game-review").click()
        await user.should_see(marker="game-apply")
        _ = user.find(marker="game-closed").click()
        _ = user.find(marker="game-apply").click()
        await user.should_see("Playbook is ready to use in Gridiron.")
        assert game_files.target.read_bytes() == playbook_to_sav(game_files.replacement)
        assert (game_files.backups / "settings.json").exists()


async def test_restore_game_dialog_with_no_open_playbook(game_files: GameFiles) -> None:
    store = GamePlaybookStore(game_files.target, game_files.backups)
    _ = store.apply(store.prepare_install(game_files.replacement))
    async with _simulate_dialogs(game_files, lambda: True) as user:
        _ = await user.open("/")
        _ = user.find("Open restore").click()
        await user.should_see(marker="game-apply")
        _ = user.find(marker="game-closed").click()
        _ = user.find(marker="game-apply").click()
        await user.should_see("Previous game playbook restored.")
        assert game_files.target.read_bytes() == game_files.original
        assert store.prepare_restore().replacement == playbook_to_sav(game_files.replacement)


async def test_restore_game_dialog_with_remembered_automatic_target(
    game_files: GameFiles,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gridiron_playbook.web import game_playbook_dialog

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    old_contents = playbook_to_sav(game_files.replacement)
    _ = (legacy / "2026-01-01_00-00-00.sav").write_bytes(old_contents)
    monkeypatch.delenv("GRIDIRON_GAME_SAVE_PATH")
    monkeypatch.setattr(game_playbook_dialog, "get_gridiron_playbook_path", lambda: game_files.target)
    monkeypatch.setattr(game_playbook_dialog, "USER_CACHE_FOLDER", legacy)
    unchanged = GameFiles(
        game_files.target,
        game_files.backups,
        game_files.original,
        sav_to_playbook(game_files.original),
    )
    async with _simulate_dialogs(unchanged, lambda: True) as user:
        _ = await user.open("/")
        _ = user.find("Open install").click()
        await user.should_see(marker="game-apply")
        _ = user.find(marker="game-closed").click()
        _ = user.find(marker="game-apply").click()
        await user.should_see("This playbook is already in game.")
    async with _simulate_dialogs(unchanged, lambda: True) as reopened:
        _ = await reopened.open("/")
        _ = reopened.find("Open restore").click()
        await reopened.should_see(marker="game-apply")
        _ = reopened.find(marker="game-closed").click()
        _ = reopened.find(marker="game-apply").click()
        await reopened.should_see("Previous game playbook restored.")
        assert game_files.target.read_bytes() == old_contents
