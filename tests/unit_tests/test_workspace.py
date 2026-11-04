"""Workspace ordering and history across open playbooks."""

from weakref import ref

import pytest

from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.playbook import playbook_to_sav
from gridiron_playbook.workspace import PlaybookCapacityError
from gridiron_playbook.workspace import PlaybookWorkspace

# The test contract includes these private composing functions.
from gridiron_playbook.workspace import _insertion  # pyright: ignore[reportPrivateUsage]
from gridiron_playbook.workspace import _selection  # pyright: ignore[reportPrivateUsage]
from gridiron_playbook.workspace import document_with_plays


@pytest.fixture
def document(custom_plays_json: str) -> GridironPlaybook:
    original = GridironPlaybook.model_validate_json(custom_plays_json)
    plays = tuple(original.root.properties.custom_plays[0].model_copy(update={"play_name": str(i)}) for i in range(5))
    return document_with_plays(original, plays)


def test__selection_with_disjoint_order() -> None:
    assert _selection((4, 0, 2), 5) == (0, 2, 4)


@pytest.mark.parametrize("indices", [(-1,), (5,), (True,)])
def test__selection_with_invalid_indices(indices: tuple[int, ...]) -> None:
    with pytest.raises(IndexError):
        _ = _selection(indices, 5)


@pytest.mark.parametrize("gap", [-1, 6, True])
def test__insertion_with_invalid_gap(gap: int) -> None:
    with pytest.raises(IndexError):
        _insertion(gap, 5)


def test_add_with_same_filename(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    first = workspace.add(document, "book.sav")
    second = workspace.add(document, "book.sav")
    assert first.id != second.id
    assert workspace.tabs == (first, second)
    assert workspace.active is second
    assert not workspace.can_undo


def test_checkpoint_with_independent_editors(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    first = workspace.add(document, "first.sav")
    second = workspace.add(document, "second.sav")
    first.editor.rename_play(0, "Changed")
    workspace.checkpoint()
    assert second.editor.playbook == document
    assert first.dirty
    workspace.undo()
    assert first.editor.playbook == document
    assert not first.dirty
    workspace.redo()
    assert first.editor.plays[0].play_name == "Changed"


def test_copy_plays_with_source_order_and_destination_metadata(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    first = workspace.add(document, "first.sav")
    properties = document.root.properties.model_copy(
        update={"last_was_drawn": not document.root.properties.last_was_drawn}
    )
    recipient = document.model_copy(update={"root": document.root.model_copy(update={"properties": properties})})
    second = workspace.add(recipient, "second.sav")
    selected = workspace.copy_plays(first.id, (3, 1), second.id)
    assert selected == (0, 1)
    assert first.editor.playbook == document
    expected = document_with_plays(
        recipient, (first.editor.plays[1], first.editor.plays[3], *document.root.properties.custom_plays)
    )
    assert second.editor.playbook == expected


def test_move_plays_with_atomic_history(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    first = workspace.add(document, "first.sav")
    second = workspace.add(document, "second.sav")
    original = document.root.properties.custom_plays
    assert workspace.move_plays(first.id, (3, 1), second.id) == (0, 1)
    moved_source = document_with_plays(document, (original[0], original[2], original[4]))
    moved_destination = document_with_plays(document, (original[1], original[3], *original))
    assert (first.editor.playbook, second.editor.playbook) == (moved_source, moved_destination)
    second.editor.rename_play(0, "Later edit")
    workspace.checkpoint()
    workspace.undo()
    assert (first.editor.playbook, second.editor.playbook) == (moved_source, moved_destination)
    workspace.undo()
    assert (first.editor.playbook, second.editor.playbook) == (document, document)
    workspace.redo()
    assert (first.editor.playbook, second.editor.playbook) == (moved_source, moved_destination)
    workspace.redo()
    assert second.editor.plays[0].play_name == "Later edit"


@pytest.mark.parametrize(
    ("indices", "gap", "expected"),
    [((1, 3), 5, (0, 2, 4, 1, 3)), ((1, 3), 0, (1, 3, 0, 2, 4)), ((1, 3), 3, (0, 2, 1, 3, 4))],
)
def test_reorder_plays(
    document: GridironPlaybook, indices: tuple[int, ...], gap: int, expected: tuple[int, ...]
) -> None:
    workspace = PlaybookWorkspace()
    tab = workspace.add(document, "book.sav")
    _ = workspace.reorder_plays(tab.id, indices, gap)
    assert tuple(play.play_name for play in tab.editor.plays) == tuple(str(i) for i in expected)
    workspace.undo()
    assert tab.editor.playbook == document


@pytest.mark.parametrize("indices", [(), (1, 1), (-1,), (5,)])
def test_move_plays_with_invalid_selection(document: GridironPlaybook, indices: tuple[int, ...]) -> None:
    workspace = PlaybookWorkspace()
    first = workspace.add(document, "first.sav")
    second = workspace.add(document, "second.sav")
    with pytest.raises((ValueError, IndexError)):
        _ = workspace.move_plays(first.id, indices, second.id)
    assert (first.editor.playbook, second.editor.playbook) == (document, document)
    assert not workspace.can_undo


def test_move_plays_with_invalid_destination_gap(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    first = workspace.add(document, "first.sav")
    second = workspace.add(document, "second.sav")
    with pytest.raises(IndexError):
        _ = workspace.move_plays(first.id, (0,), second.id, 6)
    assert (first.editor.playbook, second.editor.playbook) == (document, document)


def test_move_plays_with_size_limit(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace(max_save_bytes=len(playbook_to_sav(document)))
    first = workspace.add(document, "first.sav")
    second = workspace.add(document, "second.sav")
    with pytest.raises(PlaybookCapacityError):
        _ = workspace.move_plays(first.id, (0,), second.id)
    assert (first.editor.playbook, second.editor.playbook) == (document, document)
    assert not workspace.can_undo


def test_undo_with_closed_destination(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    first = workspace.add(document, "first.sav")
    second = workspace.add(document, "second.sav")
    _ = workspace.move_plays(first.id, (0,), second.id)
    workspace.close(second.id)
    workspace.undo()
    assert workspace.get_tab(second.id).editor.playbook == document
    assert first.editor.playbook == document


def test_checkpoint_with_redo_branch(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    first = workspace.add(document, "first.sav")
    second = workspace.add(document, "second.sav")
    _ = workspace.copy_plays(first.id, (0,), second.id)
    workspace.undo()
    first.editor.rename_play(0, "Replacement")
    workspace.checkpoint()
    assert not workspace.can_redo


def test_mark_saved_with_older_download(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    tab = workspace.add(document, "book.sav")
    tab.editor.rename_play(0, "Changed")
    workspace.checkpoint()
    workspace.mark_saved(tab.id, document)
    assert tab.dirty
    workspace.mark_saved(tab.id, tab.editor.playbook)
    assert not tab.dirty


def test_close_with_unreferenced_tab(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    tab = workspace.add(document, "book.sav")
    tab_id = tab.id
    reference = ref(tab)
    workspace.close(tab_id)
    del tab
    assert reference() is None
    workspace.mark_saved(tab_id, document)
    assert workspace.tabs == ()


def test_checkpoint_with_closed_tab_in_abandoned_redo(document: GridironPlaybook) -> None:
    workspace = PlaybookWorkspace()
    source = workspace.add(document, "source.sav")
    destination = workspace.add(document, "destination.sav")
    reference = ref(destination)
    _ = workspace.copy_plays(source.id, (0,), destination.id)
    workspace.undo()
    workspace.close(destination.id)
    del destination
    assert reference() is not None
    source.editor.rename_play(0, "New branch")
    workspace.checkpoint()
    assert reference() is None
