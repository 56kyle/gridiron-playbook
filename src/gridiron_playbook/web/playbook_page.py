"""NiceGUI page for opening, editing, and downloading a playbook."""

from collections.abc import Callable
from functools import partial
from pathlib import Path

from nicegui import events
from nicegui import ui

from gridiron_playbook.editor import PlaybookEditor
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.playbook import json_to_playbook
from gridiron_playbook.playbook import playbook_to_sav
from gridiron_playbook.playbook import sav_to_playbook
from gridiron_playbook.point import GridironPoint
from gridiron_playbook.web.play_diagram import FieldTransform
from gridiron_playbook.web.play_diagram import PlayDiagram


_MAX_FILE_BYTES: int = 16 * 1024 * 1024


def _decode_uploaded_playbook(name: str, contents: bytes) -> GridironPlaybook:
    suffix: str = Path(name).suffix.lower()
    document: GridironPlaybook
    if suffix == ".sav":
        document = sav_to_playbook(contents)
    elif suffix == ".json":
        document = json_to_playbook(contents.decode("utf-8-sig"))
    else:
        raise ValueError("Choose a .sav or .json playbook.")
    for play in document.root.properties.custom_plays:
        _ = FieldTransform.for_play(play)
    return document


def playbook_page() -> None:
    """Build a private editor for this page instance."""
    _ = ui.colors(primary="#16634c")
    ui.add_css(Path(__file__).with_name("editor.css").read_text(encoding="utf-8"))
    _PlaybookPage().render()


class _PlaybookPage:
    def __init__(self) -> None:
        self.container: ui.column = ui.column().classes("pb-app")
        self.editor: PlaybookEditor | None = None
        self.filename: str = ""
        self.formation: str | None = None
        self.play_index: int = 0
        self.route_index: int | None = None
        self.draft_slot: int | None = None
        self.generation: int = 0
        self._file_chooser: ui.upload | None = None

    def render(self) -> None:
        """Replace the page controls and invalidate gestures from the old diagram."""
        self.generation += 1
        self._file_chooser = None
        _ = self.container.clear()
        with self.container:
            with ui.element("header").classes("pb-header"):
                with ui.row().classes("pb-brand"):
                    _ = ui.icon("sports_football").classes("pb-brand-icon")
                    _ = ui.label("Gridiron").classes("pb-brand-name")
                    _ = ui.label("Playbook editor").classes("pb-brand-section")
                if self.editor is not None:
                    with ui.row().classes("pb-actions"):
                        _ = ui.button(
                            "Open playbook", icon="folder_open", color="white", on_click=self._open_dialog
                        ).props("flat no-caps")
                        _ = ui.button(
                            "Download .sav", icon="download", color="light-green-3", on_click=self._download
                        ).props("unelevated no-caps text-color=green-10")
            if self.editor is None:
                self._welcome()
            else:
                self._workspace(self.editor)

    def _welcome(self) -> None:
        with ui.element("main").classes("pb-welcome"):
            _ = ui.label("PLAYBOOK EDITOR").classes("pb-eyebrow")
            _ = ui.label("Open your playbook").classes("pb-display")
            _ = ui.label("Choose a Gridiron save or its JSON export to draw routes and create plays.").classes(
                "pb-lede"
            )
            self._upload_control()
            _ = ui.label("Download an edited copy when you're ready to use it.").classes("pb-muted")

    def _open_dialog(self) -> None:
        with ui.dialog() as dialog, ui.card().classes("pb-dialog"):
            _ = ui.label("Open playbook").classes("pb-heading")
            _ = ui.label("Opening a file replaces this tab's playbook and edit history.")
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
                if event.file.size() > _MAX_FILE_BYTES:
                    raise ValueError("Choose a file up to 16 MiB.")
                data: bytes = await event.file.read()
                if request != latest_request or not chooser_is_open():
                    return
                document: GridironPlaybook = _decode_uploaded_playbook(name, data)
            except (ValueError, OSError) as error:
                if request == latest_request and chooser_is_open():
                    _ = chooser.reset()
                    ui.notify(f"Could not open playbook. {str(error)[:250]}", type="negative")
                return
            self.editor = PlaybookEditor(document)
            self.filename = name
            self.formation = None
            if dialog is not None:
                _ = dialog.close()
            self._select_play(0)

        chooser: ui.upload = (
            ui.upload(
                label="Choose .sav or .json",
                auto_upload=True,
                max_files=1,
                max_file_size=_MAX_FILE_BYTES,
                on_upload=open_file,
                on_rejected=lambda: ui.notify("Choose a .sav or .json file up to 16 MiB.", type="warning"),
            )
            .props('accept=".sav,.json" flat bordered')
            .classes("pb-uploader")
        )
        self._file_chooser = chooser

    def _download(self) -> None:
        if self.editor is None:
            return
        try:
            contents: bytes = playbook_to_sav(self.editor.playbook)
        except ValueError as error:
            ui.notify(f"Could not encode playbook. {str(error)[:250]}", type="negative")
            return
        ui.download.content(contents, filename=f"{Path(self.filename).stem}.sav", media_type="application/octet-stream")

    def _select_play(self, index: int) -> None:
        self.play_index = index
        self.route_index = None
        self.draft_slot = None
        self.render()

    def _set_filter(self, formation: str | None) -> None:
        self.formation = formation
        self._select_play(self.play_index)

    def _history_change(self, operation: Callable[[], None]) -> None:
        operation()
        self._select_play(self.play_index)

    def _workspace(self, editor: PlaybookEditor) -> None:
        plays: tuple[GridironPlay, ...] = editor.plays
        formations: list[str] = sorted({p.formation_name for p in plays}, key=str.casefold)
        if self.formation not in formations:
            self.formation = None
        visible: list[int] = [i for i, play in enumerate(plays) if self.formation in (None, play.formation_name)]
        if visible and self.play_index not in visible:
            self.play_index = visible[0]
            self.route_index = None
            self.draft_slot = None
        with ui.element("main").classes("pb-workspace"):
            with ui.column().classes("pb-sidebar"):
                _ = ui.label("PLAYBOOK").classes("pb-eyebrow")
                _ = ui.label(self.filename).classes("pb-file")
                _ = ui.label(f"{len(plays)} plays · {len(formations)} formations").classes("pb-muted")
                _ = ui.separator()
                with ui.dropdown_button(self.formation or "All formations", auto_close=True).props("outline no-caps"):
                    _ = ui.item("All formations", on_click=partial(self._set_filter, None))
                    for formation in formations:
                        _ = ui.item(formation, on_click=partial(self._set_filter, formation))
                with ui.column().classes("pb-plays"):
                    for i in visible:
                        label: str = plays[i].play_name or "(Unnamed play)"
                        button: ui.button = ui.button(label, on_click=partial(self._select_play, i))
                        _ = button.props("flat no-caps align=left").classes("pb-play-button")
                        if i == self.play_index:
                            _ = button.classes("pb-active").props('aria-current="true"')
                _ = ui.button("New play", icon="add", on_click=partial(self._new_play_dialog, editor)).props(
                    "outline no-caps"
                )
            with ui.column().classes("pb-board"):
                with ui.row().classes("pb-board-header"):
                    with ui.column().classes("pb-title-group"):
                        _ = ui.label(plays[self.play_index].formation_name if plays else "PLAYBOOK").classes(
                            "pb-eyebrow"
                        )
                        _ = ui.label(plays[self.play_index].play_name if plays else "No plays yet").classes("pb-title")
                    with ui.row().classes("pb-actions"):
                        undo: ui.button = ui.button(
                            "Undo", icon="undo", on_click=partial(self._history_change, editor.undo)
                        )
                        redo: ui.button = ui.button(
                            "Redo", icon="redo", on_click=partial(self._history_change, editor.redo)
                        )
                        _ = undo.props("flat no-caps").set_enabled(editor.can_undo)
                        _ = redo.props("flat no-caps").set_enabled(editor.can_redo)
                if plays:
                    self._play_tools(editor, plays[self.play_index])
                else:
                    _ = ui.label("Create a play to start drawing routes.").classes("pb-muted")

    def _play_tools(self, editor: PlaybookEditor, play: GridironPlay) -> None:
        index: int = self.play_index
        with ui.row().classes("pb-actions"):
            _ = ui.button("Draw route", icon="gesture", on_click=partial(self._draw_dialog, play)).props(
                "unelevated no-caps"
            )
            _ = ui.button(
                "Duplicate", icon="content_copy", on_click=partial(self._duplicate_dialog, editor, index)
            ).props("outline no-caps")
            _ = ui.button("Rename", icon="edit", on_click=partial(self._rename_dialog, editor, index)).props(
                "flat no-caps"
            )
        self._diagram(editor, play, index)
        _ = ui.label(f"ROUTES · {len(play.routes)}").classes("pb-eyebrow")
        with ui.row().classes("pb-actions"):
            for route_index, route in enumerate(play.routes):
                route_button: ui.button = ui.button(
                    f"Slot {route.slot} · {len(route.points)} points",
                    on_click=partial(self._select_route, route_index),
                ).props("outline no-caps")
                if self.route_index == route_index:
                    _ = route_button.classes("pb-active")
            if not play.routes:
                _ = ui.label("Use Draw route to add the first player route.").classes("pb-muted")

    def _select_route(self, index: int) -> None:
        self.route_index = index
        self.draft_slot = None
        self.render()

    def _diagram(self, editor: PlaybookEditor, play: GridironPlay, index: int) -> None:
        generation: int = self.generation

        def select(route: int) -> None:
            if generation == self.generation and 0 <= route < len(play.routes):
                self._select_route(route)

        def move(route: int, point: int, x: float, y: float) -> None:
            if generation != self.generation or route != self.route_index:
                return
            try:
                editor.move_route_point(index, route, point, x, y)
            except (IndexError, ValueError) as error:
                ui.notify(str(error), type="negative")
            self.render()

        def finish(slot: int, points: tuple[GridironPoint, ...]) -> None:
            if generation == self.generation and slot == self.draft_slot:
                self._finish_route(editor, index, slot, points)

        def cancel() -> None:
            if generation == self.generation:
                self.draft_slot = None
                self.render()

        _ = PlayDiagram(
            play,
            selected_route=self.route_index,
            draft_slot=self.draft_slot,
            on_select=select,
            on_move=move,
            on_finish=finish,
            on_cancel=cancel,
        )

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
            formation: ui.input = ui.input("Formation", value=self.formation or "").classes("w-full")
            name: ui.input = ui.input("Play name").classes("w-full")

            def create() -> None:
                index: int = editor.create_play(formation.value or "", name.value or "")
                self.formation = None
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
        used: set[int] = {route.slot for route in play.routes}
        suggestion: int = next((n for n in range(256) if n not in used), 0)
        with ui.dialog() as dialog, ui.card().classes("pb-dialog"):
            _ = ui.label("Draw route").classes("pb-heading")
            slot: ui.input = ui.input("Player slot", value=str(suggestion)).props("type=number min=0 max=255 step=1")

            def start() -> None:
                value: str = slot.value or ""
                if not value.isdecimal() or not 0 <= int(value) <= 255:
                    raise ValueError("Enter a whole player slot from 0 to 255.")
                self.draft_slot = int(value)
                self.route_index = None
                self.render()

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
