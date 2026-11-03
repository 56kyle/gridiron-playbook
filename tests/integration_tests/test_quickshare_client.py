from collections.abc import Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

from gridiron_playbook.play import GridironPlay
from gridiron_playbook.quickshare.client import QuickshareClient
from gridiron_playbook.quickshare.client import QuickshareError
from gridiron_playbook.quickshare.snapshot import MAX_SNAPSHOT_BYTES
from gridiron_playbook.quickshare.snapshot import ShareSnapshot


pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]
_VALID = "a" * 22
_REDIRECT = "b" * 22
_OVERSIZED = "c" * 22


@pytest.fixture(scope="module")
def origin() -> Iterator[str]:
    play = GridironPlay(FormationName_0="Twins Right", PlayName_0="Flood", Routes_0=())
    snapshot = ShareSnapshot(version=1, kind="play", plays=(play,)).to_bytes()

    class ShareHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == f"/api/shares/{_REDIRECT}":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", f"/api/shares/{_VALID}")
                self.end_headers()
                return
            if self.path not in {f"/api/shares/{_VALID}", f"/api/shares/{_OVERSIZED}"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body: bytes = snapshot.ljust(MAX_SNAPSHOT_BYTES + 1) if self.path.endswith(_OVERSIZED) else snapshot
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            _ = self.wfile.write(body)

    with ThreadingHTTPServer(("127.0.0.1", 0), ShareHandler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join()


async def test_fetch(origin: str) -> None:
    snapshot = await QuickshareClient(origin + "/").fetch(f"{origin}/s/{_VALID}")
    assert snapshot.plays[0].play_name == "Flood"


@pytest.mark.parametrize("share_id", [_REDIRECT, _OVERSIZED], ids=["redirect", "oversized-without-content-length"])
async def test_fetch_with_invalid_response(origin: str, share_id: str) -> None:
    client = QuickshareClient(origin)
    with pytest.raises(QuickshareError):
        _ = await client.fetch(f"{origin}/s/{share_id}")


async def test_fetch_rejects_another_origin(origin: str) -> None:
    alternate: str = origin.replace("127.0.0.1", "localhost")
    with pytest.raises(QuickshareError):
        _ = await QuickshareClient(origin).fetch(f"{alternate}/s/{_VALID}")


@pytest.mark.parametrize("extra", ["?download=1", "#preview", "/"])
async def test_fetch_rejects_malformed_share_link(origin: str, extra: str) -> None:
    with pytest.raises(QuickshareError):
        _ = await QuickshareClient(origin).fetch(f"{origin}/s/{_VALID}{extra}")
