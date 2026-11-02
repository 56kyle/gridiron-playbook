from typing import TYPE_CHECKING

from gridiron_playbook.editor import PlaybookEditor
from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.playbook import playbook_to_sav
from gridiron_playbook.playbook import sav_to_playbook
from gridiron_playbook.point import GridironPoint


if TYPE_CHECKING:
    from gridiron_playbook.play import GridironPlay


def test_add_route_with_one_saved_waypoint(custom_plays_json: str) -> None:
    editor: PlaybookEditor = PlaybookEditor(GridironPlaybook.model_validate_json(custom_plays_json))
    play_index: int = editor.create_play("Shotgun Right", "QB keeper")
    drawn: GridironPoint = GridironPoint(X_0=1000, Y_0=125, Z_0=2.5)
    route_index: int = editor.add_route(play_index, 0, (drawn,))

    reopened: GridironPlaybook = sav_to_playbook(playbook_to_sav(editor.playbook))
    assert reopened.root.properties.custom_plays[play_index].routes[route_index].points == (drawn,)


def test_duplicate_play_with_edited_save_round_trip(custom_plays_json: str) -> None:
    original: GridironPlaybook = GridironPlaybook.model_validate_json(custom_plays_json)
    editor: PlaybookEditor = PlaybookEditor(original)
    copy_index: int = editor.duplicate_play(0, "Revised sweep")
    revised_x: float = original.root.properties.custom_plays[0].routes[0].points[1].x + 100.5
    editor.move_route_point(copy_index, 0, 1, revised_x, 50)
    editor.undo()
    editor.redo()

    reopened: GridironPlaybook = sav_to_playbook(playbook_to_sav(editor.playbook))
    duplicate: GridironPlay = reopened.root.properties.custom_plays[copy_index]
    edited_point: GridironPoint = duplicate.routes[0].points[1]
    assert (duplicate.play_name, edited_point.x, edited_point.y) == ("Revised sweep", revised_x, 50)
    assert reopened.root.properties.custom_plays[:-1] == original.root.properties.custom_plays
    assert reopened.model_dump(exclude={"root": {"properties": {"custom_plays"}}}, exclude_unset=True) == (
        original.model_dump(exclude={"root": {"properties": {"custom_plays"}}}, exclude_unset=True)
    )
