"""Edit the custom plays in a save document and retain undo history."""

from collections import deque
from math import isfinite
from typing import TypeVar

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
        """Append an empty play and return its index."""
        play: GridironPlay = GridironPlay(
            FormationName_0=_name(formation_name, "Formation name"),
            PlayName_0=_name(play_name, "Play name"),
            Routes_0=(),
        )
        return self._append_play(play)

    def duplicate_play(self, play_index: int, play_name: str) -> int:
        """Append a named copy of the play and return its index."""
        original: GridironPlay = _at(self.plays, play_index)
        duplicate: GridironPlay = original.model_copy(update={"play_name": _name(play_name, "Play name")})
        return self._append_play(duplicate)

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
        edited_route: GridironRoute = route.model_copy(update={"points": _replacing(route.points, point_index, moved)})
        edited_play: GridironPlay = play.model_copy(
            update={"routes": _replacing(play.routes, route_index, edited_route)}
        )
        self._commit_plays(_replacing(self.plays, play_index, edited_play))

    def _append_play(self, play: GridironPlay) -> int:
        index: int = len(self.plays)
        self._commit_plays((*self.plays, play))
        return index

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
