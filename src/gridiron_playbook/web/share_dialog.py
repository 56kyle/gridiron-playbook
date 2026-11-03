"""Create and import Quickshare snapshots in the local editor."""

import asyncio
from collections.abc import Awaitable
from collections.abc import Callable
from functools import partial
from typing import Literal
from typing import TypeVar

from nicegui import ui

from gridiron_playbook.play import GridironPlay
from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.quickshare.client import QuickshareClient
from gridiron_playbook.quickshare.client import QuickshareError
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.web.playbook_files import PlaybookFileError
from gridiron_playbook.web.playbook_files import validate_import_size


_Result = TypeVar("_Result")


def _request_actions(
    dialog: ui.dialog,
    label: str,
    is_current: Callable[[], bool],
    request: Callable[[], Awaitable[_Result]],
    apply: Callable[[_Result], None],
) -> ui.button:
    def is_open() -> bool:
        return not dialog.is_deleted and dialog.value and is_current()

    async def submit() -> None:
        if not is_open() or not button.enabled:
            return
        _ = button.disable().props("loading")
        try:
            result: _Result = await request()
            if is_open():
                apply(result)
        except (QuickshareError, PlaybookFileError) as error:
            if is_open():
                ui.notify(str(error), type="negative")
        finally:
            if not button.is_deleted:
                _ = button.enable().props(remove="loading")

    with ui.row().classes("pb-actions"):
        _ = ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
        button: ui.button = ui.button(label, on_click=submit).props("unelevated no-caps")
    _ = dialog.on("hide", dialog.delete)
    return button


def _show_link(card: ui.card, dialog: ui.dialog, url: str) -> None:
    _ = card.clear()
    with card:
        _ = ui.label("Link ready").classes("pb-heading")
        _ = ui.input("Share link", value=url).props('readonly aria-label="Share link"').classes("w-full")
        with ui.row().classes("pb-actions"):
            _ = ui.button("Done", on_click=dialog.close).props("flat no-caps")
            _ = (
                ui.button("Copy link", icon="content_copy")
                .props("unelevated no-caps")
                .on(
                    "click",
                    js_handler="""async (event) => {
                    const input = event.target.closest('.pb-dialog').querySelector('input[readonly]');
                    try {
                        await navigator.clipboard.writeText(input.value);
                        Quasar.Notify.create('Link copied');
                    } catch {
                        input.focus();
                        input.select();
                        Quasar.Notify.create('Use the copy command to copy the selected link.');
                    }
                }""",
                )
            )


def publish_dialog(
    kind: Literal["play", "playbook"],
    plays: tuple[GridironPlay, ...],
    client: QuickshareClient,
    is_current: Callable[[], bool],
) -> ui.dialog:
    """Confirm publication and show the resulting short link."""
    snapshot = ShareSnapshot(version=1, kind=kind, plays=plays)
    with ui.dialog() as dialog, ui.card().classes("pb-dialog") as card:
        _ = ui.label("Share play" if kind == "play" else "Share playbook").classes("pb-heading")
        if kind == "play":
            summary: str = plays[0].play_name or "(Unnamed play)"
        else:
            summary = "1 play" if len(plays) == 1 else f"{len(plays)} plays"
        _ = ui.label(summary)
        _ = ui.label("Anyone with the link can view and import this snapshot.")
        _ = _request_actions(
            dialog, "Create link", is_current, partial(client.publish, snapshot), partial(_show_link, card, dialog)
        )
    return dialog.open()


def import_dialog(
    recipient: GridironPlaybook,
    imported: Callable[[ShareSnapshot], None],
    client: QuickshareClient,
    is_current: Callable[[], bool],
) -> ui.dialog:
    """Fetch a snapshot and append it to the open playbook."""
    with ui.dialog() as dialog, ui.card().classes("pb-dialog"):
        _ = ui.label("Import link").classes("pb-heading")
        link: ui.input = ui.input("Share link").props('aria-label="Share link" autofocus').classes("w-full")
        _ = ui.label("Shared plays will be added to this playbook.")

        async def fetch() -> ShareSnapshot:
            snapshot: ShareSnapshot = await client.fetch((link.value or "").strip())
            if not dialog.is_deleted and dialog.value and is_current():
                await asyncio.to_thread(validate_import_size, recipient, snapshot)
            return snapshot

        submit: ui.button = _request_actions(dialog, "Import", is_current, fetch, imported)
        _ = link.bind_enabled_from(submit)
    return dialog.open()
