"""Game save replacements preserve recoverable copies of every prior version."""

import os
import stat
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest

from gridiron_playbook import game_playbook
from gridiron_playbook.editor import PlaybookEditor
from gridiron_playbook.game_playbook import GamePlaybookBackupCorruptError
from gridiron_playbook.game_playbook import GamePlaybookBackupUnavailableError
from gridiron_playbook.game_playbook import GamePlaybookBackupWriteError
from gridiron_playbook.game_playbook import GamePlaybookBusyError
from gridiron_playbook.game_playbook import GamePlaybookChange
from gridiron_playbook.game_playbook import GamePlaybookChangedError
from gridiron_playbook.game_playbook import GamePlaybookReplacementError
from gridiron_playbook.game_playbook import GamePlaybookStore
from gridiron_playbook.game_playbook import GamePlaybookUnavailableError
from gridiron_playbook.game_playbook import PreparedGamePlaybook
from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.playbook import playbook_to_sav


_DESCRIPTOR_CTIME_OFFSET_NS: int = 1_000_000_000


@pytest.fixture
def playbook(custom_plays_json: str) -> GridironPlaybook:
    return GridironPlaybook.model_validate_json(custom_plays_json)


@pytest.fixture
def replacement(playbook: GridironPlaybook) -> GridironPlaybook:
    editor = PlaybookEditor(playbook)
    editor.rename_play(0, "Installed play")
    return editor.playbook


@pytest.fixture
def original_bytes(playbook: GridironPlaybook) -> bytes:
    return playbook_to_sav(playbook)


@pytest.fixture
def save_path(tmp_path: Path, original_bytes: bytes) -> Path:
    path = tmp_path / "game" / "GridironCustomPlays.sav"
    path.parent.mkdir()
    _ = path.write_bytes(original_bytes)
    return path


@pytest.fixture
def backup_directory(tmp_path: Path) -> Path:
    return tmp_path / "backups"


@pytest.fixture
def store(save_path: Path, backup_directory: Path) -> GamePlaybookStore:
    return GamePlaybookStore(save_path, backup_directory)


@pytest.fixture
def readonly_save(save_path: Path) -> Iterator[Path]:
    permissions = save_path.stat().st_mode
    save_path.chmod(stat.S_IREAD)
    try:
        yield save_path
    finally:
        save_path.chmod(permissions)


@pytest.fixture
def descriptor_with_distinct_ctime(monkeypatch: pytest.MonkeyPatch, save_path: Path) -> None:
    actual_fstat = os.fstat
    target: os.stat_result = save_path.stat()

    def fstat(descriptor: int) -> os.stat_result:
        result: os.stat_result = actual_fstat(descriptor)
        if (result.st_dev, result.st_ino) != (target.st_dev, target.st_ino):
            return result
        return os.stat_result(
            result,
            {
                "st_atime_ns": result.st_atime_ns,
                "st_mtime_ns": result.st_mtime_ns,
                "st_ctime_ns": result.st_ctime_ns + _DESCRIPTOR_CTIME_OFFSET_NS,
            },
        )

    monkeypatch.setattr(os, "fstat", fstat)


@pytest.fixture
def save_changed_during_read(monkeypatch: pytest.MonkeyPatch, save_path: Path) -> None:
    actual_fstat = os.fstat
    target: os.stat_result = save_path.stat()
    changed: bool = False

    def fstat(descriptor: int) -> os.stat_result:
        nonlocal changed
        result: os.stat_result = actual_fstat(descriptor)
        if not changed and (result.st_dev, result.st_ino) == (target.st_dev, target.st_ino):
            changed = True
            _ = save_path.write_bytes(b"new game data written during the read")
        return result

    monkeypatch.setattr(os, "fstat", fstat)


@pytest.fixture
def save_path_with_other_file_identity(monkeypatch: pytest.MonkeyPatch, save_path: Path, original_bytes: bytes) -> None:
    other: Path = save_path.with_name("other.sav")
    _ = other.write_bytes(original_bytes)
    other_metadata: os.stat_result = other.stat()
    actual_stat = Path.stat

    def path_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if path == save_path:
            return other_metadata
        return actual_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", path_stat)


@pytest.mark.usefixtures("descriptor_with_distinct_ctime")
def test__read_current_with_distinct_descriptor_ctime(
    store: GamePlaybookStore,
    original_bytes: bytes,
) -> None:
    # Pin the filesystem read boundary independently of save encoding.
    contents: bytes = store._read_current()  # pyright: ignore[reportPrivateUsage]

    assert contents == original_bytes


@pytest.mark.usefixtures("save_changed_during_read")
def test__read_current_with_change_during_read(store: GamePlaybookStore) -> None:
    with pytest.raises(GamePlaybookChangedError):
        # Pin the filesystem read boundary independently of save encoding.
        _ = store._read_current()  # pyright: ignore[reportPrivateUsage]


@pytest.mark.usefixtures("save_path_with_other_file_identity")
def test__read_current_with_path_descriptor_identity_mismatch(store: GamePlaybookStore) -> None:
    with pytest.raises(GamePlaybookChangedError):
        # Pin the filesystem read boundary independently of save encoding.
        _ = store._read_current()  # pyright: ignore[reportPrivateUsage]


def test_prepare_install_with_no_writes(
    store: GamePlaybookStore,
    replacement: GridironPlaybook,
    save_path: Path,
    original_bytes: bytes,
    backup_directory: Path,
) -> None:
    prepared = store.prepare_install(replacement)
    assert prepared.save_path == save_path.resolve()
    assert prepared.replacement == playbook_to_sav(replacement)
    assert save_path.read_bytes() == original_bytes
    assert not backup_directory.exists()


def test_apply_with_original_backup(
    store: GamePlaybookStore,
    replacement: GridironPlaybook,
    save_path: Path,
    original_bytes: bytes,
) -> None:
    result = store.apply(store.prepare_install(replacement))
    assert result.changed
    assert result.save_path == save_path.resolve()
    assert result.backup_path is not None
    assert result.backup_path.read_bytes() == original_bytes
    assert save_path.read_bytes() == playbook_to_sav(replacement)


def test_apply_with_identical_contents(
    store: GamePlaybookStore,
    playbook: GridironPlaybook,
    save_path: Path,
    original_bytes: bytes,
    backup_directory: Path,
) -> None:
    result = store.apply(store.prepare_install(playbook))
    assert not result.changed
    assert result.backup_path is None
    assert save_path.read_bytes() == original_bytes
    assert not list(backup_directory.rglob("*.sav"))


def test_apply_with_stale_confirmation(
    store: GamePlaybookStore,
    replacement: GridironPlaybook,
    save_path: Path,
    backup_directory: Path,
) -> None:
    prepared = store.prepare_install(replacement)
    external_save = b"a newer save written outside the editor"
    _ = save_path.write_bytes(external_save)
    with pytest.raises(GamePlaybookChangedError):
        _ = store.apply(prepared)
    assert save_path.read_bytes() == external_save
    assert not list(backup_directory.rglob("*.sav"))


def test_apply_with_different_target(
    store: GamePlaybookStore,
    replacement: GridironPlaybook,
    save_path: Path,
    original_bytes: bytes,
) -> None:
    prepared = replace(store.prepare_install(replacement), save_path=save_path.with_name("another.sav"))
    with pytest.raises(GamePlaybookChangedError):
        _ = store.apply(prepared)
    assert save_path.read_bytes() == original_bytes


def test_prepare_install_with_missing_target(tmp_path: Path, replacement: GridironPlaybook) -> None:
    target = tmp_path / "missing.sav"
    with pytest.raises(GamePlaybookUnavailableError):
        _ = GamePlaybookStore(target, tmp_path / "backups").prepare_install(replacement)
    assert not target.exists()


def test_prepare_install_with_managed_backup_target(tmp_path: Path, replacement: GridironPlaybook) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    target = backups / "preserved.sav"
    _ = target.write_bytes(b"preserved archive")
    with pytest.raises(GamePlaybookUnavailableError):
        _ = GamePlaybookStore(target, backups).prepare_install(replacement)
    assert target.read_bytes() == b"preserved archive"


def test_prepare_restore_with_no_backup(store: GamePlaybookStore, backup_directory: Path) -> None:
    with pytest.raises(GamePlaybookBackupUnavailableError):
        _ = store.prepare_restore()
    assert not backup_directory.exists()


@pytest.mark.parametrize("damage", ["corrupt", "missing"])
def test_prepare_restore_with_corrupt_backup(
    store: GamePlaybookStore,
    replacement: GridironPlaybook,
    damage: str,
) -> None:
    result = store.apply(store.prepare_install(replacement))
    assert result.backup_path is not None
    if damage == "corrupt":
        _ = result.backup_path.write_bytes(b"corrupted archive")
    else:
        result.backup_path.unlink()
    with pytest.raises(GamePlaybookBackupCorruptError):
        _ = store.prepare_restore()


def test_apply_with_backup_changed_after_confirmation(
    store: GamePlaybookStore,
    replacement: GridironPlaybook,
    save_path: Path,
) -> None:
    _ = store.apply(store.prepare_install(replacement))
    prepared = store.prepare_restore()
    assert prepared.restore_backup is not None
    _ = prepared.restore_backup.path.write_bytes(b"corrupted after confirmation")
    with pytest.raises(GamePlaybookBackupCorruptError):
        _ = store.apply(prepared)
    assert save_path.read_bytes() == playbook_to_sav(replacement)


def test_backup_current_with_repeated_backup(store: GamePlaybookStore, original_bytes: bytes) -> None:
    first = store.backup_current()
    second = store.backup_current()
    assert first != second
    assert first.read_bytes() == second.read_bytes() == original_bytes


def test_apply_with_unavailable_backup_directory(
    save_path: Path,
    tmp_path: Path,
    original_bytes: bytes,
    replacement: GridironPlaybook,
) -> None:
    blocked = tmp_path / "not-a-directory"
    _ = blocked.write_bytes(b"unrelated file")
    store = GamePlaybookStore(save_path, blocked / "backups")
    prepared = store.prepare_install(replacement)
    with pytest.raises(GamePlaybookBackupWriteError):
        _ = store.apply(prepared)
    assert save_path.read_bytes() == original_bytes
    assert blocked.read_bytes() == b"unrelated file"


@pytest.mark.skipif(os.name != "nt", reason="Windows read-only attributes block atomic replacement.")
def test_apply_with_replacement_failure(
    store: GamePlaybookStore,
    readonly_save: Path,
    replacement: GridironPlaybook,
    original_bytes: bytes,
) -> None:
    prepared = store.prepare_install(replacement)
    with pytest.raises(GamePlaybookReplacementError) as failure:
        _ = store.apply(prepared)
    assert readonly_save.read_bytes() == original_bytes
    assert failure.value.backup_path.read_bytes() == original_bytes


@pytest.mark.parametrize("separate_archives", [False, True])
def test_apply_with_simultaneous_writers(
    store: GamePlaybookStore,
    playbook: GridironPlaybook,
    replacement: GridironPlaybook,
    save_path: Path,
    backup_directory: Path,
    original_bytes: bytes,
    separate_archives: bool,
) -> None:
    editor = PlaybookEditor(playbook)
    editor.rename_play(0, "Other window")
    other_directory = backup_directory.with_name("other-backups") if separate_archives else backup_directory
    other = GamePlaybookStore(save_path, other_directory)
    prepared = (store.prepare_install(replacement), other.prepare_install(editor.playbook))
    barrier = Barrier(2)

    def apply(writer: GamePlaybookStore, change: PreparedGamePlaybook) -> GamePlaybookChange:
        _ = barrier.wait(timeout=5)
        return writer.apply(change)

    with ThreadPoolExecutor(max_workers=2) as executor:
        writers = [
            executor.submit(apply, writer, change) for writer, change in zip((store, other), prepared, strict=True)
        ]
    failures = [writer.exception() for writer in writers]
    assert sum(failure is None for failure in failures) == 1
    assert sum(isinstance(failure, (GamePlaybookBusyError, GamePlaybookChangedError)) for failure in failures) == 1
    assert save_path.read_bytes() in {change.replacement for change in prepared}
    archives = {backup_directory, other_directory}
    assert [path.read_bytes() for directory in archives for path in directory.rglob("*.sav")] == [original_bytes]


def test__write_synced_with_existing_archive(tmp_path: Path) -> None:
    path = tmp_path / "immutable.sav"
    # This private boundary must reject overwriting an existing archive.
    game_playbook._write_synced(path, b"original bytes")  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(FileExistsError):
        game_playbook._write_synced(path, b"replacement bytes")  # pyright: ignore[reportPrivateUsage]
    assert path.read_bytes() == b"original bytes"


def test__locked_with_competing_store(store: GamePlaybookStore, save_path: Path, backup_directory: Path) -> None:
    other = GamePlaybookStore(save_path, backup_directory)
    # Hold the private lock boundary to make contention deterministic.
    with store._locked(), pytest.raises(GamePlaybookBusyError):  # pyright: ignore[reportPrivateUsage]
        _ = other.backup_current()


def test__replace_with_change_after_backup(
    store: GamePlaybookStore,
    replacement: GridironPlaybook,
    save_path: Path,
    original_bytes: bytes,
) -> None:
    prepared = store.prepare_install(replacement)
    backup = store.backup_current()
    _ = save_path.write_bytes(b"game wrote newer bytes after backup")
    with pytest.raises(GamePlaybookChangedError):
        # Pin the final replacement check separately from initial preparation.
        store._replace(prepared, backup)  # pyright: ignore[reportPrivateUsage]
    assert save_path.read_bytes() == b"game wrote newer bytes after backup"
    assert backup.read_bytes() == original_bytes
    assert not list(save_path.parent.glob("*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Windows read-only attributes block atomic replacement.")
def test_prepare_restore_with_failed_replacement_backup(
    store: GamePlaybookStore,
    playbook: GridironPlaybook,
    replacement: GridironPlaybook,
    save_path: Path,
    original_bytes: bytes,
) -> None:
    _ = store.apply(store.prepare_install(replacement))
    permissions = save_path.stat().st_mode
    save_path.chmod(stat.S_IREAD)
    try:
        with pytest.raises(GamePlaybookReplacementError):
            _ = store.apply(store.prepare_install(playbook))
    finally:
        save_path.chmod(permissions)
    prepared = store.prepare_restore()
    assert prepared.replacement == original_bytes
