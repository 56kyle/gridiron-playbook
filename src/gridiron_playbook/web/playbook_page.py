"""NiceGUI page for opening, editing, and downloading a playbook."""

import asyncio
from collections.abc import Callable
from functools import partial
from pathlib import Path

from nicegui import events
from nicegui import ui
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
from gridiron_playbook.quickshare.client import QuickshareClient
from gridiron_playbook.quickshare.client import QuickshareError
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.web.play_diagram import PlayDiagram
from gridiron_playbook.web.play_diagram import RouteNodeActions
from gridiron_playbook.web.playbook_files import MAX_SAVE_BYTES
from gridiron_playbook.web.playbook_files import decode_uploaded_playbook
from gridiron_playbook.web.playbook_files import validate_upload_size
from gridiron_playbook.web.share_dialog import import_dialog
from gridiron_playbook.web.share_dialog import publish_dialog


def playbook_page() -> None:
    """Build a private editor for this page instance."""
    ui.add_css(Path(__file__).with_name("editor.css").read_text(encoding="utf-8"))
    _PlaybookPage().render()


class _EditorWorkspace(ui.element, component="editor_workspace.js"):
    """Scope keyboard shortcuts to the open playbook."""


class _PlaybookPage:
    def __init__(self) -> None:
        self.container: ui.column = ui.column().classes("pb-app")
        self.editor: PlaybookEditor | None = None
        self.filename: str = ""
        self.formation: str | None = None
        self.search: str = ""
        self.play_index: int = 0
        self.route_index: int | None = None
        self.draft_slot: int | None = None
        self.generation: int = 0
        self._file_chooser: ui.upload | None = None
        self._quickshare_dialog: ui.dialog | None = None

    def render(self, *, selected_point: int | None = None) -> None:
        """Replace the page controls and invalidate gestures from the old diagram."""
        self.generation += 1
        self._file_chooser = None
        if self._quickshare_dialog is not None and not self._quickshare_dialog.is_deleted:
            _ = self._quickshare_dialog.close()
        self._quickshare_dialog = None
        _ = self.container.clear()
        with self.container:
            with ui.element("header").classes("pb-header"):
                with ui.row().classes("pb-brand"):
                    _ = ui.icon("sports_football").classes("pb-brand-icon")
                    _ = ui.label("Gridiron").classes("pb-brand-name")
                    if self.filename:
                        _ = ui.label(self.filename).classes("pb-file")
                if self.editor is not None:
                    with ui.row().classes("pb-actions").style("flex-wrap:wrap;max-width:100%"):
                        _ = ui.button("Open playbook", icon="folder_open", on_click=self._open_dialog).props(
                            "flat no-caps"
                        )
                        _ = (
                            ui.button("Import link", icon="add_link", on_click=partial(self._import_link, self.editor))
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
            if self.editor is None:
                self._welcome()
            else:
                self._workspace(self.editor, selected_point)

    def _welcome(self) -> None:
        with ui.element("main").classes("pb-welcome"):
            _ = ui.icon("route").classes("pb-welcome-icon")
            _ = ui.label("Open your playbook").classes("pb-display")
            self._upload_control()

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
            self.editor = PlaybookEditor(document)
            self.filename = name
            self.formation = None
            self.search = ""
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
        if self.editor is None:
            return
        filename: str = f"{Path(self.filename).stem}.sav"
        try:
            contents: bytes = await asyncio.to_thread(playbook_to_sav, self.editor.playbook)
        except ValueError as error:
            ui.notify(f"Could not encode playbook. {str(error)[:250]}", type="negative")
            return
        ui.download.content(contents, filename=filename, media_type="application/octet-stream")

    def _open_quickshare(
        self, editor: PlaybookEditor, open_dialog: Callable[[QuickshareClient, Callable[[], bool]], ui.dialog]
    ) -> None:
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
            client: QuickshareClient = QuickshareClient.from_env()
            with self.container:
                self._quickshare_dialog = open_dialog(client, is_current)
        except QuickshareError as error:
            ui.notify(str(error), type="negative")
        except ValidationError as error:
            reason: str = error.errors(include_input=False)[0]["msg"]
            ui.notify(f"Cannot share this snapshot. {reason}", type="negative")

    def _publish(self, editor: PlaybookEditor, play: GridironPlay | None = None) -> None:
        if play is None:
            self._open_quickshare(editor, partial(publish_dialog, "playbook", editor.plays))
        else:
            self._open_quickshare(editor, partial(publish_dialog, "play", (play,)))

    def _import_link(self, editor: PlaybookEditor) -> None:
        def append(snapshot: ShareSnapshot) -> None:
            index: int = editor.import_plays(snapshot.plays)
            self.formation = None
            self.search = ""
            self._select_play(index)

        self._open_quickshare(editor, partial(import_dialog, editor.playbook, append))

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

    def _workspace(self, editor: PlaybookEditor, selected_point: int | None) -> None:
        plays: tuple[GridironPlay, ...] = editor.plays
        formations: list[str] = sorted({p.formation_name for p in plays}, key=str.casefold)
        if self.formation not in formations:
            self.formation = None
        visible: list[int] = [i for i, play in enumerate(plays) if self.formation in (None, play.formation_name)]
        if visible and self.play_index not in visible:
            self.play_index = visible[0]
            self.route_index = None
            self.draft_slot = None
        with _EditorWorkspace().classes("pb-workspace"):
            self._library(editor, formations, visible)
            with ui.element("section").classes("pb-board").props('aria-label="Play diagram"'):
                with ui.row().classes("pb-board-header"):
                    with ui.column().classes("pb-title-group"):
                        if plays:
                            _ = ui.label(plays[self.play_index].formation_name).classes("pb-formation")
                        _ = ui.label(plays[self.play_index].play_name if plays else "No plays yet").classes("pb-title")
                    with ui.row().classes("pb-actions"):
                        self._history_button(
                            "Undo",
                            partial(self._history_change, editor.undo),
                            editor.can_undo and self.draft_slot is None,
                            "Control+Z Meta+Z",
                            "Ctrl/⌘+Z",
                        )
                        self._history_button(
                            "Redo",
                            partial(self._history_change, editor.redo),
                            editor.can_redo and self.draft_slot is None,
                            "Control+Shift+Z Meta+Shift+Z Control+Y",
                            "Ctrl/⌘+Shift+Z or Ctrl+Y",
                        )
                if plays:
                    self._diagram(editor, plays[self.play_index], self.play_index, selected_point)
                else:
                    _ = ui.icon("route").classes("pb-empty-diagram")
            if plays:
                self._inspector(editor, plays[self.play_index])

    def _library(self, editor: PlaybookEditor, formations: list[str], visible: list[int]) -> None:
        with ui.element("nav").classes("pb-library").props('aria-label="Play library"'):
            with ui.row().classes("pb-section-title"):
                _ = ui.label("Plays").classes("pb-section-name")
                _ = (
                    ui.button("New play", icon="add", on_click=partial(self._new_play_dialog, editor))
                    .props("flat dense no-caps")
                    .classes("pb-create-play")
                )
            search: ui.input = (
                ui.input(placeholder="Find a play", value=self.search)
                .props('dense outlined clearable aria-label="Find a play"')
                .classes("pb-search")
            )
            with search.add_slot("prepend"):
                _ = ui.icon("search")
            with (
                ui.dropdown_button(self.formation or "All formations", auto_close=True)
                .props("flat dense no-caps align=between")
                .classes("pb-filter")
            ):
                _ = ui.item("All formations", on_click=partial(self._set_filter, None))
                for formation in formations:
                    _ = ui.item(formation, on_click=partial(self._set_filter, formation))
            listing: ui.column = ui.column().classes("pb-plays")

            def filter_plays() -> None:
                self.search = search.value or ""
                query: str = self.search.strip().casefold()
                groups: dict[str, list[int]] = {}
                for index in visible:
                    play: GridironPlay = editor.plays[index]
                    if query in play.play_name.casefold() or query in play.formation_name.casefold():
                        groups.setdefault(play.formation_name, []).append(index)
                _ = listing.clear()
                with listing:
                    if not groups:
                        _ = ui.label("No matches" if query else "No plays").classes("pb-list-empty")
                    for formation, indices in groups.items():
                        with ui.column().classes("pb-group"):
                            if self.formation is None and len(formations) > 1:
                                _ = ui.label(formation).classes("pb-group-name")
                            for index in indices:
                                name: str = editor.plays[index].play_name or "(Unnamed play)"
                                button: ui.button = ui.button(name, on_click=partial(self._select_play, index))
                                _ = button.props("flat no-caps align=left").classes("pb-play-button")
                                if index == self.play_index:
                                    _ = button.classes("pb-active").props('aria-current="true"')

            _ = search.on_value_change(filter_plays)
            filter_plays()

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
                    "Rename", icon="edit", on_click=partial(self._rename_dialog, editor, self.play_index)
                ).props("flat dense no-caps")
                _ = ui.button(
                    "Duplicate", icon="content_copy", on_click=partial(self._duplicate_dialog, editor, self.play_index)
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
            selected: bool = route_index == self.route_index
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
        self.route_index = None
        self.render()

    def _select_route(self, index: int) -> None:
        self.route_index = index
        self.draft_slot = None
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

        _ = PlayDiagram(
            play,
            selected_route=self.route_index,
            draft_slot=self.draft_slot,
            initial_point=selected_point,
            node_actions=self._node_actions(editor, index, play, edit_point),
            on_select=select,
            on_move=move,
            on_finish=finish,
            on_cancel=cancel,
            on_draw=partial(self._draw_from_diagram, generation, play),
        )

    def _edit_point(self, generation: int, route: int, selection: int, operation: Callable[[], None]) -> None:
        if generation != self.generation or route != self.route_index:
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
                value=self.formation or (editor.plays[self.play_index].formation_name if editor.plays else ""),
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
                self.formation = None
                self.search = ""
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
