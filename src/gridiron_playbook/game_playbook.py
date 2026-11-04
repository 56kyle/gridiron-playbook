"""Module containing recoverable game-save replacement for the gridiron_playbook package."""

import errno
import hashlib
import os
import re
import stat
import sys
from collections.abc import Generator
from collections.abc import Iterator
from contextlib import contextmanager
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import ClassVar
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from pydantic import field_validator

from gridiron_playbook.constants import FILE_SAFE_DATETIME_FORMAT
from gridiron_playbook.constants import USER_DATA_FOLDER
from gridiron_playbook.playbook_document import GridironPlaybook
from gridiron_playbook.playbook_document import playbook_to_sav
from gridiron_playbook.playbook_document import sav_to_playbook


GAME_PLAYBOOK_BACKUP_DIRECTORY: Path = USER_DATA_FOLDER / "game-playbook-backups"
_ARCHIVE_NAME = re.compile(r"(?P<sequence>[0-9]{20})_[0-9a-f]{32}\.json")
_LEGACY_NAME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}\.sav")


class GamePlaybookError(RuntimeError):
    """An in-game playbook operation could not complete."""


class GamePlaybookUnavailableError(GamePlaybookError):
    """The selected game save is missing or unreadable."""


class GamePlaybookChangedError(GamePlaybookError):
    """The game save changed after the operation was prepared."""


class GamePlaybookBusyError(GamePlaybookError):
    """Another editor is changing this game save."""


class GamePlaybookBackupUnavailableError(GamePlaybookError):
    """No earlier, different game save is available to restore."""


class GamePlaybookBackupCorruptError(GamePlaybookError):
    """A game-save backup or its metadata failed verification."""


class GamePlaybookBackupWriteError(GamePlaybookError):
    """The current game save could not be backed up safely."""


class GamePlaybookEncodingError(GamePlaybookError):
    """The editor document could not be encoded as a valid game save."""


class GamePlaybookReplacementError(GamePlaybookError):
    """Replacement failed; the verified previous save remains at backup_path."""

    def __init__(self, backup_path: Path) -> None:
        """Retain the recovery location when replacement does not complete."""
        self.backup_path: Path = backup_path
        super().__init__(f"Could not replace the game save. Your previous playbook is backed up at {backup_path}.")


@dataclass(frozen=True)
class GamePlaybookBackup:
    """A verified archive of an earlier game save."""

    path: Path
    created_at: datetime
    digest: str


@dataclass(frozen=True)
class PreparedGamePlaybook:
    """The exact replacement and game-save state shown for confirmation."""

    save_path: Path
    replacement: bytes
    expected_digest: str
    restore_backup: GamePlaybookBackup | None = None


@dataclass(frozen=True)
class GamePlaybookChange:
    """A completed replacement, or an identical-content no-op."""

    save_path: Path
    backup_path: Path | None
    changed: bool


class _BackupRecord(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(strict=True, frozen=True, extra="forbid")

    version: Literal[1]
    save_path: Path
    sequence: int = Field(ge=1)
    created_at: datetime
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Backup timestamps must include their timezone.")
        return value


def _digest(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _write_synced(path: Path, contents: bytes) -> None:
    with path.open("xb") as stream:
        if stream.write(contents) != len(contents):
            raise OSError("The complete file could not be written.")
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != contents:
        raise OSError("The saved file failed verification.")


def _sync_directory(path: Path) -> None:
    if sys.platform != "win32":
        descriptor: int = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _remove_temporary(path: Path) -> None:
    with suppress(OSError):
        path.unlink(missing_ok=True)


def _lock_descriptor(descriptor: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _open_lock(path: Path) -> int:
    if path.is_symlink():
        raise GamePlaybookBackupWriteError("The game-save lock cannot be a symbolic link.")
    flags: int = os.O_RDWR | os.O_CREAT
    if sys.platform != "win32":
        flags |= os.O_NOFOLLOW
    descriptor: int = os.open(path, flags, 0o600)
    try:
        opened = os.fstat(descriptor)
        linked = path.lstat()
        if not stat.S_ISREG(linked.st_mode) or (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino):
            raise GamePlaybookBackupWriteError("The game-save lock changed while it was opened. Try again.")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


class GamePlaybookStore:
    """Replace a closed game's save only after preserving its existing bytes."""

    def __init__(self, save_path: Path, backup_directory: Path, *, legacy_backup_directory: Path | None = None) -> None:
        """Bind the game destination and archive root without creating files."""
        try:
            self.save_path: Path = save_path.expanduser().resolve()
            self.backup_directory: Path = backup_directory.expanduser().resolve()
            self.legacy_backup_directory: Path | None = (
                legacy_backup_directory.expanduser().resolve() if legacy_backup_directory is not None else None
            )
        except (OSError, RuntimeError) as error:
            raise GamePlaybookUnavailableError("The game save or backup location could not be resolved.") from error
        if self.save_path.suffix.lower() != ".sav":
            raise GamePlaybookUnavailableError("Select the game's existing .sav file.")
        if self.save_path.is_relative_to(self.backup_directory):
            raise GamePlaybookUnavailableError("Select the game's save, not a managed backup.")
        key: str = str(self.save_path).casefold() if sys.platform == "win32" else str(self.save_path)
        self._history_directory: Path = self.backup_directory / _digest(key.encode("utf-8"))[:32]
        self._lock_path: Path = self.save_path.with_name(f".{self.save_path.name}.gridiron-playbook.lock")

    def prepare_install(self, playbook: GridironPlaybook) -> PreparedGamePlaybook:
        """Encode and validate a replacement before any file is modified."""
        try:
            replacement: bytes = playbook_to_sav(playbook)
            _ = sav_to_playbook(replacement)
        except ValueError as error:
            raise GamePlaybookEncodingError("This playbook could not be encoded as a valid game save.") from error
        return PreparedGamePlaybook(self.save_path, replacement, _digest(self._read_current()))

    def prepare_restore(self) -> PreparedGamePlaybook:
        """Select the newest verified backup that differs from the current save."""
        current_digest: str = _digest(self._read_current())
        paths: tuple[Path, ...] = self._record_paths()
        archives: Iterator[tuple[GamePlaybookBackup, bytes]] = (
            (self._read_archive(path) for path in paths) if paths else self._legacy_archives()
        )
        for backup, contents in archives:
            if backup.digest != current_digest:
                return PreparedGamePlaybook(self.save_path, contents, current_digest, backup)
        raise GamePlaybookBackupUnavailableError("There is no previous playbook to restore for this game save.")

    def apply(self, change: PreparedGamePlaybook) -> GamePlaybookChange:
        """Back up and replace the confirmed save, rejecting changed destinations."""
        if change.save_path != self.save_path:
            raise GamePlaybookChangedError("The confirmed game-save location changed. Review it again.")
        with self._locked():
            current: bytes = self._require_current(change.expected_digest)
            self._require_restore_archive(change)
            if current == change.replacement:
                return GamePlaybookChange(self.save_path, None, changed=False)
            if change.restore_backup is not None and self._is_legacy_backup(change.restore_backup.path):
                _ = self._write_backup(change.replacement)
            backup_path: Path = self._write_backup(current)
            self._replace(change, backup_path)
            return GamePlaybookChange(self.save_path, backup_path, changed=True)

    def backup_current(self) -> Path:
        """Preserve the current game save without changing it."""
        with self._locked():
            current: bytes = self._read_current()
            backup_path: Path = self._write_backup(current)
            _ = self._require_current(_digest(current))
            return backup_path

    def _read_current(self) -> bytes:
        try:
            if not self.save_path.is_file():
                raise GamePlaybookUnavailableError("Select an existing game save, then close Gridiron and try again.")
            with self.save_path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                contents: bytes = stream.read()
                after = os.fstat(stream.fileno())
            if _stat_identity(before) != _stat_identity(after) or _stat_identity(after) != _stat_identity(
                self.save_path.stat()
            ):
                raise GamePlaybookChangedError("The game save changed while it was read. Close Gridiron and try again.")
            return contents
        except OSError as error:
            raise GamePlaybookUnavailableError(
                "The game save could not be read. Check the location and access."
            ) from error

    def _require_current(self, expected_digest: str) -> bytes:
        try:
            current: bytes = self._read_current()
        except GamePlaybookUnavailableError as error:
            raise GamePlaybookChangedError(
                "The confirmed game save is no longer available. Review it again."
            ) from error
        if _digest(current) != expected_digest:
            raise GamePlaybookChangedError("The game save changed after confirmation was prepared. Review it again.")
        return current

    @contextmanager
    def _locked(self) -> Generator[None, None, None]:
        try:
            self._history_directory.mkdir(parents=True, exist_ok=True)
            with os.fdopen(_open_lock(self._lock_path), "r+b") as stream:
                if stream.seek(0, os.SEEK_END) == 0:
                    _ = stream.write(b"\0")
                    stream.flush()
                _ = stream.seek(0)
                try:
                    _lock_descriptor(stream.fileno())
                except OSError as error:
                    if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise GamePlaybookBusyError("Another editor is changing this game save. Try again.") from error
                    raise
                yield
        except OSError as error:
            raise GamePlaybookBackupWriteError(
                "The game save or backup folder could not be opened or locked."
            ) from error

    def _record_paths(self) -> tuple[Path, ...]:
        try:
            paths = (path for path in self._history_directory.iterdir() if _ARCHIVE_NAME.fullmatch(path.name))
            return tuple(sorted(paths, reverse=True))
        except FileNotFoundError:
            return ()
        except OSError as error:
            raise GamePlaybookBackupUnavailableError("The backup history could not be read.") from error

    def _read_archive(self, path: Path) -> tuple[GamePlaybookBackup, bytes]:
        try:
            record: _BackupRecord = _BackupRecord.model_validate_json(path.read_bytes())
            if record.save_path != self.save_path or record.sequence != int(path.name[:20]):
                raise GamePlaybookBackupCorruptError(f"Backup metadata failed verification: {path}")
            backup = GamePlaybookBackup(path.with_suffix(".sav"), record.created_at, record.digest)
            return backup, self._verified_backup_bytes(backup)
        except (OSError, ValueError, ValidationError) as error:
            raise GamePlaybookBackupCorruptError(f"The backup could not be verified: {path}") from error

    def _verified_backup_bytes(self, backup: GamePlaybookBackup) -> bytes:
        managed: bool = backup.path.parent == self._history_directory and backup.path.suffix == ".sav"
        if not managed and not self._is_legacy_backup(backup.path):
            raise GamePlaybookBackupCorruptError("The selected backup is outside this game's archive.")
        try:
            contents: bytes = backup.path.read_bytes()
        except OSError as error:
            raise GamePlaybookBackupCorruptError(f"The backup could not be read: {backup.path}") from error
        if _digest(contents) != backup.digest:
            raise GamePlaybookBackupCorruptError(f"The backup failed verification: {backup.path}")
        return contents

    def _is_legacy_backup(self, path: Path) -> bool:
        return (
            self.legacy_backup_directory is not None
            and path.parent == self.legacy_backup_directory
            and _LEGACY_NAME.fullmatch(path.name) is not None
        )

    def _legacy_archives(self) -> Iterator[tuple[GamePlaybookBackup, bytes]]:
        if self.legacy_backup_directory is None:
            return
        candidates: list[tuple[datetime, Path]] = []
        try:
            for path in self.legacy_backup_directory.iterdir():
                if not self._is_legacy_backup(path):
                    continue
                try:
                    timestamp = datetime.strptime(path.stem, FILE_SAFE_DATETIME_FORMAT).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                candidates.append((timestamp, path))
        except FileNotFoundError:
            return
        except OSError as error:
            raise GamePlaybookBackupUnavailableError("The previous backup folder could not be read.") from error
        for timestamp, path in sorted(candidates, reverse=True):
            try:
                if path.resolve().parent != self.legacy_backup_directory:
                    raise GamePlaybookBackupCorruptError("A previous backup points outside its archive folder.")
                contents: bytes = path.read_bytes()
                _ = sav_to_playbook(contents)
            except (OSError, ValueError) as error:
                raise GamePlaybookBackupCorruptError(f"The previous backup could not be verified: {path}") from error
            yield GamePlaybookBackup(path, timestamp, _digest(contents)), contents

    def _require_restore_archive(self, change: PreparedGamePlaybook) -> None:
        if (
            change.restore_backup is not None
            and self._verified_backup_bytes(change.restore_backup) != change.replacement
        ):
            raise GamePlaybookBackupCorruptError("The selected backup changed after confirmation was prepared.")

    def _write_backup(self, contents: bytes) -> Path:
        paths: tuple[Path, ...] = self._record_paths()
        sequence: int = int(paths[0].name[:20]) + 1 if paths else 1
        stem: str = f"{sequence:020d}_{uuid4().hex}"
        save_path: Path = self._history_directory / f"{stem}.sav"
        metadata_path: Path = self._history_directory / f"{stem}.json"
        temporary_path: Path = self._history_directory / f"{stem}.tmp"
        record = _BackupRecord(
            version=1,
            save_path=self.save_path,
            sequence=sequence,
            created_at=datetime.now(timezone.utc),
            digest=_digest(contents),
        )
        try:
            _write_synced(save_path, contents)
            _write_synced(temporary_path, record.model_dump_json().encode("utf-8"))
            _ = temporary_path.replace(metadata_path)
            _sync_directory(self._history_directory)
            return save_path
        except OSError as error:
            raise GamePlaybookBackupWriteError(
                "The current game save could not be backed up. It was not replaced."
            ) from error
        finally:
            _remove_temporary(temporary_path)

    def _replace(self, change: PreparedGamePlaybook, backup_path: Path) -> None:
        temporary_path: Path = self.save_path.with_name(f".{self.save_path.name}.{uuid4().hex}.tmp")
        try:
            _write_synced(temporary_path, change.replacement)
            _ = self._require_current(change.expected_digest)
            _ = temporary_path.replace(self.save_path)
            _sync_directory(self.save_path.parent)
            if self.save_path.read_bytes() != change.replacement:
                raise OSError("The replaced game save failed verification.")
        except OSError as error:
            raise GamePlaybookReplacementError(backup_path) from error
        finally:
            _remove_temporary(temporary_path)
