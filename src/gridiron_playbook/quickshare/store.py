"""Durable SQLite storage for unlisted Quickshare snapshots."""

import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

from pydantic import TypeAdapter

from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.quickshare.snapshot import is_share_id


_SNAPSHOT_ROW = TypeAdapter(tuple[bytes] | None)


class SnapshotStore:
    """Keep immutable snapshots in an on-disk database across service restarts."""

    def __init__(self, path: Path) -> None:
        """Open or initialize the database and its parent directory."""
        if path == Path(":memory:"):
            raise ValueError("Quickshare requires an on-disk database path.")
        self._path: Path = path.resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as connection, connection:
            _ = connection.execute("CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, payload BLOB NOT NULL)")

    def create(self, snapshot: ShareSnapshot) -> str:
        """Store a snapshot atomically and return its random share identifier."""
        data: bytes = snapshot.to_bytes()
        with closing(sqlite3.connect(self._path)) as connection, connection:
            while True:
                share_id: str = secrets.token_urlsafe(16)
                inserted: sqlite3.Cursor = connection.execute(
                    "INSERT INTO snapshots (id, payload) VALUES (?, ?) ON CONFLICT(id) DO NOTHING", (share_id, data)
                )
                if inserted.rowcount:
                    return share_id

    def get(self, share_id: str) -> ShareSnapshot | None:
        """Read a snapshot, returning None for an unknown or malformed identifier."""
        if not is_share_id(share_id):
            return None
        with closing(sqlite3.connect(self._path)) as connection:
            cursor: sqlite3.Cursor = connection.execute("SELECT payload FROM snapshots WHERE id = ?", (share_id,))
            row: tuple[bytes] | None = _SNAPSHOT_ROW.validate_python(cursor.fetchone(), strict=True)
        return None if row is None else ShareSnapshot.from_bytes(row[0])
