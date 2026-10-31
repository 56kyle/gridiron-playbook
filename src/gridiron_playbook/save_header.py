"""Module containing save header schemas for the gridiron_playbook package."""

from uuid import UUID

from gridiron_playbook.schema import GridironModel


class GridironPackageVersion(GridironModel):
    """Unreal package version numbers."""

    ue4: int
    ue5: int


class GridironCustomVersion(GridironModel):
    """A custom version identifier and its version number."""

    id: UUID
    value: int


class GridironSaveHeader(GridironModel):
    """Save format and Unreal engine version metadata."""

    magic: int
    save_game_version: int
    package_version: GridironPackageVersion
    engine_version_major: int
    engine_version_minor: int
    engine_version_patch: int
    engine_version_build: int
    engine_version: str
    custom_version: tuple[int, tuple[GridironCustomVersion, ...]]
