---
status: accepted
date: 2026-11-02
---

# Edit a playbook in a local browser

## Context and problem statement

A player needs to draw routes and edit individual points in an existing Unreal
save. The package already models the complete document and converts save bytes
through its Maturin extension. A gesture may generate many pointer events, but
the player expects Undo to reverse the whole gesture.

## Decision drivers

- Preserve the save envelope, route order, slot numbers and untouched coordinates.
- Keep file conversion available to Python callers without UI dependencies.
- Give each open tab an independent document and undo history.
- Support both mouse and touch input without a server round trip for each movement.

## Considered options

- A local NiceGUI page with an SVG diagram and a Python editor.
- A desktop Qt graphics scene using the same Python models.
- A browser app with a separate frontend build and document API.

## Decision outcome

Use NiceGUI as the optional `web` extra. A page instance owns selection and
one `PlaybookEditor`. The editor replaces the affected frozen models and keeps
up to 100 prior document versions. Undo and redo operate on documents. Changing
the selection does not enter history.

The SVG component previews gestures locally and sends the final point position
or finished route to Python. The page rejects callbacks from superseded diagrams.
Field coordinates are a reversible projection of the saved X/Y coordinates.
Existing points keep their Z. New routes are drawn on the zero-height plane.

Open and Download use the shared model-to-bytes conversion. Documents remain
in memory until downloaded. The server binds to loopback and does not need a
database, Steam installation, or a frontend build tool to edit an uploaded save.

### Consequences

- The Python editing operations can be tested independently of a browser.
- The web extra brings an HTTP server and additional dependencies. Updating it
  requires checking the packaged JavaScript component and pointer interactions.
- Refreshing a tab discards undownloaded edits. A diagram shows relative geometry;
  the fixture does not establish the game's orientation or a yards-per-unit scale.

### Confirmation

Compare an unchanged fixture export byte for byte. Edit a duplicate, undo and
redo, then reopen its binary export. Check that the original play, metadata and
last-drawn state are preserved. Exercise actual SVG pointer events in a browser.

## Pros and cons of the options

Qt provides native diagram interaction but adds a desktop runtime. A separately
built frontend gives full control over gestures but adds a second build system
and API boundary. NiceGUI supplies page lifecycle and file transfer while the
small SVG component handles direct manipulation.

## Dependency choice

NiceGUI 3.18 supports Python 3.10 and provides the page, upload, and download
interfaces used here. Its MIT-licensed distribution includes a server stack,
so it belongs in the optional web extra. Playwright is a separate development
group for browser checks. Neither dependency is required to convert saves.
