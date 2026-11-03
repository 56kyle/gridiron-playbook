"""Portable Quickshare v2 encoder and v1/v2 decoder."""

import math
import struct
import zlib
from enum import Enum
from io import BytesIO

from gridiron_playbook.formations import formation_starts
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.point import GridironPoint
from gridiron_playbook.quickshare.block_tokens import BLOCK_POINTS
from gridiron_playbook.quickshare.block_tokens import Direction
from gridiron_playbook.quickshare.block_tokens import RouteBlock
from gridiron_playbook.quickshare.block_tokens import check_direction
from gridiron_playbook.quickshare.block_tokens import compact_heading
from gridiron_playbook.quickshare.block_tokens import expand_blocks
from gridiron_playbook.quickshare.block_tokens import has_block_strokes
from gridiron_playbook.quickshare.block_tokens import heading_direction
from gridiron_playbook.quickshare.block_tokens import inferred_direction
from gridiron_playbook.quickshare.block_tokens import split_blocks
from gridiron_playbook.quickshare.snapshot import MAX_NAME_LENGTH
from gridiron_playbook.quickshare.snapshot import MAX_PLAYS
from gridiron_playbook.quickshare.snapshot import MAX_POINTS_PER_PLAY
from gridiron_playbook.quickshare.snapshot import MAX_ROUTES_PER_PLAY
from gridiron_playbook.quickshare.snapshot import MAX_SNAPSHOT_BYTES
from gridiron_playbook.quickshare.snapshot import MAX_TOTAL_POINTS
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.quickshare.snapshot import SnapshotTooLargeError
from gridiron_playbook.quickshare.snapshot import validate_share_name
from gridiron_playbook.route import GridironRoute


class Precision(str, Enum):
    """Coordinate precision available for a portable link."""

    EXACT = "exact"
    MILLIMETER = "1mm"
    CENTIMETER = "1cm"


_MAGIC = b"GQS"
WIRE_VERSION = 2
_BLOCK_TABLE = 8
MAX_SHARE_BYTES: int = MAX_SNAPSHOT_BYTES
_GRID_LIMIT = (1 << 30) - 1
_MAX_DELTA_CODE = 4 * _GRID_LIMIT
_XY = struct.Struct("<dd")
_XYZ = struct.Struct("<ddd")


def _uint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 128:
        encoded.append((value & 127) | 128)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _text(value: str) -> bytes:
    data: bytes = value.encode("utf-8")
    return _uint(len(data)) + data


def _route_mode(points: list[GridironPoint], precision: Precision) -> int:
    if precision == Precision.EXACT or has_block_strokes(points):
        return 0
    mode: int = 1 if precision == Precision.MILLIMETER else 2
    limit: float = _GRID_LIMIT / 10 if mode == 1 else _GRID_LIMIT
    for point in points:
        if max(abs(point.x), abs(point.y), abs(point.z)) > limit:
            return 0
    return mode


def _write_points(data: bytearray, points: list[GridironPoint], mode: int, has_z: bool) -> None:
    data.extend(_uint(len(points)))
    previous: list[int] = [0, 0, 0]
    multiplier: int = 10 if mode == 1 else 1
    for point in points:
        coords: tuple[float, ...] = (point.x, point.y, point.z) if has_z else (point.x, point.y)
        if mode == 0:
            data.extend((_XYZ if has_z else _XY).pack(*coords))
        else:
            for axis, coord in enumerate(coords):
                value: int = round(coord * multiplier)
                delta: int = value - previous[axis]
                previous[axis] = value
                data.extend(_uint(2 * delta if delta >= 0 else -2 * delta - 1))


def _write_block(data: bytearray, points: list[GridironPoint], block: RouteBlock, mode: int) -> None:
    data.extend(_uint(block.anchor))
    if mode:
        data.append(2)
        data.extend(struct.pack("<H", compact_heading(block.direction)))
    else:
        inferred: Direction | None = inferred_direction(points, block.anchor)
        vector: bytes = _XY.pack(*block.direction)
        if inferred is not None and _XY.pack(*inferred) == vector:
            data.append(0)
        else:
            data.append(1)
            data.extend(vector)


def _write_route(
    data: bytearray, route: GridironRoute, precision: Precision, start: tuple[float, float] | None
) -> None:
    points, blocks = split_blocks(route.points, start)
    mode: int = _route_mode(points, precision)
    if mode == 0:
        has_z: bool = any(p.z != 0.0 or math.copysign(1, p.z) < 0 for p in points)
    else:
        multiplier: int = 10 if mode == 1 else 1
        has_z = any(round(p.z * multiplier) != 0 for p in points)
    flags: int = (2 * mode + has_z) | (_BLOCK_TABLE if blocks else 0)
    data.extend((route.slot, flags))
    _write_points(data, points, mode, has_z)
    if blocks:
        data.extend(_uint(len(blocks)))
        for block in blocks:
            _write_block(data, points, block, mode)


def encode_share(snapshot: ShareSnapshot, precision: Precision = Precision.EXACT) -> bytes:
    """Encode a bounded self-contained payload, using exact coordinates by default."""
    precision = Precision(precision)
    data = bytearray(_MAGIC)
    data.append(WIRE_VERSION)
    data.append(0 if snapshot.kind == "play" else 1)
    formations: dict[str, int] = {}
    for play in snapshot.plays:
        _ = formations.setdefault(play.formation_name, len(formations))
    data.extend(_uint(len(formations)))
    for formation in formations:
        data.extend(_text(formation))
    data.extend(_uint(len(snapshot.plays)))
    for play in snapshot.plays:
        data.extend(_uint(formations[play.formation_name]))
        data.extend(_text(play.play_name))
        data.extend(_uint(len(play.routes)))
        for route in play.routes:
            _write_route(data, route, precision, formation_starts(play.formation_name).get(route.slot))
        if len(data) > MAX_SHARE_BYTES:
            raise SnapshotTooLargeError("The Quickshare size limit is 16 MiB.")
    compressed: bytes = zlib.compress(data, level=9)
    if len(compressed) > MAX_SHARE_BYTES:
        raise SnapshotTooLargeError("The Quickshare size limit is 16 MiB.")
    return compressed


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.stream: BytesIO = BytesIO(data)
        self.points_left: int = MAX_TOTAL_POINTS

    def take(self, size: int) -> bytes:
        value: bytes = self.stream.read(size)
        if len(value) != size:
            raise ValueError("The Quickshare data is incomplete.")
        return value

    def uint(self, limit: int) -> int:
        value: int = 0
        for shift in range(0, limit.bit_length() + 1, 7):
            byte: int = self.take(1)[0]
            value |= (byte & 127) << shift
            if byte < 128:
                if value <= limit and (shift == 0 or byte != 0):
                    return value
                break
        raise ValueError("Invalid Quickshare count or coordinate.")

    def text(self) -> str:
        value: str = self.take(self.uint(4 * MAX_NAME_LENGTH)).decode("utf-8")
        validate_share_name(value)
        return value

    def literal_points(self, flags: int, count: int) -> list[GridironPoint]:
        mode: int = flags >> 1
        has_z: bool = bool(flags & 1)
        previous: list[int] = [0, 0, 0]
        points: list[GridironPoint] = []
        for _ in range(count):
            if mode == 0:
                layout: struct.Struct = _XYZ if has_z else _XY
                coords: tuple[float, ...] = layout.unpack(self.take(layout.size))
            else:
                for axis in range(3 if has_z else 2):
                    code: int = self.uint(_MAX_DELTA_CODE)
                    previous[axis] += (code >> 1) ^ -(code & 1)
                    if abs(previous[axis]) > _GRID_LIMIT:
                        raise ValueError("Quickshare grid coordinate is out of range.")
                coords = tuple(value / (10 if mode == 1 else 1) for value in previous)
            points.append(GridironPoint(X_0=coords[0], Y_0=coords[1], Z_0=coords[2] if has_z else 0.0))
        return points

    def block_direction(self, points: list[GridironPoint], anchor: int, mode: int) -> Direction:
        tag: int = self.take(1)[0]
        if mode and tag == 2:
            return heading_direction(int.from_bytes(self.take(2), "little"))
        if mode == 0 and tag == 0:
            direction: Direction | None = inferred_direction(points, anchor)
            if direction is not None:
                return direction
        if mode == 0 and tag == 1:
            vector: Direction = _XY.unpack(self.take(_XY.size))
            check_direction(vector)
            return vector
        raise ValueError("Invalid Quickshare block instruction.")

    def blocks(self, points: list[GridironPoint], mode: int, remaining: int) -> list[RouteBlock]:
        count: int = self.uint(min(remaining, self.points_left) // BLOCK_POINTS)
        if not points or not count:
            raise ValueError("Empty Quickshare block table or route.")
        self.points_left -= count * BLOCK_POINTS
        blocks: list[RouteBlock] = []
        for _ in range(count):
            anchor: int = self.uint(len(points) - 1)
            if blocks and anchor < blocks[-1].anchor:
                raise ValueError("Quickshare block anchors must follow route order.")
            blocks.append(RouteBlock(anchor, self.block_direction(points, anchor, mode)))
        return blocks

    def route(self, remaining: int, version: int) -> GridironRoute:
        slot, flags = self.take(2)
        has_blocks: bool = version == 2 and bool(flags & _BLOCK_TABLE)
        if has_blocks:
            flags ^= _BLOCK_TABLE
        if flags > 5:
            raise ValueError("Unknown Quickshare coordinate format.")
        count: int = self.uint(min(remaining, self.points_left))
        self.points_left -= count
        points: list[GridironPoint] = self.literal_points(flags, count)
        if has_blocks:
            points = expand_blocks(points, self.blocks(points, flags >> 1, remaining - count))
        return GridironRoute(Slot_0=slot, Points_0=tuple(points))

    def play(self, formations: list[str], version: int) -> GridironPlay:
        formation: str = formations[self.uint(len(formations) - 1)]
        name: str = self.text()
        routes: list[GridironRoute] = []
        remaining: int = MAX_POINTS_PER_PLAY
        for _ in range(self.uint(MAX_ROUTES_PER_PLAY)):
            route: GridironRoute = self.route(remaining, version)
            remaining -= len(route.points)
            routes.append(route)
        return GridironPlay(FormationName_0=formation, PlayName_0=name, Routes_0=tuple(routes))


def decode_share(data: bytes) -> ShareSnapshot:
    """Validate and decode one complete compressed Quickshare file or link payload."""
    if len(data) > MAX_SHARE_BYTES:
        raise SnapshotTooLargeError("The Quickshare size limit is 16 MiB.")
    inflater = zlib.decompressobj()
    try:
        raw: bytes = inflater.decompress(data, MAX_SHARE_BYTES + 1)
    except zlib.error as error:
        raise ValueError("Invalid compressed Quickshare data.") from error
    if len(raw) > MAX_SHARE_BYTES:
        raise SnapshotTooLargeError("The Quickshare size limit is 16 MiB.")
    if not inflater.eof or inflater.unused_data:
        raise ValueError("Expected one complete Quickshare payload.")
    reader = _Reader(raw)
    magic: bytes = reader.take(len(_MAGIC))
    version: int = reader.take(1)[0]
    if magic != _MAGIC or version not in {1, WIRE_VERSION}:
        raise ValueError("Unknown Quickshare file format or version.")
    kind: int = reader.take(1)[0]
    if kind > 1:
        raise ValueError("Unknown Quickshare selection.")
    formations: list[str] = [reader.text() for _ in range(reader.uint(MAX_PLAYS))]
    if not formations:
        raise ValueError("The Quickshare formation table is empty.")
    plays: tuple[GridironPlay, ...] = tuple(
        reader.play(formations, version) for _ in range(reader.uint(1 if kind == 0 else MAX_PLAYS))
    )
    if reader.stream.read(1):
        raise ValueError("Unexpected trailing Quickshare data.")
    return ShareSnapshot(version=1, kind="play" if kind == 0 else "playbook", plays=plays)
