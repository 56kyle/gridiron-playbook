from pathlib import Path

import pytest
from pydantic import JsonValue
from pydantic import TypeAdapter

from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.save import json_to_sav
from gridiron_playbook.save import sav_to_json


_SAV_FIXTURE: Path = Path(__file__).parents[2] / "data" / "GridIronCustomPlays.sav"
_ENGINE_VERSION_STRING_OFFSET: int = 26
_SAV_READ_ERROR: str = r"^Could not read Unreal save:"
_JSON_READ_ERROR: str = r"^Invalid uesave JSON:"


def test_sav_to_json(custom_plays_json: str) -> None:
    decoded: str = sav_to_json(_SAV_FIXTURE.read_bytes())
    adapter: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)

    assert adapter.validate_json(decoded) == adapter.validate_json(custom_plays_json)


def test_json_to_sav(custom_plays_json: str) -> None:
    assert json_to_sav(custom_plays_json) == _SAV_FIXTURE.read_bytes()


def test_json_to_sav_with_renamed_play(custom_plays_json: str) -> None:
    edited: str = custom_plays_json.replace('"P11A-SWRT"', '"Revised sweep"', 1)
    saved: bytes = json_to_sav(edited)
    playbook: GridironPlaybook = GridironPlaybook.model_validate_json(sav_to_json(saved))

    assert playbook.root.properties.custom_plays[0].play_name == "Revised sweep"


def test_sav_to_json_with_truncated_save() -> None:
    with pytest.raises(ValueError, match=_SAV_READ_ERROR):
        _ = sav_to_json(b"GVAS")


def test_sav_to_json_with_unpaired_utf16_surrogate() -> None:
    header_prefix: bytes = _SAV_FIXTURE.read_bytes()[:_ENGINE_VERSION_STRING_OFFSET]
    malformed_engine_version: bytes = bytes.fromhex("ff ff ff ff 00 d8")

    with pytest.raises(ValueError, match=_SAV_READ_ERROR):
        _ = sav_to_json(header_prefix + malformed_engine_version)


@pytest.mark.parametrize("invalid_json", ["{", "{}"])
def test_json_to_sav_with_invalid_save(invalid_json: str) -> None:
    with pytest.raises(ValueError, match=_JSON_READ_ERROR):
        _ = json_to_sav(invalid_json)
