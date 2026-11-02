import pytest

from gridiron_playbook.formations import FORMATION_NAMES
from gridiron_playbook.formations import formation_starts
from gridiron_playbook.formations import observed_route_slots
from gridiron_playbook.formations import position_label


@pytest.mark.parametrize(
    ("slot", "label"),
    [(0, "QB"), (1, "C"), (2, "LT"), (3, "RT"), (4, "RB"), (5, "WR-R"), (6, "WR-L"), (255, "Slot 255")],
)
def test_position_label(slot: int, label: str) -> None:
    for name in FORMATION_NAMES:
        assert position_label(name, slot) == label


def test_position_label_with_unknown_formation() -> None:
    assert position_label("Custom spread", 2) == "Slot 2"


@pytest.mark.parametrize(
    ("formation", "slots"),
    [
        ("Twins Right", (0, 2, 3, 4, 5, 6)),
        ("Twins Left", (0, 3, 4, 5, 6)),
        ("Singleback Deuce", (0, 2, 4, 5, 6)),
        ("Shotgun Right", (0, 2, 4, 5, 6)),
        ("Shotgun Left", (0, 3, 4, 5, 6)),
        ("I-Wing Right", (0, 2, 4, 5, 6)),
        ("I-Wing Left", (0, 3, 4, 5, 6)),
        ("Goal Line", (0, 2, 4, 5, 6)),
        ("Bunch Right", (0, 2, 4, 5, 6)),
        ("Bunch Left", (0, 3, 4, 5, 6)),
    ],
)
def test_observed_route_slots(formation: str, slots: tuple[int, ...]) -> None:
    assert formation in FORMATION_NAMES
    assert observed_route_slots(formation) == slots


def test_observed_route_slots_with_unknown_formation() -> None:
    assert observed_route_slots("Custom spread") == ()


def test_formation_starts_with_unknown_formation() -> None:
    assert not formation_starts("Custom spread")


def test_formation_starts_with_twins_right() -> None:
    assert formation_starts("Twins Right") == {
        0: (-600, 0),
        1: (-50, 0),
        2: (-50, -350),
        3: (-50, 350),
        4: (-50, 1050),
        5: (-50, 1650),
        6: (-50, -1350),
    }


@pytest.mark.parametrize("formation", FORMATION_NAMES)
def test_formation_starts_with_configured_formation(formation: str) -> None:
    assert set(formation_starts(formation)) == set(range(7))


def test_formation_starts_with_mirrored_wing() -> None:
    assert formation_starts("I-Wing Right")[5] == (-150, 700)
    assert formation_starts("I-Wing Left")[6] == (-150, -700)
