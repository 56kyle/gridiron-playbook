"""Module containing game playbook confirmations for the gridiron_playbook package."""

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import ClassVar
from typing import Literal

from nicegui import ui
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import ValidationError

from gridiron_playbook.constants import USER_CACHE_FOLDER
from gridiron_playbook.game import get_gridiron_playbook_path
from gridiron_playbook.game_playbook import GAME_PLAYBOOK_BACKUP_DIRECTORY
from gridiron_playbook.game_playbook import GamePlaybookError
from gridiron_playbook.game_playbook import GamePlaybookReplacementError
from gridiron_playbook.game_playbook import GamePlaybookStore
from gridiron_playbook.game_playbook import PreparedGamePlaybook
from gridiron_playbook.playbook import GridironPlaybook


class GamePlaybookLocationError(ValueError):
    """A game save location must be selected before preparing a change."""


class _LocationSettings(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1]
    save_path: Path


@dataclass(frozen=True)
class _GameTarget:
    save_path: Path
    legacy_backup_directory: Path | None = None


def _resolved_location(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise GamePlaybookLocationError("Could not resolve the selected path. Choose an existing location.") from error


def _backup_directory() -> Path:
    configured: str | None = os.environ.get("GRIDIRON_GAME_BACKUP_DIRECTORY")
    return _resolved_location(Path(configured) if configured else GAME_PLAYBOOK_BACKUP_DIRECTORY)


def _remembered_game_target(save_path: Path) -> _GameTarget:
    try:
        automatic: Path = get_gridiron_playbook_path().resolve()
        remembered: Path = save_path.resolve()
    except (OSError, KeyError, RuntimeError, ValueError):
        return _GameTarget(save_path)
    if remembered == automatic:
        return _GameTarget(remembered, USER_CACHE_FOLDER)
    return _GameTarget(remembered)


def _preferred_game_target(backup_directory: Path) -> _GameTarget:
    configured: str | None = os.environ.get("GRIDIRON_GAME_SAVE_PATH")
    if configured:
        return _GameTarget(_resolved_location(Path(configured)))
    settings_path: Path = backup_directory / "settings.json"
    try:
        if settings_path.exists():
            settings = _LocationSettings.model_validate_json(settings_path.read_bytes())
            if not settings.save_path.is_absolute():
                raise GamePlaybookLocationError("Choose the full path to your game save.")
            return _remembered_game_target(settings.save_path)
        return _GameTarget(_resolved_location(get_gridiron_playbook_path()), USER_CACHE_FOLDER)
    except (OSError, KeyError, RuntimeError, ValidationError) as error:
        raise GamePlaybookLocationError("Could not locate your game save. Choose its .sav file.") from error


def _remember_game_path(save_path: Path, backup_directory: Path) -> None:
    settings = _LocationSettings(version=1, save_path=save_path)
    backup_directory.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=backup_directory, suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            _ = stream.write(settings.model_dump_json())
            stream.flush()
            os.fsync(stream.fileno())
        _ = temporary.replace(backup_directory / "settings.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class _ConfirmationControls:
    closed: ui.checkbox
    apply: ui.button
    cancel: ui.button
    change: ui.button


class _GamePlaybookDialog(ui.dialog):
    def __init__(
        self,
        title: str,
        action_label: str,
        prepare: Callable[[GamePlaybookStore], PreparedGamePlaybook],
        is_current: Callable[[], bool],
        success_message: str,
    ) -> None:
        super().__init__()
        _ = self.props("persistent")
        self._prepare: Callable[[GamePlaybookStore], PreparedGamePlaybook] = prepare
        self._is_current: Callable[[], bool] = is_current
        self._action_label: str = action_label
        self._success_message: str = success_message
        self._backup_directory: Path = _backup_directory()
        self._prepared: tuple[GamePlaybookStore, PreparedGamePlaybook] | None = None
        self._confirmation: _ConfirmationControls | None = None
        self._request: int = 0
        self._busy: bool = False
        with self, ui.card().classes("pb-dialog"):
            _ = ui.label(title).classes("pb-heading")
            self._content: ui.column = ui.column().classes("w-full gap-3")
        _ = self.on("hide", self.delete)
        self._loading()
        _ = self.open()
        with self:
            _ = ui.timer(0, self._discover, once=True)

    def _active(self) -> bool:
        if self.is_deleted or not self.value:
            return False
        if not self._is_current():
            _ = self.close()
            return False
        return True

    def _loading(self) -> None:
        self._confirmation = None
        _ = self._content.clear()
        with self._content:
            _ = ui.spinner()
            _ = ui.button("Cancel", on_click=self._cancel).props("flat no-caps")

    def _cancel(self) -> None:
        if not self._busy or self._confirmation is None:
            _ = self.close()

    async def _discover(self) -> None:
        if not self._active():
            return
        try:
            target = await asyncio.to_thread(_preferred_game_target, self._backup_directory)
        except (OSError, ValueError) as error:
            if self._active():
                self._choose_path("", str(error))
            return
        await self._review(target)

    def _choose_path(self, value: str, problem: str = "") -> None:
        if not self._active() or self._busy:
            return
        self._request += 1
        self._prepared = None
        self._confirmation = None
        _ = self._content.clear()
        with self._content:
            if problem:
                _ = ui.label(problem).classes("text-negative break-all")
            location: ui.input = ui.input("Game save", value=value).classes("w-full").mark("game-save-path")

            async def review() -> None:
                candidate: str = (location.value or "").strip().strip('"')
                if not candidate:
                    ui.notify("Choose your game save's .sav file.", type="warning")
                    return
                try:
                    selected: Path = _resolved_location(Path(candidate))
                except GamePlaybookLocationError as error:
                    ui.notify(str(error), type="negative")
                    return
                await self._review(_GameTarget(selected))

            with ui.row().classes("pb-actions"):
                _ = ui.button("Cancel", on_click=self._cancel).props("flat no-caps")
                _ = ui.button("Review", on_click=review).props("unelevated no-caps").mark("game-review")

    def _prepare_target(self, target: _GameTarget) -> tuple[GamePlaybookStore, PreparedGamePlaybook]:
        store = GamePlaybookStore(
            target.save_path, self._backup_directory, legacy_backup_directory=target.legacy_backup_directory
        )
        return store, self._prepare(store)

    async def _review(self, target: _GameTarget) -> None:
        if not self._active() or self._busy:
            return
        self._busy = True
        self._request += 1
        request: int = self._request
        self._loading()
        try:
            prepared = await asyncio.to_thread(self._prepare_target, target)
        except (GamePlaybookError, OSError, ValueError) as error:
            self._busy = False
            if request == self._request and self._active():
                self._choose_path(str(target.save_path), str(error))
            return
        self._busy = False
        if request == self._request and self._active():
            self._prepared = prepared
            self._confirm(prepared[1])

    def _confirm(self, prepared: PreparedGamePlaybook) -> None:
        _ = self._content.clear()
        with self._content:
            _ = ui.label(str(prepared.save_path)).classes("font-mono text-xs break-all").mark("game-target")
            change = ui.button("Change file", on_click=lambda: self._choose_path(str(prepared.save_path))).props(
                "flat no-caps dense"
            )
            if prepared.restore_backup is not None:
                date: str = prepared.restore_backup.created_at.astimezone().strftime("%b %d, %Y at %H:%M")
                _ = ui.label(f"Backup from {date}")
                _ = (
                    ui.label(str(prepared.restore_backup.path))
                    .classes("font-mono text-xs break-all")
                    .mark("game-backup")
                )
            _ = ui.label("Your current game playbook will be backed up.")
            closed = ui.checkbox("Gridiron is closed").mark("game-closed")
            with ui.row().classes("pb-actions"):
                cancel = ui.button("Cancel", on_click=self._cancel).props("flat no-caps")
                apply = (
                    ui.button(self._action_label, on_click=self._apply)
                    .props("unelevated no-caps")
                    .set_enabled(False)
                    .mark("game-apply")
                )
            _ = closed.on_value_change(lambda event: apply.set_enabled(bool(event.value) and not self._busy))
            self._confirmation = _ConfirmationControls(closed, apply, cancel, change)

    async def _apply(self) -> None:
        controls = self._confirmation
        if self._busy or self._prepared is None or controls is None or not controls.closed.value or not self._active():
            return
        store, prepared = self._prepared
        self._busy = True
        for control in (controls.closed, controls.apply, controls.cancel, controls.change):
            _ = control.disable()
        try:
            result = await asyncio.to_thread(store.apply, prepared)
        except (GamePlaybookError, OSError, ValueError) as error:
            self._busy = False
            if self._active():
                problem: str = str(error)
                if isinstance(error, GamePlaybookReplacementError):
                    problem = f"{problem} Backup: {error.backup_path}"
                self._choose_path(str(prepared.save_path), problem)
            return
        try:
            await asyncio.to_thread(_remember_game_path, result.save_path, self._backup_directory)
        except OSError:
            ui.notify("The game save is ready, but its location could not be remembered.", type="warning")
        ui.notify(self._success_message if result.changed else "This playbook is already in game.", type="positive")
        self._busy = False
        if not self.is_deleted:
            _ = self.close()


def install_game_dialog(document: GridironPlaybook, filename: str, is_current: Callable[[], bool]) -> ui.dialog:
    """Review and confirm installing a captured editor document in the game."""
    return _GamePlaybookDialog(
        f"Use {filename} in game",
        "Use in game",
        lambda store: store.prepare_install(document),
        is_current,
        "Playbook is ready to use in Gridiron.",
    )


def restore_game_dialog(is_current: Callable[[], bool]) -> ui.dialog:
    """Review and confirm restoring the previous game playbook without an editor tab."""
    return _GamePlaybookDialog(
        "Restore previous playbook",
        "Restore previous playbook",
        GamePlaybookStore.prepare_restore,
        is_current,
        "Previous game playbook restored.",
    )
