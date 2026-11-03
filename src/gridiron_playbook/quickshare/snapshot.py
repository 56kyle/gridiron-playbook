"""Versioned Quickshare payloads containing only completed plays."""

import re
from math import isfinite
from sys import float_info
from typing import Literal

from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator
from typing_extensions import Self

from gridiron_playbook.play import GridironPlay
from gridiron_playbook.schema import GridironModel


MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
_MAX_PLAYS = 2_000
_MAX_ROUTES_PER_PLAY = 256
_MAX_POINTS_PER_PLAY = 16_384
_MAX_TOTAL_POINTS = 200_000
_MAX_NAME_LENGTH = 1_024
# Leave room to fit a field spanning the origin and sum every segment's length.
_MAX_FIELD_COORDINATE: float = float_info.max / (4 * _MAX_POINTS_PER_PLAY)
_SHARE_ID = re.compile(r"[A-Za-z0-9_-]{22}")
_UNSAVABLE_NAME_CHARACTER = re.compile(r"[\x00\ud800-\udfff]")


class SnapshotTooLargeError(ValueError):
    """A serialized snapshot exceeds the transfer limit."""


def is_share_id(value: str) -> bool:
    """Check the URL-safe identifier issued for a stored snapshot."""
    return _SHARE_ID.fullmatch(value) is not None


def _validate_name(name: str) -> None:
    if len(name) > _MAX_NAME_LENGTH:
        raise ValueError("A play or formation name exceeds the Quickshare name limit.")
    if _UNSAVABLE_NAME_CHARACTER.search(name):
        raise ValueError("Play and formation names must contain valid Unicode text without NUL characters.")


def _point_count(play: GridironPlay) -> int:
    _validate_name(play.formation_name)
    _validate_name(play.play_name)
    if len(play.routes) > _MAX_ROUTES_PER_PLAY:
        raise ValueError("A play exceeds the Quickshare route limit.")
    count: int = sum(len(route.points) for route in play.routes)
    if count > _MAX_POINTS_PER_PLAY:
        raise ValueError("A play exceeds the Quickshare waypoint limit.")
    for route in play.routes:
        if not 0 <= route.slot <= 255:
            raise ValueError("A player slot must be between 0 and 255.")
        for point in route.points:
            if not (
                abs(point.x) <= _MAX_FIELD_COORDINATE and abs(point.y) <= _MAX_FIELD_COORDINATE and isfinite(point.z)
            ):
                raise ValueError("Route coordinates must be finite and fit the field diagram.")
    return count


class ShareSnapshot(GridironModel):
    """An ordered, immutable selection of plays independent of the sender's save."""

    version: Literal[1]
    kind: Literal["play", "playbook"]
    plays: tuple[GridironPlay, ...] = Field(min_length=1, max_length=_MAX_PLAYS)

    @field_validator("version", mode="before")
    @classmethod
    def _require_integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("The Quickshare version must be an integer.")
        return value

    @model_validator(mode="after")
    def _validate_selection(self) -> Self:
        if self.kind == "play" and len(self.plays) != 1:
            raise ValueError("A single-play share must contain exactly one play.")
        if sum(_point_count(play) for play in self.plays) > _MAX_TOTAL_POINTS:
            raise ValueError("This playbook exceeds the Quickshare waypoint limit.")
        return self

    def to_bytes(self) -> bytes:
        """Encode compact JSON for storage or transfer."""
        data: bytes = self.model_dump_json(by_alias=False).encode("utf-8")
        if len(data) > MAX_SNAPSHOT_BYTES:
            raise SnapshotTooLargeError("The Quickshare size limit is 16 MiB.")
        return data

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        """Decode and validate a bounded snapshot."""
        if len(data) > MAX_SNAPSHOT_BYTES:
            raise SnapshotTooLargeError("The Quickshare size limit is 16 MiB.")
        return cls.model_validate_json(data, strict=True)
