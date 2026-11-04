---
status: accepted
date: 2026-11-04
---

# Install game playbooks with retained backups

## Context and problem statement

The editor needs an explicit action to use an open playbook in Gridiron. A user
must also be able to restore the previous game playbook without losing the save
that the restore replaces. Editor working copies must remain separate from the
game's save file.

The previous helpers wrote directly to the game save. Their backup names reused
the application start time, and restore did not back up the replaced file.

## Decision drivers

- Preserve the exact bytes of every game save that an operation replaces.
- Leave the game save unchanged if a backup cannot be created and verified.
- Retain recoverable backups across failed operations and editor restarts.
- Reject a confirmation if the destination changes before application.
- Support independent editor windows without concurrent application writes.
- Keep the interface explicit and use the standard library.

## Considered options

- Download a save and require users to install and back it up manually.
- Replace the game save after copying it to one fixed backup file.
- Use a separate game-save service with immutable backup history and prepared changes.

## Decision outcome

Use `GamePlaybookStore` for installation, backup, and restoration. Its constructor
receives an explicit game-save path and backup directory. The legacy Python
helpers use the same service, so they cannot bypass backup-before-replacement.
The document models and pure codecs live in `playbook_document.py`; `playbook.py`
keeps their existing public imports and the legacy file helpers. This removes
the dependency cycle between the document model and game-save operations.

Preparation resolves the destination, encodes the replacement, and captures the
current file's digest. It does not write files. Restore preparation selects a
backup before the service backs up the current game save. The UI shows the exact
destination and requires the user to confirm that Gridiron is closed.

Application locks the target against other application writers and checks its
digest again. It creates a unique backup, flushes it, reads it back, and publishes
validated metadata. Only then does it flush a temporary replacement beside the
game save, recheck the current digest, and atomically replace the destination.
The service verifies the installed bytes before reporting success.

Backups live under `USER_DATA_FOLDER / "game-playbook-backups"` by default. Each
canonical target has a separate archive directory. An operating-system advisory
lock beside the canonical game save serializes writers even when they use
different backup directories.
Archive names contain a monotonic sequence and a unique identifier. Metadata
contains a format version, target, sequence, creation time, and content digest.
The service derives archive paths from validated filenames, rather than paths
inside metadata. No operation deletes an older backup.

Restore selects the most recent verified backup whose contents differ from the
current game file. A same-content installation does nothing. A failed attempt's
backup therefore cannot hide the previous useful version. Repeated restoration
can swap the two most recent versions while retaining the rest of the history.
A corrupt backup raises an explicit error instead of silently choosing an older
version.

When managed history is empty, the automatically discovered game target can use
legacy backups directly under the application's cache folder. Only names that
match the former timestamp format are eligible. Preparation validates the newest
candidate without writing files; application archives it before replacement.
Legacy files remain untouched. Only a target verified against current automatic
discovery receives this legacy association. Other manual or environment-selected
destinations do not inherit these older, unscoped backups.

Installation and restoration remain explicit actions. They do not bind an editor
tab to the game save or redirect working-copy autosave. Restore is available even
when no playbook is open in the editor. Users can select an existing game-save
file when automatic discovery fails.

### Consequences

- Good, because a successful replacement has a verified backup available first.
- Good, because restore also preserves the contents it replaces.
- Good, because preparation and application separate confirmation from effects
  and permit tests with real files in temporary directories.
- Good, because a process interruption before replacement leaves the current
  save, and an interruption after replacement leaves a published backup.
- Bad, because retained history consumes disk space and has no automatic pruning.
- Bad, because advisory locks serialize this application's writers only. An
  independent game process does not participate in the lock. The final digest
  check reduces the conflict window but cannot eliminate an external write race.
  Gridiron must remain closed throughout the operation.
- Bad, because guarantees after power loss depend on the filesystem and storage
  device honoring flush and replacement operations.

### Confirmation

Use real temporary saves to verify install, restore, repeated restore, and
byte-for-byte backup retention. Exercise stale confirmations, concurrent writers,
missing targets, corrupt backups, backup failures, and replacement failures.
Verify that a failed attempt does not hide the prior restore candidate and that
same-content installs do not create new history. UI tests must confirm the
destination and game-closed requirement before writing an isolated fake save.

## Pros and cons of the options

### Manual download and installation

- Good, because the editor never writes to the game directory.
- Bad, because users must locate, back up, and replace files themselves.
- Bad, because recovery depends on whether the user created a backup.

### One fixed backup file

- Good, because the implementation and restore lookup are small.
- Bad, because each operation destroys an earlier recovery point.
- Bad, because a restore can overwrite the file it still needs to read.

### Prepared changes and retained history

- Good, because confirmation names the destination and rejects stale state.
- Good, because unique verified archives preserve each replaced version.
- Good, because independent windows use the same preservation contract.
- Bad, because metadata, locking, and interrupted-operation handling require more
  code than a direct file copy.

## More information

[ADR 0004](0004-persist-independent-local-working-copies.md) describes editor
working copies. Those records are separate from game-save backups. The
[local setup guide](../../src/gridiron_playbook/quickshare/README.md#run-locally)
describes the user-facing actions.
