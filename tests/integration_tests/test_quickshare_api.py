from collections.abc import AsyncIterator
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import TypeAdapter

from gridiron_playbook.play import GridironPlay
from gridiron_playbook.quickshare.snapshot import MAX_SNAPSHOT_BYTES
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.quickshare.snapshot import is_share_id
from gridiron_playbook.quickshare.store import SnapshotStore


if TYPE_CHECKING:
    from httpx import AsyncClient


pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]
_JSON = {"Content-Type": "application/json"}


@pytest.fixture
def snapshot() -> ShareSnapshot:
    play = GridironPlay(FormationName_0="Shotgun Right", PlayName_0="Flood", Routes_0=())
    return ShareSnapshot(version=1, kind="play", plays=(play,))


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator["AsyncClient"]:
    if find_spec("nicegui") is None:
        pytest.skip("Install the web extra to exercise the Quickshare API.")
    from fastapi import FastAPI
    from httpx import ASGITransport
    from httpx import AsyncClient

    from gridiron_playbook.quickshare.api import register_api

    app = FastAPI()
    register_api(app, SnapshotStore(tmp_path / "shares.db"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        yield client


async def test_publish_and_retrieve_snapshot(api: "AsyncClient", snapshot: ShareSnapshot) -> None:
    created = await api.post("/api/shares", content=snapshot.to_bytes(), headers=_JSON)
    assert created.status_code == 201
    share_id = TypeAdapter(dict[str, str]).validate_json(created.content)["id"]
    assert is_share_id(share_id)
    retrieved = await api.get(f"/api/shares/{share_id}")
    assert retrieved.status_code == 200
    assert ShareSnapshot.from_bytes(retrieved.content) == snapshot


@pytest.mark.parametrize(
    ("payload", "content_type", "status"),
    [(b"{}", "text/plain", 415), (b"broken", "application/json", 422), (b'{"version":2}', "application/json", 422)],
)
async def test_publish_rejects_invalid_request(
    api: "AsyncClient", payload: bytes, content_type: str, status: int
) -> None:
    response = await api.post("/api/shares", content=payload, headers={"Content-Type": content_type})
    assert response.status_code == status


async def test_publish_rejects_oversized_stream(api: "AsyncClient") -> None:
    async def chunks() -> AsyncIterator[bytes]:
        chunk = b" " * (MAX_SNAPSHOT_BYTES // 4)
        for _ in range(4):
            yield chunk
        yield b"x"

    response = await api.post("/api/shares", content=chunks(), headers=_JSON)
    assert response.status_code == 413


async def test_publish_limits_repeated_creates(api: "AsyncClient", snapshot: ShareSnapshot) -> None:
    for _ in range(20):
        response = await api.post("/api/shares", content=snapshot.to_bytes(), headers=_JSON)
        assert response.status_code == 201
    rejected = await api.post(
        "/api/shares", content=snapshot.to_bytes(), headers={**_JSON, "X-Forwarded-For": "192.0.2.2"}
    )
    assert rejected.status_code == 429
    assert int(rejected.headers["Retry-After"]) > 0


@pytest.mark.parametrize("share_id", ["invalid", "A" * 22])
async def test_retrieve_missing_snapshot(api: "AsyncClient", share_id: str) -> None:
    response = await api.get(f"/api/shares/{share_id}")
    assert response.status_code == 404
