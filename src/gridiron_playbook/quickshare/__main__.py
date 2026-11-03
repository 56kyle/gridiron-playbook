"""Serve the static Quickshare viewer locally or export it for hosting."""

from pathlib import Path
from typing import Annotated

import typer

from gridiron_playbook.quickshare.preview import export_viewer
from gridiron_playbook.quickshare.preview import serve_viewer


def main(
    host: Annotated[str, typer.Option(help="Interface for the local static viewer.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535, help="Port for the local static viewer.")] = 8081,
    export: Annotated[Path | None, typer.Option(help="Export all viewer assets to a new or empty directory.")] = None,
) -> None:
    """Start the browser-only viewer, or export its files and exit."""
    if export is None:
        serve_viewer(host, port)
    else:
        try:
            export_viewer(export)
        except OSError as error:
            raise typer.BadParameter(str(error), param_hint="--export") from error
        typer.echo(f"Exported Quickshare viewer to {export.resolve()}")


if __name__ == "__main__":
    typer.run(main)
