"""Game deployment preserves imported files and makes restores reversible."""

from pathlib import Path

import pytest

from gridiron_playbook import game_playbook as game_playbook_module
from gridiron_playbook import playbook as playbook_module
from gridiron_playbook.editor import PlaybookEditor
from gridiron_playbook.game_playbook import GamePlaybookBackupCorruptError
from gridiron_playbook.game_playbook import GamePlaybookBackupUnavailableError
from gridiron_playbook.game_playbook import GamePlaybookStore
from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.playbook import playbook_to_sav
from gridiron_playbook.playbook import sav_to_playbook
from gridiron_playbook.workspace import document_with_plays


@pytest.fixture
def playbook(custom_plays_json: str) -> GridironPlaybook:
    return GridironPlaybook.model_validate_json(custom_plays_json)


@pytest.fixture
def game_save(tmp_path: Path, playbook: GridironPlaybook) -> Path:
    path = tmp_path / "GridironCustomPlays.sav"
    _ = path.write_bytes(playbook_to_sav(playbook))
    return path


def test_apply_with_reversible_restore(game_save: Path, playbook: GridironPlaybook, tmp_path: Path) -> None:
    original = game_save.read_bytes()
    editor = PlaybookEditor(playbook)
    editor.rename_play(0, "Chosen playbook")
    replacement = playbook_to_sav(editor.playbook)
    store = GamePlaybookStore(game_save, tmp_path / "backups")
    first = store.apply(store.prepare_install(editor.playbook))
    second = store.apply(store.prepare_restore())
    assert game_save.read_bytes() == original
    assert second.backup_path is not None
    assert second.backup_path.read_bytes() == replacement
    third = store.apply(store.prepare_restore())
    assert game_save.read_bytes() == replacement
    assert first.backup_path is not None
    assert third.backup_path is not None
    assert first.backup_path.read_bytes() == third.backup_path.read_bytes() == original


def test_apply_with_opaque_original(game_save: Path, playbook: GridironPlaybook, tmp_path: Path) -> None:
    original = b"unrecognized original save contents\x00\xff"
    _ = game_save.write_bytes(original)
    store = GamePlaybookStore(game_save, tmp_path / "backups")
    _ = store.apply(store.prepare_install(playbook))
    _ = store.apply(store.prepare_restore())
    assert game_save.read_bytes() == original


def test_apply_with_large_playbook(game_save: Path, playbook: GridironPlaybook, tmp_path: Path) -> None:
    plays = tuple(
        playbook.root.properties.custom_plays[0].model_copy(update={"play_name": f"Play {index}"})
        for index in range(125)
    )
    document = document_with_plays(playbook, plays)
    uploaded = tmp_path / "uploaded.sav"
    source_bytes = playbook_to_sav(document)
    _ = uploaded.write_bytes(source_bytes)
    store = GamePlaybookStore(game_save, tmp_path / "backups")
    _ = store.apply(store.prepare_install(sav_to_playbook(uploaded.read_bytes())))
    assert sav_to_playbook(game_save.read_bytes()) == document
    assert uploaded.read_bytes() == source_bytes


def test_prepare_restore_with_target_scoped_history(
    game_save: Path, playbook: GridironPlaybook, tmp_path: Path
) -> None:
    backups = tmp_path / "backups"
    first = GamePlaybookStore(game_save, backups)
    editor = PlaybookEditor(playbook)
    editor.rename_play(0, "First game")
    _ = first.apply(first.prepare_install(editor.playbook))
    other_save = tmp_path / "other.sav"
    _ = other_save.write_bytes(b"other installation")
    second = GamePlaybookStore(other_save, backups)
    with pytest.raises(GamePlaybookBackupUnavailableError):
        _ = second.prepare_restore()
    _ = second.apply(second.prepare_install(editor.playbook))
    assert second.prepare_restore().replacement == b"other installation"
    assert first.prepare_restore().replacement == playbook_to_sav(playbook)


@pytest.fixture
def legacy_cache(tmp_path: Path) -> Path:
    path = tmp_path / "legacy-cache"
    path.mkdir()
    return path


def test_prepare_restore_with_legacy_backup(
    game_save: Path,
    playbook: GridironPlaybook,
    tmp_path: Path,
    legacy_cache: Path,
) -> None:
    editor = PlaybookEditor(playbook)
    editor.rename_play(0, "Legacy original")
    legacy_bytes = playbook_to_sav(editor.playbook)
    legacy = legacy_cache / "2026-01-01_10-20-30.sav"
    _ = legacy.write_bytes(legacy_bytes)
    current = game_save.read_bytes()
    backups = tmp_path / "backups"
    store = GamePlaybookStore(game_save, backups, legacy_backup_directory=legacy_cache)
    prepared = store.prepare_restore()
    assert prepared.replacement == legacy_bytes
    assert not backups.exists()
    _ = store.apply(prepared)
    assert game_save.read_bytes() == legacy_bytes
    assert legacy.read_bytes() == legacy_bytes
    assert store.prepare_restore().replacement == current


@pytest.mark.parametrize(
    "relative_path", ["unrelated.sav", "9999-99-99_99-99-99.sav", "nested/2026-01-01_10-20-30.sav"]
)
def test_prepare_restore_with_unrelated_legacy_file(
    game_save: Path,
    tmp_path: Path,
    legacy_cache: Path,
    relative_path: str,
) -> None:
    path = legacy_cache / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_bytes(b"unrelated cache bytes")
    store = GamePlaybookStore(game_save, tmp_path / "backups", legacy_backup_directory=legacy_cache)
    with pytest.raises(GamePlaybookBackupUnavailableError):
        _ = store.prepare_restore()
    assert path.read_bytes() == b"unrelated cache bytes"


def test_prepare_restore_with_corrupt_newest_legacy_backup(
    game_save: Path,
    playbook: GridironPlaybook,
    tmp_path: Path,
    legacy_cache: Path,
) -> None:
    _ = (legacy_cache / "2026-01-01_00-00-00.sav").write_bytes(playbook_to_sav(playbook))
    corrupt = legacy_cache / "2026-01-02_00-00-00.sav"
    _ = corrupt.write_bytes(b"corrupt newest backup")
    store = GamePlaybookStore(game_save, tmp_path / "backups", legacy_backup_directory=legacy_cache)
    with pytest.raises(GamePlaybookBackupCorruptError):
        _ = store.prepare_restore()
    assert corrupt.read_bytes() == b"corrupt newest backup"


def test_prepare_restore_with_managed_history_before_legacy(
    game_save: Path,
    playbook: GridironPlaybook,
    tmp_path: Path,
    legacy_cache: Path,
) -> None:
    original = game_save.read_bytes()
    _ = (legacy_cache / "2099-12-31_23-59-59.sav").write_bytes(b"ignored malformed legacy backup")
    store = GamePlaybookStore(game_save, tmp_path / "backups", legacy_backup_directory=legacy_cache)
    editor = PlaybookEditor(playbook)
    editor.rename_play(0, "Managed new version")
    _ = store.apply(store.prepare_install(editor.playbook))
    assert store.prepare_restore().replacement == original


@pytest.fixture
def legacy_helpers(monkeypatch: pytest.MonkeyPatch, game_save: Path, tmp_path: Path, legacy_cache: Path) -> None:
    monkeypatch.setattr(playbook_module, "get_gridiron_playbook_path", lambda: game_save)
    monkeypatch.setattr(playbook_module, "USER_CACHE_FOLDER", legacy_cache)
    monkeypatch.setattr(game_playbook_module, "GAME_PLAYBOOK_BACKUP_DIRECTORY", tmp_path / "backups")


@pytest.mark.parametrize("suffix", [".sav", ".json"])
@pytest.mark.usefixtures("legacy_helpers")
def test_import_playbook_with_backup(
    game_save: Path,
    playbook: GridironPlaybook,
    tmp_path: Path,
    suffix: str,
) -> None:
    original = game_save.read_bytes()
    editor = PlaybookEditor(playbook)
    editor.rename_play(0, "Imported with backup")
    source = tmp_path / f"uploaded{suffix}"
    contents = (
        playbook_to_sav(editor.playbook)
        if suffix == ".sav"
        else playbook_module.playbook_to_json(editor.playbook).encode("utf-8")
    )
    _ = source.write_bytes(contents)
    playbook_module.import_playbook(source)
    assert sav_to_playbook(game_save.read_bytes()) == editor.playbook
    assert source.read_bytes() == contents
    assert [path.read_bytes() for path in (tmp_path / "backups").rglob("*.sav")] == [original]


@pytest.mark.usefixtures("legacy_helpers")
def test_load_backup_playbook_with_reversible_restore(
    game_save: Path,
    playbook: GridironPlaybook,
) -> None:
    original = game_save.read_bytes()
    _ = playbook_module.save_backup_playbook()
    editor = PlaybookEditor(playbook)
    editor.rename_play(0, "Game changed after manual backup")
    current = playbook_to_sav(editor.playbook)
    _ = game_save.write_bytes(current)
    playbook_module.load_backup_playbook()
    assert game_save.read_bytes() == original
    playbook_module.load_backup_playbook()
    assert game_save.read_bytes() == current


@pytest.mark.parametrize("blocked_directory", ["managed", "legacy"])
def test_prepare_restore_with_unreadable_backup_directory(
    game_save: Path,
    playbook: GridironPlaybook,
    tmp_path: Path,
    blocked_directory: str,
) -> None:
    legacy = tmp_path / "legacy"
    backups = tmp_path / "backups"
    store = GamePlaybookStore(game_save, backups, legacy_backup_directory=legacy)
    if blocked_directory == "managed":
        legacy.mkdir()
        editor = PlaybookEditor(playbook)
        editor.rename_play(0, "Different legacy backup")
        _ = (legacy / "2026-01-01_00-00-00.sav").write_bytes(playbook_to_sav(editor.playbook))
        # Force a real filesystem failure at the private archive-directory boundary.
        history = store._history_directory  # pyright: ignore[reportPrivateUsage]
        history.parent.mkdir()
        _ = history.write_bytes(b"not a directory")
    else:
        _ = legacy.write_bytes(b"not a directory")
    with pytest.raises(GamePlaybookBackupUnavailableError):
        _ = store.prepare_restore()
