"""Module containing property schemas for the gridiron_playbook package."""

from typing import TypeAlias
from uuid import UUID

from pydantic import Field

from gridiron_playbook.schema import GridironModel


class GridironStructType(GridironModel):
    """An Unreal struct type name."""

    struct: str = Field(alias="Struct")


class GridironStructDescriptor(GridironModel):
    """An Unreal struct's type and identifier."""

    struct_type: GridironStructType
    id: UUID


class GridironStructPropertySchema(GridironModel):
    """A property represented by an Unreal struct."""

    struct: GridironStructDescriptor = Field(alias="Struct")


class GridironArrayPropertySchema(GridironModel):
    """An array of Unreal structs."""

    array: GridironStructPropertySchema = Field(alias="Array")


class GridironOtherPropertySchema(GridironModel):
    """A scalar property described by its Unreal type name."""

    other: str = Field(alias="Other")


class GridironBytePropertySchema(GridironModel):
    """A byte property with a required null descriptor."""

    byte: None = Field(alias="Byte")


GridironPropertyData: TypeAlias = (
    GridironArrayPropertySchema
    | GridironStructPropertySchema
    | GridironOtherPropertySchema
    | GridironBytePropertySchema
)


class GridironPropertySchema(GridironModel):
    """A property schema containing one supported descriptor."""

    data: GridironPropertyData


class GridironSchemaRegistry(GridironModel):
    """Property paths mapped to their Unreal serialization schemas."""

    schemas: dict[str, GridironPropertySchema]
