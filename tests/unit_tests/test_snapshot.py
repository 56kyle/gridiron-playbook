import json

import pytest
from pydantic import ValidationError

from gridiron_playbook.play import GridironPlay
from gridiron_playbook.quickshare.snapshot import MAX_SNAPSHOT_BYTES
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.quickshare.snapshot import SnapshotTooLargeError


def _wire(plays: int = 1, **fields: object) -> bytes:
    play = GridironPlay(FormationName_0="Custom spread", PlayName_0="Switch", Routes_0=())
    return json.dumps({"version": 1, "kind": "play", "plays": [play.model_dump()] * plays, **fields}).encode()


@pytest.mark.parametrize(
    "payload",
    [
        b"{",
        _wire(version=2),
        _wire(kind="route"),
        _wire(plays=2),
        _wire(plays=0, kind="playbook"),
        _wire(header={"not": "share data"}),
    ],
    ids=["invalid-json", "unknown-version", "unknown-kind", "multiple-in-single", "empty-book", "save-metadata"],
)
def test_from_bytes_with_invalid_snapshot(payload: bytes) -> None:
    with pytest.raises(ValidationError):
        _ = ShareSnapshot.from_bytes(payload)


def test_from_bytes_with_oversized_snapshot() -> None:
    with pytest.raises(SnapshotTooLargeError):
        _ = ShareSnapshot.from_bytes(_wire().ljust(MAX_SNAPSHOT_BYTES + 1))


@pytest.mark.parametrize("field", ["play_name", "formation_name"])
def test_from_bytes_with_nul_in_name(field: str) -> None:
    play = GridironPlay(FormationName_0="Custom", PlayName_0="Slant", Routes_0=())
    payload = {"version": 1, "kind": "play", "plays": [play.model_dump() | {field: "left\x00right"}]}
    with pytest.raises(ValidationError):
        _ = ShareSnapshot.from_bytes(json.dumps(payload).encode())


@pytest.mark.parametrize("field", ["play_name", "formation_name"])
def test_snapshot_rejects_unencodable_name(field: str) -> None:
    play = GridironPlay(FormationName_0="Custom", PlayName_0="Slant", Routes_0=()).model_copy(update={field: "\ud800"})
    with pytest.raises(ValidationError):
        _ = ShareSnapshot(version=1, kind="play", plays=(play,))


def test_to_bytes_with_unicode_names() -> None:
    play = GridironPlay(FormationName_0="Formación 🏈", PlayName_0="右", Routes_0=())
    snapshot = ShareSnapshot(version=1, kind="play", plays=(play,))
    assert ShareSnapshot.from_bytes(snapshot.to_bytes()).plays == (play,)


@pytest.mark.parametrize(("slot", "value"), [(-1, 1), (256, 1), (0, float("inf")), (0, float("nan"))])
def test_from_bytes_with_invalid_geometry(slot: int, value: float) -> None:
    play = {
        "formation_name": "Custom",
        "play_name": "Drift",
        "routes": [{"slot": slot, "points": [{"x": value, "y": 0, "z": 0}]}],
    }
    body = json.dumps({"version": 1, "kind": "play", "plays": [play]}).encode()
    with pytest.raises(ValidationError):
        _ = ShareSnapshot.from_bytes(body)
