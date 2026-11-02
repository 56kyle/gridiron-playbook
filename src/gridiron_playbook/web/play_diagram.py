"""Interactive field diagram for one drawn play."""

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from sys import float_info
from typing import ClassVar
from typing import Protocol

from nicegui import ui
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError

from gridiron_playbook.play import GridironPlay
from gridiron_playbook.point import GridironPoint


_FIELD_WIDTH = 960
_FIELD_HEIGHT = 580
_FIELD_MARGIN = 48
_MIN_GAME_WIDTH = 3200
_MIN_GAME_HEIGHT = 1800
# Reserve float headroom for a span across the origin and the padded viewport.
_MAX_PROJECTABLE_COORDINATE = float_info.max / 4


def _check_projectable(x: float, y: float) -> None:
    if not (abs(x) <= _MAX_PROJECTABLE_COORDINATE and abs(y) <= _MAX_PROJECTABLE_COORDINATE):
        raise ValueError("The route coordinates exceed the diagram's numeric range.")


@dataclass(frozen=True)
class FieldTransform:
    """Uniform scale between game coordinates and the top-down SVG field."""

    center_x: float
    center_y: float
    scale: float

    @classmethod
    def for_play(cls, play: GridironPlay) -> "FieldTransform":
        """Fit the routes and origin, raising ValueError for unusable coordinates."""
        left = right = bottom = top = 0.0
        for route in play.routes:
            for point in route.points:
                _check_projectable(point.x, point.y)
                if not isfinite(point.z):
                    raise ValueError("Route point heights must be finite.")
                left, right = min(left, point.x), max(right, point.x)
                bottom, top = min(bottom, point.y), max(top, point.y)
        scale: float = min(
            (_FIELD_WIDTH - 2 * _FIELD_MARGIN) / max(_MIN_GAME_WIDTH, right - left),
            (_FIELD_HEIGHT - 2 * _FIELD_MARGIN) / max(_MIN_GAME_HEIGHT, top - bottom),
        )
        return cls((left + right) / 2, (bottom + top) / 2, scale)

    def game_to_field(self, x: float, y: float) -> tuple[float, float]:
        """Project game coordinates into the SVG view box."""
        return (
            _FIELD_WIDTH / 2 + (x - self.center_x) * self.scale,
            _FIELD_HEIGHT / 2 - (y - self.center_y) * self.scale,
        )

    def field_to_game(self, x: float, y: float) -> tuple[float, float]:
        """Map an SVG position back into game coordinates."""
        game_x: float = self.center_x + (x - _FIELD_WIDTH / 2) / self.scale
        game_y: float = self.center_y - (y - _FIELD_HEIGHT / 2) / self.scale
        _check_projectable(game_x, game_y)
        return game_x, game_y


class _Event(Protocol):
    @property
    def args(self) -> object: ...


class _Input(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class _FieldPoint(_Input):
    x: float = Field(ge=0, le=_FIELD_WIDTH)
    y: float = Field(ge=0, le=_FIELD_HEIGHT)


class _PointMove(_FieldPoint):
    point: int = Field(ge=0)


class _RouteSelection(_Input):
    route: int = Field(ge=0)


class _RouteDraft(_Input):
    points: list[_FieldPoint] = Field(min_length=2)


def _validate_event(handler: Callable[[_Event], None]) -> Callable[[_Event], None]:
    def handle(event: _Event) -> None:
        try:
            handler(event)
        except ValidationError:
            ui.notify("The diagram received an invalid edit.", type="warning")
        except ValueError as error:
            ui.notify(str(error), type="warning")

    return handle


class PlayDiagram(ui.element, component="play_diagram.js"):
    """Render routes and report completed edits from the current diagram."""

    def __init__(
        self,
        play: GridironPlay,
        *,
        selected_route: int | None,
        draft_slot: int | None,
        on_select: Callable[[int], None],
        on_move: Callable[[int, int, float, float], None],
        on_finish: Callable[[int, tuple[GridironPoint, ...]], None],
        on_cancel: Callable[[], None],
    ) -> None:
        """Bind pointer events to routes in this snapshot of the play."""
        super().__init__()
        transform: FieldTransform = FieldTransform.for_play(play)
        self._props.update(
            routes=[
                {"slot": route.slot, "points": [transform.game_to_field(point.x, point.y) for point in route.points]}
                for route in play.routes
            ],
            selected=selected_route,
            draftSlot=draft_slot,
            originY=transform.game_to_field(0, 0)[1],
            fieldWidth=_FIELD_WIDTH,
            fieldHeight=_FIELD_HEIGHT,
            diagramId=self.id,
        )
        _ = self.classes("w-full")

        def select(event: _Event) -> None:
            selection: _RouteSelection = _RouteSelection.model_validate(event.args)
            if draft_slot is None and selection.route < len(play.routes):
                on_select(selection.route)

        def move(event: _Event) -> None:
            movement: _PointMove = _PointMove.model_validate(event.args)
            if selected_route is not None and movement.point < len(play.routes[selected_route].points):
                on_move(selected_route, movement.point, *transform.field_to_game(movement.x, movement.y))

        def finish(event: _Event) -> None:
            draft: _RouteDraft = _RouteDraft.model_validate(event.args)
            if draft_slot is not None:
                points: list[GridironPoint] = []
                for point in draft.points:
                    x, y = transform.field_to_game(point.x, point.y)
                    points.append(GridironPoint(X_0=x, Y_0=y, Z_0=0.0))
                on_finish(draft_slot, tuple(points))

        if draft_slot is None:
            _ = self.on("route_select", _validate_event(select))
            _ = self.on("point_move", _validate_event(move))
        else:
            _ = self.on("route_finish", _validate_event(finish))
            _ = self.on("route_cancel", on_cancel)
