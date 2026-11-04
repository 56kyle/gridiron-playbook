"""Durable working-copy storage with optimistic concurrency."""

import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from gzip import compress
from pathlib import Path
from uuid import uuid4

import pytest

from gridiron_playbook.working_copy import WorkingCopyConflictError
from gridiron_playbook.working_copy import WorkingCopyFormatError
from gridiron_playbook.working_copy import WorkingCopyStore
from gridiron_playbook.working_copy import WorkingCopyStoreError
from gridiron_playbook.working_copy import _decode_copy  # pyright: ignore[reportPrivateUsage]
from gridiron_playbook.working_copy import _integer_row  # pyright: ignore[reportPrivateUsage]

# Identifier normalization is part of the store's boundary contract.
from gridiron_playbook.working_copy import _workspace_id  # pyright: ignore[reportPrivateUsage]


_INVALID_UUID = "UUID"
_INTERRUPTED_WRITE = """
import os
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
connection.execute('PRAGMA cache_size = 1')
connection.execute('BEGIN IMMEDIATE')
connection.execute('UPDATE working_copies SET revision = 2, data = ? WHERE workspace_id = ?', (b'x' * 2_000_000, sys.argv[2]))
os._exit(0)
"""


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "recovery" / "working.sqlite3"


@pytest.fixture
def store(database_path: Path) -> WorkingCopyStore:
    return WorkingCopyStore(database_path)


@pytest.fixture
def workspace_id() -> str:
    return uuid4().hex


@pytest.fixture
def corrupt_store(store: WorkingCopyStore, database_path: Path, workspace_id: str) -> WorkingCopyStore:
    _ = store.save(workspace_id, b"original", expected_revision=0)
    with sqlite3.connect(database_path) as connection:
        _ = connection.execute("UPDATE working_copies SET data = ? WHERE workspace_id = ?", (b"broken", workspace_id))
    return store


def test__workspace_id_with_hyphenated_uuid() -> None:
    identifier = uuid4()
    assert _workspace_id(str(identifier)) == identifier.hex


@pytest.mark.parametrize("identifier", ["", "../original.sav", "not-a-uuid"])
def test__workspace_id_with_invalid_identifier(identifier: str) -> None:
    with pytest.raises(ValueError, match=_INVALID_UUID):
        _ = _workspace_id(identifier)


def test_load_with_missing_database(store: WorkingCopyStore, database_path: Path, workspace_id: str) -> None:
    assert store.load(workspace_id) is None
    assert not database_path.exists()


def test_load_with_missing_workspace(store: WorkingCopyStore, workspace_id: str) -> None:
    _ = store.save(uuid4().hex, b"another book", expected_revision=0)
    assert store.load(workspace_id) is None


def test_save_with_reopened_store(store: WorkingCopyStore, database_path: Path, workspace_id: str) -> None:
    contents = b'{"tabs": ["working copy"]}'
    saved = store.save(workspace_id, contents, expected_revision=0)
    assert (saved.workspace_id, saved.revision, saved.data) == (workspace_id, 1, contents)
    assert WorkingCopyStore(database_path).load(workspace_id) == saved


def test_save_with_current_revision(store: WorkingCopyStore, workspace_id: str) -> None:
    first = store.save(workspace_id, b"first", expected_revision=0)
    second = store.save(workspace_id, b"second", expected_revision=first.revision)
    assert (second.revision, second.data) == (2, b"second")
    assert store.load(workspace_id) == second


@pytest.mark.parametrize("expected_revision", [0, 1])
def test_save_with_stale_writer(
    store: WorkingCopyStore, database_path: Path, workspace_id: str, expected_revision: int
) -> None:
    _ = store.save(workspace_id, b"first", expected_revision=0)
    current = store.save(workspace_id, b"newer", expected_revision=1)
    other_writer = WorkingCopyStore(database_path)
    with pytest.raises(WorkingCopyConflictError):
        _ = other_writer.save(workspace_id, b"stale", expected_revision=expected_revision)
    assert store.load(workspace_id) == current


def test_save_with_unknown_revision(store: WorkingCopyStore, workspace_id: str) -> None:
    with pytest.raises(WorkingCopyConflictError):
        _ = store.save(workspace_id, b"working", expected_revision=1)
    assert store.load(workspace_id) is None


def test_save_with_simultaneous_writers(store: WorkingCopyStore, workspace_id: str) -> None:
    _ = store.save(workspace_id, b"first", expected_revision=0)
    with ThreadPoolExecutor(max_workers=2) as executor:
        writers = [
            executor.submit(store.save, workspace_id, contents, expected_revision=1) for contents in (b"left", b"right")
        ]
    failures = [writer.exception() for writer in writers]
    assert sum(failure is None for failure in failures) == 1
    assert sum(isinstance(failure, WorkingCopyConflictError) for failure in failures) == 1
    restored = store.load(workspace_id)
    assert restored is not None
    assert restored.revision == 2
    assert restored.data in (b"left", b"right")


def test_save_with_large_working_copy(store: WorkingCopyStore, workspace_id: str) -> None:
    contents = b"route points and metadata\n" * 1_000_000
    _ = store.save(workspace_id, contents, expected_revision=0)
    restored = store.load(workspace_id)
    assert restored is not None
    assert restored.data == contents


def test_load_with_corrupted_payload(corrupt_store: WorkingCopyStore, workspace_id: str) -> None:
    with pytest.raises(WorkingCopyFormatError):
        _ = corrupt_store.load(workspace_id)


@pytest.mark.parametrize("row", [(0, compress(b"state")), (1, b"broken"), ("1", compress(b"state"))])
def test__decode_copy_with_invalid_row(workspace_id: str, row: object) -> None:
    with pytest.raises(WorkingCopyFormatError):
        _ = _decode_copy(workspace_id, row)


def test__decode_copy_with_valid_row(workspace_id: str) -> None:
    record = _decode_copy(workspace_id, (3, compress(b"working")))
    assert (record.workspace_id, record.revision, record.data) == (workspace_id, 3, b"working")


@pytest.mark.parametrize("row", [None, (True,), ("1",), (1, 2)])
def test__integer_row_with_invalid_row(row: object) -> None:
    with pytest.raises(WorkingCopyFormatError):
        _ = _integer_row(row)


@pytest.fixture
def unsupported_store(database_path: Path) -> WorkingCopyStore:
    database_path.parent.mkdir()
    with sqlite3.connect(database_path) as connection:
        _ = connection.execute("PRAGMA user_version = 999")
    return WorkingCopyStore(database_path)


def test_load_with_unsupported_schema(unsupported_store: WorkingCopyStore, workspace_id: str) -> None:
    with pytest.raises(WorkingCopyFormatError):
        _ = unsupported_store.load(workspace_id)


@pytest.fixture
def blocked_store_path(tmp_path: Path) -> Path:
    path = tmp_path / "existing-file"
    _ = path.write_bytes(b"unrelated contents")
    return path / "working.sqlite3"


def test_save_with_unavailable_directory(blocked_store_path: Path, workspace_id: str) -> None:
    with pytest.raises(WorkingCopyStoreError):
        _ = WorkingCopyStore(blocked_store_path).save(workspace_id, b"new", expected_revision=0)
    assert blocked_store_path.parent.read_bytes() == b"unrelated contents"


@pytest.fixture
def rejecting_store(store: WorkingCopyStore, database_path: Path, workspace_id: str) -> WorkingCopyStore:
    _ = store.save(workspace_id, b"last durable state", expected_revision=0)
    with sqlite3.connect(database_path) as connection:
        _ = connection.execute(
            """CREATE TRIGGER reject_update BEFORE UPDATE ON working_copies
            BEGIN SELECT RAISE(ABORT, 'fixture write failure'); END"""
        )
    return store


def test_save_with_database_write_failure(rejecting_store: WorkingCopyStore, workspace_id: str) -> None:
    with pytest.raises(WorkingCopyStoreError):
        _ = rejecting_store.save(workspace_id, b"unsaved newer state", expected_revision=1)
    previous = rejecting_store.load(workspace_id)
    assert previous is not None
    assert (previous.revision, previous.data) == (1, b"last durable state")


@pytest.fixture
def interrupted_store(store: WorkingCopyStore, database_path: Path, workspace_id: str) -> WorkingCopyStore:
    _ = store.save(workspace_id, b"last committed state", expected_revision=0)
    _ = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _INTERRUPTED_WRITE, str(database_path), workspace_id], check=True, timeout=30
    )
    assert database_path.with_name(database_path.name + "-journal").exists()
    return store


def test_load_with_interrupted_transaction(interrupted_store: WorkingCopyStore, workspace_id: str) -> None:
    restored = interrupted_store.load(workspace_id)
    assert restored is not None
    assert (restored.revision, restored.data) == (1, b"last committed state")
