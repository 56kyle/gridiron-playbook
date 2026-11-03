"""Read-only browser preview for shared plays and playbooks."""

from asyncio import to_thread
from pathlib import Path

from nicegui import ui
from nicegui.events import ValueChangeEventArguments

from gridiron_playbook.block import route_yards_without_blocks
from gridiron_playbook.formations import formation_starts
from gridiron_playbook.formations import position_label
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.quickshare.snapshot import is_share_id
from gridiron_playbook.quickshare.store import SnapshotStore
from gridiron_playbook.web.play_diagram import PlayField


def _show_play(play: GridironPlay) -> None:
    with ui.element("section").classes("pb-board"):
        _ = ui.label(play.formation_name).classes("pb-formation")
        with ui.element("h1").classes("pb-title"):
            _ = ui.label(play.play_name or "(Unnamed play)")
        _ = PlayField(play)
    with ui.element("aside").classes("pb-inspector").props('aria-label="Routes"'):
        _ = ui.label("Routes").classes("pb-section-name")
        starts = formation_starts(play.formation_name)
        if not play.routes:
            _ = ui.label("No routes").classes("pb-count")
        for route in play.routes:
            position: str = position_label(play.formation_name, route.slot)
            yards: str = f"{route_yards_without_blocks(route, starts.get(route.slot)):.0f}"
            with ui.row().classes("pb-preview-route").props(f'data-position="{position}"'):
                _ = ui.element("span").classes("pb-dot").props("aria-hidden=true")
                _ = ui.label(position).classes("pb-route-name")
                _ = (
                    ui.label("1 yd" if yards == "1" else f"{yards} yds")
                    .classes("pb-route-yardage")
                    .props('data-testid="preview-yardage"')
                )


def _show_snapshot(snapshot: ShareSnapshot) -> None:
    with ui.column().classes("pb-app"):
        with ui.element("header").classes("pb-header"):
            with ui.row().classes("pb-brand"):
                _ = ui.icon("sports_football").classes("pb-brand-icon")
                _ = ui.label("Gridiron").classes("pb-brand-name")
                _ = ui.label("Quickshare").classes("pb-file")
            with ui.row().classes("pb-actions"):
                _ = (
                    ui.button("Copy link", icon="link")
                    .props("flat no-caps")
                    .on(
                        "click",
                        js_handler="""async () => {
                        try {
                            await navigator.clipboard.writeText(window.location.origin + window.location.pathname);
                            Quasar.Notify.create('Link copied');
                        } catch {
                            Quasar.Notify.create('Copy the address from your browser.');
                        }
                    }""",
                    )
                )
        with ui.element("main").classes("pb-preview"):
            selector: ui.select | None = None
            if snapshot.kind == "playbook":
                options: dict[int, str] = {
                    index: f"{index + 1}. {play.play_name or '(Unnamed play)'} · {play.formation_name}"
                    for index, play in enumerate(snapshot.plays)
                }
                selector = (
                    ui.select(options, label="Find a play", value=0, with_input=True)
                    .props("dense outlined")
                    .classes("pb-preview-picker")
                )
            diagram = ui.element("div").classes("pb-preview-grid")

            def choose(event: ValueChangeEventArguments[object]) -> None:
                index: object = event.value
                if type(index) is int and 0 <= index < len(snapshot.plays):
                    _ = diagram.clear()
                    with diagram:
                        _show_play(snapshot.plays[index])

            if selector is not None:
                _ = selector.on_value_change(choose)
            with diagram:
                _show_play(snapshot.plays[0])
            _ = ui.label("To import, open your playbook in the editor and choose Import link.").classes(
                "pb-preview-import"
            )


def register_preview(store: SnapshotStore) -> None:
    """Register the hosted Quickshare page before starting NiceGUI."""

    @ui.page("/s/{share_id}", title="Quickshare · Gridiron")
    async def shared_play(share_id: str) -> None:
        ui.add_css((Path(__file__).parents[1] / "web" / "editor.css").read_text(encoding="utf-8"))
        ui.add_head_html('<meta name="robots" content="noindex,nofollow">')
        snapshot: ShareSnapshot | None = await to_thread(store.get, share_id) if is_share_id(share_id) else None
        if snapshot is None:
            ui.status_code(404)
            with ui.element("main").classes("pb-welcome"):
                _ = ui.label("Share not found").classes("pb-display")
            return
        _show_snapshot(snapshot)
