"""Publish and retrieve immutable Quickshare snapshots over HTTP."""

from asyncio import to_thread
from collections import deque
from time import monotonic

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from pydantic import ValidationError

from gridiron_playbook.quickshare.snapshot import MAX_SNAPSHOT_BYTES
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.quickshare.snapshot import SnapshotTooLargeError
from gridiron_playbook.quickshare.store import SnapshotStore


_WINDOW_SECONDS = 60
_PUBLISHES_PER_ADDRESS = 20
_PUBLISHES_PER_SERVICE = 120


class _PublishQuota:
    def __init__(self) -> None:
        self._attempts: deque[tuple[float, str]] = deque()

    def reserve(self, address: str) -> None:
        now: float = monotonic()
        while self._attempts and self._attempts[0][0] <= now - _WINDOW_SECONDS:
            _ = self._attempts.popleft()
        if (
            len(self._attempts) >= _PUBLISHES_PER_SERVICE
            or sum(peer == address for _, peer in self._attempts) >= _PUBLISHES_PER_ADDRESS
        ):
            raise HTTPException(
                status_code=429, detail="Too many share requests.", headers={"Retry-After": str(_WINDOW_SECONDS)}
            )
        self._attempts.append((now, address))


async def _read_body(request: Request) -> bytes:
    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Send the snapshot as application/json.")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_SNAPSHOT_BYTES:
            raise HTTPException(status_code=413, detail="The snapshot exceeds the size limit.")
        body.extend(chunk)
    return bytes(body)


def _publish(store: SnapshotStore, data: bytes) -> str:
    try:
        return store.create(ShareSnapshot.from_bytes(data))
    except SnapshotTooLargeError as error:
        raise HTTPException(status_code=413, detail="The snapshot exceeds the size limit.") from error
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="Invalid Quickshare snapshot.") from error


def _load(store: SnapshotStore, share_id: str) -> Response:
    snapshot: ShareSnapshot | None = store.get(share_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Share not found.")
    return Response(content=snapshot.to_bytes(), media_type="application/json")


def register_api(app: FastAPI, store: SnapshotStore) -> None:
    """Mount the snapshot API and its per-process publishing quota on an application."""
    quota = _PublishQuota()

    async def publish(request: Request) -> dict[str, str]:
        quota.reserve(request.client.host if request.client is not None else "")
        share_id: str = await to_thread(_publish, store, await _read_body(request))
        return {"id": share_id}

    async def fetch(share_id: str) -> Response:
        return await to_thread(_load, store, share_id)

    app.add_api_route("/api/shares", publish, methods=["POST"], status_code=201)
    app.add_api_route("/api/shares/{share_id}", fetch, methods=["GET"])
