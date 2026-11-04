"""Edit the custom plays in a save document and retain undo history."""

from collections import deque
from math import hypot
from math import isfinite
from typing import TypeVar

from gridiron_playbook.block import block_waypoints
from gridiron_playbook.formations import formation_starts
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.playbook import GridironPlaybookProperties
from gridiron_playbook.playbook import GridironSaveRoot
from gridiron_playbook.point import GridironPoint
from gridiron_playbook.route import GridironRoute


_Item = TypeVar("_Item")
_HISTORY_LIMIT = 100
_MAX_BYTE = 255


def _at(items: tuple[_Item, ...], index: int) -> _Item:
    if not 0 <= index < len(items):
        raise IndexError(f"Index {index} is outside the collection of {len(items)} items.")
    return items[index]


def _replacing(items: tuple[_Item, ...], index: int, replacement: _Item) -> tuple[_Item, ...]:
    return (*items[:index], replacement, *items[index + 1 :])


def _name(value: str, field: str) -> str:
    trimmed: str = value.strip()
    if not trimmed:
        raise ValueError(f"{field} cannot be blank.")
    return trimmed


def _inserted_height(points: tuple[GridironPoint, ...], index: int, x: float, y: float) -> float:
    if not points:
        return 0.0
    if index == 0:
        return points[0].z
    previous: GridironPoint = points[index - 1]
    if index == len(points):
        return previous.z
    following: GridironPoint = points[index]
    dx, dy = following.x - previous.x, following.y - previous.y
    length: float = hypot(dx, dy)
    if length == 0:
        return previous.z
    projection: float = (x - previous.x) * (dx / length) + (y - previous.y) * (dy / length)
    fraction: float = max(0.0, min(1.0, projection / length))
    return (1.0 - fraction) * previous.z + fraction * following.z


class PlaybookEditor:
    """Own the current document and the history of completed edits to its custom plays."""

    def __init__(self, playbook: GridironPlaybook) -> None:
        """Open a save document with an empty edit history."""
        self._playbook: GridironPlaybook = playbook
        self._revision: int = 0
        self._undo: deque[GridironPlaybook] = deque(maxlen=_HISTORY_LIMIT)
        self._redo: list[GridironPlaybook] = []

    @property
    def playbook(self) -> GridironPlaybook:
        """Current save document, including its original metadata."""
        return self._playbook

    @property
    def plays(self) -> tuple[GridironPlay, ...]:
        """Completed plays in their save-file order."""
        return self._playbook.root.properties.custom_plays

    @property
    def revision(self) -> int:
        """Generation of the displayed document, including undo and redo operations."""
        return self._revision

    @property
    def can_undo(self) -> bool:
        """Whether a previous document is available."""
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        """Whether an undone edit is available."""
        return bool(self._redo)

    def undo(self) -> None:
        """Restore the document before the last edit, if available."""
        if self._undo:
            self._redo.append(self._playbook)
            self._playbook = self._undo.pop()
            self._revision += 1

    def redo(self) -> None:
        """Restore the next undone edit, if available."""
        if self._redo:
            self._undo.append(self._playbook)
            self._playbook = self._redo.pop()
            self._revision += 1

    def create_play(self, formation_name: str, play_name: str) -> int:
        """Insert an empty play at the top and return its index."""
        play: GridironPlay = GridironPlay(
            FormationName_0=_name(formation_name, "Formation name"),
            PlayName_0=_name(play_name, "Play name"),
            Routes_0=(),
        )
        return self.import_plays((play,))

    def duplicate_play(self, play_index: int, play_name: str) -> int:
        """Insert a named copy at the top and return its index."""
        original: GridironPlay = _at(self.plays, play_index)
        duplicate: GridironPlay = original.model_copy(update={"play_name": _name(play_name, "Play name")})
        return self.import_plays((duplicate,))

    def rename_play(self, play_index: int, play_name: str) -> None:
        """Change a play's name while retaining its formation and routes."""
        play: GridironPlay = _at(self.plays, play_index)
        renamed: GridironPlay = play.model_copy(update={"play_name": _name(play_name, "Play name")})
        self._commit_plays(_replacing(self.plays, play_index, renamed))

    def add_route(self, play_index: int, slot: int, points: tuple[GridironPoint, ...]) -> int:
        """Commit a drawn line as one route and return its index within the play."""
        play: GridironPlay = _at(self.plays, play_index)
        if not 0 <= slot <= _MAX_BYTE:
            raise ValueError("A player slot must be an integer from 0 to 255.")
        if not points:
            raise ValueError("Draw at least one waypoint for the route.")
        if len(points) == 1 and slot not in formation_starts(play.formation_name):
            raise ValueError("Draw two waypoints for a player without a known starting position.")
        if not all(isfinite(value) for point in points for value in (point.x, point.y, point.z)):
            raise ValueError("Route coordinates must be finite.")
        route: GridironRoute = GridironRoute(Slot_0=slot, Points_0=points)
        extended: GridironPlay = play.model_copy(update={"routes": (*play.routes, route)})
        self._commit_plays(_replacing(self.plays, play_index, extended))
        return len(play.routes)

    def move_route_point(self, play_index: int, route_index: int, point_index: int, x: float, y: float) -> None:
        """Move one point in the field plane, preserving its height."""
        play: GridironPlay = _at(self.plays, play_index)
        route: GridironRoute = _at(play.routes, route_index)
        point: GridironPoint = _at(route.points, point_index)
        if not (isfinite(x) and isfinite(y)):
            raise ValueError("Route coordinates must be finite.")
        moved: GridironPoint = GridironPoint(X_0=x, Y_0=y, Z_0=point.z)
        self._replace_route_points(play_index, route_index, _replacing(route.points, point_index, moved))

    def insert_route_point(self, play_index: int, route_index: int, point_index: int, x: float, y: float) -> None:
        """Insert before a waypoint or append at the route length, interpolating height between saved neighbors."""
        play: GridironPlay = _at(self.plays, play_index)
        route: GridironRoute = _at(play.routes, route_index)
        if not 0 <= point_index <= len(route.points):
            raise IndexError("Choose an insertion index within the route or at its end.")
        z: float = _inserted_height(route.points, point_index, x, y)
        if not (isfinite(x) and isfinite(y) and isfinite(z)):
            raise ValueError("Route coordinates must be finite.")
        point: GridironPoint = GridironPoint(X_0=x, Y_0=y, Z_0=z)
        self._replace_route_points(
            play_index, route_index, (*route.points[:point_index], point, *route.points[point_index:])
        )

    def delete_route_point(self, play_index: int, route_index: int, point_index: int) -> None:
        """Remove a saved waypoint while retaining enough points to draw the route."""
        play: GridironPlay = _at(self.plays, play_index)
        route: GridironRoute = _at(play.routes, route_index)
        _ = _at(route.points, point_index)
        minimum: int = 1 if route.slot in formation_starts(play.formation_name) else 2
        if len(route.points) <= minimum:
            raise ValueError("The route needs its remaining waypoints.")
        self._replace_route_points(
            play_index, route_index, (*route.points[:point_index], *route.points[point_index + 1 :])
        )

    def add_route_block(self, play_index: int, route_index: int, point_index: int) -> None:
        """Insert a blocking bar at a saved waypoint as one undoable edit."""
        play: GridironPlay = _at(self.plays, play_index)
        route: GridironRoute = _at(play.routes, route_index)
        start: tuple[float, float] | None = formation_starts(play.formation_name).get(route.slot)
        stamp: tuple[GridironPoint, ...] = block_waypoints(route.points, point_index, start)
        after: int = point_index + 1
        self._replace_route_points(play_index, route_index, (*route.points[:after], *stamp, *route.points[after:]))

    def _replace_route_points(self, play_index: int, route_index: int, points: tuple[GridironPoint, ...]) -> None:
        play: GridironPlay = self.plays[play_index]
        edited_route: GridironRoute = play.routes[route_index].model_copy(update={"points": points})
        edited_play: GridironPlay = play.model_copy(
            update={"routes": _replacing(play.routes, route_index, edited_route)}
        )
        self._commit_plays(_replacing(self.plays, play_index, edited_play))

    def import_plays(self, plays: tuple[GridironPlay, ...]) -> int:
        """Insert plays at the top in source order and return the first imported index."""
        if not plays:
            raise ValueError("Choose at least one play to import.")
        self._commit_plays((*plays, *self.plays))
        return 0

    def _commit_plays(self, plays: tuple[GridironPlay, ...]) -> None:
        if plays == self.plays:
            return
        properties: GridironPlaybookProperties = self._playbook.root.properties.model_copy(
            update={"custom_plays": plays}
        )
        root: GridironSaveRoot = self._playbook.root.model_copy(update={"properties": properties})
        document: GridironPlaybook = self._playbook.model_copy(update={"root": root})
        self._undo.append(self._playbook)
        self._redo.clear()
        self._playbook = document
        self._revision += 1
