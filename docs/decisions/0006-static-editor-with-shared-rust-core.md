---
status: accepted
date: 2026-11-04
---

# Run the editor as a static application with a shared Rust core

## Context and problem statement

The editor must run on GitHub Pages without a Python server or storage service.
NiceGUI owns UI state and callbacks on the Python server, which static hosting
cannot provide. Save conversion is already implemented in Rust through PyO3.
There are no users to migrate, so maintaining a transitional NiceGUI application
is unnecessary. Existing save and Quickshare formats still need to round-trip.

## Decision drivers

- Publish a complete editor as static assets with no playbook uploads.
- Preserve Unreal metadata and Exact-mode binary64 coordinate values.
- Keep one Rust implementation behind native and browser bindings.
- Preserve route editing, tabs, ordering, transfers, and independent recovery.
- Retain verified filesystem backups before explicit game-save replacement.
- Reuse the existing Vue/SVG interaction model and in-game color palette.

## Considered options

- Host the NiceGUI server separately and point a Pages site at it.
- Move Python and its dependencies into a browser Python runtime.
- Rewrite the full application, including its UI, in Rust.
- Use Vue/TypeScript for the browser and a shared Rust core for file/domain logic.

## Decision outcome

Use Vue/TypeScript built with Vite and a Cargo workspace containing core, Python,
and Wasm crates. Maturin builds the PyO3 adapter. wasm-bindgen builds the browser
adapter with the same pinned CLI and crate version. The production build is a
static directory with relative asset URLs; no server routing fallback is needed.

The complete save document crosses the browser boundary as an opaque JSON
string. Rust parses and edits it while retaining metadata and optional-field
presence. Vue receives typed display views and sends narrowly scoped edit
commands. It never reconstructs an entire document from a JavaScript object:
JavaScript JSON serialization changes signed zero, and large metadata integers
may exceed its exact integer range. Cross-book operations receive both opaque
documents and preserve the destination's save metadata.

The Rust core owns Quickshare binary versions 1 and 2, encoding version 2 under
the existing #v1/ fragment and .gridironshare extension. It retains Exact values,
ties-to-even compact rounding, block-template compression, hand-edited block
protection, and decoded-size limits. Python and browser tests compare independent
implementations and fixed vectors rather than requiring identical zlib output.

Run the Wasm module in a dedicated worker. Rust's browser target normally aborts
on panic; the native catch_unwind contract cannot be assumed to recover there.
A Wasm trap rejects pending operations and replaces the worker on the next call.
Working documents remain outside the worker and edits commit only on success.

IndexedDB holds opaque workspace snapshots and saved baselines. A browser-window
identity and Web Lock distinguish refresh from another active window. Writes are
revision checked; stale writers fork instead of overwriting another workspace.
Working-copy recovery does not bind autosave to imported or game files.

Explicit installation uses user-granted directory access, a fixed game filename,
retained backup metadata, digest checks, and a verified backup before a writable
replacement is closed. Restoration chooses a different verified backup before
archiving the current save. Application Web Locks coordinate windows, but cannot
lock the independent game process. The confirmation therefore requires the game
to remain closed. Unsupported browsers keep import and download available.

### Consequences

- Good, because GitHub Pages serves only application assets and plays stay local.
- Good, because Python and Wasm share the save and Quickshare engine.
- Good, because raw document commands preserve data unrelated to an edit.
- Good, because browser tests exercise a real static build under a project path.
- Bad, because the browser build requires Node, Rust, and matching Wasm tooling.
- Bad, because filesystem permissions and support differ between browsers.
- Bad, because browser working copies can be cleared and do not sync devices.
- Bad, because browser filesystem writes cannot provide native OS advisory locks
  or a guarantee against external game/cloud writers and power loss.

### Confirmation

Build the native and Wasm adapters. Verify Python/Rust and browser round-trips,
old Quickshare fixtures, Exact signed zero, reduced precision, edited blocks,
large playbooks, and malformed-save recovery. Test independent windows and
refresh recovery with real IndexedDB. Exercise backup/install/restore with real
isolated browser filesystem handles. Serve browser tests from the built static
site at /gridiron-playbook/ without a backend or SPA fallback.

## Pros and cons of the options

### Separate NiceGUI server

- Good, because it preserves the existing Python UI code.
- Bad, because it adds runtime hosting and sends document state to a server.
- Bad, because it does not meet the requested static application structure.

### Python in the browser

- Good, because some domain code could remain Python.
- Bad, because NiceGUI's server architecture and native extensions still need
  adaptation, adding a Python runtime without removing the browser UI migration.

### Entirely Rust UI

- Good, because it provides one implementation language.
- Bad, because it gives up reusable Vue/SVG interactions without a demonstrated
  benefit for UI rendering or pointer handling.

### Vue/TypeScript and shared Rust

- Good, because the frontend uses browser APIs directly and reuses existing
  interaction patterns, while Rust owns the formats that need exact fidelity.
- Bad, because binding contracts and two compilation toolchains need tests.

## More information

This decision supersedes the NiceGUI delivery choice in ADR 0002 and the
server-side browser-recovery implementation in ADR 0004. ADR 0005's retained
backup-before-replacement principle remains; its OS-specific implementation is
still available to Python callers, while the browser uses a permissioned adapter.

References: https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
and https://doc.rust-lang.org/rustc/platform-support/wasm32-unknown-unknown.html.
