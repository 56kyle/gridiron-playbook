"""Store local working copies separately from imported playbook files."""

import gzip
import sqlite3
import zlib
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

from pydantic import TypeAdapter
from pydantic import ValidationError


_SCHEMA_VERSION = 1
_INTEGER_ROW = TypeAdapter(tuple[int])
_COPY_ROW = TypeAdapter(tuple[int, bytes])


class WorkingCopyStoreError(OSError):
    """A working copy could not be read or saved on local storage."""


class WorkingCopyFormatError(WorkingCopyStoreError):
    """The working store contains corrupt or unsupported recovery data."""


class WorkingCopyConflictError(ValueError):
    """Another editor has already saved a newer working copy."""


@dataclass(frozen=True)
class WorkingCopy:
    """One durable revision and its uncompressed recovery contents."""

    workspace_id: str
    revision: int
    data: bytes


def _workspace_id(value: str) -> str:
    """Require a canonical UUID and normalize it to its hexadecimal form."""
    parsed = UUID(value)
    if value not in (parsed.hex, str(parsed)):
        raise ValueError("Use a canonical UUID for the working copy.")
    return parsed.hex


def _integer_row(value: object) -> int:
    """Validate an integer returned by the storage boundary."""
    try:
        return _INTEGER_ROW.validate_python(value, strict=True)[0]
    except ValidationError as error:
        raise WorkingCopyFormatError("The working store contains invalid metadata.") from error


def _fetch_one(cursor: sqlite3.Cursor) -> object:
    """Expose unvalidated SQLite results at the parsing boundary."""
    # sqlite3 types fetchone as Any. Callers validate the returned object before use.
    return cast("object", cursor.fetchone())


def _schema_version(connection: sqlite3.Connection) -> int:
    """Read the version without changing an existing database."""
    return _integer_row(_fetch_one(connection.execute("PRAGMA user_version")))


def _prepare_schema(connection: sqlite3.Connection) -> None:
    """Initialize an empty database or require the supported schema version."""
    version: int = _schema_version(connection)
    if version == 0:
        tables: int = _integer_row(
            _fetch_one(connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table'"))
        )
        if tables:
            raise WorkingCopyFormatError("The working store has an unrecognized schema.")
        _ = connection.execute(
            """CREATE TABLE working_copies (
                workspace_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL CHECK(revision > 0),
                data BLOB NOT NULL
            )"""
        )
        _ = connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    elif version != _SCHEMA_VERSION:
        raise WorkingCopyFormatError("The working store uses an unsupported version.")


def _decode_copy(workspace_id: str, row: object) -> WorkingCopy:
    """Decode a valid stored revision or report corrupt recovery data."""
    try:
        revision, compressed = _COPY_ROW.validate_python(row, strict=True)
        if revision <= 0:
            raise WorkingCopyFormatError("The working copy has an invalid revision.")
        data: bytes = gzip.decompress(compressed)
    except (ValidationError, EOFError, zlib.error, gzip.BadGzipFile) as error:
        raise WorkingCopyFormatError("The working copy contains invalid recovery data.") from error
    return WorkingCopy(workspace_id, revision, data)


class WorkingCopyStore:
    """Read and atomically save recovery revisions with conflict detection."""

    def __init__(self, path: Path) -> None:
        """Choose the working database without opening or creating any files."""
        self.path: Path = path.resolve()

    def load(self, workspace_id: str) -> WorkingCopy | None:
        """Load a working copy, raising StoreError for unreadable or invalid storage."""
        identifier: str = _workspace_id(workspace_id)
        try:
            if not self.path.exists():
                return None
            # SQLite needs write access to recover a hot rollback journal after a crash.
            with closing(sqlite3.connect(f"{self.path.as_uri()}?mode=rw", uri=True)) as connection:
                if _schema_version(connection) != _SCHEMA_VERSION:
                    raise WorkingCopyFormatError("The working store uses an unsupported version.")
                row: object = _fetch_one(
                    connection.execute(
                        "SELECT revision, data FROM working_copies WHERE workspace_id = ?", (identifier,)
                    )
                )
            return None if row is None else _decode_copy(identifier, row)
        except (sqlite3.Error, OSError) as error:
            if isinstance(error, WorkingCopyStoreError):
                raise
            raise WorkingCopyStoreError("Could not read the local working copy.") from error

    def save(self, workspace_id: str, data: bytes, *, expected_revision: int) -> WorkingCopy:
        """Commit the next revision or raise Conflict when the stored revision changed."""
        identifier: str = _workspace_id(workspace_id)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("The expected working-copy revision must be a nonnegative integer.")
        compressed: bytes = gzip.compress(data, compresslevel=1, mtime=0)
        revision: int = expected_revision + 1
        try:
            if expected_revision and not self.path.exists():
                raise WorkingCopyConflictError("The expected working copy no longer exists.")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, isolation_level=None)) as connection, connection:
                _ = connection.execute("BEGIN IMMEDIATE")
                _prepare_schema(connection)
                current: object = _fetch_one(
                    connection.execute("SELECT revision FROM working_copies WHERE workspace_id = ?", (identifier,))
                )
                actual: int = 0 if current is None else _integer_row(current)
                if actual != expected_revision:
                    raise WorkingCopyConflictError("This working copy was saved by another editor.")
                _ = connection.execute(
                    """INSERT INTO working_copies (workspace_id, revision, data) VALUES (?, ?, ?)
                    ON CONFLICT(workspace_id) DO UPDATE SET revision=excluded.revision, data=excluded.data""",
                    (identifier, revision, compressed),
                )
        except (sqlite3.Error, OSError) as error:
            if isinstance(error, WorkingCopyStoreError):
                raise
            raise WorkingCopyStoreError("Could not save the local working copy.") from error
        return WorkingCopy(identifier, revision, data)
