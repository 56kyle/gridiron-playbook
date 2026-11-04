"""Coordinate open playbooks, ordered transfers, and shared edit history."""

from collections import deque
from dataclasses import dataclass
from dataclasses import field
from uuid import uuid4

from gridiron_playbook.editor import PlaybookEditor
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.playbook import playbook_to_sav


_HISTORY_LIMIT = 100
DEFAULT_MAX_SAVE_BYTES = 64 * 1024 * 1024


class PlaybookCapacityError(ValueError):
    """A resulting playbook cannot fit the editor's save-file limit."""


@dataclass
class PlaybookTab:
    """An open document with stable identity and a download baseline."""

    filename: str
    editor: PlaybookEditor
    id: str = field(default_factory=lambda: uuid4().hex)
    saved_document: GridironPlaybook = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Remember the opened document as the initial download baseline."""
        self.saved_document = self.editor.playbook

    @property
    def dirty(self) -> bool:
        """Whether this document differs from its last opened or downloaded version."""
        return self.editor.playbook != self.saved_document


@dataclass(frozen=True)
class _DocumentChange:
    tab_id: str
    before: GridironPlaybook
    after: GridironPlaybook


def document_with_plays(document: GridironPlaybook, plays: tuple[GridironPlay, ...]) -> GridironPlaybook:
    """Replace plays while retaining the document's Unreal save metadata."""
    properties = document.root.properties.model_copy(update={"custom_plays": plays})
    root = document.root.model_copy(update={"properties": properties})
    return document.model_copy(update={"root": root})


def _selection(indices: tuple[int, ...], length: int) -> tuple[int, ...]:
    if not indices:
        raise ValueError("Select at least one play.")
    if any(type(index) is not int or not 0 <= index < length for index in indices):
        raise IndexError("A selected play is no longer available.")
    if len(set(indices)) != len(indices):
        raise ValueError("Select each play only once.")
    return tuple(sorted(indices))


def _insertion(index: int, length: int) -> None:
    if type(index) is not int or not 0 <= index <= length:
        raise IndexError("The insertion position is outside the playbook.")


class PlaybookWorkspace:
    """Own tabs and one chronological undo history across their documents."""

    def __init__(self, *, max_save_bytes: int = DEFAULT_MAX_SAVE_BYTES) -> None:
        """Start an empty workspace with a configurable encoded save-size limit."""
        if max_save_bytes <= 0:
            raise ValueError("The save-file limit must be positive.")
        self._max_save_bytes: int = max_save_bytes
        self._tabs: dict[str, PlaybookTab] = {}
        self._open: list[str] = []
        self._active_id: str | None = None
        self._baseline: dict[str, GridironPlaybook] = {}
        self._undo: deque[tuple[_DocumentChange, ...]] = deque(maxlen=_HISTORY_LIMIT)
        self._redo: list[tuple[_DocumentChange, ...]] = []

    @property
    def tabs(self) -> tuple[PlaybookTab, ...]:
        """Currently open tabs in their display order."""
        return tuple(self._tabs[tab_id] for tab_id in self._open)

    @property
    def active(self) -> PlaybookTab | None:
        """The selected tab, or None when the workspace is empty."""
        return self._tabs[self._active_id] if self._active_id is not None else None

    @property
    def can_undo(self) -> bool:
        """Whether a completed workspace edit can be undone."""
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        """Whether an undone workspace edit can be restored."""
        return bool(self._redo)

    def get_tab(self, tab_id: str) -> PlaybookTab:
        """Return an open tab or raise KeyError for a stale tab identifier."""
        if tab_id not in self._open:
            raise KeyError(tab_id)
        return self._tabs[tab_id]

    def add(self, document: GridironPlaybook, filename: str) -> PlaybookTab:
        """Open and activate another playbook without replacing existing tabs."""
        self.checkpoint()
        tab = PlaybookTab(filename=filename, editor=PlaybookEditor(document))
        self._tabs[tab.id] = tab
        self._open.append(tab.id)
        self._baseline[tab.id] = document
        self._active_id = tab.id
        return tab

    def activate(self, tab_id: str) -> None:
        """Select an open tab without changing edit history."""
        _ = self.get_tab(tab_id)
        self._active_id = tab_id

    def close(self, tab_id: str) -> None:
        """Close a tab, retaining documents needed to undo previous transfers."""
        _ = self.get_tab(tab_id)
        self.checkpoint()
        index: int = self._open.index(tab_id)
        self._open.remove(tab_id)
        if self._active_id == tab_id:
            self._active_id = self._open[min(index, len(self._open) - 1)] if self._open else None
        self._prune_closed_tabs()

    def mark_saved(self, tab_id: str, document: GridironPlaybook) -> None:
        """Record the exact downloaded version even if edits occurred during encoding."""
        tab: PlaybookTab | None = self._tabs.get(tab_id)
        if tab is not None:
            tab.saved_document = document

    def _prune_closed_tabs(self) -> None:
        retained: set[str] = set(self._open)
        for transaction in (*self._undo, *self._redo):
            retained.update(change.tab_id for change in transaction)
        for tab_id in tuple(self._tabs):
            if tab_id not in retained:
                del self._tabs[tab_id]
                del self._baseline[tab_id]

    def checkpoint(self) -> None:
        """Record completed direct editor mutations as one workspace transaction."""
        changes: tuple[_DocumentChange, ...] = tuple(
            _DocumentChange(tab.id, self._baseline[tab.id], tab.editor.playbook)
            for tab in self.tabs
            if self._baseline[tab.id] != tab.editor.playbook
        )
        if changes:
            self._record(changes)

    def _record(self, changes: tuple[_DocumentChange, ...]) -> None:
        self._undo.append(changes)
        self._redo.clear()
        for change in changes:
            self._baseline[change.tab_id] = change.after
        self._prune_closed_tabs()

    def undo(self) -> None:
        """Restore all documents affected by the latest edit together."""
        self.checkpoint()
        if self._undo:
            changes = self._undo.pop()
            self._restore(tuple((change.tab_id, change.before) for change in changes))
            self._redo.append(changes)
            self._prune_closed_tabs()

    def redo(self) -> None:
        """Reapply all documents affected by the next undone edit together."""
        self.checkpoint()
        if self._redo:
            changes = self._redo.pop()
            self._restore(tuple((change.tab_id, change.after) for change in changes))
            self._undo.append(changes)
            self._prune_closed_tabs()

    def _restore(self, documents: tuple[tuple[str, GridironPlaybook], ...]) -> None:
        for tab_id, document in documents:
            self._tabs[tab_id].editor = PlaybookEditor(document)
            self._baseline[tab_id] = document
            if tab_id not in self._open:
                self._open.append(tab_id)
        self._active_id = documents[0][0]

    def _commit(self, documents: tuple[tuple[PlaybookTab, GridironPlaybook], ...]) -> None:
        changes: tuple[_DocumentChange, ...] = tuple(
            _DocumentChange(tab.id, tab.editor.playbook, document)
            for tab, document in documents
            if tab.editor.playbook != document
        )
        if changes:
            self.checkpoint()
            for change in changes:
                self._tabs[change.tab_id].editor = PlaybookEditor(change.after)
            self._record(changes)

    def _validate_save(self, document: GridironPlaybook) -> None:
        if len(playbook_to_sav(document)) > self._max_save_bytes:
            raise PlaybookCapacityError("The combined playbook exceeds the save-file size limit.")

    def copy_plays(
        self, source_id: str, indices: tuple[int, ...], destination_id: str, insertion_index: int = 0
    ) -> tuple[int, ...]:
        """Copy selected plays in source order, validating the complete destination first."""
        source: PlaybookTab = self.get_tab(source_id)
        destination: PlaybookTab = self.get_tab(destination_id)
        selected: tuple[int, ...] = _selection(indices, len(source.editor.plays))
        _insertion(insertion_index, len(destination.editor.plays))
        plays: tuple[GridironPlay, ...] = tuple(source.editor.plays[index] for index in selected)
        existing: tuple[GridironPlay, ...] = destination.editor.plays
        document: GridironPlaybook = document_with_plays(
            destination.editor.playbook, (*existing[:insertion_index], *plays, *existing[insertion_index:])
        )
        self._validate_save(document)
        self._commit(((destination, document),))
        return tuple(range(insertion_index, insertion_index + len(plays)))

    def move_plays(
        self, source_id: str, indices: tuple[int, ...], destination_id: str, insertion_index: int = 0
    ) -> tuple[int, ...]:
        """Move plays atomically so Undo restores both source and destination together."""
        if source_id == destination_id:
            return self.reorder_plays(source_id, indices, insertion_index)
        source: PlaybookTab = self.get_tab(source_id)
        destination: PlaybookTab = self.get_tab(destination_id)
        selected: tuple[int, ...] = _selection(indices, len(source.editor.plays))
        _insertion(insertion_index, len(destination.editor.plays))
        selection: set[int] = set(selected)
        plays: tuple[GridironPlay, ...] = tuple(source.editor.plays[index] for index in selected)
        remaining: tuple[GridironPlay, ...] = tuple(
            play for index, play in enumerate(source.editor.plays) if index not in selection
        )
        existing: tuple[GridironPlay, ...] = destination.editor.plays
        combined: GridironPlaybook = document_with_plays(
            destination.editor.playbook, (*existing[:insertion_index], *plays, *existing[insertion_index:])
        )
        self._validate_save(combined)
        self._commit(((source, document_with_plays(source.editor.playbook, remaining)), (destination, combined)))
        return tuple(range(insertion_index, insertion_index + len(plays)))

    def reorder_plays(self, tab_id: str, indices: tuple[int, ...], insertion_index: int) -> tuple[int, ...]:
        """Place selected plays at an original-list gap while preserving their relative order."""
        tab: PlaybookTab = self.get_tab(tab_id)
        existing: tuple[GridironPlay, ...] = tab.editor.plays
        selected: tuple[int, ...] = _selection(indices, len(existing))
        _insertion(insertion_index, len(existing))
        selection: set[int] = set(selected)
        plays: tuple[GridironPlay, ...] = tuple(existing[index] for index in selected)
        remaining: tuple[GridironPlay, ...] = tuple(
            play for index, play in enumerate(existing) if index not in selection
        )
        target: int = insertion_index - sum(index < insertion_index for index in selected)
        reordered: tuple[GridironPlay, ...] = (*remaining[:target], *plays, *remaining[target:])
        self._commit(((tab, document_with_plays(tab.editor.playbook, reordered)),))
        return tuple(range(target, target + len(plays)))
