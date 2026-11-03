"""Export and import self-contained Quickshare links and files in the editor."""

import asyncio
from collections.abc import Callable
from typing import Literal
from typing import Protocol

from nicegui import events
from nicegui import ui
from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError

from gridiron_playbook.play import GridironPlay
from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.quickshare.codec import MAX_SHARE_BYTES
from gridiron_playbook.quickshare.codec import Precision
from gridiron_playbook.quickshare.codec import decode_share
from gridiron_playbook.quickshare.codec import encode_share
from gridiron_playbook.quickshare.links import MAX_LINK_CHARS
from gridiron_playbook.quickshare.links import decode_link
from gridiron_playbook.quickshare.links import make_link
from gridiron_playbook.quickshare.links import viewer_url_from_env
from gridiron_playbook.quickshare.links import warning_level
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.web.playbook_files import validate_import_size


class _Choice(BaseModel):
    precision: Precision


class _SubmittedLink(BaseModel):
    link: str = Field(max_length=65_536)


class _ControlEvent(Protocol):
    @property
    def args(self) -> object: ...


def _error_text(error: ValueError) -> str:
    if isinstance(error, ValidationError):
        return str(error.errors(include_input=False)[0]["msg"])
    return str(error)[:250]


class _ShareControls(ui.element, component="share_controls.js"):
    """Measure the selected link and encode a file at the precision requested by the client."""

    def __init__(self, snapshot: ShareSnapshot, is_open: Callable[[], bool]) -> None:
        super().__init__()
        self._snapshot: ShareSnapshot = snapshot
        self._is_open: Callable[[], bool] = is_open
        self._revision: int = 0
        self._current: tuple[Precision, str] | None = None
        self._downloading: bool = False
        self._viewer: str | None = None
        try:
            self._viewer = viewer_url_from_env()
        except ValueError as error:
            self._props["viewerProblem"] = _error_text(error)
        self._props["options"] = [
            {"label": "Exact", "value": "exact"},
            {"label": "1 mm", "value": "1mm"},
            {"label": "1 cm", "value": "1cm"},
        ]
        _ = self.on("measure", self._measure)
        _ = self.on("reveal", self._reveal)
        _ = self.on("download", self._download)

    def _encode_link(self, viewer: str, precision: Precision) -> str:
        return make_link(viewer, encode_share(self._snapshot, precision))

    async def _measure(self, event: _ControlEvent) -> None:
        if self._viewer is None or not self._is_open():
            return
        self._revision += 1
        request: int = self._revision
        self._current = None
        try:
            precision: Precision = _Choice.model_validate(event.args).precision
            url: str = await asyncio.to_thread(self._encode_link, self._viewer, precision)
        except ValueError as error:
            if request == self._revision and self._is_open():
                self._props.update(problem=_error_text(error), result=None, longLink=None)
                self.update()
            return
        if request != self._revision or not self._is_open():
            return
        self._current = (precision, url)
        level = warning_level(len(url))
        self._props.update(
            problem="",
            longLink=None,
            result={"precision": precision.value, "length": len(url), "level": level, "url": None if level else url},
        )
        self.update()

    def _reveal(self, event: _ControlEvent) -> None:
        if self._current is None or not self._is_open():
            return
        precision, url = self._current
        if event.args == {"precision": precision.value}:
            self._props["longLink"] = {"precision": precision.value, "url": url}
            self.update()

    async def _download(self, event: _ControlEvent) -> None:
        if self._downloading or not self._is_open():
            return
        self._downloading = True
        self._props["downloading"] = True
        self.update()
        try:
            precision: Precision = _Choice.model_validate(event.args).precision
            data: bytes = await asyncio.to_thread(encode_share, self._snapshot, precision)
            if self._is_open():
                filename: str = f"gridiron-{self._snapshot.kind}-{precision.value}.gridironshare"
                ui.download.content(data, filename, media_type="application/octet-stream")
        except ValueError as error:
            if self._is_open():
                ui.notify(_error_text(error), type="negative")
        finally:
            self._downloading = False
            if self._is_open():
                self._props["downloading"] = False
                self.update()


def publish_dialog(
    kind: Literal["play", "playbook"], plays: tuple[GridironPlay, ...], is_current: Callable[[], bool]
) -> ui.dialog:
    """Choose the precision for a self-contained link or downloadable share file."""
    snapshot = ShareSnapshot(version=1, kind=kind, plays=plays)
    with ui.dialog() as dialog, ui.card().classes("pb-dialog"):
        _ = ui.label("Share play" if kind == "play" else "Share playbook").classes("pb-heading")
        _ = _ShareControls(snapshot, lambda: not dialog.is_deleted and dialog.value and is_current()).classes("w-full")
        _ = ui.button("Done", on_click=dialog.close).props("flat no-caps").classes("self-end")
    _ = dialog.on("hide", dialog.delete)
    return dialog.open()


class _LocalLinkInput(ui.element, component="share_link_input.js"):
    """Keep arbitrary-length pasted text in the browser until Import is pressed."""

    def set_busy(self, busy: bool) -> None:
        self._props["disabled"] = busy
        self.update()


class _ImportDialog(ui.dialog):
    """Append one locally decoded share while the destination revision is current."""

    def __init__(
        self, recipient: GridironPlaybook, imported: Callable[[ShareSnapshot], None], is_current: Callable[[], bool]
    ) -> None:
        super().__init__()
        self._recipient: GridironPlaybook = recipient
        self._imported: Callable[[ShareSnapshot], None] = imported
        self._is_current: Callable[[], bool] = is_current
        self._contents: bytes | None = None
        self._has_link: bool = False
        self._busy: bool = False
        with self, ui.card().classes("pb-dialog"):
            _ = ui.label("Import share").classes("pb-heading")
            self._link: _LocalLinkInput = _LocalLinkInput().classes("w-full")
            self._uploader: ui.upload = (
                ui.upload(
                    label="Choose a share file",
                    auto_upload=True,
                    max_files=1,
                    max_file_size=MAX_SHARE_BYTES,
                    on_upload=self._load_file,
                    on_rejected=lambda: ui.notify(
                        "Choose a .gridironshare file within the size limit.", type="warning"
                    ),
                )
                .props('accept=".gridironshare" flat bordered')
                .classes("pb-uploader")
            )
            self._long_link_upload: ui.upload = ui.upload(
                auto_upload=True,
                max_files=1,
                max_file_size=MAX_LINK_CHARS,
                on_upload=self._import_link_upload,
                on_rejected=lambda: ui.notify(
                    "The link exceeds the import size limit. Choose a share file.", type="warning"
                ),
            ).classes("pb-long-link-upload hidden")
            with ui.row().classes("pb-actions"):
                _ = ui.button("Cancel", on_click=self.close).props("flat no-caps")
                self._submit: ui.button = ui.button("Import").props("unelevated no-caps")
                _ = self._submit.on(
                    "click",
                    self._submit_source,
                    js_handler="""(event) => {
                        const panel = event.target.closest('.pb-dialog');
                        const link = panel.querySelector('.pb-pasted-link input').value.trim();
                        if (link.length <= 65536) { emit({link}); return; }
                        // Socket.IO limits event frames. Upload the complete text to the local editor instead.
                        try {
                            const input = panel.querySelector('.pb-long-link-upload input[type=file]');
                            const transfer = new DataTransfer();
                            transfer.items.add(new File([link], 'pasted-link.txt', {type: 'text/plain'}));
                            input.files = transfer.files;
                            input.dispatchEvent(new Event('change', {bubbles: true}));
                        } catch {
                            Quasar.Notify.create('Open the link in the viewer, download its share file, and import that file.');
                        }
                    }""",
                )
                _ = self._submit.disable()
        _ = self._uploader.on("removed", self._forget_file)
        _ = self._link.on("presence", self._link_changed)
        _ = self.on("hide", self.delete)

    def _is_open(self) -> bool:
        return not self.is_deleted and self.value and self._is_current()

    def _sync_controls(self) -> None:
        ready: bool = self._contents is not None or self._has_link
        _ = self._submit.set_enabled(ready and not self._busy)
        self._link.set_busy(self._busy)
        _ = self._uploader.set_enabled(not self._busy)

    def _forget_file(self) -> None:
        self._contents = None
        self._sync_controls()

    def _link_changed(self, event: _ControlEvent) -> None:
        self._has_link = event.args == {"hasText": True}
        if self._has_link and self._contents is not None:
            self._contents = None
            _ = self._uploader.reset()
        self._sync_controls()

    async def _load_file(self, event: events.UploadEventArguments) -> None:
        if self._busy or not self._is_open():
            return
        self._busy = True
        self._sync_controls()
        try:
            if event.file.size() > MAX_SHARE_BYTES:
                raise ValueError("The share file exceeds the size limit.")
            contents: bytes = await event.file.read()
            if self._is_open():
                self._contents = contents
                self._has_link = False
                _ = self._link.run_method("clear")
        except (ValueError, OSError) as error:
            if self._is_open():
                self._contents = None
                _ = self._uploader.reset()
                ui.notify(str(error)[:250], type="negative")
        finally:
            self._busy = False
            if self._is_open():
                self._sync_controls()

    def _prepare(self, pasted: str, contents: bytes | None) -> ShareSnapshot:
        snapshot: ShareSnapshot = decode_share(contents) if contents is not None else decode_link(pasted)
        validate_import_size(self._recipient, snapshot)
        return snapshot

    async def _submit_source(self, event: _ControlEvent) -> None:
        try:
            link: str = _SubmittedLink.model_validate(event.args).link
        except ValidationError:
            return
        await self._apply(link)

    async def _import_link_upload(self, event: events.UploadEventArguments) -> None:
        if not self._is_open() or self._busy:
            return
        try:
            if event.file.size() > MAX_LINK_CHARS:
                raise ValueError("Choose a share file. The link exceeds the import size limit.")
            text: str = (await event.file.read()).decode("utf-8")
            await self._apply(text)
        except (ValueError, OSError) as error:
            if self._is_open():
                ui.notify(_error_text(error) if isinstance(error, ValueError) else str(error)[:250], type="negative")
        finally:
            if self._is_open():
                _ = self._long_link_upload.reset()

    async def _apply(self, pasted: str) -> None:
        if self._busy or not self._is_open() or not self._submit.enabled:
            return
        self._busy = True
        self._sync_controls()
        _ = self._submit.props("loading")
        try:
            snapshot = await asyncio.to_thread(self._prepare, pasted, None if pasted else self._contents)
            if self._is_open():
                self._imported(snapshot)
        except ValueError as error:
            if self._is_open():
                ui.notify(_error_text(error), type="negative")
        finally:
            self._busy = False
            if self._is_open():
                _ = self._submit.props(remove="loading")
                self._sync_controls()


def import_dialog(
    recipient: GridironPlaybook, imported: Callable[[ShareSnapshot], None], is_current: Callable[[], bool]
) -> ui.dialog:
    """Choose a link or file to import into the open playbook."""
    return _ImportDialog(recipient, imported, is_current).open()
