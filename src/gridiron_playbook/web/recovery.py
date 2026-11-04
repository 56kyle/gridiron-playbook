"""Persist browser workspace working copies independently of imported save files."""

import os
from math import isfinite
from pathlib import Path
from typing import ClassVar
from typing import Literal
from uuid import uuid4

from nicegui import ui
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from gridiron_playbook.constants import USER_DATA_FOLDER
from gridiron_playbook.point import GridironPoint
from gridiron_playbook.working_copy import WorkingCopyConflictError
from gridiron_playbook.working_copy import WorkingCopyStore
from gridiron_playbook.workspace import WorkspaceSnapshot


class SavedView(BaseModel):
    """Retain each tab's focused play, selection, and filters."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)
    formation: str | None = None
    search: str = ""
    play_index: int = Field(default=0, ge=0)
    route_index: int | None = Field(default=None, ge=0)
    selected: tuple[int, ...] = ()
    anchor: int | None = Field(default=None, ge=0)


class SavedDraft(BaseModel):
    """Retain an unfinished route in game coordinates."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)
    slot: int = Field(ge=0, le=255)
    points: tuple[GridironPoint, ...] = ()

    @model_validator(mode="after")
    def validate_points(self) -> "SavedDraft":
        """Reject nonfinite coordinates before they reach the field diagram."""
        if not all(isfinite(value) for point in self.points for value in (point.x, point.y, point.z)):
            raise ValueError("A saved route draft contains invalid coordinates.")
        return self


class RecoveryState(BaseModel):
    """A versioned working workspace including its current view and route draft."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1]
    workspace: WorkspaceSnapshot
    views: dict[str, SavedView] = Field(default_factory=dict)
    draft: SavedDraft | None = None

    @model_validator(mode="after")
    def validate_views(self) -> "RecoveryState":
        """Require saved view references to belong to the persisted documents."""
        tabs = {tab.id: tab for tab in self.workspace.tabs}
        for tab_id, view in self.views.items():
            if tab_id not in tabs:
                raise ValueError("A saved view refers to an unavailable tab.")
            plays = tabs[tab_id].document.root.properties.custom_plays
            if view.play_index >= max(1, len(plays)) or any(
                index < 0 or index >= len(plays) for index in view.selected
            ):
                raise ValueError("A saved view refers to an unavailable play.")
            if view.route_index is not None and (not plays or view.route_index >= len(plays[view.play_index].routes)):
                raise ValueError("A saved view refers to an unavailable route.")
        if self.draft is not None and (
            self.workspace.active_id is None or not tabs[self.workspace.active_id].document.root.properties.custom_plays
        ):
            raise ValueError("A route draft requires an active play.")
        return self


class RecoveryIdentity(BaseModel):
    """Validate opaque browser working-copy identifiers before accessing storage."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)
    workspace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


def working_copy_store() -> WorkingCopyStore:
    """Resolve the local working database, allowing isolated test or portable storage."""
    configured: str | None = os.environ.get("GRIDIRON_WORKING_COPY_PATH")
    path = Path(configured) if configured else USER_DATA_FOLDER / "working-copies.sqlite3"
    return WorkingCopyStore(path)


class WorkingRecovery:
    """Track one page's durable revision and fork competing writers safely."""

    def __init__(self, store: WorkingCopyStore) -> None:
        """Bind a page to an injected local working store."""
        self.store: WorkingCopyStore = store
        self.workspace_id: str | None = None
        self.revision: int = 0
        self._saved: RecoveryState | None = None

    def restore(self, identity: RecoveryIdentity) -> RecoveryState | None:
        """Read and validate recovery before making this identity writable."""
        record = self.store.load(identity.source_id) if identity.source_id is not None else None
        state = RecoveryState.model_validate_json(record.data) if record is not None else None
        self.workspace_id = identity.workspace_id
        self.revision = record.revision if record is not None and identity.source_id == identity.workspace_id else 0
        self._saved = state if self.revision else None
        return state

    def start_new(self) -> None:
        """Use a separate working copy without modifying a failed recovery record."""
        self.workspace_id = uuid4().hex
        self.revision = 0
        self._saved = None

    def save(self, state: RecoveryState) -> str:
        """Commit a complete workspace, or fork if another page advanced its revision."""
        if self.workspace_id is None:
            raise ValueError("Restore or start a working copy before saving it.")
        if state == self._saved:
            return self.workspace_id
        data = state.model_dump_json(by_alias=True, exclude_unset=True).encode("utf-8")
        try:
            record = self.store.save(self.workspace_id, data, expected_revision=self.revision)
        except WorkingCopyConflictError:
            record = self.store.save(uuid4().hex, data, expected_revision=0)
        self.workspace_id = record.workspace_id
        self.revision = record.revision
        self._saved = state
        return self.workspace_id


class RecoveryBridge(ui.element, component="recovery.js"):
    """Keep recovery identities and window locks in the local browser."""

    def __init__(self) -> None:
        """Create the browser identity bridge in its loading state."""
        super().__init__()
        _ = self.props('data-recovery-status="loading" data-recovery-revision="0"')

    def saved(self, workspace_id: str, revision: int) -> None:
        """Acknowledge the durable working copy to this browser window."""
        self._props["failed"] = False
        _ = self.props(f'data-recovery-status="saving" data-recovery-revision="{revision}"')
        self.update()
        _ = self.run_method("saved", workspace_id, revision)

    def failed(self) -> None:
        """Warn before leaving while the current edits could not be persisted."""
        self._props["failed"] = True
        _ = self.props('data-recovery-status="error"')
        self.update()
