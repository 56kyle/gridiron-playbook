---
status: accepted
date: 2026-11-04
---

# Persist independent local working copies

## Context and problem statement

The editor must restore open playbook tabs and unsaved edits after a refresh or
restart. Recovery must not modify the imported save files. Separate browser
windows must retain independent working copies. Reopening the editor should
restore the most recently used copy.

## Decision drivers

- Preserve complete save documents, tab order, dirty state, and unfinished routes.
- Keep working saves separate from uploaded files and Quickshare.
- Recover after an interrupted write without replacing the last committed state.
- Prevent concurrent windows from overwriting each other's changes.
- Support playbooks with more than 100 plays without browser storage quotas.
- Use the existing runtime and standard library.

## Considered options

- Store complete workspaces in browser storage.
- Store each workspace in an atomically replaced JSON file.
- Store versioned workspace snapshots in a local SQLite database.

## Decision outcome

Store compressed, lossless workspace snapshots in `working-copies.sqlite3` under
the application's local data folder. `GRIDIRON_WORKING_COPY_PATH` can select a
different database for tests or portable use. A snapshot contains every open
document, its last downloaded baseline, the active tab, tab views, and the active
route draft. Undo and redo history starts fresh after restoration.

The browser stores only opaque identifiers. Session storage identifies its
working copy during refresh. Local storage identifies the most recently used
copy when a new window opens. A browser Web Lock lets an idle copy be reused;
an already open copy is cloned for the new window. If Web Locks are unavailable,
the editor clones the source copy.

SQLite commits the whole workspace in one transaction, including moves between
playbooks. Each save checks the revision read by its page. A stale writer creates
a separate working copy and keeps both versions. The browser records the new
identifier only after the save succeeds.

The page validates recovery before enabling edits. Failed recovery remains in
storage. The user can retry or start a separate workspace. Save failures remain
visible and trigger a browser warning before leaving with unpersisted edits.
Only explicit downloads produce exported `.sav` files.

### Consequences

- Good, because the original uploads remain unchanged and workspace recovery is
  independent of the exported save format.
- Good, because SQLite supplies atomic commits and recovery from interrupted
  writes without another dependency.
- Good, because database revisions also protect against stale writers when a
  browser cannot acquire a lock.
- Bad, because recovery uses both the local database and browser identifiers.
  Clearing browser storage or changing the editor's origin loses the automatic
  association with an existing copy.
- Bad, because historical independent copies remain in the local database; this
  change does not add a browser for old copies or automatic deletion.
- Bad, because undo and redo history does not survive recovery.

### Confirmation

Tests restore ordered tabs, dirty baselines, selections, and route drafts. They
check independent windows, reopen behavior, closing all tabs, and a 125-play
workspace. Storage tests exercise concurrent writers, transaction rollback,
corrupt data, and a process interrupted during a SQLite write. Source-file tests
compare uploaded bytes before and after recovery.

## Pros and cons of the options

### Complete workspaces in browser storage

- Good, because all recovery data stays in the browser profile.
- Bad, because full workspaces and download baselines can exceed synchronous
  browser storage quotas.
- Bad, because an IndexedDB implementation would add a second persistence layer
  with serialization and lifecycle logic in JavaScript.

### Atomically replaced JSON files

- Good, because snapshots are directly inspectable and require no database schema.
- Bad, because safe concurrent updates need an additional locking protocol.
- Bad, because cross-window revision checks and replacement failure recovery
  would duplicate behavior already supplied by SQLite.

### Local SQLite snapshots

- Good, because transactions provide atomic workspace updates and revision checks.
- Good, because compression reduces repeated document data without losing values.
- Good, because the standard library supports the implementation.
- Bad, because users need SQLite tooling to inspect stored snapshots.

## More information

This decision replaces the in-memory-only recovery behavior in
[ADR 0002](0002-edit-playbooks-in-a-local-browser.md). It does not change the
storage-free Quickshare format. See the [local setup guide](../../src/gridiron_playbook/quickshare/README.md#run-locally)
for normal launch and export behavior.
