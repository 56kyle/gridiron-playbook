"""Game target discovery attaches legacy history only to the automatic target."""

import json
from importlib.util import find_spec
from pathlib import Path

import pytest


if find_spec("nicegui") is None:
    pytest.skip("Install the web extra to test game-save target settings.", allow_module_level=True)


@pytest.fixture
def remembered_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    target = tmp_path / "GridironCustomPlays.sav"
    settings = tmp_path / "backups"
    settings.mkdir()
    _ = (settings / "settings.json").write_text(
        json.dumps({"version": 1, "save_path": str(target)}),
        encoding="utf-8",
    )
    monkeypatch.delenv("GRIDIRON_GAME_SAVE_PATH", raising=False)
    return target, settings


@pytest.mark.parametrize("automatic", ["same", "other", "unavailable", "unresolvable"])
def test__preferred_game_target_with_remembered_location(
    remembered_target: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    automatic: str,
) -> None:
    from gridiron_playbook.web import game_playbook_dialog

    target, settings = remembered_target
    legacy = tmp_path / "legacy"

    def discover() -> Path:
        if automatic == "unavailable":
            raise KeyError("No installed game")
        if automatic == "unresolvable":
            raise RuntimeError("The discovered path cannot be resolved.")
        return target if automatic == "same" else tmp_path / "other.sav"

    monkeypatch.setattr(game_playbook_dialog, "get_gridiron_playbook_path", discover)
    monkeypatch.setattr(game_playbook_dialog, "USER_CACHE_FOLDER", legacy)
    # Pin the private settings boundary without requiring a Steam installation.
    result = game_playbook_dialog._preferred_game_target(settings)  # pyright: ignore[reportPrivateUsage]
    assert result.save_path == target
    assert result.legacy_backup_directory == (legacy if automatic == "same" else None)


def test__preferred_game_target_with_environment_override(
    remembered_target: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gridiron_playbook.web import game_playbook_dialog

    _, settings = remembered_target
    explicit_target = tmp_path / "explicit.sav"

    def unavailable_discovery() -> Path:
        raise AssertionError("An explicit target must bypass Steam discovery.")

    monkeypatch.setenv("GRIDIRON_GAME_SAVE_PATH", str(explicit_target))
    monkeypatch.setattr(game_playbook_dialog, "get_gridiron_playbook_path", unavailable_discovery)
    # The explicit-path boundary must not attach an unrelated game's legacy cache.
    result = game_playbook_dialog._preferred_game_target(settings)  # pyright: ignore[reportPrivateUsage]
    assert result.save_path == explicit_target
    assert result.legacy_backup_directory is None
