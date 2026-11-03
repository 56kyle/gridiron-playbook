from math import copysign
from struct import pack
from zlib import compress
from zlib import decompress

import pytest

from gridiron_playbook.block import block_waypoints
from gridiron_playbook.block import ends_with_block
from gridiron_playbook.block import route_yards_without_blocks
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.point import GridironPoint
from gridiron_playbook.quickshare.codec import MAX_SHARE_BYTES
from gridiron_playbook.quickshare.codec import Precision
from gridiron_playbook.quickshare.codec import decode_share
from gridiron_playbook.quickshare.codec import encode_share
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.quickshare.snapshot import SnapshotTooLargeError
from gridiron_playbook.route import GridironRoute


_BAD_SHARE = "Quickshare"


@pytest.fixture
def share() -> ShareSnapshot:
    first = GridironPoint(X_0=17.6253, Y_0=-3.7975, Z_0=-0.0)
    last = GridironPoint(X_0=-128.48413, Y_0=999.954931, Z_0=3.74963)
    route = GridironRoute(Slot_0=250, Points_0=(first, first, last))
    play = GridironPlay(FormationName_0="Trébol", PlayName_0="左 🏈", Routes_0=(route, route))
    return ShareSnapshot(version=1, kind="playbook", plays=(play, play))


def test_encode_share_with_exact_coordinates(share: ShareSnapshot) -> None:
    restored = decode_share(encode_share(share))
    assert restored == share
    assert copysign(1, restored.plays[0].routes[0].points[0].z) == -1


def test_encode_share_with_only_negative_zero_height() -> None:
    point = GridironPoint(X_0=-0.0, Y_0=0.0, Z_0=-0.0)
    route = GridironRoute(Slot_0=4, Points_0=(point,))
    snapshot = ShareSnapshot(
        version=1, kind="play", plays=(GridironPlay(FormationName_0="Unknown", PlayName_0="", Routes_0=(route,)),)
    )
    restored = decode_share(encode_share(snapshot)).plays[0].routes[0].points[0]
    assert pack("<ddd", restored.x, restored.y, restored.z) == pack("<ddd", point.x, point.y, point.z)


@pytest.mark.parametrize(("precision", "step_cm"), [(Precision("1mm"), 0.1), (Precision("1cm"), 1.0)])
def test_encode_share_with_rounded_coordinates(share: ShareSnapshot, precision: Precision, step_cm: float) -> None:
    original = share.plays[0].routes[0]
    restored = decode_share(encode_share(share, precision)).plays[0].routes[0]
    for before, after in zip(original.points, restored.points, strict=True):
        for initial, decoded in [(before.x, after.x), (before.y, after.y), (before.z, after.z)]:
            assert decoded == pytest.approx(round(initial / step_cm) * step_cm, abs=1e-10, rel=0)


@pytest.mark.parametrize("precision", [Precision("1mm"), Precision("1cm")])
@pytest.mark.parametrize("terminal", [True, False], ids=["at-end", "mid-route"])
def test_encode_share_with_standard_block(share: ShareSnapshot, precision: Precision, terminal: bool) -> None:
    play = share.plays[0]
    route = play.routes[0]
    anchor: int = len(route.points) - 1 if terminal else 1
    stamp = block_waypoints(route.points, anchor, None)
    blocked = route.model_copy(update={"points": (*route.points[: anchor + 1], *stamp, *route.points[anchor + 1 :])})
    shared = ShareSnapshot(version=1, kind="play", plays=(play.model_copy(update={"routes": (blocked,)}),))

    restored = decode_share(encode_share(shared, precision)).plays[0].routes[0]
    assert ends_with_block(restored.points[: anchor + 1 + len(stamp)])
    assert route_yards_without_blocks(restored, None) == pytest.approx(
        route_yards_without_blocks(route, None), abs=0.02
    )


def test_decode_share_with_version_one_exact_wire() -> None:
    # One form "F", one play "P", one route in slot 5, one XY point with implicit zero Z.
    raw = b"GQS\x01\x00\x01\x01F\x01\x00\x01P\x01\x05\x00\x01" + pack("<dd", -4.5, 71.25)
    snap = decode_share(compress(raw))
    assert snap.kind == "play"
    assert snap.plays == (
        GridironPlay(
            FormationName_0="F",
            PlayName_0="P",
            Routes_0=(GridironRoute(Slot_0=5, Points_0=(GridironPoint(X_0=-4.5, Y_0=71.25, Z_0=0),)),),
        ),
    )


@pytest.mark.parametrize(
    "invalid",
    [
        b"not compressed",
        compress(b"GQS\x03\x00"),
        compress(b"GQS\x01\x00\x01\x01F\x01\x00\x01P\x01\x05\x00\xff\xff\x7f"),
        compress(b"GQS\x01\x00" + b"\x80" * 32),
    ],
    ids=["not-zlib", "unknown-version", "huge-waypoint-count", "unterminated-count"],
)
def test_decode_share_with_invalid_format(invalid: bytes) -> None:
    with pytest.raises(ValueError, match=_BAD_SHARE):
        _ = decode_share(invalid)


def test_decode_share_with_truncated_payload(share: ShareSnapshot) -> None:
    with pytest.raises(ValueError, match=_BAD_SHARE):
        _ = decode_share(encode_share(share)[:-1])


@pytest.mark.parametrize("compressed", [False, True], ids=["oversized-file", "oversized-inflated-data"])
def test_decode_share_with_oversized_payload(compressed: bool) -> None:
    raw: bytes = bytes(MAX_SHARE_BYTES + 1)
    with pytest.raises(SnapshotTooLargeError):
        _ = decode_share(compress(raw) if compressed else raw)


@pytest.mark.parametrize("inside_stream", [True, False], ids=["after-last-play", "after-compressed-stream"])
def test_decode_share_with_trailing_bytes(share: ShareSnapshot, inside_stream: bool) -> None:
    valid: bytes = encode_share(share)
    invalid: bytes = compress(decompress(valid) + b"x") if inside_stream else valid + b"x"
    with pytest.raises(ValueError, match=_BAD_SHARE):
        _ = decode_share(invalid)
