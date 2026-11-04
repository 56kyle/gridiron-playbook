from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from gridiron_playbook.point import GridironPoint


if TYPE_CHECKING:
    from gridiron_playbook.editor import PlaybookEditor
    from gridiron_playbook.play import GridironPlay
    from gridiron_playbook.playbook import GridironPlaybook


_NONFINITE = "coordinates must be finite"
_SLOT_RANGE = "slot must be an integer from 0 to 255"
_NO_WAYPOINTS = "at least one waypoint"
_TOO_FEW_POINTS = "without a known starting position"
_BLANK_NAME = "cannot be blank"
_REQUIRED_NODES = "remaining waypoints"


def test_create_play(editor: PlaybookEditor) -> None:
    previous: tuple[GridironPlay, ...] = editor.plays
    index: int = editor.create_play(" Bunch ", " Jet sweep ")
    play: GridironPlay = editor.playbook.root.properties.custom_plays[index]

    assert (play.formation_name, play.play_name, play.routes) == ("Bunch", "Jet sweep", ())
    assert index == 0
    assert editor.plays == (play, *previous)


def test_duplicate_play(editor: PlaybookEditor) -> None:
    original: GridironPlaybook = editor.playbook
    previous: tuple[GridironPlay, ...] = editor.plays
    index: int = editor.duplicate_play(len(previous) - 1, " Copy ")
    assert index == 0
    assert editor.plays == (previous[-1].model_copy(update={"play_name": "Copy"}), *previous)
    duplicated: GridironPlaybook = editor.playbook
    editor.undo()
    assert editor.playbook == original
    editor.redo()
    assert editor.playbook == duplicated


def test_move_route_point(editor: PlaybookEditor) -> None:
    play_index: int = editor.create_play("Twins", "Cross")
    start: GridironPoint = GridironPoint(X_0=-2.5, Y_0=0, Z_0=7.25)
    end: GridironPoint = GridironPoint(X_0=5, Y_0=10, Z_0=11.5)
    route_index: int = editor.add_route(play_index, 2, (start, end))

    editor.move_route_point(play_index, route_index, 1, x=9.125, y=-3.5)

    assert editor.playbook.root.properties.custom_plays[play_index].routes[route_index].points == (
        start,
        GridironPoint(X_0=9.125, Y_0=-3.5, Z_0=11.5),
    )


@pytest.mark.parametrize(
    ("play_index", "route_index", "point_index"),
    [(-1, 0, 0), (0, -1, 0), (0, 0, -1), (999, 0, 0), (0, 999, 0), (0, 0, 999)],
)
def test_move_route_point_with_invalid_index(
    editor: PlaybookEditor, play_index: int, route_index: int, point_index: int
) -> None:
    with pytest.raises(IndexError):
        editor.move_route_point(play_index, route_index, point_index, 3, 4)

    assert editor.revision == 0


@pytest.mark.parametrize("axis", [float("inf"), float("-inf"), float("nan")])
def test_move_route_point_with_nonfinite_coordinate(editor: PlaybookEditor, axis: float) -> None:
    with pytest.raises(ValueError, match=_NONFINITE):
        editor.move_route_point(0, 0, 0, axis, 0.0)

    assert not editor.can_undo


@pytest.mark.parametrize(
    ("slot", "points", "expected_error"),
    [
        (-1, (GridironPoint(X_0=0, Y_0=0, Z_0=0), GridironPoint(X_0=1, Y_0=1, Z_0=0)), _SLOT_RANGE),
        (256, (GridironPoint(X_0=0, Y_0=0, Z_0=0), GridironPoint(X_0=1, Y_0=1, Z_0=0)), _SLOT_RANGE),
        (0, (), _NO_WAYPOINTS),
        (255, (GridironPoint(X_0=0, Y_0=0, Z_0=0),), _TOO_FEW_POINTS),
        (1, (GridironPoint(X_0=0, Y_0=0, Z_0=0), GridironPoint(X_0=0, Y_0=1, Z_0=float("nan"))), _NONFINITE),
    ],
)
def test_add_route_with_invalid_input(
    editor: PlaybookEditor, slot: int, points: tuple[GridironPoint, ...], expected_error: str
) -> None:
    with pytest.raises(ValueError, match=expected_error):
        _ = editor.add_route(0, slot, points)

    assert editor.revision == 0


@pytest.mark.parametrize(("formation", "name"), [("", "Cross"), ("Twins", "   ")])
def test_create_play_with_blank_name(editor: PlaybookEditor, formation: str, name: str) -> None:
    with pytest.raises(ValueError, match=_BLANK_NAME):
        _ = editor.create_play(formation, name)

    assert not editor.can_undo


def test_undo_and_redo(editor: PlaybookEditor) -> None:
    original: GridironPlaybook = editor.playbook
    _ = editor.create_play("Bunch", "Sweep")
    edited: GridironPlaybook = editor.playbook
    editor.undo()
    assert editor.playbook == original
    editor.redo()
    assert editor.playbook == edited
    assert editor.revision == 3


def test_undo_with_new_branch(editor: PlaybookEditor) -> None:
    _ = editor.create_play("Bunch", "First")
    editor.undo()
    _ = editor.create_play("Bunch", "Second")

    assert not editor.can_redo


def test_rename_play_with_unchanged_name_preserves_redo(editor: PlaybookEditor) -> None:
    original_name: str = editor.playbook.root.properties.custom_plays[0].play_name
    editor.rename_play(0, "New")
    editor.undo()
    editor.rename_play(0, original_name)

    assert (editor.can_redo, editor.revision) == (True, 2)


@pytest.mark.parametrize(
    ("index", "x", "height"),
    [(0, -10, 8), (1, 25, 12), (2, 120, 24)],
    ids=["before-first", "between-nodes", "after-last"],
)
def test_insert_route_point(editor: PlaybookEditor, index: int, x: float, height: float) -> None:
    start = GridironPoint(X_0=0, Y_0=40, Z_0=8)
    end = GridironPoint(X_0=100, Y_0=40, Z_0=24)
    points: tuple[GridironPoint, ...] = (start, end)
    route: int = editor.add_route(0, 1, points)
    original: GridironPlaybook = editor.playbook

    editor.insert_route_point(0, route, index, x, 45)

    inserted = GridironPoint(X_0=x, Y_0=45, Z_0=height)
    assert editor.plays[0].routes[route].points == (*points[:index], inserted, *points[index:])
    editor.undo()
    assert editor.playbook == original


@pytest.mark.parametrize(
    ("index", "x", "error"), [(-1, 0, IndexError), (100, 0, IndexError), (0, float("nan"), ValueError)]
)
def test_insert_route_point_with_invalid_input(
    editor: PlaybookEditor, index: int, x: float, error: type[Exception]
) -> None:
    with pytest.raises(error):
        editor.insert_route_point(0, 0, index, x, 0)
    assert editor.revision == 0


def test_delete_route_point_with_duplicate_coordinates(editor: PlaybookEditor) -> None:
    start = GridironPoint(X_0=30, Y_0=20, Z_0=5)
    duplicate = GridironPoint(X_0=30, Y_0=20, Z_0=10)
    end = GridironPoint(X_0=90, Y_0=40, Z_0=10)
    route: int = editor.add_route(0, 1, (start, duplicate, end))
    original: GridironPlaybook = editor.playbook

    editor.delete_route_point(0, route, 1)

    assert editor.plays[0].routes[route].points == (start, end)
    editor.undo()
    assert editor.playbook == original


@pytest.mark.parametrize(("slot", "minimum"), [(1, 1), (255, 2)], ids=["formation-anchor", "unknown-slot"])
def test_delete_route_point_at_minimum_length(editor: PlaybookEditor, slot: int, minimum: int) -> None:
    points = tuple(GridironPoint(X_0=i, Y_0=i, Z_0=0) for i in range(minimum + 1))
    route: int = editor.add_route(0, slot, points)
    editor.delete_route_point(0, route, 0)
    revision: int = editor.revision

    with pytest.raises(ValueError, match=_REQUIRED_NODES):
        editor.delete_route_point(0, route, 0)
    assert editor.revision == revision
    assert editor.plays[0].routes[route].points == points[1:]


def test_add_route_block_with_midroute_node(editor: PlaybookEditor) -> None:
    start = GridironPoint(X_0=-400, Y_0=25, Z_0=0)
    at = GridironPoint(X_0=100, Y_0=25, Z_0=8)
    end = GridironPoint(X_0=350, Y_0=500, Z_0=20)
    route: int = editor.add_route(0, 1, (start, at, at, end))
    original: GridironPlaybook = editor.playbook

    editor.add_route_block(0, route, 2)

    points: tuple[GridironPoint, ...] = editor.plays[0].routes[route].points
    assert points[:3] == (start, at, at)
    assert points[-2:] == (at, end)
    assert len(points) > 4
    edited: GridironPlaybook = editor.playbook
    editor.undo()
    assert editor.playbook == original
    editor.redo()
    assert editor.playbook == edited
