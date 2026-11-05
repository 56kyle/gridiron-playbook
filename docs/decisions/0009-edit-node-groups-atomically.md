---
status: accepted
date: 2026-11-04
---

# Edit selected node groups atomically

## Context and problem statement

The browser editor supports individual node edits, but users need to select a
group with a rectangle and move or delete that group. A selection can cross
routes. Sending one command per node would create multiple undo steps and make
deletion depend on shifting route and point indices.

## Decision drivers

- Select the nodes inside the rectangle, including nodes on different routes.
- Preview movement immediately and preserve the group's relative spacing.
- Commit each gesture as one edit and one undo step.
- Preserve point heights and unknown Unreal metadata.
- Keep selection and drag cancellation independent of saved geometry.

## Considered options

- Send an existing single-node command for each selected node.
- Replace complete routes with geometry assembled in TypeScript.
- Add typed group-edit commands to the shared Rust core.

## Decision outcome

Add `move_points` and `delete_points` commands. Each contains node references
with a route index and point index in the original play. Movement carries one
coordinate offset. Rust validates the selection, retains unselected values and
metadata, and returns a complete document only when the whole edit succeeds.
Deletion removes points in reverse index order, then removes emptied routes.
Partial deletion that leaves an unknown-formation route with one point fails
without changing the document; it does not remove an unselected point.

Keep transient node selection and pointer state in the field component. A box
selects every node inside it. The route with the most selected nodes becomes
active in the inspector; the current route wins ties. Shift-drag adds nodes and
Shift-click or Ctrl/Command-click toggles one node. Group movement uses a common
offset constrained by the field bounds, rather than clamping nodes separately.

Delete targets selected nodes first, then the selected route if no nodes are
selected. Selecting a route explicitly clears its node selection. Escape cancels
an active gesture before clearing selection. Existing application guards prevent
keyboard deletion while editing text or using a dialog. Node selection is
transient; the resulting document edits use the existing local recovery system.
The busy state temporarily makes the field inert. Restore its prior keyboard
focus after an edit only if the same field remains mounted and focus has not
moved to another control or a dialog.

### Consequences

- Good, because a gesture maps to one Rust edit and one workspace transaction.
- Good, because Wasm and native bindings expose the same validated operations.
- Good, because unknown fields and heights remain in the original document.
- Bad, because the core gains two commands alongside existing single-node APIs.
- Bad, because index-based selection must be cleared when route topology changes.

### Confirmation

Rust tests verify translation, deletion order, metadata preservation, signed zero,
invalid selections, and route minimums. TypeScript tests verify rectangle bounds,
selection merging, active-route choice, and shared movement bounds. Browser tests
exercise the real Wasm worker, pointer capture, previews, deletion, undo/redo,
Escape, text-field guards, and the existing drawing and node-editing controls.

## Pros and cons of the options

### Send single-node commands

- Good, because the existing commands need no extension.
- Bad, because deletion indices shift and one gesture creates several undo steps.

### Replace routes from TypeScript

- Good, because the browser already has coordinates for the preview.
- Bad, because normalized browser data omits unknown Unreal metadata.
- Bad, because mutation rules would be split between TypeScript and Rust.

### Add group commands to Rust

- Good, because one validated boundary controls each edit and preserves metadata.
- Bad, because both bindings must accept the additional command variants.

## More information

This extends ADR 0006's shared Rust edit boundary and reuses the existing
workspace history and working-copy recovery.
