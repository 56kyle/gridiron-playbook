"""Recovery storage preserves working documents independently of source saves."""

from pathlib import Path
from uuid import uuid4

import pytest

from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.playbook import playbook_to_sav
from gridiron_playbook.playbook import sav_to_playbook
from gridiron_playbook.working_copy import WorkingCopyStore
from gridiron_playbook.workspace import PlaybookWorkspace
from gridiron_playbook.workspace import WorkspaceSnapshot
from gridiron_playbook.workspace import document_with_plays


@pytest.fixture
def original_file(custom_plays_json: str, tmp_path: Path) -> Path:
    original = GridironPlaybook.model_validate_json(custom_plays_json)
    plays = tuple(
        original.root.properties.custom_plays[0].model_copy(update={"play_name": f"Play {index}"})
        for index in range(125)
    )
    path = tmp_path / "original.sav"
    _ = path.write_bytes(playbook_to_sav(document_with_plays(original, plays)))
    return path


def test_save_with_large_playbook_recovery(original_file: Path, tmp_path: Path) -> None:
    original_bytes = original_file.read_bytes()
    workspace = PlaybookWorkspace()
    tab = workspace.add(sav_to_playbook(original_bytes), original_file.name)
    tab.editor.rename_play(100, "Recovered working edit")
    working_database = tmp_path / "working" / "recovery.sqlite3"
    identifier = uuid4().hex
    _ = WorkingCopyStore(working_database).save(
        identifier,
        workspace.snapshot().model_dump_json(by_alias=True, exclude_unset=True).encode(),
        expected_revision=0,
    )
    loaded = WorkingCopyStore(working_database).load(identifier)
    assert loaded is not None
    recovered = PlaybookWorkspace.from_snapshot(WorkspaceSnapshot.model_validate_json(loaded.data))
    assert recovered.active is not None
    assert len(recovered.active.editor.plays) == 125
    assert recovered.active.editor.plays[100].play_name == "Recovered working edit"
    assert recovered.active.dirty
    assert original_file.read_bytes() == original_bytes


def test_save_with_closed_workspace_recovery(original_file: Path, tmp_path: Path) -> None:
    workspace = PlaybookWorkspace()
    tab = workspace.add(sav_to_playbook(original_file.read_bytes()), original_file.name)
    identifier = uuid4().hex
    store = WorkingCopyStore(tmp_path / "working.sqlite3")
    first = store.save(identifier, workspace.snapshot().model_dump_json().encode(), expected_revision=0)
    workspace.close(tab.id)
    _ = store.save(identifier, workspace.snapshot().model_dump_json().encode(), expected_revision=first.revision)
    loaded = store.load(identifier)
    assert loaded is not None
    recovered = PlaybookWorkspace.from_snapshot(WorkspaceSnapshot.model_validate_json(loaded.data))
    assert recovered.tabs == ()
    assert recovered.active is None
