"""Interactive field diagram for one drawn play."""

from collections.abc import Callable
from collections.abc import Mapping
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

from gridiron_playbook.formations import formation_starts
from gridiron_playbook.formations import position_label
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.point import GridironPoint


_FIELD_WIDTH = 800
_FIELD_HEIGHT = 630
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
        """Fit the lineup, drawn waypoints and line of scrimmage."""
        min_x = max_x = min_y = max_y = 0.0
        for x, y in formation_starts(play.formation_name).values():
            min_x, max_x = min(min_x, x), max(max_x, x)
            min_y, max_y = min(min_y, y), max(max_y, y)
        for route in play.routes:
            for point in route.points:
                _check_projectable(point.x, point.y)
                if not isfinite(point.z):
                    raise ValueError("Route point heights must be finite.")
                min_x, max_x = min(min_x, point.x), max(max_x, point.x)
                min_y, max_y = min(min_y, point.y), max(max_y, point.y)
        scale: float = min(
            (_FIELD_WIDTH - 2 * _FIELD_MARGIN) / max(_MIN_GAME_WIDTH, max_y - min_y),
            (_FIELD_HEIGHT - 2 * _FIELD_MARGIN) / max(_MIN_GAME_HEIGHT, max_x - min_x),
        )
        return cls((min_x + max_x) / 2, (min_y + max_y) / 2, scale)

    def game_to_field(self, x: float, y: float) -> tuple[float, float]:
        """Project game coordinates into the SVG view box."""
        return (
            _FIELD_WIDTH / 2 + (y - self.center_y) * self.scale,
            _FIELD_HEIGHT / 2 - (x - self.center_x) * self.scale,
        )

    def field_to_game(self, x: float, y: float) -> tuple[float, float]:
        """Map an SVG position back into game coordinates."""
        game_x: float = self.center_x - (y - _FIELD_HEIGHT / 2) / self.scale
        game_y: float = self.center_y + (x - _FIELD_WIDTH / 2) / self.scale
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


class _PlayerSelection(_Input):
    slot: int = Field(ge=0, le=255)


class _RouteDraft(_Input):
    points: list[_FieldPoint] = Field(min_length=1)


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
        on_draw: Callable[[int], None] | None = None,
    ) -> None:
        """Bind pointer events to routes in this snapshot of the play."""
        super().__init__()
        transform: FieldTransform = FieldTransform.for_play(play)
        starts: Mapping[int, tuple[float, float]] = formation_starts(play.formation_name)
        self._props.update(
            lineup=[
                {
                    "slot": slot,
                    "label": position_label(play.formation_name, slot),
                    "at": transform.game_to_field(*start),
                }
                for slot, start in starts.items()
            ],
            routes=[
                {
                    "slot": route.slot,
                    "label": position_label(play.formation_name, route.slot),
                    "points": [transform.game_to_field(point.x, point.y) for point in route.points],
                }
                for route in play.routes
            ],
            selected=selected_route,
            draftSlot=draft_slot,
            draftLabel=position_label(play.formation_name, draft_slot) if draft_slot is not None else "",
            canDraw=on_draw is not None,
            originY=transform.game_to_field(0, 0)[1],
            fieldWidth=_FIELD_WIDTH,
            fieldHeight=_FIELD_HEIGHT,
            diagramId=self.id,
        )
        _ = self.classes("w-full")
        if draft_slot is None:
            self._bind_route_actions(play, transform, selected_route, on_select, on_move, on_draw)
        else:
            self._bind_draft_actions(draft_slot, transform, on_finish, on_cancel)

    def _bind_route_actions(
        self,
        play: GridironPlay,
        transform: FieldTransform,
        selected_route: int | None,
        on_select: Callable[[int], None],
        on_move: Callable[[int, int, float, float], None],
        on_draw: Callable[[int], None] | None,
    ) -> None:
        def select(event: _Event) -> None:
            selection: _RouteSelection = _RouteSelection.model_validate(event.args)
            if selection.route < len(play.routes):
                on_select(selection.route)

        def start(event: _Event) -> None:
            player: _PlayerSelection = _PlayerSelection.model_validate(event.args)
            if (
                on_draw is not None
                and player.slot in formation_starts(play.formation_name)
                and all(route.slot != player.slot for route in play.routes)
            ):
                on_draw(player.slot)

        def move(event: _Event) -> None:
            movement: _PointMove = _PointMove.model_validate(event.args)
            if selected_route is not None and movement.point < len(play.routes[selected_route].points):
                on_move(selected_route, movement.point, *transform.field_to_game(movement.x, movement.y))

        _ = self.on("route_select", _validate_event(select))
        if on_draw is not None:
            _ = self.on("route_start", _validate_event(start))
        if selected_route is not None:
            _ = self.on("point_move", _validate_event(move))

    def _bind_draft_actions(
        self,
        slot: int,
        transform: FieldTransform,
        on_finish: Callable[[int, tuple[GridironPoint, ...]], None],
        on_cancel: Callable[[], None],
    ) -> None:
        def finish(event: _Event) -> None:
            draft: _RouteDraft = _RouteDraft.model_validate(event.args)
            points: list[GridironPoint] = []
            for point in draft.points:
                x, y = transform.field_to_game(point.x, point.y)
                points.append(GridironPoint(X_0=x, Y_0=y, Z_0=0.0))
            on_finish(slot, tuple(points))

        _ = self.on("route_finish", _validate_event(finish))
        _ = self.on("route_cancel", on_cancel)
