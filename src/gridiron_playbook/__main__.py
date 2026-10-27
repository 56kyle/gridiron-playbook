"""Command-line interface."""

import typer


app: typer.Typer = typer.Typer()


@app.command(name="gridiron-playbook")
def main() -> None:
    """Gridiron Playbook."""


if __name__ == "__main__":
    app()  # pragma: no cover
