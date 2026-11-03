"""Publish and fetch immutable snapshots at the editor's configured Quickshare service."""

import asyncio
import os
from http.client import HTTPConnection
from http.client import HTTPException
from http.client import HTTPSConnection
from ipaddress import ip_address
from typing import ClassVar
from typing import Literal
from urllib.parse import SplitResult
from urllib.parse import urlsplit

from pydantic import BaseModel
from pydantic import ConfigDict

from gridiron_playbook.quickshare.snapshot import MAX_SNAPSHOT_BYTES
from gridiron_playbook.quickshare.snapshot import ShareSnapshot
from gridiron_playbook.quickshare.snapshot import is_share_id


_URL_ENV = "GRIDIRON_QUICKSHARE_URL"
_TIMEOUT_SECONDS = 15
_MAX_RECEIPT_BYTES = 1024


class QuickshareError(ValueError):
    """The editor could not complete a Quickshare request."""


class _Receipt(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(strict=True, extra="forbid")

    id: str


def _parse_url(value: str) -> SplitResult:
    if not value or any(char.isspace() or ord(char) < 32 or char == "\\" for char in value):
        raise QuickshareError("Enter a valid Quickshare URL.")
    try:
        url: SplitResult = urlsplit(value)
        _ = url.port
    except ValueError as error:
        raise QuickshareError("Enter a valid Quickshare host and port.") from error
    if url.scheme not in {"http", "https"} or not url.hostname or url.username is not None:
        raise QuickshareError("Enter an HTTP or HTTPS URL without credentials.")
    if url.query or url.fragment:
        raise QuickshareError("Use the original Quickshare URL without a query or fragment.")
    return url


def _port(url: SplitResult) -> int:
    return url.port if url.port is not None else (443 if url.scheme == "https" else 80)


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


class QuickshareClient:
    """Use a single service origin for both publishing and importing."""

    def __init__(self, base_url: str) -> None:
        """Configure the HTTPS origin, or an HTTP loopback origin for local use."""
        url: SplitResult = _parse_url(base_url.strip())
        host: str = url.hostname or ""
        if url.path not in {"", "/"}:
            raise QuickshareError(f"Set {_URL_ENV} to the service origin without a path.")
        if url.scheme == "http" and not _is_loopback(host):
            raise QuickshareError("Use HTTPS for Quickshare outside localhost.")
        self._url: SplitResult = url
        self._host: str = host
        self._origin: str = url._replace(path="").geturl()

    @classmethod
    def from_env(cls) -> "QuickshareClient":
        """Load the service origin from the editor's environment."""
        origin: str = os.environ.get(_URL_ENV, "").strip()
        if not origin:
            raise QuickshareError(f"Set {_URL_ENV} to your Quickshare service URL and restart the editor.")
        return cls(origin)

    async def publish(self, snapshot: ShareSnapshot) -> str:
        """Return the short preview link after the service accepts the whole snapshot."""
        return await asyncio.to_thread(self._publish, snapshot)

    def _publish(self, snapshot: ShareSnapshot) -> str:
        try:
            body: bytes = snapshot.to_bytes()
        except ValueError as error:
            raise QuickshareError(str(error)) from error
        reply: bytes = self._request("POST", "/api/shares", body, _MAX_RECEIPT_BYTES)
        try:
            share_id: str = _Receipt.model_validate_json(reply).id
        except ValueError as error:
            raise QuickshareError("The service returned an invalid share ID.") from error
        if not is_share_id(share_id):
            raise QuickshareError("The service returned an invalid share ID.")
        return f"{self._origin}/s/{share_id}"

    async def fetch(self, link: str) -> ShareSnapshot:
        """Read a snapshot referenced by a preview link on this service."""
        url: SplitResult = _parse_url(link.strip())
        prefix: str = "/s/"
        share_id: str = url.path.removeprefix(prefix)
        if (url.scheme, url.hostname, _port(url)) != (self._url.scheme, self._host, _port(self._url)):
            raise QuickshareError("Use a link from the configured Quickshare service.")
        if not url.path.startswith(prefix) or not is_share_id(share_id):
            raise QuickshareError("Paste a Quickshare preview link ending in /s/<share-id>.")
        return await asyncio.to_thread(self._fetch, share_id)

    def _fetch(self, share_id: str) -> ShareSnapshot:
        body: bytes = self._request("GET", f"/api/shares/{share_id}", None, MAX_SNAPSHOT_BYTES)
        try:
            return ShareSnapshot.from_bytes(body)
        except ValueError as error:
            raise QuickshareError("The service returned an invalid or unsupported snapshot.") from error

    def _request(self, method: Literal["POST", "GET"], path: str, body: bytes | None, limit: int) -> bytes:
        connection_type = HTTPSConnection if self._url.scheme == "https" else HTTPConnection
        connection: HTTPConnection = connection_type(self._host, _port(self._url), timeout=_TIMEOUT_SECONDS)
        try:
            connection.request(
                method, path, body=body, headers={"Accept": "application/json", "Content-Type": "application/json"}
            )
            with connection.getresponse() as response:
                if response.status != (201 if method == "POST" else 200):
                    messages: dict[int, str] = {
                        404: "This Quickshare snapshot could not be found.",
                        413: "This snapshot exceeds the service's size limit.",
                        422: "The service rejected this snapshot.",
                        429: "Too many snapshots have been shared. Try again later.",
                    }
                    raise QuickshareError(messages.get(response.status, f"Quickshare returned HTTP {response.status}."))
                result: bytes = response.read(limit + 1)
                if len(result) > limit:
                    raise QuickshareError("The service response exceeds the size limit.")
                return result
        except (OSError, HTTPException) as error:
            raise QuickshareError("Could not reach the Quickshare service. Check its address and try again.") from error
        finally:
            connection.close()
