"""Module containing shared schema configuration for the gridiron_playbook package."""

from typing import ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict

from gridiron_playbook.constants import DEFAULT_PYDANTIC_CONFIG


GRIDIRON_PYDANTIC_CONFIG: ConfigDict = {
    **DEFAULT_PYDANTIC_CONFIG,
    "frozen": True,
    "extra": "forbid",
    "validate_by_name": True,
    "validate_by_alias": True,
}


class GridironModel(BaseModel):
    """A frozen save model that accepts aliases and rejects unknown fields."""

    model_config: ClassVar[ConfigDict] = GRIDIRON_PYDANTIC_CONFIG
