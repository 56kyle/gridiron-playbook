# Quickshare

Quickshare carries plays inside a link or a `.gridironshare` file. The static
editor previews and imports either format in the recipient's browser. No play
storage service is used. The payload after `#v1/` is not sent when the browser
requests the page. Anyone with the complete link or file can read and forward it.

## Share and import

Choose **Share play** or **Share playbook** and select a precision. The displayed
character count includes the entire URL, including the site's address.

| Precision | Effect on coordinates                                      |
| --------- | ---------------------------------------------------------- |
| Exact     | Preserves the original coordinates, including signed zero. |
| 1 mm      | Rounds eligible coordinates to the nearest millimeter.     |
| 1 cm      | Rounds eligible coordinates to the nearest centimeter.     |

A standard block can be represented by its anchor and facing instead of its 28
waypoints. Exact mode uses that shortcut only when reconstruction preserves every
coordinate bit. Reduced precision uses rounded anchors and compact headings.
Hand-edited block strokes retain their original coordinates.

**Download share file** uses the selected precision. **Download exact file**
keeps the original coordinates. Both files can be opened in the editor.

Links up to 2,000 characters copy directly. Longer links require confirmation:
2,001–4,000 characters exceed Discord's standard message limit, and more than
4,000 exceed its Nitro message limit. Copying remains available after the warning.
The counts apply to the link alone. For large books, send the share file.

An incoming link opens a preview before changing the workspace. Importing an
individual play adds it to the top of the active book. Importing a whole playbook
opens another tab. Without an active book, the editor uses its blank save
template. Imported books retain the destination template's Unreal save metadata.

New and duplicated plays also appear at the top. Select plays to reorder, copy,
or move them between tabs. **Merge** copies every source play into the selected
destination in source order. Transfers participate in the shared undo history.

## Run and host

After the one-time tool setup in the [repository guide](../../../README.md), run:

```powershell
npm run dev
```

The editor and Quickshare preview are the same browser application. No environment
variable, Python server, or second terminal is required. Links use the current
site's address; localhost links work only on the same computer.

To host the entire editor and viewer:

```powershell
npm run build
```

Publish the `dist` directory to an HTTPS static host or use the manual **Deploy
editor to Pages** GitHub Actions workflow. Preserve the hosted address and deploy
all assets together so existing links continue to open. Working copies remain
in each visitor's browser; hosting does not store their plays.

The Python library also retains a standalone read-only viewer exporter:

```powershell
uv run python -m gridiron_playbook.quickshare --export ./quickshare-site
```

This exports static files to a new or empty directory. It is a library utility;
the primary application and its viewer are built with `npm run build`.

## Format compatibility and limits

Both binary versions 1 and 2 remain readable. New links and files use version 2
with block compression. Both versions use `#v1/` in URLs and `.gridironshare` for
files. Exact mode preserves values supplied to the encoder; it cannot recover
precision already removed by a sender.

The format allows up to 2,000 plays, 256 routes per play, 16,384 waypoints per
play, and 200,000 waypoints in total after block expansion. Compressed and
inflated payloads are each limited to 16 MiB. Save imports and exports have a
64 MiB limit. These are format limits, not a guarantee that a large book fits in
a chat message or that every game version accepts that many plays.
