"""Offensive alignments for the ten formations in the reference playbook.

Game-space X points upfield and Y points to the offense's right. The playtest's
CustomCookData/formations.txt (Steam build 26369073) supplies the slot roles and
pre-snap locations. Its T and WR roles are distinguished here by starting side.
The drawn-slot samples come from the 34-play GridironCustomPlays.json export.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class _Formation:
    starts: Mapping[int, tuple[float, float]]
    observed_slots: tuple[int, ...]


def _formation(
    *,
    qb_x: float,
    rb: tuple[float, float],
    right_wr: tuple[float, float],
    left_wr: tuple[float, float],
    drawn_tackles: tuple[int, ...],
) -> _Formation:
    starts: dict[int, tuple[float, float]] = {
        0: (qb_x, 0),
        1: (-50, 0),
        2: (-50, -350),
        3: (-50, 350),
        4: rb,
        5: right_wr,
        6: left_wr,
    }
    return _Formation(MappingProxyType(starts), (0, *drawn_tackles, 4, 5, 6))


_FORMATIONS: Mapping[str, _Formation] = MappingProxyType(
    {
        "Twins Right": _formation(
            qb_x=-600, rb=(-50, 1050), right_wr=(-50, 1650), left_wr=(-50, -1350), drawn_tackles=(2, 3)
        ),
        "Twins Left": _formation(
            qb_x=-600, rb=(-50, -1050), right_wr=(-50, 1400), left_wr=(-50, -1650), drawn_tackles=(3,)
        ),
        "Singleback Deuce": _formation(
            qb_x=-400, rb=(-650, 0), right_wr=(-50, 1700), left_wr=(-50, -1700), drawn_tackles=(2,)
        ),
        "Shotgun Right": _formation(
            qb_x=-600, rb=(-550, 300), right_wr=(-50, 1650), left_wr=(-50, -1650), drawn_tackles=(2,)
        ),
        "Shotgun Left": _formation(
            qb_x=-600, rb=(-550, -300), right_wr=(-50, 1650), left_wr=(-50, -1650), drawn_tackles=(3,)
        ),
        "I-Wing Right": _formation(
            qb_x=-400, rb=(-700, 0), right_wr=(-150, 700), left_wr=(-50, -1650), drawn_tackles=(2,)
        ),
        "I-Wing Left": _formation(
            qb_x=-400, rb=(-700, 0), right_wr=(-50, 1650), left_wr=(-150, -700), drawn_tackles=(3,)
        ),
        "Goal Line": _formation(
            qb_x=-400, rb=(-650, 0), right_wr=(-100, 700), left_wr=(-100, -700), drawn_tackles=(2,)
        ),
        "Bunch Right": _formation(
            qb_x=-600, rb=(-200, 1050), right_wr=(-50, 1650), left_wr=(-50, -1350), drawn_tackles=(2,)
        ),
        "Bunch Left": _formation(
            qb_x=-600, rb=(-200, -1050), right_wr=(-50, 1350), left_wr=(-50, -1650), drawn_tackles=(3,)
        ),
    }
)
FORMATION_NAMES: tuple[str, ...] = tuple(_FORMATIONS)
_POSITION_LABELS: tuple[str, ...] = ("QB", "C", "LT", "RT", "RB", "WR-R", "WR-L")
_NO_STARTS: Mapping[int, tuple[float, float]] = MappingProxyType({})


def formation_starts(formation_name: str) -> Mapping[int, tuple[float, float]]:
    """Return read-only pre-snap (X, Y) coordinates by slot, or an empty mapping for an unknown formation."""
    formation: _Formation | None = _FORMATIONS.get(formation_name)
    return formation.starts if formation is not None else _NO_STARTS


def observed_route_slots(formation_name: str) -> tuple[int, ...]:
    """Return slots with routes in the reference export as suggestions for an editor."""
    formation: _Formation | None = _FORMATIONS.get(formation_name)
    return formation.observed_slots if formation is not None else ()


def position_label(formation_name: str, slot: int) -> str:
    """Describe a known formation slot, retaining the slot number when the position is unknown."""
    if formation_name in _FORMATIONS and 0 <= slot < len(_POSITION_LABELS):
        return _POSITION_LABELS[slot]
    return f"Slot {slot}"
