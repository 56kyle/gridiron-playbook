from uuid import UUID

import pytest
from pydantic import ValidationError

from gridiron_playbook.play import GridironLastDrawnPlay
from gridiron_playbook.play import GridironPlay
from gridiron_playbook.point import GridironPoint
from gridiron_playbook.property_schema import GridironArrayPropertySchema
from gridiron_playbook.property_schema import GridironBytePropertySchema
from gridiron_playbook.property_schema import GridironOtherPropertySchema
from gridiron_playbook.property_schema import GridironPropertyData
from gridiron_playbook.property_schema import GridironPropertySchema
from gridiron_playbook.property_schema import GridironStructPropertySchema
from gridiron_playbook.route import GridironRoute
from gridiron_playbook.save_header import GridironCustomVersion


@pytest.mark.parametrize(
    "payload",
    [
        {"X_0": -1.5, "Y_0": 2.25, "Z_0": 3.0},
        {"x": -1.5, "y": 2.25, "z": 3.0},
    ],
)
def test_model_validate_with_point_aliases(payload: dict[str, float]) -> None:
    point: GridironPoint = GridironPoint.model_validate(payload)

    assert (point.x, point.y, point.z) == (-1.5, 2.25, 3.0)


def test_model_dump_with_point_aliases() -> None:
    point: GridironPoint = GridironPoint.model_validate({"x": 1.0, "y": 2.0, "z": 3.0})

    assert point.model_dump(by_alias=True) == {"X_0": 1.0, "Y_0": 2.0, "Z_0": 3.0}


@pytest.mark.parametrize("missing_field", ["FormationName_0", "PlayName_0", "Routes_0"])
def test_model_validate_with_missing_play_field(missing_field: str) -> None:
    payload: dict[str, object] = {"FormationName_0": "Twins Right", "PlayName_0": "Out", "Routes_0": []}
    del payload[missing_field]

    with pytest.raises(ValidationError) as caught:
        _ = GridironPlay.model_validate(payload)

    assert [(error["loc"], error["type"]) for error in caught.value.errors()] == [((missing_field,), "missing")]


def test_model_validate_with_empty_play_routes() -> None:
    play: GridironPlay = GridironPlay.model_validate(
        {"formation_name": "New formation", "play_name": "New play", "routes": []}
    )

    assert play.routes == ()


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        ({"FormationName_0": "Twins Right", "PlayName_0": None}, "string_type"),
        ({"FormationName_0": "Twins Right", "Routes_0": None}, "tuple_type"),
    ],
)
def test_model_validate_with_null_last_drawn_fields(payload: dict[str, object], expected_error: str) -> None:
    with pytest.raises(ValidationError) as caught:
        _ = GridironLastDrawnPlay.model_validate(payload)

    assert [error["type"] for error in caught.value.errors()] == [expected_error]


@pytest.mark.parametrize(
    "payload",
    [
        {"FormationName_0": "Twins Right"},
        {"FormationName_0": "Twins Right", "PlayName_0": "", "Routes_0": []},
        {"FormationName_0": "Twins Right", "PlayName_0": "Out", "Routes_0": []},
    ],
)
def test_model_dump_with_last_drawn_field_presence(payload: dict[str, object]) -> None:
    play: GridironLastDrawnPlay = GridironLastDrawnPlay.model_validate(payload)

    assert play.model_dump(mode="json", by_alias=True, exclude_unset=True) == payload


@pytest.mark.parametrize(
    ("point", "expected_location", "expected_error"),
    [
        ({"X_0": "bad", "Y_0": 0.0, "Z_0": 0.0}, ("Points_0", 0, "X_0"), "float_parsing"),
        ({"X_0": 0.0, "Y_0": 0.0}, ("Points_0", 0, "Z_0"), "missing"),
        ({"X_0": 0.0, "Y_0": 0.0, "Z_0": 0.0, "W_0": 0.0}, ("Points_0", 0, "W_0"), "extra_forbidden"),
    ],
)
def test_model_validate_with_invalid_nested_point(
    point: dict[str, object], expected_location: tuple[str | int, ...], expected_error: str
) -> None:
    with pytest.raises(ValidationError) as caught:
        _ = GridironRoute.model_validate({"Slot_0": 2, "Points_0": [point]})

    assert [(error["loc"], error["type"]) for error in caught.value.errors()] == [(expected_location, expected_error)]


def test_model_validate_with_route_points() -> None:
    route: GridironRoute = GridironRoute.model_validate({"Slot_0": 2, "Points_0": [{"X_0": 1, "Y_0": 2, "Z_0": 3}]})

    assert route.points == (GridironPoint.model_validate({"x": 1, "y": 2, "z": 3}),)


def test_model_validate_with_frozen_point() -> None:
    point: GridironPoint = GridironPoint.model_validate({"x": 1, "y": 2, "z": 3})

    with pytest.raises(ValidationError) as caught:
        point.x = 4.0

    assert [error["type"] for error in caught.value.errors()] == ["frozen_instance"]


@pytest.mark.parametrize(
    ("payload", "expected_type"),
    [
        ({"Other": "StrProperty"}, GridironOtherPropertySchema),
        ({"Byte": None}, GridironBytePropertySchema),
        (
            {"Struct": {"struct_type": {"Struct": "GIDrawnPlay"}, "id": "00000000-0000-0000-0000-000000000000"}},
            GridironStructPropertySchema,
        ),
        (
            {
                "Array": {
                    "Struct": {"struct_type": {"Struct": "GIDrawnRoute"}, "id": "00000000-0000-0000-0000-000000000000"}
                }
            },
            GridironArrayPropertySchema,
        ),
    ],
)
def test_model_validate_with_property_descriptor(
    payload: dict[str, object], expected_type: type[GridironPropertyData]
) -> None:
    descriptor: GridironPropertySchema = GridironPropertySchema.model_validate({"data": payload})

    assert isinstance(descriptor.data, expected_type)


@pytest.mark.parametrize("payload", [{"Other": "StrProperty", "Byte": None}, {"Map": {}}, {"Byte": 0}])
def test_model_validate_with_invalid_property_descriptor(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _ = GridironPropertySchema.model_validate({"data": payload})


def test_model_validate_with_custom_version_uuid() -> None:
    version: GridironCustomVersion = GridironCustomVersion.model_validate(
        {"id": "fcf57afa-5076-4283-b9a9-e658ffa02d32", "value": 76}
    )

    assert version.id == UUID("fcf57afa-5076-4283-b9a9-e658ffa02d32")


def test_model_validate_with_invalid_custom_version_uuid() -> None:
    with pytest.raises(ValidationError) as caught:
        _ = GridironCustomVersion.model_validate({"id": "invalid", "value": 76})

    assert [(error["loc"], error["type"]) for error in caught.value.errors()] == [(("id",), "uuid_parsing")]
