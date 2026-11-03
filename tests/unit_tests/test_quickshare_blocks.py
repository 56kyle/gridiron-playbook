from base64 import b64decode
from hashlib import sha256
from math import hypot
from struct import pack
from zlib import compress

import pytest

from gridiron_playbook.block import block_waypoints
from gridiron_playbook.block import ends_with_block
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.point import GridironPoint
from gridiron_playbook.quickshare.codec import Precision
from gridiron_playbook.quickshare.codec import decode_share
from gridiron_playbook.quickshare.codec import encode_share
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.route import GridironRoute


# Published v1 bytes for a two-node oblique route with a terminal block and a negative-zero height.
_V1_BLOCK = b64decode("""
eNpzDwxmZGBkdAMSAYysjHIMIKBgdwBMT4h2YICABjApWgLmN9jXwMVvyGz76FNf7pA2y2ruijnFcHGLXf7NIuLpDttK978r
eF4PF3+aKhow+2O6g/6v+2nXNRrg4us+SURMeFPuwCdpXfOMrQQu3nqiet/lyAqH7dOto1UKEeKTBG/LKJ3JcGi2TAj7Foswx27v
gpcrlmU63Kh44Co6GSEePe+eivjxCod4MRurpNsIcwxLHLujTCodOKbaSC5wLYWLv8pI26bfmOWgsyPB1OQEwpwZIjrN26KzHRq+P1A
J/osQ5/Ba8nHuwkqHDcK2P+6uR5hzT5494iFflUPEJNvr0lJlcHGXAx/9bc1yHK6YJYoUGTXCxT9mb5c5IpDroFH2kHliOkJ8y9fMf
So1VQ4MgnbbIlsQ5nSdPqOS8bLKYUW/3dTp7xDic8VrX3q9znWo2Zr4ef0chDleh522XTya53Dhy8NH5y4ixBMX6nevDqt2COSzL7k
aUQ4XNy+f9PHd4WqHnz32wcKHEeLf8jiaIxbkO6iaJF16y9YEFw/ifb4837bAobL40UEeG4Q4n+/XcCPDGodF3A5GgboVcPEnShH7Su
fVOHh1OQj2T0eIazz25Nu8qsDh7KakjdqFTQTDDVf6BABlK9oT
""")
_V2_SINGLE_ROUTE = b"GQS\x02\x00\x01\x01F\x01\x00\x01P\x01"
_BAD_SHARE = "Quickshare"


def _xyz_bytes(points: tuple[GridironPoint, ...]) -> bytes:
    return b"".join(pack("<ddd", p.x, p.y, p.z) for p in points)


def _share(points: tuple[GridironPoint, ...]) -> ShareSnapshot:
    route = GridironRoute(Slot_0=5, Points_0=points)
    play = GridironPlay(FormationName_0="Unknown", PlayName_0="Block", Routes_0=(route,))
    return ShareSnapshot(version=1, kind="play", plays=(play,))


def _insert_block(points: tuple[GridironPoint, ...], anchor: int) -> tuple[GridironPoint, ...]:
    after: int = anchor + 1
    return points[:after] + block_waypoints(points, anchor, None) + points[after:]


def test_decode_share_with_version_one_literal_block() -> None:
    points = decode_share(_V1_BLOCK).plays[0].routes[0].points
    assert sha256(_xyz_bytes(points)).hexdigest() == "11ecb77c697981419aa9556c6580b94c5bb8086c812cfbe5655e03b082b31875"


@pytest.mark.parametrize(
    ("encoded", "expected"),
    [
        ("eNpzDwxmZGBkdAMSAYyszEw3WeYIMnwx22LKAAA35QUv", ((-30.1, 110.2, 0.0), (321.3, 452.0, 0.0))),
        ("eNpzDwxmZGBkdAMSAYysrEzWdxgZ9rGuYWUAAC8kBCA=", ((-30.0, 110.0, 0.0), (321.0, 452.0, 0.0))),
    ],
    ids=["1mm", "1cm"],
)
def test_decode_share_with_version_one_compact_coordinates(
    encoded: str, expected: tuple[tuple[float, float, float], ...]
) -> None:
    route = decode_share(b64decode(encoded)).plays[0].routes[0]
    assert tuple((p.x, p.y, p.z) for p in route.points) == expected


@pytest.mark.parametrize("precision", list(Precision))
def test_encode_share_compresses_standard_block(precision: Precision) -> None:
    shared = decode_share(_V1_BLOCK)
    assert len(encode_share(shared, precision)) < len(_V1_BLOCK) // 2


@pytest.fixture
def oblique_block() -> ShareSnapshot:
    before = GridironPoint(X_0=-6, Y_0=-400, Z_0=8.375)
    center = GridironPoint(X_0=950.739124, Y_0=-804.91804, Z_0=8.375)
    return _share(_insert_block((before, center), 1))


@pytest.mark.parametrize("precision", [Precision.MILLIMETER, Precision.CENTIMETER])
def test_encode_share_reuses_compact_block_heading(oblique_block: ShareSnapshot, precision: Precision) -> None:
    data = encode_share(oblique_block, precision)
    assert encode_share(decode_share(data), precision) == data


@pytest.mark.parametrize("precision", [Precision.MILLIMETER, Precision.CENTIMETER])
def test_encode_share_with_exact_copy_of_compact_block(oblique_block: ShareSnapshot, precision: Precision) -> None:
    data = encode_share(oblique_block, precision)
    original = decode_share(data)
    exact = encode_share(original, Precision.EXACT)
    assert len(exact) < 4 * len(data)
    assert _xyz_bytes(decode_share(exact).plays[0].routes[0].points) == _xyz_bytes(original.plays[0].routes[0].points)


@pytest.mark.parametrize("precision", [Precision.MILLIMETER, Precision.CENTIMETER])
def test_encode_share_stably_omits_rounded_zero_block_heights(precision: Precision) -> None:
    data = encode_share(decode_share(_V1_BLOCK), precision)
    assert encode_share(decode_share(data), precision) == data


@pytest.mark.parametrize("anchor", [0, 1, 4, 29], ids=["first-node", "adjacent", "nested", "last-node"])
def test_encode_share_with_multiple_exact_blocks(anchor: int) -> None:
    points = decode_share(_V1_BLOCK).plays[0].routes[0].points
    expanded = _insert_block(points, anchor)
    actual = decode_share(encode_share(_share(expanded))).plays[0].routes[0].points
    assert _xyz_bytes(actual) == _xyz_bytes(expanded)


@pytest.mark.parametrize("precision", list(Precision))
def test_encode_share_preserves_a_hand_edited_block(precision: Precision) -> None:
    points = decode_share(_V1_BLOCK).plays[0].routes[0].points
    adjusted = points[5].model_copy(update={"x": points[5].x + 0.025})
    edited = (*points[:5], adjusted, *points[6:])
    assert ends_with_block(edited)
    restored = decode_share(encode_share(_share(edited), precision)).plays[0].routes[0].points
    assert _xyz_bytes(restored) == _xyz_bytes(edited)


@pytest.mark.parametrize("precision", [Precision.MILLIMETER, Precision.CENTIMETER])
@pytest.mark.parametrize("edit", ["moved-return", "removed-stroke"])
def test_encode_share_preserves_an_incomplete_block(precision: Precision, edit: str) -> None:
    points = decode_share(_V1_BLOCK).plays[0].routes[0].points
    if edit == "moved-return":
        moved = points[-1].model_copy(update={"y": points[-1].y + 0.025})
        edited = (*points[:-1], moved)
    else:
        edited = (*points[:12], *points[13:])
    assert not ends_with_block(edited)
    restored = decode_share(encode_share(_share(edited), precision)).plays[0].routes[0].points
    assert _xyz_bytes(restored) == _xyz_bytes(edited)


@pytest.mark.parametrize("precision", [Precision.MILLIMETER, Precision.CENTIMETER])
def test_encode_share_rounds_an_ordinary_loop_the_size_of_a_block(precision: Precision) -> None:
    path = tuple(GridironPoint(X_0=i + 0.125, Y_0=i * i - 0.25, Z_0=1.625) for i in range(28))
    loop = (*path, path[0])
    restored = decode_share(encode_share(_share(loop), precision)).plays[0].routes[0].points
    multiplier = 10 if precision == Precision.MILLIMETER else 1
    expected = tuple(
        GridironPoint(
            X_0=round(p.x * multiplier) / multiplier,
            Y_0=round(p.y * multiplier) / multiplier,
            Z_0=round(p.z * multiplier) / multiplier,
        )
        for p in loop
    )
    assert restored == expected


@pytest.mark.parametrize("precision", [Precision.MILLIMETER, Precision.CENTIMETER])
def test_encode_share_preserves_heading_when_quantized_approach_collapses(precision: Precision) -> None:
    before = GridironPoint(X_0=3.010, Y_0=2.010, Z_0=0)
    anchor = GridironPoint(X_0=3.048, Y_0=2.041, Z_0=0)
    original = _insert_block((before, anchor), 1)
    restored = decode_share(encode_share(_share(original), precision)).plays[0].routes[0].points
    assert restored[0] == restored[1] == GridironPoint(X_0=3, Y_0=2, Z_0=0)
    dx, dy = anchor.x - before.x, anchor.y - before.y
    sideways = restored[-2]
    sx, sy = sideways.x - restored[-1].x, sideways.y - restored[-1].y
    assert (sy / hypot(sx, sy), -sx / hypot(sx, sy)) == pytest.approx(
        (dx / hypot(dx, dy), dy / hypot(dx, dy)), abs=0.00005
    )


@pytest.mark.parametrize("token", [b"\x00", b"\x01" + pack("<dd", 1.0, 0.0)], ids=["inferred-facing", "stored-facing"])
def test_decode_share_with_version_two_recipe(token: bytes) -> None:
    literals = b"\x05\x08\x02" + pack("<dddd", 0.0, 0.0, 1.0, 0.0)
    route = decode_share(compress(_V2_SINGLE_ROUTE + literals + b"\x01\x01" + token)).plays[0].routes[0]
    assert (
        sha256(_xyz_bytes(route.points)).hexdigest()
        == "cde9ba0562aa8f5dbad4a8d5b8d6eb810896100021e1c73068004033f6d526d9"
    )


@pytest.mark.parametrize(
    "table",
    [
        b"\x00",
        b"\x01\x02\x01" + pack("<dd", 1.0, 0.0),
        b"\x01\x00\x00",
        b"\x01\x01\x03",
        b"\x01\x01\x01" + pack("<dd", 2.0, 0.0),
        b"\x01\x01\x02\x00\x00",
        b"\x02\x01\x00\x00\x01" + pack("<dd", 1.0, 0.0),
        b"\xca\x04" + 586 * b"\x01\x00",
    ],
    ids=[
        "empty",
        "bad-anchor",
        "missing-approach",
        "unknown-tag",
        "nonunit",
        "angle-in-exact",
        "unordered",
        "over-limit",
    ],
)
def test_decode_share_with_invalid_block_table(table: bytes) -> None:
    literals = b"\x05\x08\x02" + pack("<dddd", 0.0, 0.0, 1.0, 0.0)
    with pytest.raises(ValueError, match=_BAD_SHARE):
        _ = decode_share(compress(_V2_SINGLE_ROUTE + literals + table))
