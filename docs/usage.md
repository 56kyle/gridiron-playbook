# Usage

## Browser editor

After the one-time setup in the [repository guide](../README.md), run from the
repository root:

```console
npm run dev
```

Open the address printed by Vite. The editor and Quickshare preview run in the
browser; no Python server or separate viewer process is required.

Choose **Open files** for `.sav`, `.json`, or `.gridironshare` files, or start with
**New playbook**. Full playbooks open in separate tabs. New, duplicated, and
imported individual plays appear at the top of the active playbook.

1. Select a play to edit its name, formation, and routes. Use Ctrl/Command-click
   or Shift-click to select several plays.
2. Drag plays within the list to reorder them or onto another tab to move them.
   Hold Ctrl/Command to copy. Copy, move, and merge controls provide the same
   operations without dragging.
3. Click a player to start drawing, or choose a position and **Draw route**.
   Click to add points; the preview follows the pointer. Enter finishes the
   route, Escape cancels it, and Backspace removes the last point.
4. Select a route to move its nodes. Use **N** to insert a node, **Delete** to
   remove the selected node, and **B** to add a block at that node. Displayed
   yardage excludes the strokes used to draw a standard block.
5. Ctrl/Command-Z undoes a completed edit; Ctrl/Command-Shift-Z redoes it.
   Transfers between books are one undo operation.
6. **Download .sav** exports the active book. **Share play** and **Share
   playbook** provide self-contained links and files with selectable precision.

The field fits the selected play. The ten [documented formations](reference.md#offensive-formations-and-slots)
provide player starting positions. These starting markers are display references;
the editor does not add them as saved waypoints.

## Recovery and game installation

The browser saves tabs, unsaved edits, and unfinished drawings as working copies.
Refresh restores the current window. New windows get independent copies of the
most recently used workspace. Undo history starts fresh after recovery. Keep
separate downloads: clearing the site's browser data removes working copies.

Opening a file never binds editing to that file. Use **Game → Use in game** to
explicitly install the active book. On a browser that supports directory access,
choose SaveGames or the Gridiron installation folder. The first-use dialog
provides a copyable default Windows Steam folder path. For another Steam library,
use **Gridiron → Manage → Browse local files** in Steam.

The browser remembers the selected folder across visits. If permission expires,
**Use saved folder** requests access again. **Game → Game folder…** lets you
change or forget the folder. Forgetting removes the remembered choice without
deleting game saves or backups. If browser storage is unavailable, a selected
folder still works for the current visit and the editor reports that limitation.

Confirm that Gridiron is closed before applying a change. The editor creates and
verifies a retained backup before replacing the game save.

**Game → Restore previous playbook** restores the latest different backup and
backs up the file it replaces. Filesystem backups live in the selected folder's
`GridironPlaybookBackups` directory, independently of browser working copies.
Without directory access support, import and download still work.

## Build and test the static site

```console
npm run build
npm run preview
```

Publish the `dist` directory to GitHub Pages or another HTTPS static host. The
**Deploy editor to Pages** workflow builds, tests, and deploys pushes to `develop`.
Pull requests to `develop` run the same checks without deploying. To redeploy,
open the workflow in GitHub Actions, choose **Run workflow**, and select `develop`.
Manual runs on other branches only build and test.
The workflow opens the production build in a browser before publishing it. Failed
browser checks retain traces and screenshots in the run's
`browser-failure-diagnostics` artifact for seven days.

In a new repository or fork, set **Settings → Pages → Source** to **GitHub Actions**.
If the `github-pages` environment restricts branches, allow `develop` to deploy.
The published site is `https://56kyle.github.io/gridiron-playbook/`. Quickshare uses
the current site's address and does not need an environment variable.

To test the built browser application and its Wasm bindings:

```console
npm run build:test
npm test
npm run test:browser
```

The browser suite starts and stops its own static server. It uses Edge on Windows
and Playwright Chromium elsewhere. It checks a GitHub Pages-style project path
and uses isolated working copies and filesystem fixtures.

## Python library

The Python package remains available for scripts. Maturin builds its native
bindings from the same Rust core used by the browser.

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

The Python models preserve the save header, schema registry, play data, and
trailing bytes. Use `by_alias=True` for exported keys such as `CustomPlays_0` and
`X_0`. Use `exclude_unset=True` to preserve omitted fields in the last drawn play.
Unknown fields raise a Pydantic `ValidationError`. The browser's Rust document
commands instead retain unrelated raw metadata without rebuilding it in JavaScript.

## Command line

```{eval-rst}
.. typer:: gridiron_playbook.__main__:main
    :prog: gridiron-playbook
    :nested: full
```
