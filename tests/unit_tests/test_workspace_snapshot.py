"""Working snapshots preserve open documents and their download baselines."""

import pytest
from pydantic import ValidationError

from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.workspace import PlaybookWorkspace
from gridiron_playbook.workspace import TabSnapshot
from gridiron_playbook.workspace import WorkspaceSnapshot


@pytest.fixture
def document(custom_plays_json: str) -> GridironPlaybook:
    return GridironPlaybook.model_validate_json(custom_plays_json)


def test_snapshot_with_open_tabs(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    first = workspace.add(document, "first.sav")
    second = workspace.add(document, "second.sav")
    workspace.activate(first.id)
    snapshot = workspace.snapshot()
    assert tuple((tab.id, tab.filename) for tab in snapshot.tabs) == (
        (first.id, "first.sav"),
        (second.id, "second.sav"),
    )
    assert snapshot.active_id == first.id


def test_snapshot_with_closed_history_tab(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    source = workspace.add(document, "source.sav")
    destination = workspace.add(document, "destination.sav")
    _ = workspace.move_plays(source.id, (0,), destination.id)
    workspace.close(destination.id)
    assert tuple(tab.id for tab in workspace.snapshot().tabs) == (source.id,)


def test_snapshot_with_all_tabs_closed(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    tab = workspace.add(document, "book.sav")
    workspace.close(tab.id)
    assert workspace.snapshot() == WorkspaceSnapshot(tabs=(), active_id=None)


def test_from_snapshot_with_document_field_presence(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    tab = workspace.add(document, "book.sav")
    tab.editor.rename_play(0, "Working edit")
    snapshot = WorkspaceSnapshot.model_validate_json(
        workspace.snapshot().model_dump_json(by_alias=True, exclude_unset=True)
    )
    restored = PlaybookWorkspace.from_snapshot(snapshot)
    assert restored.active is not None
    assert restored.active.id == tab.id
    assert restored.active.editor.playbook.model_dump(exclude_unset=True) == tab.editor.playbook.model_dump(
        exclude_unset=True
    )
    assert restored.active.saved_document.model_dump(exclude_unset=True) == document.model_dump(exclude_unset=True)


def test_from_snapshot_with_dirty_and_downloaded_tabs(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    dirty = workspace.add(document, "dirty.sav")
    clean = workspace.add(document, "downloaded.sav")
    dirty.editor.rename_play(0, "Unsaved")
    clean.editor.rename_play(0, "Downloaded")
    workspace.mark_saved(clean.id, clean.editor.playbook)
    restored = PlaybookWorkspace.from_snapshot(workspace.snapshot())
    assert restored.get_tab(dirty.id).dirty
    assert not restored.get_tab(clean.id).dirty


def test_from_snapshot_with_new_history(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    tab = workspace.add(document, "book.sav")
    tab.editor.rename_play(0, "Saved working state")
    workspace.checkpoint()
    restored = PlaybookWorkspace.from_snapshot(workspace.snapshot())
    assert not restored.can_undo
    assert not restored.can_redo
    active = restored.get_tab(tab.id)
    active.editor.rename_play(0, "New edit")
    restored.checkpoint()
    restored.undo()
    assert active.editor.plays[0].play_name == "Saved working state"


@pytest.fixture
def tab_snapshot(document: GridironPlaybook) -> TabSnapshot:
    return TabSnapshot(id="tab", filename="book.sav", document=document, saved_document=document)


def test_workspace_snapshot_with_duplicate_tab_id(tab_snapshot: TabSnapshot) -> None:
    with pytest.raises(ValidationError):
        _ = WorkspaceSnapshot(tabs=(tab_snapshot, tab_snapshot), active_id="tab")


@pytest.mark.parametrize("active_id", [None, "missing"])
def test_workspace_snapshot_with_missing_active_tab(tab_snapshot: TabSnapshot, active_id: str | None) -> None:
    with pytest.raises(ValidationError):
        _ = WorkspaceSnapshot(tabs=(tab_snapshot,), active_id=active_id)


def test_workspace_snapshot_with_active_empty_workspace() -> None:
    with pytest.raises(ValidationError):
        _ = WorkspaceSnapshot(tabs=(), active_id="missing")
