from importlib.util import find_spec

import pytest

from gridiron_playbook.play import GridironPlay
from gridiron_playbook.point import GridironPoint
from gridiron_playbook.route import GridironRoute


if find_spec("nicegui") is None:
    pytest.skip("Install the web extra to exercise field projection.", allow_module_level=True)


def _play_with_points(*points: GridironPoint) -> GridironPlay:
    route: GridironRoute = GridironRoute(Slot_0=1, Points_0=points)
    return GridironPlay(FormationName_0="Test formation", PlayName_0="Test route", Routes_0=(route,))


def test_field_to_game_with_asymmetric_play() -> None:
    from gridiron_playbook.web.play_diagram import FieldTransform

    point: GridironPoint = GridironPoint(X_0=31.25, Y_0=-89.125, Z_0=9)
    play: GridironPlay = _play_with_points(point, GridironPoint(X_0=2111.5, Y_0=-7003.75, Z_0=5))
    transform: FieldTransform = FieldTransform.for_play(play)

    assert transform.field_to_game(*transform.game_to_field(point.x, point.y)) == pytest.approx((point.x, point.y))


@pytest.mark.parametrize(
    "points",
    [
        (GridironPoint(X_0=0, Y_0=0, Z_0=float("nan")),),
        (GridironPoint(X_0=0, Y_0=float("inf"), Z_0=0),),
        (GridironPoint(X_0=-1e308, Y_0=0, Z_0=0), GridironPoint(X_0=1e308, Y_0=0, Z_0=0)),
    ],
)
def test_for_play_with_unrenderable_route(points: tuple[GridironPoint, ...]) -> None:
    from gridiron_playbook.web.play_diagram import FieldTransform

    with pytest.raises(ValueError):  # noqa: PT011 - multiple coordinate failures share this public error
        _ = FieldTransform.for_play(_play_with_points(*points))
