# Gridiron Playbook

**[Open the live editor](https://56kyle.github.io/gridiron-playbook/)**

Create, edit, and share Gridiron plays in your browser. No installation required.

The editor is a static Vue/TypeScript application. Rust runs locally in
WebAssembly to read and write Unreal saves, apply edits, and encode Quickshare
links. No Python server or play storage service is required.

## Local development

Install Node.js 22.12 or later and a current stable Rust toolchain. On Windows,
Rust also requires the Visual Studio C++ build tools.

Run these setup commands once from the repository root:

```powershell
npm ci
rustup target add wasm32-unknown-unknown
cargo install wasm-bindgen-cli --version 0.2.130 --locked --root .tools
```

Then start the complete editor and Quickshare viewer with one command:

```powershell
npm run dev
```

Open the address printed by Vite. The command rebuilds the Rust browser module
before starting. After opening the site, editing and file conversion run on your
computer. Files are not uploaded to a playbook service.

## Build and host

```powershell
npm run build
npm run preview
```

The `dist` directory contains the complete site, including its Wasm module.
Upload those files together to an HTTPS static host. Relative asset URLs support
both a domain root and a GitHub Pages project path such as
`https://56kyle.github.io/gridiron-playbook/`. The app uses URL fragments for
Quickshare and does not require server route rewrites.

The **Deploy editor to Pages** workflow tests and publishes the editor when changes
are pushed to `develop`. Pull requests to `develop` run the same build and tests
without publishing. You can also run the workflow manually from the Actions tab;
select `develop` to deploy. Other branches only build and test.

For a new repository or fork, select **GitHub Actions** in **Settings → Pages**.
If the `github-pages` environment restricts deployment branches, allow `develop`.
The deployment job runs only after the Rust, TypeScript, and browser checks pass.
It publishes the production `dist` directory without the browser test harness.
The workflow smoke-tests that production build before upload and retains browser
failure traces and screenshots as an Actions artifact for seven days.

Quickshare links use the current site's address. Share files also work without
a public host. See the [Quickshare guide](src/gridiron_playbook/quickshare/README.md)
for precision options, size limits, and compatibility.

## Working copies and game saves

Opening a file creates an editor working copy. Tabs, unsaved changes, selections,
and unfinished routes are stored in this browser's IndexedDB database. Refresh
restores the current window; a new window gets an independent copy of the most
recent workspace. Undo history starts fresh after recovery.

Working copies do not write to the file you opened. Browser storage belongs to
this site and browser profile. Clearing site data removes it; use **Download
.sav** to keep a separate file. Moving to a different hostname or port does not
move these working copies automatically.

Browsers with directory access support can use **Use in game** and **Restore
previous**. Choose SaveGames or the Gridiron installation folder once. The editor
remembers the folder in this browser and checks access when you use it again.
If access has expired, select **Use saved folder** to allow access again.
**Game → Game folder…** lets you change or forget the selection.
The first-use dialog includes Steam navigation and a copyable default Windows
Steam folder path. This path is a hint, not a detected installation.

Confirm that Gridiron is closed. Before replacing `GridironCustomPlays.sav`, the editor writes and verifies
a separate backup in that directory. Restore also backs up what it replaces.
Backups are retained on disk, independently of browser working copies. The site
cannot discover Steam folders or check whether the game is running. Remembering
or forgetting a folder does not modify the game save. Browsers
without directory access can still import and download saves.

## Project structure

- `web/src`: Vue interface, browser working copies, file access, and Wasm worker.
- `rust/core`: Shared save, edit, formation, route, block, and Quickshare logic.
- `rust/wasm`: Browser bindings to the core.
- `rust/python`: PyO3 bindings for the Python library.
- `src/gridiron_playbook`: Python library and standalone Quickshare exporter.
- `web/tests`: TypeScript unit tests and Playwright browser tests.
- `tests`: Python library and Python/Rust integration tests.

Complete save documents remain opaque strings in the browser. Edit commands run
in Rust, retaining unrelated Unreal metadata and Exact-mode coordinate bits.
The Wasm module runs in a worker, so file processing does not block pointer
interaction and a parser trap can be recovered without losing the workspace.

## Verify

```powershell
npm run build:test
npm test
npm run test:browser
cargo test --manifest-path rust/Cargo.toml -p gridiron-playbook-core
cargo clippy --manifest-path rust/Cargo.toml --workspace --all-targets -- -D warnings
uv sync --group dev
uv run pytest tests
```

Browser tests use installed Microsoft Edge on Windows. Elsewhere, install the
Playwright browser with `npx playwright install --with-deps chromium`. The tests
serve the built site under `/gridiron-playbook/` and use isolated browser storage
and temporary files. They never access an actual game save.

Build the Python extension with `uv sync --group dev` or `uv pip install -e .`.
Maturin compiles the same core for native Python; Python is not required to build
or use the browser editor.
