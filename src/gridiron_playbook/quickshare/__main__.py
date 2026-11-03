"""Run a Quickshare service for publishing and previewing saved plays."""

from pathlib import Path
from typing import Annotated

import typer


def main(
    host: Annotated[str, typer.Option(help="Network interface to listen on.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535, help="TCP port to listen on.")] = 8081,
    database: Annotated[Path | None, typer.Option(help="Persistent SQLite file for published snapshots.")] = None,
) -> None:
    """Serve Quickshare snapshots and their read-only previews."""
    try:
        from nicegui import app
        from nicegui import ui
    except ModuleNotFoundError as error:
        if error.name != "nicegui":
            raise
        raise SystemExit("Install the web extra with 'uv sync --extra web', then run this command again.") from error

    from gridiron_playbook.constants import USER_DATA_FOLDER
    from gridiron_playbook.quickshare.api import register_api
    from gridiron_playbook.quickshare.preview import register_preview
    from gridiron_playbook.quickshare.store import SnapshotStore

    store = SnapshotStore(database if database is not None else USER_DATA_FOLDER / "quickshare.sqlite3")
    register_api(app, store)
    register_preview(store)
    # NiceGUI leaves the optional root callback unparameterized.
    ui.run(host=host, port=port, title="Gridiron Quickshare", show=False, dark=True, reload=False)  # pyright: ignore[reportUnknownMemberType]


if __name__ == "__main__":
    typer.run(main)
