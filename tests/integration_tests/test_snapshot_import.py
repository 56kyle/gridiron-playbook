from importlib.util import find_spec
from pathlib import Path

import pytest

from gridiron_playbook.block import ends_with_block
from gridiron_playbook.editor import PlaybookEditor
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.playbook import playbook_to_sav
from gridiron_playbook.playbook import sav_to_playbook
from gridiron_playbook.point import GridironPoint
from gridiron_playbook.quickshare.codec import decode_share
from gridiron_playbook.quickshare.codec import encode_share
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.route import GridironRoute


_EMPTY_IMPORT = "at least one play"


@pytest.fixture
def original(custom_plays_json: str) -> GridironPlaybook:
    return GridironPlaybook.model_validate_json(custom_plays_json)


@pytest.fixture
def large_snapshot(original: GridironPlaybook) -> ShareSnapshot:
    sender = PlaybookEditor(original)
    sender.add_route_block(0, 0, len(sender.plays[0].routes[0].points) - 1)
    unusual = sender.plays[0].model_copy(update={"formation_name": "Custom spread"})
    plays: tuple[GridironPlay, ...] = (unusual, *(sender.plays[i % len(sender.plays)] for i in range(123)), unusual)
    return ShareSnapshot(version=1, kind="playbook", plays=plays)


def test_import_plays_with_large_share_file(
    original: GridironPlaybook, large_snapshot: ShareSnapshot, tmp_path: Path
) -> None:
    editor = PlaybookEditor(original)
    previous = original.root.properties.custom_plays
    share_file: Path = tmp_path / "full-book.gridironshare"
    _ = share_file.write_bytes(encode_share(large_snapshot))
    index = editor.import_plays(decode_share(share_file.read_bytes()).plays)
    assert index == 0
    assert editor.revision == 1
    imported = editor.playbook
    assert editor.plays == (*large_snapshot.plays, *previous)
    editor.undo()
    assert editor.playbook == original
    assert not editor.can_undo
    editor.redo()
    assert editor.playbook == imported

    reopened = sav_to_playbook(playbook_to_sav(imported))
    assert reopened.root.properties.custom_plays == (*large_snapshot.plays, *previous)
    assert ends_with_block(reopened.root.properties.custom_plays[index].routes[0].points)
    unchanged = {"root": {"properties": {"custom_plays"}}}
    assert reopened.model_dump(exclude=unchanged, exclude_unset=True) == original.model_dump(
        exclude=unchanged, exclude_unset=True
    )


def test_import_plays_with_empty_collection(original: GridironPlaybook) -> None:
    editor = PlaybookEditor(original)
    with pytest.raises(ValueError, match=_EMPTY_IMPORT):
        _ = editor.import_plays(())
    assert editor.revision == 0


@pytest.mark.skipif(find_spec("nicegui") is None, reason="The upload decoder uses the web extra.")
def test_decode_uploaded_playbook_with_dense_import(original: GridironPlaybook) -> None:
    from gridiron_playbook.web.playbook_files import decode_uploaded_playbook

    node = GridironPoint(X_0=250, Y_0=125, Z_0=0)
    route = GridironRoute(Slot_0=5, Points_0=(node,) * 1000)
    play = GridironPlay(FormationName_0="Twins Right", PlayName_0="Dense", Routes_0=(route,))
    incoming = ShareSnapshot(version=1, kind="playbook", plays=(play,) * 125)
    editor = PlaybookEditor(original)
    _ = editor.import_plays(incoming.plays)
    data = playbook_to_sav(editor.playbook)
    assert len(data) > 16 * 1024 * 1024

    reopened = decode_uploaded_playbook("Imported.sav", data)
    assert reopened.root.properties.custom_plays == (*incoming.plays, *original.root.properties.custom_plays)


def test_validate_import_size_with_combined_oversized_save(
    original: GridironPlaybook, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gridiron_playbook.web import playbook_files

    editor = PlaybookEditor(original)
    room: int = len(playbook_to_sav(original))
    monkeypatch.setattr(playbook_files, "MAX_SAVE_BYTES", room)
    single = ShareSnapshot(version=1, kind="play", plays=editor.plays[:1])

    with pytest.raises(playbook_files.PlaybookFileError):
        playbook_files.validate_import_size(editor.playbook, single)
    assert editor.playbook is original
    assert editor.revision == 0


def test_validate_import_size_with_whole_book_in_new_tab(
    original: GridironPlaybook, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gridiron_playbook.web import playbook_files

    monkeypatch.setattr(playbook_files, "MAX_SAVE_BYTES", len(playbook_to_sav(original)))
    snapshot = ShareSnapshot(version=1, kind="playbook", plays=original.root.properties.custom_plays)
    playbook_files.validate_import_size(original, snapshot)
