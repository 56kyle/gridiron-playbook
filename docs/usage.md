# Usage

## Local playbook editor

From the repository root, run:

```console
uv run --extra web python -m gridiron_playbook.web
```

Open the loopback URL printed in the terminal (normally `http://127.0.0.1:8080`).
Choose a custom-play `.sav` or its uesave `.json` export. Each tab holds its own
copy in memory. Download your changes before closing or refreshing the page.

1. Search the play library or filter by formation. Use **Duplicate** to try a variation or
   **New play** to add an empty play to the open document.
2. Select a route on the field or in the lineup. Drag a handle to move a waypoint.
   A drag preserves its game-space height and counts as one edit.
3. Select an unused player on the field or in the lineup to draw their route.
   Alternatively, choose **Draw route**, choose a position or **Custom slot**,
   and start drawing. Click the field to add waypoints. A verified starting
   position needs only one waypoint; a route without a known start needs two.
   Choose **Finish route** to keep the route or **Cancel** to discard it.
   New waypoints have a height of zero.
4. Use **Undo** and **Redo** to step through completed edits.
5. Choose **Download .sav** to save the edited copy. Use **Open playbook** to
   reopen it. Downloading uses the browser's download location.

The field fits the selected play. For the ten [documented formations](reference.md#offensive-formations-and-slots),
player markers show the game's starting positions. Routes connect those markers
to the saved waypoints. Starting positions are display references and are never
added to the downloaded save.

### Verify a browser drag

The optional browser integration test opens the checked-in fixture, moves a
route point, and checks the downloaded save. To run it on Windows with Edge,
start the editor in one terminal:

```powershell
uv run --extra web --group browser-tests python -m gridiron_playbook.web
```

In a second terminal, run:

```powershell
$env:PLAYBOOK_EDITOR_TEST_URL = "http://127.0.0.1:8080"
$env:PLAYBOOK_EDITOR_BROWSER_CHANNEL = "msedge"
uv run --extra web --group browser-tests pytest tests/integration_tests/test_browser_diagram.py
```

## Validate custom plays

```python
from pathlib import Path

from gridiron_playbook.playbook import GridironPlaybook

playbook = GridironPlaybook.model_validate_json(
    Path("data/GridIronCustomPlays.json").read_text(encoding="utf-8")
)
play = playbook.root.properties.custom_plays[0]
print(play.formation_name, play.play_name)

exported_json = playbook.model_dump_json(by_alias=True, exclude_unset=True, indent=2)
```

The models preserve the save header, schema registry, play data, and trailing bytes.
Use `by_alias=True` to retain exported keys such as `CustomPlays_0` and `X_0`.
Use `exclude_unset=True` to preserve omitted fields in the last drawn play.
Unknown fields raise a Pydantic `ValidationError`.

## Command line

```{eval-rst}
.. typer:: gridiron_playbook.__main__:main
    :prog: gridiron-playbook
    :nested: full
```
