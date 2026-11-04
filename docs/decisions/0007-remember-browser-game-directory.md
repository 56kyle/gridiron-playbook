---
status: accepted
date: 2026-11-04
---

# Remember the selected game directory in the browser

## Context and problem statement

The static editor needs a convenient way to return to the user's current game
save. Browser pickers cannot start at an arbitrary filesystem path, and Wasm
cannot discover Steam installations through native filesystem APIs. Repeated
manual navigation makes the existing install and restore actions difficult to use.

## Decision drivers

- Keep the complete editor deployable as static assets.
- Reuse a confirmed folder across refreshes and later visits.
- Keep permission prompts tied to an explicit user action.
- Preserve working-copy isolation and backup-before-replacement behavior.
- Handle cancelled selections, stale handles, and unavailable browser storage.

## Considered options

- Ask for the SaveGames folder for every visit.
- Store an absolute path or add a native Steam discovery helper.
- Store the browser's directory handle and reconnect when needed.

## Decision outcome

Store the selected directory handle in a dedicated IndexedDB database. This is a
site preference, separate from playbook working copies. Each open window keeps
its chosen handle until the user changes it. A choice in another window does not
change a pending installation or restoration.

Read the stored handle during startup without reading the game save or requesting
permission. Before an install or restore, query permission. When access is
required, show the saved folder and a button that requests permission directly
from its click handler. Directory picking also starts directly from a click.

Accept SaveGames or the Gridiron installation directory by checking only the known
relative save locations. Validate the selected save before replacing
the remembered choice. Cancelled or invalid choices preserve the previous handle.
Seed subsequent pickers with that handle and retain the existing picker ID.

Show Steam's local-files navigation and a copyable default Windows Steam common
directory as first-use help. Do not claim that this hint identifies the user's
installation. Do not guess an edition's Steam installation directory name.

If storing a valid selection fails, allow its use for the current visit and report
that it was not remembered. Forgetting removes only the stored handle. None of
these actions writes to the game save or bypasses the installation confirmation.

### Consequences

- Good, because returning users can reuse their selected folder.
- Good, because the same static site works without a native helper or service.
- Good, because working-copy records do not contain filesystem capabilities.
- Bad, because browser permissions can expire and require another user gesture.
- Bad, because stored handles are specific to the site and browser profile.
- Bad, because a default-path hint does not cover every Steam library location.

### Confirmation

Use real browser IndexedDB and isolated filesystem handles to verify persistence,
reload, forgetting, and invalid records. Replace only picker and permission
boundaries in UI tests so no test opens an actual game directory. Verify that
permission requests have user activation, denied access can be retried, stale
folders have a recovery path, and selection never modifies the existing save.

## Pros and cons of the options

### Select on every visit

- Good, because it needs no persistent handle storage.
- Bad, because users must repeat navigation for ordinary install and restore work.

### Absolute path or native discovery

- Good, because native integration can discover installed Steam games.
- Bad, because browser pickers do not accept arbitrary absolute starting paths.
- Bad, because a native helper would add an installation requirement.

### Remember the browser directory handle

- Good, because browsers can persist and reuse handles after explicit selection.
- Bad, because access must still be checked and stale selections need recovery.

## More information

This extends ADR 0006's browser filesystem adapter without changing ADR 0005's
backup-before-replacement requirement.

- [Picker starting directories](https://wicg.github.io/file-system-access/#starting-directory)
- [Stored handles and permissions](https://developer.chrome.com/docs/capabilities/web-apis/file-system-access#stored-file-or-directory-handles-and-permissions)
