"""NiceGUI page for opening, editing, and downloading a playbook."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from functools import partial
from html import escape
from itertools import groupby
from pathlib import Path
from typing import ClassVar
from typing import Literal
from typing import Protocol

from nicegui import events
from nicegui import ui
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import ValidationError

from gridiron_playbook.block import route_yards_without_blocks
from gridiron_playbook.editor import PlaybookEditor
from gridiron_playbook.formations import FORMATION_NAMES
from gridiron_playbook.formations import formation_starts
from gridiron_playbook.formations import observed_route_slots
from gridiron_playbook.formations import position_label
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.playbook import playbook_to_sav
from gridiron_playbook.point import GridironPoint
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.route import GridironRoute
from gridiron_playbook.web.play_diagram import FieldTransform
from gridiron_playbook.web.play_diagram import PlayDiagram
from gridiron_playbook.web.play_diagram import RouteNodeActions
from gridiron_playbook.web.playbook_files import MAX_SAVE_BYTES
from gridiron_playbook.web.playbook_files import decode_uploaded_playbook
from gridiron_playbook.web.playbook_files import validate_upload_size
from gridiron_playbook.web.recovery import RecoveryBridge
from gridiron_playbook.web.recovery import RecoveryIdentity
from gridiron_playbook.web.recovery import RecoveryState
from gridiron_playbook.web.recovery import SavedDraft
from gridiron_playbook.web.recovery import SavedView
from gridiron_playbook.web.recovery import WorkingRecovery
from gridiron_playbook.web.recovery import working_copy_store
from gridiron_playbook.web.share_dialog import import_dialog
from gridiron_playbook.web.share_dialog import publish_dialog
from gridiron_playbook.workspace import PlaybookWorkspace
from gridiron_playbook.workspace import document_with_plays


def playbook_page() -> None:
    """Build a private editor for this page instance."""
    ui.add_css(Path(__file__).with_name("editor.css").read_text(encoding="utf-8"))
    _PlaybookPage().render()


class _EditorWorkspace(ui.element, component="editor_workspace.js"):
    """Scope keyboard shortcuts to the open playbook."""


class _WorkspaceSurface(ui.element, component="workspace_surface.js"):
    """Route drag gestures between play lists and playbook tabs."""

    def set_context(self, generation: int, tab_id: str, selected: set[int], *, disabled: bool) -> None:
        self._props.update(generation=generation, activeTab=tab_id, selected=sorted(selected), disabled=disabled)
        self.update()


class _ControlEvent(Protocol):
    args: object


@dataclass
class _TabView:
    formation: str | None = None
    search: str = ""
    play_index: int = 0
    route_index: int | None = None
    selected: set[int] = field(default_factory=set)
    anchor: int | None = None


class _PlayClick(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(strict=True, frozen=True)
    shift: bool = False
    toggle: bool = False


class _PlayDrop(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(strict=True, frozen=True)
    generation: int
    source: str
    destination: str
    indices: list[int]
    insertion: int
    is_copy: bool


class _PlaybookPage:
    def __init__(self) -> None:
        self.books: PlaybookWorkspace = PlaybookWorkspace()
        self.views: dict[str, _TabView] = {}
        self.view: _TabView = _TabView()
        self.recovery: WorkingRecovery = WorkingRecovery(working_copy_store())
        self._recovery_ready: bool = False
        self._recovery_identity: RecoveryIdentity | None = None
        self._recovery_problem: str = ""
        self._browser_storage_failed: bool = False
        self._recovery_bridge: RecoveryBridge = RecoveryBridge()
        _ = self._recovery_bridge.on("ready", self._restore_working_copy)
        _ = self._recovery_bridge.on("unavailable", self._browser_storage_unavailable)
        _ = self._recovery_bridge.on("available", self._browser_storage_available)
        self.container: _WorkspaceSurface = _WorkspaceSurface().classes("pb-app")
        _ = self.container.on("drop_plays", self._drop_plays)
        self.draft_slot: int | None = None
        self.draft_points: tuple[GridironPoint, ...] = ()
        self.generation: int = 0
        self._file_chooser: ui.upload | None = None
        self._quickshare_dialog: ui.dialog | None = None

    @property
    def editor(self) -> PlaybookEditor | None:
        return self.books.active.editor if self.books.active is not None else None

    @property
    def filename(self) -> str:
        return self.books.active.filename if self.books.active is not None else ""

    def render(self, *, selected_point: int | None = None) -> None:
        """Replace the page controls and invalidate gestures from the old diagram."""
        if not self._recovery_ready:
            _ = self.container.clear()
            with self.container, ui.column().classes("pb-welcome"):
                if self._recovery_problem:
                    _ = ui.label(self._recovery_problem)
                    _ = ui.button("Retry recovery", on_click=self._retry_recovery).props("flat no-caps")
                    _ = ui.button("Start new workspace", on_click=self._start_new_workspace).props("unelevated no-caps")
                else:
                    _ = ui.spinner()
                    _ = ui.label("Restoring workspace")
            return
        self.books.checkpoint()
        active = self.books.active
        if active is not None:
            self.view = self.views.setdefault(active.id, _TabView())
            self.view.play_index = min(self.view.play_index, max(0, len(active.editor.plays) - 1))
            self.view.selected.intersection_update(range(len(active.editor.plays)))
        _ = self._persist_working_copy()
        self.generation += 1
        self.container.set_context(
            self.generation,
            active.id if active is not None else "",
            self.view.selected,
            disabled=self.draft_slot is not None,
        )
        self._file_chooser = None
        if self._quickshare_dialog is not None and not self._quickshare_dialog.is_deleted:
            _ = self._quickshare_dialog.close()
        self._quickshare_dialog = None
        _ = self.container.clear()
        with self.container:
            if self._recovery_problem:
                with ui.row().classes("w-full items-center p-3"):
                    _ = ui.icon("warning").classes("text-warning")
                    _ = ui.label(self._recovery_problem)
                    _ = ui.button("Retry saving", on_click=self.render).props("flat no-caps")
            with ui.element("header").classes("pb-header"):
                with ui.row().classes("pb-brand"):
                    _ = ui.icon("sports_football").classes("pb-brand-icon")
                    _ = ui.label("Gridiron").classes("pb-brand-name")
                if self.editor is not None:
                    with ui.row().classes("pb-actions").style("flex-wrap:wrap;max-width:100%"):
                        _ = ui.button("Open playbook", icon="folder_open", on_click=self._open_dialog).props(
                            "flat no-caps"
                        )
                        _ = (
                            ui.button(
                                "Import share", icon="add_link", on_click=partial(self._import_share, self.editor)
                            )
                            .props("flat no-caps")
                            .set_enabled(self.draft_slot is None)
                        )
                        _ = (
                            ui.button("Share playbook", icon="share", on_click=partial(self._publish, self.editor))
                            .props("flat no-caps")
                            .set_enabled(bool(self.editor.plays) and self.draft_slot is None)
                        )
                        _ = ui.button("Download .sav", icon="download", on_click=self._download).props(
                            "unelevated no-caps"
                        )
            if self.books.tabs:
                self._tabs()
            if self.editor is None:
                self._welcome()
            else:
                self._workspace(self.editor, selected_point)

    def _restore_working_copy(self, event: _ControlEvent) -> None:
        if self._recovery_ready:
            return
        try:
            identity = RecoveryIdentity.model_validate(event.args)
        except ValidationError:
            return
        self._restore_identity(identity)

    def _restore_identity(self, identity: RecoveryIdentity) -> None:
        self._recovery_identity = identity
        try:
            state = self.recovery.restore(identity)
            if state is not None:
                for tab in state.workspace.tabs:
                    for play in tab.document.root.properties.custom_plays:
                        _ = FieldTransform.for_play(play)
                    if tab.id == state.workspace.active_id and state.draft is not None:
                        view = state.views.get(tab.id, SavedView())
                        play = tab.document.root.properties.custom_plays[view.play_index]
                        draft_route = GridironRoute(Slot_0=state.draft.slot, Points_0=state.draft.points)
                        _ = FieldTransform.for_play(play.model_copy(update={"routes": (*play.routes, draft_route)}))
                self.books = PlaybookWorkspace.from_snapshot(state.workspace)
                self.views = {
                    tab_id: _TabView(
                        formation=view.formation,
                        search=view.search,
                        play_index=view.play_index,
                        route_index=view.route_index,
                        selected=set(view.selected),
                        anchor=view.anchor,
                    )
                    for tab_id, view in state.views.items()
                }
                self.draft_slot = state.draft.slot if state.draft is not None else None
                self.draft_points = state.draft.points if state.draft is not None else ()
            self._recovery_problem = ""
            self._recovery_ready = True
        except (OSError, ValueError) as error:
            self._recovery_problem = f"Could not restore the local working copy. {str(error)[:180]}"
            self._recovery_bridge.failed()
        self.render()

    def _retry_recovery(self) -> None:
        if self._recovery_identity is not None:
            self._restore_identity(self._recovery_identity)
        else:
            _ = self._recovery_bridge.run_method("initialize")

    def _start_new_workspace(self) -> None:
        self.recovery.start_new()
        self._recovery_problem = ""
        self._recovery_ready = True
        self.render()

    def _browser_storage_unavailable(self) -> None:
        problem = "Browser storage is unavailable. Keep this page open and download your playbooks."
        if self._browser_storage_failed:
            return
        self._browser_storage_failed = True
        self._recovery_problem = problem
        self._recovery_bridge.failed()
        self.render()

    def _browser_storage_available(self) -> None:
        if self._browser_storage_failed:
            self._browser_storage_failed = False
            self._recovery_problem = ""
            self.render()

    def _working_state(self) -> RecoveryState:
        views: dict[str, SavedView] = {}
        for tab in self.books.tabs:
            view = self.views.get(tab.id, _TabView())
            plays = tab.editor.plays
            play_index = min(view.play_index, max(0, len(plays) - 1))
            route_index = view.route_index
            if route_index is not None and (not plays or route_index >= len(plays[play_index].routes)):
                route_index = None
            views[tab.id] = SavedView(
                formation=view.formation,
                search=view.search,
                play_index=play_index,
                route_index=route_index,
                selected=tuple(sorted(index for index in view.selected if index < len(plays))),
                anchor=view.anchor,
            )
        draft = SavedDraft(slot=self.draft_slot, points=self.draft_points) if self.draft_slot is not None else None
        return RecoveryState(version=1, workspace=self.books.snapshot(), views=views, draft=draft)

    def _persist_working_copy(self) -> bool:
        if not self._recovery_ready:
            return False
        try:
            workspace_id = self.recovery.save(self._working_state())
            self._recovery_bridge.saved(workspace_id, self.recovery.revision)
            if self._browser_storage_failed:
                self._recovery_bridge.failed()
            else:
                self._recovery_problem = ""
            return not self._browser_storage_failed
        except (OSError, ValueError) as error:
            problem = f"Local working copy could not be saved. {str(error)[:180]}"
            if problem != self._recovery_problem:
                ui.notify(problem, type="negative")
            self._recovery_problem = problem
            self._recovery_bridge.failed()
            return False

    def _welcome(self) -> None:
        with ui.element("main").classes("pb-welcome"):
            _ = ui.icon("route").classes("pb-welcome-icon")
            _ = ui.label("Open your playbook").classes("pb-display")
            self._upload_control()

    def _can_leave_draft(self) -> bool:
        if self.draft_slot is None:
            return True
        ui.notify("Finish or cancel the route first.", type="warning")
        return False

    def _unique_filename(self, filename: str, excluding: str | None = None) -> str:
        existing = {tab.filename for tab in self.books.tabs if tab.id != excluding}
        path = Path(filename)
        candidate = filename
        suffix = 2
        while candidate in existing:
            candidate = f"{path.stem} ({suffix}){path.suffix}"
            suffix += 1
        return candidate

    def _tabs(self) -> None:
        with ui.row().classes("pb-tabbar").props('role="tablist" aria-label="Playbooks"'):
            for tab in self.books.tabs:
                selected = tab is self.books.active
                with ui.row().classes("pb-tab-shell").props(f'data-tab-id="{tab.id}"'):
                    button = (
                        ui.button(tab.filename, on_click=partial(self._activate, tab.id))
                        .props(f'flat no-caps role="tab" aria-selected="{str(selected).lower()}"')
                        .classes("pb-tab")
                    )
                    if selected:
                        _ = button.classes("pb-tab-active")
                    if tab.dirty:
                        _ = ui.icon("circle").classes("pb-dirty").props('aria-label="Unsaved changes"')
                    with (
                        ui.button(icon="more_horiz").props(
                            f'flat round dense aria-label="Playbook actions for {escape(tab.filename, quote=True)}"'
                        ),
                        ui.menu(),
                    ):
                        _ = ui.menu_item("Rename playbook", on_click=partial(self._rename_book_dialog, tab.id)).props(
                            'role="menuitem"'
                        )
                        with (
                            ui.menu_item("Merge into", auto_close=False)
                            .props('role="menuitem" aria-label="Merge into"')
                            .set_enabled(len(self.books.tabs) > 1 and bool(tab.editor.plays)),
                            ui.menu().props('anchor="top end" self="top start"'),
                        ):
                            for destination in self.books.tabs:
                                if destination.id != tab.id:
                                    _ = ui.menu_item(
                                        destination.filename,
                                        on_click=partial(
                                            self._transfer,
                                            tab.id,
                                            tuple(range(len(tab.editor.plays))),
                                            destination.id,
                                            "copy",
                                        ),
                                    ).props('role="menuitem"')
                    _ = ui.button(icon="close", on_click=partial(self._close_book, tab.id)).props(
                        f'flat round dense aria-label="Close {escape(tab.filename, quote=True)}"'
                    )
            _ = (
                ui.button(icon="add", on_click=self._new_book_dialog)
                .props('flat round dense aria-label="New playbook"')
                .tooltip("New playbook")
            )

    def _activate(self, tab_id: str) -> None:
        if not self._can_leave_draft():
            return
        self.books.activate(tab_id)
        self.render()

    def _new_book_dialog(self) -> None:
        editor = self.editor
        if editor is None or not self._can_leave_draft():
            return
        with ui.dialog() as dialog, ui.card().classes("pb-dialog"):
            _ = ui.label("New playbook").classes("pb-heading")
            name = ui.input("Playbook name", value="Untitled.sav").classes("w-full")

            def create() -> None:
                filename = (name.value or "").strip()
                if not filename:
                    raise ValueError("Enter a playbook name.")
                _ = self.books.add(document_with_plays(editor.playbook, ()), self._unique_filename(filename))
                self.render()

            self._dialog_actions(dialog, "Create playbook", create)
        _ = dialog.open()

    def _rename_book_dialog(self, tab_id: str) -> None:
        if not self._can_leave_draft():
            return
        tab = self.books.get_tab(tab_id)
        with ui.dialog() as dialog, ui.card().classes("pb-dialog"):
            _ = ui.label("Rename playbook").classes("pb-heading")
            name = ui.input("Playbook name", value=tab.filename).classes("w-full")

            def rename() -> None:
                filename = (name.value or "").strip()
                if not filename:
                    raise ValueError("Enter a playbook name.")
                tab.filename = self._unique_filename(filename, tab_id)
                self.render()

            self._dialog_actions(dialog, "Rename playbook", rename)
        _ = dialog.open()

    def _close_book(self, tab_id: str) -> None:
        if not self._can_leave_draft():
            return
        tab = self.books.get_tab(tab_id)

        def close() -> None:
            self.books.close(tab_id)
            self.render()

        if not tab.dirty:
            close()
            return
        with ui.dialog() as dialog, ui.card().classes("pb-dialog"):
            _ = ui.label(f"Close {tab.filename}?").classes("pb-heading")
            generation = self.generation

            async def download_and_close() -> None:
                document = tab.editor.playbook
                if (
                    await self._download_tab(tab_id)
                    and self.generation == generation
                    and not dialog.is_deleted
                    and dialog.value
                    and tab.editor.playbook is document
                ):
                    _ = dialog.close()
                    close()

            _ = ui.button("Download and close", icon="download", on_click=download_and_close).props(
                "unelevated no-caps"
            )
            self._dialog_actions(dialog, "Close without downloading", close)
        _ = dialog.open()

    def _open_dialog(self) -> None:
        if not self._can_leave_draft():
            return
        with ui.dialog() as dialog, ui.card().classes("pb-dialog"):
            _ = ui.label("Open playbook").classes("pb-heading")
            self._upload_control(dialog)
            _ = ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
        _ = dialog.on("hide", dialog.delete)
        _ = dialog.open()

    def _upload_control(self, dialog: ui.dialog | None = None) -> None:
        latest_request: int = 0

        def chooser_is_open() -> bool:
            return self._file_chooser is chooser and not chooser.is_deleted and (dialog is None or dialog.value)

        async def open_file(event: events.UploadEventArguments) -> None:
            nonlocal latest_request
            if not chooser_is_open():
                return
            latest_request += 1
            request: int = latest_request
            try:
                name: str = Path(event.file.name).name
                validate_upload_size(name, event.file.size())
                data: bytes = await event.file.read()
                if request != latest_request or not chooser_is_open():
                    return
                document: GridironPlaybook = await asyncio.to_thread(decode_uploaded_playbook, name, data)
            except (ValueError, OSError) as error:
                if request == latest_request and chooser_is_open():
                    _ = chooser.reset()
                    ui.notify(f"Could not open playbook. {str(error)[:250]}", type="negative")
                return
            if request != latest_request or not chooser_is_open():
                return
            tab = self.books.add(document, self._unique_filename(name))
            self.view = self.views.setdefault(tab.id, _TabView())
            if dialog is not None:
                _ = dialog.close()
            self._select_play(0)

        chooser: ui.upload = (
            ui.upload(
                label="Choose .sav or .json",
                auto_upload=True,
                max_files=1,
                max_file_size=MAX_SAVE_BYTES,
                on_upload=open_file,
                on_rejected=lambda: ui.notify("Choose a .sav up to 64 MiB or .json up to 16 MiB.", type="warning"),
            )
            .props('accept=".sav,.json" flat bordered')
            .classes("pb-uploader")
        )
        self._file_chooser = chooser

    async def _download(self) -> None:
        active = self.books.active
        if active is None:
            return
        generation = self.generation
        if await self._download_tab(active.id) and self.generation == generation:
            self.render()

    async def _download_tab(self, tab_id: str) -> bool:
        tab = self.books.get_tab(tab_id)
        document = tab.editor.playbook
        filename: str = f"{Path(tab.filename).stem}.sav"
        try:
            contents: bytes = await asyncio.to_thread(playbook_to_sav, document)
        except ValueError as error:
            ui.notify(f"Could not encode playbook. {str(error)[:250]}", type="negative")
            return False
        ui.download.content(contents, filename=filename, media_type="application/octet-stream")
        self.books.mark_saved(tab_id, document)
        _ = self._persist_working_copy()
        return True

    def _open_quickshare(self, editor: PlaybookEditor, open_dialog: Callable[[Callable[[], bool]], ui.dialog]) -> None:
        if self.editor is not editor:
            return
        active: ui.dialog | None = self._quickshare_dialog
        if active is not None and not active.is_deleted and active.value:
            return
        generation: int = self.generation
        revision: int = editor.revision

        def is_current() -> bool:
            return self.generation == generation and self.editor is editor and editor.revision == revision

        try:
            with self.container:
                self._quickshare_dialog = open_dialog(is_current)
        except ValidationError as error:
            reason: str = error.errors(include_input=False)[0]["msg"]
            ui.notify(f"Cannot share this snapshot. {reason}", type="negative")

    def _publish(self, editor: PlaybookEditor, play: GridironPlay | None = None) -> None:
        if play is None:
            self._open_quickshare(editor, partial(publish_dialog, "playbook", editor.plays))
        else:
            self._open_quickshare(editor, partial(publish_dialog, "play", (play,)))

    def _import_share(self, editor: PlaybookEditor) -> None:
        def import_and_select(snapshot: ShareSnapshot) -> None:
            if snapshot.kind == "playbook":
                tab = self.books.add(
                    document_with_plays(editor.playbook, snapshot.plays), self._unique_filename("Shared playbook.sav")
                )
                self.view = self.views.setdefault(tab.id, _TabView())
                self._select_play(0)
                return
            index = editor.import_plays(snapshot.plays)
            self.view.formation = None
            self.view.search = ""
            self._select_play(index)

        self._open_quickshare(editor, partial(import_dialog, editor.playbook, import_and_select))

    def _select_play(self, index: int) -> None:
        self.view.play_index = index
        self.view.selected = {index} if self.editor is not None and self.editor.plays else set()
        self.view.anchor = index
        self.view.route_index = None
        self.draft_slot = None
        self.draft_points = ()
        self.render()

    def _set_filter(self, formation: str | None) -> None:
        self.view.formation = formation
        self._select_play(self.view.play_index)

    def _history_change(self, operation: Callable[[], None]) -> None:
        operation()
        for view in self.views.values():
            view.selected.clear()
            view.anchor = None
            view.route_index = None
        if self.books.active is not None:
            self.view = self.views.setdefault(self.books.active.id, _TabView())
        self._select_play(self.view.play_index)

    def _transfer(
        self,
        source_id: str,
        indices: tuple[int, ...],
        destination_id: str,
        action: Literal["copy", "move"],
        insertion: int = 0,
    ) -> None:
        if not self._can_leave_draft():
            return
        try:
            operation = self.books.copy_plays if action == "copy" else self.books.move_plays
            selected = operation(source_id, indices, destination_id, insertion)
            self.books.activate(destination_id)
        except (KeyError, IndexError, ValueError) as error:
            ui.notify(str(error), type="negative")
            return
        for tab_id in (source_id, destination_id):
            view = self.views.setdefault(tab_id, _TabView())
            view.selected.clear()
            view.anchor = None
            view.route_index = None
        self.view = self.views[destination_id]
        self.view.selected = set(selected)
        self.view.play_index = selected[0]
        self.view.anchor = selected[0]
        self.view.formation = None
        self.view.search = ""
        self.render()

    def _drop_plays(self, event: _ControlEvent) -> None:
        try:
            dropped = _PlayDrop.model_validate(event.args)
        except ValidationError:
            return
        if dropped.generation != self.generation:
            return
        self._transfer(
            dropped.source,
            tuple(dropped.indices),
            dropped.destination,
            "copy" if dropped.is_copy and dropped.source != dropped.destination else "move",
            dropped.insertion,
        )

    def _reorder(self, position: Literal["top", "up", "down", "bottom"]) -> None:
        active = self.books.active
        selection = tuple(sorted(self.view.selected))
        if active is None or not selection:
            return
        insertion = {
            "top": 0,
            "up": max(0, selection[0] - 1),
            "down": min(len(active.editor.plays), selection[-1] + 2),
            "bottom": len(active.editor.plays),
        }[position]
        self._transfer(active.id, selection, active.id, "move", insertion)

    def _pick_play(self, index: int, matches: tuple[int, ...], event: _ControlEvent) -> None:
        if not self._can_leave_draft():
            return
        try:
            click = _PlayClick.model_validate(event.args)
        except ValidationError:
            return
        if click.shift and self.view.anchor in matches:
            first, last = sorted((matches.index(self.view.anchor), matches.index(index)))
            span = set(matches[first : last + 1])
            self.view.selected = self.view.selected | span if click.toggle else span
        elif click.toggle:
            self.view.selected.symmetric_difference_update({index})
            self.view.anchor = index
        else:
            self.view.selected = {index}
            self.view.anchor = index
        self.view.play_index = index
        self.view.route_index = None
        self.render()

    def _toggle_play(self, index: int) -> None:
        if not self._can_leave_draft():
            return
        self.view.selected.symmetric_difference_update({index})
        self.view.anchor = index
        self.render()

    def _select_all(self, matches: tuple[int, ...]) -> None:
        if not self._can_leave_draft():
            return
        if set(matches).issubset(self.view.selected):
            self.view.selected.difference_update(matches)
        else:
            self.view.selected.update(matches)
        self.render()

    def _selection_controls(self, editor: PlaybookEditor, matches: tuple[int, ...]) -> None:
        active = self.books.active
        if active is None:
            return
        selected = tuple(sorted(self.view.selected))
        with ui.row().classes("pb-selection"):
            _ = (
                ui.checkbox(
                    value=bool(matches) and set(matches).issubset(selected),
                    on_change=partial(self._select_all, matches),
                )
                .props('dense aria-label="Select all visible plays"')
                .set_enabled(bool(matches) and self.draft_slot is None)
            )
            _ = ui.label(str(len(selected))).classes("pb-selection-count")
            transfers: tuple[tuple[str, Literal["copy", "move"]], ...] = (
                ("Copy to", "copy"),
                ("Move to", "move"),
            )
            for label, action in transfers:
                with (
                    ui.dropdown_button(label, auto_close=True)
                    .props(f'flat dense no-caps aria-label="{label}"')
                    .set_enabled(bool(selected) and len(self.books.tabs) > 1 and self.draft_slot is None)
                ):
                    for destination in self.books.tabs:
                        if destination.id != active.id:
                            _ = ui.item(
                                destination.filename,
                                on_click=partial(self._transfer, active.id, selected, destination.id, action),
                            ).props('role="menuitem"')
        if selected:
            with ui.row().classes("pb-order-actions"):
                positions: tuple[tuple[str, Literal["top", "up", "down", "bottom"], str], ...] = (
                    ("Move to top", "top", "vertical_align_top"),
                    ("Move up", "up", "arrow_upward"),
                    ("Move down", "down", "arrow_downward"),
                    ("Move to bottom", "bottom", "vertical_align_bottom"),
                )
                for label, position, icon in positions:
                    disabled = (position in ("top", "up") and selected == tuple(range(len(selected)))) or (
                        position in ("down", "bottom")
                        and selected == tuple(range(len(editor.plays) - len(selected), len(editor.plays)))
                    )
                    _ = (
                        ui.button(icon=icon, on_click=partial(self._reorder, position))
                        .props(f'flat dense aria-label="{label}"')
                        .tooltip(label)
                        .set_enabled(not disabled and self.draft_slot is None)
                    )

    def _workspace(self, editor: PlaybookEditor, selected_point: int | None) -> None:
        plays: tuple[GridironPlay, ...] = editor.plays
        formations: list[str] = sorted({p.formation_name for p in plays}, key=str.casefold)
        if self.view.formation not in formations:
            self.view.formation = None
        visible: list[int] = [i for i, play in enumerate(plays) if self.view.formation in (None, play.formation_name)]
        if visible and self.view.play_index not in visible:
            self.view.play_index = visible[0]
            self.view.route_index = None
            self.draft_slot = None
        with _EditorWorkspace().classes("pb-workspace"):
            self._library(editor, formations, visible)
            with ui.element("section").classes("pb-board").props('aria-label="Play diagram"'):
                with ui.row().classes("pb-board-header"):
                    with ui.column().classes("pb-title-group"):
                        if plays:
                            _ = ui.label(plays[self.view.play_index].formation_name).classes("pb-formation")
                        _ = ui.label(plays[self.view.play_index].play_name if plays else "No plays yet").classes(
                            "pb-title"
                        )
                    with ui.row().classes("pb-actions"):
                        self._history_button(
                            "Undo",
                            partial(self._history_change, self.books.undo),
                            self.books.can_undo and self.draft_slot is None,
                            "Control+Z Meta+Z",
                            "Ctrl/⌘+Z",
                        )
                        self._history_button(
                            "Redo",
                            partial(self._history_change, self.books.redo),
                            self.books.can_redo and self.draft_slot is None,
                            "Control+Shift+Z Meta+Shift+Z Control+Y",
                            "Ctrl/⌘+Shift+Z or Ctrl+Y",
                        )
                if plays:
                    self._diagram(editor, plays[self.view.play_index], self.view.play_index, selected_point)
                else:
                    _ = ui.icon("route").classes("pb-empty-diagram")
            if plays:
                self._inspector(editor, plays[self.view.play_index])

    def _library(self, editor: PlaybookEditor, formations: list[str], visible: list[int]) -> None:
        with ui.element("nav").classes("pb-library").props('aria-label="Play library"'):
            with ui.row().classes("pb-section-title"):
                _ = ui.label("Plays").classes("pb-section-name")
                _ = (
                    ui.button("New play", icon="add", on_click=partial(self._new_play_dialog, editor))
                    .props("flat dense no-caps")
                    .classes("pb-create-play")
                    .mark("new-play")
                )
            search: ui.input = (
                ui.input(placeholder="Find a play", value=self.view.search)
                .props('dense outlined clearable aria-label="Find a play"')
                .classes("pb-search")
            )
            with search.add_slot("prepend"):
                _ = ui.icon("search")
            with (
                ui.dropdown_button(self.view.formation or "All formations", auto_close=True)
                .props("flat dense no-caps align=between")
                .classes("pb-filter")
            ):
                _ = ui.item("All formations", on_click=partial(self._set_filter, None))
                for formation in formations:
                    _ = ui.item(formation, on_click=partial(self._set_filter, formation))
            selection_controls = ui.column().classes("pb-selection-controls")
            listing: ui.column = ui.column().classes("pb-plays")
            active = self.books.active
            if active is not None:
                _ = listing.props(f'data-play-list="{active.id}" data-play-count="{len(editor.plays)}"')

            def filter_plays() -> None:
                self.view.search = search.value or ""
                query: str = self.view.search.strip().casefold()
                matches: list[int] = []
                for index in visible:
                    play: GridironPlay = editor.plays[index]
                    if query in play.play_name.casefold() or query in play.formation_name.casefold():
                        matches.append(index)
                _ = selection_controls.clear()
                with selection_controls:
                    self._selection_controls(editor, tuple(matches))
                _ = listing.clear()
                with listing:
                    if not matches:
                        _ = ui.label("No matches" if query else "No plays").classes("pb-list-empty")
                    self._play_rows(editor, matches, formations)
                _ = self._persist_working_copy()

            _ = search.on_value_change(filter_plays)
            filter_plays()

    def _play_rows(self, editor: PlaybookEditor, matches: list[int], formations: list[str]) -> None:
        for formation, indices in groupby(matches, key=lambda index: editor.plays[index].formation_name):
            with ui.column().classes("pb-group"):
                if self.view.formation is None and len(formations) > 1:
                    _ = ui.label(formation).classes("pb-group-name")
                for index in indices:
                    name: str = editor.plays[index].play_name or "(Unnamed play)"
                    with ui.row().classes("pb-play-row").props(f'data-play-index="{index}"') as row:
                        if index in self.view.selected:
                            _ = row.classes("pb-row-selected")
                        _ = (
                            ui.icon("drag_indicator")
                            .classes("pb-drag-handle")
                            .props(
                                f'draggable="true" data-drag-play="{index}" aria-label="Drag {escape(name, quote=True)}"'
                            )
                        )
                        _ = (
                            ui.checkbox(
                                value=index in self.view.selected,
                                on_change=partial(self._toggle_play, index),
                            )
                            .props(f'dense aria-label="Select {escape(name, quote=True)}"')
                            .set_enabled(self.draft_slot is None)
                        )
                        button: ui.button = ui.button(name)
                        _ = button.on(
                            "click",
                            partial(self._pick_play, index, tuple(matches)),
                            js_handler="(event) => emit({shift: event.shiftKey, toggle: event.ctrlKey || event.metaKey})",
                        )
                        _ = button.props("flat no-caps align=left").classes("pb-play-button")
                        if index == self.view.play_index:
                            _ = button.classes("pb-active").props('aria-current="true"')

    @staticmethod
    def _history_button(label: str, action: Callable[[], None], enabled: bool, keys: str, hint: str) -> None:
        icon: str = label.lower()
        button: ui.button = ui.button(icon=icon, on_click=action).props(
            f'flat dense round aria-label="{label}" aria-keyshortcuts="{keys}" data-history="{icon}"'
        )
        _ = button.tooltip(f"{label} ({hint})")
        _ = button.set_enabled(enabled)

    def _inspector(self, editor: PlaybookEditor, play: GridironPlay) -> None:
        with ui.element("aside").classes("pb-inspector").props('aria-label="Lineup"'):
            with ui.row().classes("pb-section-title"):
                _ = ui.label("Lineup").classes("pb-section-name")
                count: int = len(play.routes)
                _ = ui.label(f"{count} route" if count == 1 else f"{count} routes").classes("pb-count")
            slots: tuple[int, ...] = tuple(
                dict.fromkeys((*formation_starts(play.formation_name), *(r.slot for r in play.routes)))
            )
            for slot in slots:
                indices: list[int] = [i for i, r in enumerate(play.routes) if r.slot == slot]
                if not indices:
                    self._lineup_row(play, slot, None)
                for index in indices:
                    self._lineup_row(play, slot, index)
            _ = (
                ui.button("Draw route", icon="gesture", on_click=partial(self._draw_dialog, play))
                .props("unelevated no-caps")
                .classes("pb-draw")
            )
            with ui.row().classes("pb-play-actions").style("flex-wrap:wrap"):
                _ = (
                    ui.button("Share play", icon="share", on_click=partial(self._publish, editor, play))
                    .props("flat dense no-caps")
                    .set_enabled(self.draft_slot is None)
                )
                _ = ui.button(
                    "Rename", icon="edit", on_click=partial(self._rename_dialog, editor, self.view.play_index)
                ).props("flat dense no-caps")
                _ = ui.button(
                    "Duplicate",
                    icon="content_copy",
                    on_click=partial(self._duplicate_dialog, editor, self.view.play_index),
                ).props("flat dense no-caps")

    def _lineup_row(self, play: GridironPlay, slot: int, route_index: int | None) -> None:
        position: str = position_label(play.formation_name, slot)
        yardage: str | None = None
        if route_index is None:
            button: ui.button = ui.button(on_click=partial(self._start_drawing, slot))
            _ = button.props(f'aria-label="Draw route for {position}, slot {slot}"').classes("pb-unassigned")
            tooltip: str = f"Draw route · Slot {slot}"
        else:
            button = ui.button(on_click=partial(self._select_route, route_index))
            selected: bool = route_index == self.view.route_index
            start: tuple[float, float] | None = formation_starts(play.formation_name).get(slot)
            yards: str = f"{route_yards_without_blocks(play.routes[route_index], start):.0f}"
            yardage = "1 yd" if yards == "1" else f"{yards} yds"
            label: str = f"Select {position}, slot {slot}, route {route_index + 1}, {yardage}"
            tooltip = f"Slot {slot}" if start is not None else f"Slot {slot} · Distance from first saved point"
            _ = button.props(
                f'aria-label="{label}" aria-pressed="{str(selected).lower()}" data-testid="route-{route_index}"'
            )
            if selected:
                _ = button.classes("pb-active")
        with button.props(f'flat no-caps data-position="{position}"').classes("pb-route"):
            _ = ui.element("span").classes("pb-dot").props("aria-hidden=true")
            _ = ui.label(position).classes("pb-route-name")
            if yardage is None:
                _ = ui.icon("add").classes("pb-route-add")
            else:
                _ = ui.label(yardage).classes("pb-route-yardage")
        _ = button.tooltip(tooltip)

    def _start_drawing(self, slot: int) -> None:
        self.draft_slot = slot
        self.draft_points = ()
        self.view.route_index = None
        self.render()

    def _select_route(self, index: int) -> None:
        self.view.route_index = index
        self.draft_slot = None
        self.draft_points = ()
        self.render()

    def _diagram(self, editor: PlaybookEditor, play: GridironPlay, index: int, selected_point: int | None) -> None:
        generation: int = self.generation

        def select(route: int) -> None:
            if generation == self.generation and 0 <= route < len(play.routes):
                self._select_route(route)

        edit_point = partial(self._edit_point, generation)

        def move(route: int, point: int, x: float, y: float) -> None:
            edit_point(route, point, partial(editor.move_route_point, index, route, point, x, y))

        def finish(slot: int, points: tuple[GridironPoint, ...]) -> None:
            if generation == self.generation and slot == self.draft_slot:
                self._finish_route(editor, index, slot, points)

        def cancel() -> None:
            if generation == self.generation:
                self._select_play(index)

        def remember_draft(points: tuple[GridironPoint, ...]) -> bool:
            if generation != self.generation or self.draft_slot is None:
                return False
            self.draft_points = points
            return self._persist_working_copy()

        _ = PlayDiagram(
            play,
            selected_route=self.view.route_index,
            draft_slot=self.draft_slot,
            initial_point=selected_point,
            initial_draft=self.draft_points,
            on_draft=remember_draft,
            node_actions=self._node_actions(editor, index, play, edit_point),
            on_select=select,
            on_move=move,
            on_finish=finish,
            on_cancel=cancel,
            on_draw=partial(self._draw_from_diagram, generation, play),
        )

    def _edit_point(self, generation: int, route: int, selection: int, operation: Callable[[], None]) -> None:
        if generation != self.generation or route != self.view.route_index:
            return
        try:
            operation()
        except (IndexError, ValueError) as error:
            ui.notify(str(error), type="negative")
            return
        self.render(selected_point=selection)

    @staticmethod
    def _node_actions(
        editor: PlaybookEditor,
        index: int,
        play: GridironPlay,
        edit_point: Callable[[int, int, Callable[[], None]], None],
    ) -> RouteNodeActions:
        def insert(route: int, point: int, x: float, y: float) -> None:
            edit_point(route, point, partial(editor.insert_route_point, index, route, point, x, y))

        def delete(route: int, point: int) -> None:
            next_point: int = min(point, len(play.routes[route].points) - 2)
            edit_point(route, next_point, partial(editor.delete_route_point, index, route, point))

        def add_block(route: int, point: int) -> None:
            edit_point(route, point, partial(editor.add_route_block, index, route, point))

        return RouteNodeActions(insert=insert, delete=delete, add_block=add_block)

    def _draw_from_diagram(self, generation: int, play: GridironPlay, slot: int) -> None:
        if generation == self.generation and slot in formation_starts(play.formation_name):
            self._start_drawing(slot)

    def _finish_route(self, editor: PlaybookEditor, index: int, slot: int, points: tuple[GridironPoint, ...]) -> None:
        try:
            route: int = editor.add_route(index, slot, points)
        except (IndexError, ValueError) as error:
            ui.notify(str(error), type="negative")
            return
        self._select_route(route)

    def _new_play_dialog(self, editor: PlaybookEditor) -> None:
        with ui.dialog() as dialog, ui.card().classes("pb-dialog"):
            _ = ui.label("New play").classes("pb-heading")
            formation_names: list[str] = list(
                dict.fromkeys((*FORMATION_NAMES, *(p.formation_name for p in editor.plays)))
            )
            formation: ui.input = ui.input(
                "Formation",
                value=self.view.formation
                or (editor.plays[self.view.play_index].formation_name if editor.plays else ""),
                autocomplete=formation_names,
            ).classes("w-full")
            with (
                formation.add_slot("append"),
                ui.dropdown_button(auto_close=True).props('flat round dense aria-label="Choose formation"'),
            ):
                for name_option in formation_names:
                    _ = ui.item(name_option, on_click=partial(formation.set_value, name_option))
            name: ui.input = ui.input("Play name").classes("w-full")

            def create() -> None:
                index: int = editor.create_play(formation.value or "", name.value or "")
                self.view.formation = None
                self.view.search = ""
                self._select_play(index)

            self._dialog_actions(dialog, "Create play", create)
        _ = dialog.open()

    def _duplicate_dialog(self, editor: PlaybookEditor, index: int) -> None:
        original: GridironPlay = editor.plays[index]
        with ui.dialog() as dialog, ui.card().classes("pb-dialog"):
            _ = ui.label("Duplicate play").classes("pb-heading")
            name: ui.input = ui.input("Play name", value=f"{original.play_name} (copy)").classes("w-full")
            self._dialog_actions(
                dialog, "Duplicate play", lambda: self._select_play(editor.duplicate_play(index, name.value or ""))
            )
        _ = dialog.open()

    def _rename_dialog(self, editor: PlaybookEditor, index: int) -> None:
        original: GridironPlay = editor.plays[index]
        with ui.dialog() as dialog, ui.card().classes("pb-dialog"):
            _ = ui.label("Rename play").classes("pb-heading")
            name: ui.input = ui.input("Play name", value=original.play_name).classes("w-full")

            def rename() -> None:
                editor.rename_play(index, name.value or "")
                self._select_play(index)

            self._dialog_actions(dialog, "Rename play", rename)
        _ = dialog.open()

    def _draw_dialog(self, play: GridironPlay) -> None:
        known: tuple[int, ...] = tuple(formation_starts(play.formation_name))
        used: list[int] = [r.slot for r in play.routes]
        slots: tuple[int, ...] = tuple(dict.fromkeys((*observed_route_slots(play.formation_name), *known, *used)))
        preferred: int | None = next((slot for slot in slots if slot not in used), slots[0] if slots else None)
        selected: int | None = preferred
        with ui.dialog() as dialog, ui.card().classes("pb-dialog"):
            _ = ui.label("Draw route").classes("pb-heading")
            slot_field: ui.input = ui.input("Player slot").props("type=number min=0 max=255 step=1")
            choices: dict[int | None, ui.button] = {}

            def choose(slot: int | None) -> None:
                nonlocal selected
                selected = slot
                for key, choice in choices.items():
                    _ = choice.classes(
                        add="pb-active" if key == slot else None, remove=None if key == slot else "pb-active"
                    )
                    _ = choice.props(f'aria-pressed="{str(key == slot).lower()}"')
                _ = slot_field.set_visibility(slot is None)

            with ui.row().classes("pb-position-choices"):
                for slot in (*slots, None):
                    label: str = position_label(play.formation_name, slot) if slot is not None else "Custom slot"
                    choice: ui.button = ui.button(label, on_click=partial(choose, slot)).props("outline no-caps")
                    if slot is not None:
                        _ = choice.tooltip(f"Slot {slot}")
                    choices[slot] = choice
            _ = slot_field.move()
            choose(selected)

            def start() -> None:
                if selected is not None:
                    self._start_drawing(selected)
                    return
                value: str = slot_field.value or ""
                if not value.isdecimal() or not 0 <= int(value) <= 255:
                    raise ValueError("Enter a whole player slot from 0 to 255.")
                self._start_drawing(int(value))

            self._dialog_actions(dialog, "Start drawing", start)
        _ = dialog.open()

    def _dialog_actions(self, dialog: ui.dialog, label: str, action: Callable[[], None]) -> None:
        generation: int = self.generation

        def submit() -> None:
            if generation != self.generation:
                if not dialog.is_deleted:
                    _ = dialog.close()
                return
            try:
                action()
            except (IndexError, ValueError) as error:
                ui.notify(str(error), type="negative")
                return
            if not dialog.is_deleted:
                _ = dialog.close()

        with ui.row().classes("pb-actions"):
            _ = ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
            _ = ui.button(label, on_click=submit).props("unelevated no-caps")
        _ = dialog.on("hide", dialog.delete)
