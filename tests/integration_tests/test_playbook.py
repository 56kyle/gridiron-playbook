from typing import TYPE_CHECKING

from pydantic import JsonValue
from pydantic import TypeAdapter

from gridiron_playbook.playbook import GridironPlaybook


if TYPE_CHECKING:
    from gridiron_playbook.play import GridironPlay
    from gridiron_playbook.point import GridironPoint
    from gridiron_playbook.route import GridironRoute


def test_model_validate_json_with_custom_plays(custom_plays_json: str) -> None:
    playbook: GridironPlaybook = GridironPlaybook.model_validate_json(custom_plays_json)
    plays: tuple[GridironPlay, ...] = playbook.root.properties.custom_plays
    routes: tuple[GridironRoute, ...] = tuple(route for play in plays for route in play.routes)
    points: tuple[GridironPoint, ...] = tuple(point for route in routes for point in route.points)

    assert (len(plays), len(routes), len(points)) == (24, 108, 363)


def test_model_dump_json_with_custom_plays_round_trip(custom_plays_json: str) -> None:
    playbook: GridironPlaybook = GridironPlaybook.model_validate_json(custom_plays_json)
    exported_json: str = playbook.model_dump_json(by_alias=True, exclude_unset=True)
    adapter: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)

    assert adapter.validate_json(exported_json) == adapter.validate_json(custom_plays_json)


def test_model_json_schema_with_document_fields() -> None:
    schema: dict[str, object] = GridironPlaybook.model_json_schema(by_alias=True)
    properties: dict[str, object] = TypeAdapter(dict[str, object]).validate_python(schema["properties"])

    assert set(properties) == {"header", "schemas", "root", "extra"}
