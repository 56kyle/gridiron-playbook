import json
from struct import pack
from typing import Literal

import pytest
from pydantic import JsonValue
from pydantic import TypeAdapter

from gridiron_playbook import _native
from gridiron_playbook.block import block_waypoints
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.playbook_document import GridironPlaybook
from gridiron_playbook.playbook_document import playbook_to_json
from gridiron_playbook.point import GridironPoint
from gridiron_playbook.quickshare.codec import Precision
from gridiron_playbook.quickshare.codec import decode_share
from gridiron_playbook.quickshare.codec import encode_share
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.route import GridironRoute
from gridiron_playbook.workspace import document_with_plays


_STRING_OBJECT = TypeAdapter(dict[str, str])
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_PROBE_INTEGER = 9_007_199_254_740_993


def _point_bits(plays: tuple[GridironPlay, ...]) -> bytes:
    return b"".join(
        pack("<ddd", point.x, point.y, point.z) for play in plays for route in play.routes for point in route.points
    )


def _play(points: tuple[GridironPoint, ...], *, name: str = "Motion 🏈") -> GridironPlay:
    return GridironPlay(
        FormationName_0="Unrecognized formation",
        PlayName_0=name,
        Routes_0=(GridironRoute(Slot_0=250, Points_0=points),),
    )


def _document(source: str, plays: tuple[GridironPlay, ...]) -> str:
    template: GridironPlaybook = GridironPlaybook.model_validate_json(source)
    return playbook_to_json(document_with_plays(template, plays))


def _signed_points() -> tuple[GridironPoint, ...]:
    return (
        GridironPoint(X_0=-0.0, Y_0=0.0, Z_0=-0.0),
        GridironPoint(X_0=123.45678901234567, Y_0=-987.6543210987654, Z_0=9.25),
    )


def _blocked_points() -> tuple[GridironPoint, ...]:
    approach: tuple[GridironPoint, ...] = (
        GridironPoint(X_0=-6.0, Y_0=-400.0, Z_0=-0.0),
        GridironPoint(X_0=950.739124, Y_0=-804.91804, Z_0=-0.0),
    )
    return (*approach, *block_waypoints(approach, 1, None))


def test_new_document_with_empty_playbook() -> None:
    document: GridironPlaybook = GridironPlaybook.model_validate_json(_native.new_document())

    assert document.root.properties.custom_plays == ()


def test_new_document_with_save_roundtrip() -> None:
    saved: bytes = _native.json_to_sav(_native.new_document())

    assert _native.json_to_sav(_native.sav_to_json(saved)) == saved


@pytest.mark.parametrize("field", ["header", "schemas", "extra"])
def test_apply_edit_with_preserved_metadata(custom_plays_json: str, field: str) -> None:
    command: str = json.dumps({"type": "rename_play", "play_index": 0, "play_name": "Renamed"})
    original: dict[str, JsonValue] = _JSON_OBJECT.validate_json(custom_plays_json)
    edited: dict[str, JsonValue] = _JSON_OBJECT.validate_json(_native.apply_edit(custom_plays_json, command))

    assert edited[field] == original[field]


def test_apply_edit_with_large_unknown_metadata(custom_plays_json: str) -> None:
    original: dict[str, JsonValue] = _JSON_OBJECT.validate_json(custom_plays_json)
    original["future_metadata"] = {"identifier": _PROBE_INTEGER}
    document: str = json.dumps(original)
    command: str = json.dumps({"type": "rename_play", "play_index": 0, "play_name": "Renamed"})
    edited: dict[str, JsonValue] = _JSON_OBJECT.validate_json(_native.apply_edit(document, command))

    assert edited["future_metadata"] == {"identifier": _PROBE_INTEGER}


def test_apply_edit_with_omitted_last_drawn_fields(custom_plays_json: str) -> None:
    command: str = json.dumps({"type": "rename_play", "play_index": 0, "play_name": "Renamed"})
    original: GridironPlaybook = GridironPlaybook.model_validate_json(custom_plays_json)
    edited: GridironPlaybook = GridironPlaybook.model_validate_json(_native.apply_edit(custom_plays_json, command))

    assert (
        edited.root.properties.last_drawn_play.model_fields_set
        == original.root.properties.last_drawn_play.model_fields_set
    )


def test_apply_edit_with_untouched_float_bits(custom_plays_json: str) -> None:
    plays: tuple[GridironPlay, ...] = (_play(_signed_points()),)
    command: str = json.dumps({"type": "rename_play", "play_index": 0, "play_name": "Renamed"})
    edited: GridironPlaybook = GridironPlaybook.model_validate_json(
        _native.apply_edit(_document(custom_plays_json, plays), command)
    )

    assert _point_bits(edited.root.properties.custom_plays) == _point_bits(plays)


@pytest.mark.parametrize("operation", ["create_play", "duplicate_play"])
def test_apply_edit_with_prepended_play(custom_plays_json: str, operation: str) -> None:
    command: dict[str, str | int] = {"type": operation, "play_name": "First"}
    if operation == "create_play":
        command["formation_name"] = "Twins Right"
    else:
        command["play_index"] = 0
    edited: GridironPlaybook = GridironPlaybook.model_validate_json(
        _native.apply_edit(custom_plays_json, json.dumps(command))
    )

    assert edited.root.properties.custom_plays[0].play_name == "First"


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_transfer_plays_with_preserved_float_bits(custom_plays_json: str, mode: str) -> None:
    plays: tuple[GridironPlay, ...] = (_play(_signed_points()),)
    result: dict[str, str] = _STRING_OBJECT.validate_json(
        _native.transfer_plays(_document(custom_plays_json, plays), _native.new_document(), "[0]", 0, mode)
    )
    target: GridironPlaybook = GridironPlaybook.model_validate_json(result["target"])

    assert _point_bits(target.root.properties.custom_plays) == _point_bits(plays)


@pytest.mark.parametrize(("mode", "remaining"), [("copy", 1), ("move", 0)])
def test_transfer_plays_with_source_retention(custom_plays_json: str, mode: str, remaining: int) -> None:
    source: str = _document(custom_plays_json, (_play(_signed_points()),))
    result: dict[str, str] = _STRING_OBJECT.validate_json(
        _native.transfer_plays(source, _native.new_document(), "[0]", 0, mode)
    )
    document: GridironPlaybook = GridironPlaybook.model_validate_json(result["source"])

    assert len(document.root.properties.custom_plays) == remaining


@pytest.mark.parametrize("points", [_signed_points(), _blocked_points()], ids=["signed-zero", "block"])
def test_encode_share_with_exact_python_decode(custom_plays_json: str, points: tuple[GridironPoint, ...]) -> None:
    plays: tuple[GridironPlay, ...] = (_play(points),)
    encoded: bytes = _native.encode_share(_document(custom_plays_json, plays), "[0]", "play", "exact")

    assert _point_bits(decode_share(encoded).plays) == _point_bits(plays)


@pytest.mark.parametrize("precision", list(Precision))
def test_encode_share_with_python_rounding(custom_plays_json: str, precision: Precision) -> None:
    points: tuple[GridironPoint, ...] = tuple(
        GridironPoint(X_0=value, Y_0=-value, Z_0=value) for value in (0.05, 0.15, 0.25, 0.5, 1.5, 2.5, 123.125)
    )
    plays: tuple[GridironPlay, ...] = (_play(points),)
    snapshot: ShareSnapshot = ShareSnapshot(version=1, kind="play", plays=plays)
    expected: ShareSnapshot = decode_share(encode_share(snapshot, precision))
    actual: ShareSnapshot = decode_share(
        _native.encode_share(_document(custom_plays_json, plays), "[0]", "play", precision.value)
    )

    assert _point_bits(actual.plays) == _point_bits(expected.plays)


@pytest.mark.parametrize("precision", list(Precision))
def test_encode_share_with_hand_edited_block(custom_plays_json: str, precision: Precision) -> None:
    points: tuple[GridironPoint, ...] = _blocked_points()
    moved: GridironPoint = points[5].model_copy(update={"x": points[5].x + 0.025})
    plays: tuple[GridironPlay, ...] = (_play((*points[:5], moved, *points[6:])),)
    encoded: bytes = _native.encode_share(_document(custom_plays_json, plays), "[0]", "play", precision.value)

    assert _point_bits(decode_share(encoded).plays) == _point_bits(plays)


@pytest.mark.parametrize("precision", list(Precision))
def test_import_share_with_python_encoded_file(precision: Precision) -> None:
    snapshot: ShareSnapshot = ShareSnapshot(version=1, kind="play", plays=(_play(_signed_points()),))
    data: bytes = encode_share(snapshot, precision)
    result: dict[str, str] = _STRING_OBJECT.validate_json(_native.import_share(_native.new_document(), data))
    document: GridironPlaybook = GridironPlaybook.model_validate_json(result["document"])

    assert _point_bits(document.root.properties.custom_plays) == _point_bits(decode_share(data).plays)


@pytest.mark.parametrize("kind", ["play", "playbook"])
def test_import_share_with_kind_specific_order(custom_plays_json: str, kind: Literal["play", "playbook"]) -> None:
    existing: tuple[GridironPlay, ...] = (_play(_signed_points(), name="Existing"),)
    snapshot: ShareSnapshot = ShareSnapshot(version=1, kind=kind, plays=(_play(_signed_points(), name="Imported"),))
    result: dict[str, str] = _STRING_OBJECT.validate_json(
        _native.import_share(_document(custom_plays_json, existing), encode_share(snapshot))
    )
    document: GridironPlaybook = GridironPlaybook.model_validate_json(result["document"])
    expected: tuple[str, ...] = ("Imported", "Existing") if kind == "play" else ("Imported",)

    assert tuple(play.play_name for play in document.root.properties.custom_plays) == expected


def test_encode_share_with_large_playbook(custom_plays_json: str) -> None:
    plays: tuple[GridironPlay, ...] = tuple(_play(_signed_points(), name=f"Play {index}") for index in range(125))
    encoded: bytes = _native.encode_share(
        _document(custom_plays_json, plays), json.dumps(list(range(len(plays)))), "playbook", "exact"
    )
    actual: ShareSnapshot = decode_share(encoded)

    assert tuple(play.play_name for play in actual.plays) == tuple(play.play_name for play in plays)


@pytest.mark.parametrize(
    ("document", "code"), [("{", "invalid_json"), ("{}", "invalid_document"), ("[]", "invalid_document")]
)
def test_validate_document_with_invalid(document: str, code: str) -> None:
    with pytest.raises(_native.CoreError) as raised:
        _native.validate_document(document)

    assert raised.value.code == code


def test_import_share_with_truncated_stream() -> None:
    snapshot: ShareSnapshot = ShareSnapshot(version=1, kind="play", plays=(_play(_signed_points()),))

    with pytest.raises(_native.CoreError) as raised:
        _ = _native.import_share(_native.new_document(), encode_share(snapshot)[:-1])

    assert raised.value.code == "invalid_share"
