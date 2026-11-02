"""Start the local playbook editor."""


def main() -> None:
    """Serve the editor on the local loopback interface."""
    try:
        from nicegui import ui
    except ModuleNotFoundError as error:
        if error.name != "nicegui":
            raise
        raise SystemExit("Install the web extra with 'uv sync --extra web', then run this command again.") from error

    from gridiron_playbook.web.playbook_page import playbook_page

    # NiceGUI declares the root callback as an unparameterized Callable.
    ui.run(playbook_page, host="127.0.0.1", title="Gridiron Playbook", dark=True, reload=False)  # pyright: ignore[reportUnknownMemberType]


if __name__ == "__main__":
    main()
