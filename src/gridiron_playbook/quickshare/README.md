# Quickshare

A Quickshare link opens a read-only snapshot of one play or an ordered playbook. Anyone with the link can preview and import the plays. The sender can close the editor after creating the link.

## Try it locally

Install the web extra from the project directory.

```powershell
uv sync --extra web
```

Start the service in one terminal.

```powershell
uv run --extra web python -m gridiron_playbook.quickshare
```

Start the editor in a second PowerShell terminal.

```powershell
$env:GRIDIRON_QUICKSHARE_URL = "http://127.0.0.1:8081"
uv run --extra web python -m gridiron_playbook.web
```

Open a playbook. Choose **Share play** or **Share playbook**, then **Create link**. Copy the link and open it in another browser. A loopback link works on the computer that runs the service.

To import, open the destination playbook in the editor. Choose **Import link**, paste the preview URL, and confirm the import. The editor appends the plays in order. **Undo** removes the entire import. Choose **Download .sav** to save the result.

## Share across computers

1. Run one Quickshare service on a host with persistent storage. Use `--database` to select a SQLite file on that storage. The default is `quickshare.sqlite3` in the user's application data directory.
2. Serve the process through an HTTPS reverse proxy at the root of your domain. Forward HTTP and WebSocket traffic to the service. Its default listener is `127.0.0.1:8081`. Use `--host` and `--port` to change the listener.
3. On each editor computer, set `GRIDIRON_QUICKSHARE_URL` to the same public origin, for example `https://share.example.org`. Restart the editor after changing the variable.

Keep the public origin and database across deployments. Back up the database to preserve published links. The service accepts anonymous publications. It limits publishing attempts per minute to 20 per client address and 120 per process. Configure the reverse proxy to supply the actual client address from a trusted upstream.

## Playbook size and contents

A link contains a random 22-character ID regardless of the number of plays. The preview lets the recipient search the book and draws one play at a time.

Each version 1 snapshot supports up to 2,000 plays, 200,000 total waypoints, and 16 MiB of JSON. Each play supports up to 256 routes and 16,384 waypoints. Formation names, route slots, heights, block strokes, and duplicate play names survive import. The destination supplies its own Unreal save header and drawing state.

Before import, the editor checks that it can encode and reopen the combined playbook. The local file limits are 64 MiB for `.sav` and 16 MiB for JSON.
