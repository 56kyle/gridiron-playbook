"""Export and serve the Quickshare viewer as static files."""

import json
from functools import partial
from http.server import SimpleHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

from gridiron_playbook.block import BLOCK_OFFSETS
from gridiron_playbook.block import BLOCK_TOLERANCE_CM
from gridiron_playbook.formations import FORMATION_NAMES
from gridiron_playbook.formations import formation_starts
from gridiron_playbook.formations import position_label
from gridiron_playbook.route import CENTIMETERS_PER_YARD


def export_viewer(destination: Path) -> None:
    """Write the complete viewer to a new or empty directory for static hosting."""
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise FileExistsError(f"Choose an empty viewer directory: {destination}")
    source: Path = Path(__file__).parent
    for name in ("index.html", "viewer.css", "viewer.js", "decode.js", "editor.css"):
        _ = copyfile(source / name, destination / name)
    formations: dict[str, dict[int, tuple[str, float, float]]] = {
        name: {slot: (position_label(name, slot), *xy) for slot, xy in formation_starts(name).items()}
        for name in FORMATION_NAMES
    }
    config: dict[str, object] = {
        "formations": formations,
        "blockOffsets": BLOCK_OFFSETS,
        "blockTolerance": BLOCK_TOLERANCE_CM,
        "cmPerYard": CENTIMETERS_PER_YARD,
    }
    _ = (destination / "field-data.js").write_text(f"export default {json.dumps(config)};\n", encoding="utf-8")


def serve_viewer(host: str, port: int) -> None:
    """Serve a directory containing only the exported browser assets."""
    with TemporaryDirectory(prefix="gridiron-viewer-") as directory:
        export_viewer(Path(directory))
        handler = partial(SimpleHTTPRequestHandler, directory=directory)
        with ThreadingHTTPServer((host, port), handler) as server:
            print(f"Quickshare viewer listening on http://{host}:{server.server_port}", flush=True)
            server.serve_forever()
