"""Working-copy recovery validates state before permitting writes."""

from __future__ import annotations

from importlib.util import find_spec
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from pydantic import ValidationError

from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.working_copy import WorkingCopyStore
from gridiron_playbook.workspace import PlaybookWorkspace
from gridiron_playbook.workspace import WorkspaceSnapshot


if TYPE_CHECKING:
    from pathlib import Path

    from gridiron_playbook.web.recovery import RecoveryState


if find_spec("nicegui") is None:
    pytest.skip("Install the web extra to test recovery integration.", allow_module_level=True)


_RESTORE_REQUIRED = "Restore or start"


@pytest.fixture
def store(tmp_path: Path) -> WorkingCopyStore:
    return WorkingCopyStore(tmp_path / "working.sqlite3")


@pytest.fixture
def state() -> RecoveryState:
    from gridiron_playbook.web.recovery import RecoveryState

    return RecoveryState(version=1, workspace=PlaybookWorkspace().snapshot())


def test_restore_with_corrupt_state(store: WorkingCopyStore, state: RecoveryState) -> None:
    from gridiron_playbook.web.recovery import RecoveryIdentity
    from gridiron_playbook.web.recovery import WorkingRecovery

    identifier = uuid4().hex
    record = store.save(identifier, b'{"version":999}', expected_revision=0)
    recovery = WorkingRecovery(store)
    with pytest.raises(ValidationError):
        _ = recovery.restore(RecoveryIdentity(workspace_id=identifier, source_id=identifier))
    with pytest.raises(ValueError, match=_RESTORE_REQUIRED):
        _ = recovery.save(state)
    assert store.load(identifier) == record


def test_start_new_with_corrupt_state_preserved(store: WorkingCopyStore, state: RecoveryState) -> None:
    from gridiron_playbook.web.recovery import RecoveryIdentity
    from gridiron_playbook.web.recovery import WorkingRecovery

    identifier = uuid4().hex
    record = store.save(identifier, b"invalid recovery", expected_revision=0)
    recovery = WorkingRecovery(store)
    with pytest.raises(ValidationError):
        _ = recovery.restore(RecoveryIdentity(workspace_id=identifier, source_id=identifier))
    recovery.start_new()
    fresh = recovery.save(state)
    assert fresh != identifier
    assert store.load(identifier) == record


def test_restore_with_independent_copy(store: WorkingCopyStore, state: RecoveryState) -> None:
    from gridiron_playbook.web.recovery import RecoveryIdentity
    from gridiron_playbook.web.recovery import WorkingRecovery

    source_id, destination_id = uuid4().hex, uuid4().hex
    record = store.save(source_id, state.model_dump_json().encode(), expected_revision=0)
    recovery = WorkingRecovery(store)
    restored = recovery.restore(RecoveryIdentity(workspace_id=destination_id, source_id=source_id))
    assert restored == state
    assert recovery.revision == 0
    assert recovery.save(state) == destination_id
    assert store.load(source_id) == record
    assert store.load(destination_id) is not None


def test_save_with_unchanged_state(store: WorkingCopyStore, state: RecoveryState) -> None:
    from gridiron_playbook.web.recovery import WorkingRecovery

    recovery = WorkingRecovery(store)
    recovery.start_new()
    identifier = recovery.save(state)
    _ = recovery.save(state)
    assert recovery.workspace_id == identifier
    assert recovery.revision == 1


def test_save_with_competing_writer(store: WorkingCopyStore, state: RecoveryState, custom_plays_json: str) -> None:
    from gridiron_playbook.web.recovery import RecoveryIdentity
    from gridiron_playbook.web.recovery import RecoveryState
    from gridiron_playbook.web.recovery import WorkingRecovery

    identifier = uuid4().hex
    _ = store.save(identifier, state.model_dump_json().encode(), expected_revision=0)
    first, second = WorkingRecovery(store), WorkingRecovery(store)
    identity = RecoveryIdentity(workspace_id=identifier, source_id=identifier)
    _ = first.restore(identity)
    _ = second.restore(identity)
    workspace = PlaybookWorkspace()
    tab = workspace.add(GridironPlaybook.model_validate_json(custom_plays_json), "local.sav")
    tab.editor.rename_play(0, "First window")
    first_edit = RecoveryState(version=1, workspace=workspace.snapshot())
    _ = first.save(first_edit)
    tab.editor.rename_play(0, "Second window")
    second_edit = RecoveryState(version=1, workspace=workspace.snapshot())
    fork = second.save(second_edit)
    assert fork != identifier
    original_record = store.load(identifier)
    assert original_record is not None
    assert RecoveryState.model_validate_json(original_record.data) == first_edit
    forked_record = store.load(fork)
    assert forked_record is not None
    assert RecoveryState.model_validate_json(forked_record.data) == second_edit


def test_validate_views_with_draft_without_active_play() -> None:
    from gridiron_playbook.web.recovery import RecoveryState
    from gridiron_playbook.web.recovery import SavedDraft

    with pytest.raises(ValidationError):
        _ = RecoveryState(version=1, workspace=WorkspaceSnapshot(tabs=(), active_id=None), draft=SavedDraft(slot=1))
