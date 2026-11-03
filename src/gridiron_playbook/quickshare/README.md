# Quickshare

Quickshare carries the plays inside a link or a `.gridironshare` file. The viewer opens either format in the recipient's browser. Hosting the viewer requires only static files. The part of the URL after `#v1/` stays in the browser when it requests the page. Anyone with the complete link or file can read and forward the plays.

## Share and import

Open a playbook in the editor and choose **Share play** or **Share playbook**. Select a precision for the link and file. The character count includes the entire URL, including your viewer address.

| Precision | Effect on coordinates |
| --- | --- |
| Exact (default) | Preserves the original coordinates. |
| 1 mm | Rounds to the nearest millimeter. |
| 1 cm | Rounds to the nearest centimeter. |

Quickshare can represent a standard block with its anchor waypoint and facing. The viewer and editor expand the instruction back into the 28 game waypoints. Exact mode uses this shortcut only when it reproduces every coordinate bit for bit. With 1 mm or 1 cm precision, a standard block follows the rounded anchor and uses a two-byte heading. Hand-edited strokes remain individual waypoints.

**Download share file** uses the selected precision. When a compact precision is selected, **Download exact file** saves the original coordinates. You can download and import files even without a configured viewer address.

**Copy link** copies links of up to 2,000 characters directly. At 2,001–4,000 characters, confirm the warning that the link exceeds the standard Discord message limit. Above 4,000, confirm the stronger warning that the link also exceeds the Nitro limit. For long playbooks, send the share file as an attachment. These counts apply to the link alone.

Recipients can open a link in a browser or choose a local share file on the viewer page. To use the plays in the game, open the destination playbook in the editor and import the link or file. The plays are appended in order. **Undo** removes the entire import. **Download .sav** saves the result using the recipient's Unreal save metadata.

The viewer's **Download share file** button saves the received precision. For original coordinates, the sender can use **Download exact file** in their editor.

### Existing shares

The updated editor and viewer open both the original binary format and the newer block-compressed format. Both use the same `#v1/` URL fragment and `.gridironshare` extension. When updating a hosted viewer, export the new assets and deploy them together at its existing address so old links keep working.

## Run locally

From the repository root, start the editor and its Quickshare viewer with one command.

```powershell
uv run --extra web python -m gridiron_playbook.web
```

Open the [editor](http://127.0.0.1:8080/) to create or edit plays. Copied links open in the [local viewer](http://127.0.0.1:8080/quickshare/). To share with someone on another computer, send a `.gridironshare` file or configure a public viewer as described below.

## Host the viewer

1. Export the viewer into a new or empty directory.

   ```powershell
   uv run --extra web python -m gridiron_playbook.quickshare --export ./quickshare-site
   ```

2. Upload the exported files together to an HTTPS static site. Preserve their names and directory structure.
3. Set `GRIDIRON_QUICKSHARE_URL` in the editor's environment to the viewer page, for example `https://share.example.org/playbook/`. Restart the editor.

The host serves the same assets to each visitor. Importing a link in the editor decodes the payload locally. Keep the viewer address and versioned decoder available for existing self-contained links.

## Limits

The snapshot format supports up to 2,000 plays and 200,000 total waypoints, with up to 256 routes and 16,384 waypoints per play. Encoded size limits also apply. The recipient's combined playbook must fit the editor's 64 MiB `.sav` limit. The editor checks that limit before changing the destination.
