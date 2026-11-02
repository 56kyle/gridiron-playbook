---
status: accepted
date: 2026-11-02
---

# Use a verified formation catalog for pre-snap alignments

## Context and decision drivers

A custom play contains a formation name and routes keyed by numeric slot.
Each route holds an ordered sequence of drawn waypoints. Players without a
route have no entry. The editor needs to place those players, draw the first
segment of a route, and keep the original waypoint sequence intact on export.
It must also open saves from unfamiliar formations without a game installation.

## Considered options

- Infer the lineup from the first waypoint of each route.
- Read the installed game's formation assets whenever a playbook is opened.
- Ship a small catalog of verified starts and positions for the formations
  demonstrated in the supplied playbook.

## Decision outcome

Use the catalog. Look up the pre-snap position by formation name and slot.
Draw it as a fixed player marker and prepend it to the displayed path. The
editable handles still correspond one-to-one with the saved waypoints. For
a known start, a single drawn waypoint completes a route. Where a lookup
fails, show the raw slot and draw only the supplied geometry.

Use the observed route-slot combinations as editor suggestions. The model
continues to accept other byte-valued slots. Project game X upfield and game
Y to the right, with the inverse mapping applied when a point is dragged.

### Consequences

All seven players are visible for each known formation, including players with
no drawn route. A change to a game's formation data requires a catalog update.
The [formation reference](../reference.md#offensive-formations-and-slots)
records the build, asset fingerprint, and coordinates used for verification.

### Confirmation

Compare the catalog with the game definitions and the slot sets in the supplied
save. Check an anchored one-waypoint route through binary export and reload.
In a browser, drag a waypoint and verify the game-axis displacement while the
lineup and untouched data remain intact.

## Tradeoffs

Inferring from waypoints would place players differently on successive plays
in the same formation and omit anyone without a route. Reading the assets on
each launch would track game updates but would couple the editor to a local
game install and archive format. The catalog provides reproducible alignments
for its documented build and leaves unknown saves editable.
