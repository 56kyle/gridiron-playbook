"""Start the local playbook editor."""

from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> None:
    """Serve the editor and its Quickshare viewer on the local loopback interface."""
    try:
        from nicegui import app
        from nicegui import ui
    except ModuleNotFoundError as error:
        if error.name != "nicegui":
            raise
        raise SystemExit("Install the web extra with 'uv sync --extra web', then run this command again.") from error

    from starlette.staticfiles import StaticFiles

    from gridiron_playbook.quickshare.links import LOCAL_VIEWER_PATH
    from gridiron_playbook.quickshare.preview import export_viewer
    from gridiron_playbook.web.playbook_page import playbook_page

    with TemporaryDirectory(prefix="gridiron-viewer-") as directory:
        export_viewer(Path(directory))
        app.mount(LOCAL_VIEWER_PATH, StaticFiles(directory=directory, html=True))
        # NiceGUI declares the root callback as an unparameterized Callable.
        ui.run(playbook_page, host="127.0.0.1", title="Gridiron Playbook", dark=True, reload=False)  # pyright: ignore[reportUnknownMemberType]


if __name__ == "__main__":
    main()
