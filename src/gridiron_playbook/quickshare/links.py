"""Build and read portable Quickshare links without contacting the viewer."""

import base64
import os
import re
from ipaddress import IPv6Address
from ipaddress import ip_address
from typing import Literal
from urllib.parse import quote
from urllib.parse import urlsplit

from gridiron_playbook.quickshare.codec import MAX_SHARE_BYTES
from gridiron_playbook.quickshare.codec import decode_share
from gridiron_playbook.quickshare.snapshot import ShareSnapshot


_FRAGMENT = "#v1/"
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+")
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_STANDARD_LIMIT = 2_000
_NITRO_LIMIT = 4_000
_MAX_VIEWER_CHARS = 8_192
_MAX_TOKEN_CHARS = (4 * MAX_SHARE_BYTES + 2) // 3
MAX_LINK_CHARS = _MAX_VIEWER_CHARS + len(_FRAGMENT) + _MAX_TOKEN_CHARS


def warning_level(length: int) -> Literal["standard", "nitro"] | None:
    """Classify the length of the complete URL for Discord's message limits."""
    if length > _NITRO_LIMIT:
        return "nitro"
    if length > _STANDARD_LIMIT:
        return "standard"
    return None


def _viewer_url(value: str) -> str:
    """Return an ASCII viewer URL so its length matches the text copied to chat."""
    if any(ord(char) < 32 for char in value) or any(char in value for char in "\\?#"):
        raise ValueError("Use a viewer URL without a query or fragment.")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None:
        raise ValueError("Use an HTTP or HTTPS viewer URL without credentials.")
    host: str = parsed.hostname.encode("idna").decode("ascii").lower()
    if ":" in host:
        authority: str = f"[{IPv6Address(host)}]"
    elif re.fullmatch(r"[a-z0-9_.-]+", host):
        authority = host
    else:
        raise ValueError("Invalid Quickshare viewer hostname.")
    if parsed.scheme == "http" and host != "localhost":
        try:
            loopback: bool = ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise ValueError("Use HTTPS for a Quickshare viewer outside localhost.")
    if parsed.port is not None and parsed.port != (443 if parsed.scheme == "https" else 80):
        authority += f":{parsed.port}"
    path: str = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    result: str = f"{parsed.scheme}://{authority}{path}"
    if len(result) > _MAX_VIEWER_CHARS:
        raise ValueError("The Quickshare viewer address is too long.")
    return result


def viewer_url_from_env() -> str:
    """Read the address of the static viewer used for new links."""
    value: str = os.environ.get("GRIDIRON_QUICKSHARE_URL", "").strip()
    if not value:
        raise ValueError("Set GRIDIRON_QUICKSHARE_URL to your viewer address to copy a link.")
    return _viewer_url(value)


def make_link(viewer_url: str, data: bytes) -> str:
    """Embed the complete encoded share in the viewer's URL fragment."""
    if not 0 < len(data) <= MAX_SHARE_BYTES:
        raise ValueError("Invalid Quickshare payload size.")
    payload: str = base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
    return f"{_viewer_url(viewer_url)}{_FRAGMENT}{payload}"


def decode_link(link: str) -> ShareSnapshot:
    """Decode the fragment locally, including links from other static viewer hosts."""
    if len(link) > MAX_LINK_CHARS:
        raise ValueError("The Quickshare link exceeds the size limit.")
    base, marker, payload = link.strip().partition(_FRAGMENT)
    if not marker:
        raise ValueError("Paste a Quickshare link containing a #v1/ fragment.")
    _ = _viewer_url(base)
    if len(payload) > _MAX_TOKEN_CHARS:
        raise ValueError("The Quickshare link exceeds the size limit.")
    if not _BASE64URL.fullmatch(payload) or len(payload) % 4 == 1:
        raise ValueError("The Quickshare link contains invalid encoded data.")
    unused_bits: int = (6 * len(payload)) % 8
    if _ALPHABET.index(payload[-1]) & ((1 << unused_bits) - 1):
        raise ValueError("The Quickshare link contains nonzero padding bits.")
    data: bytes = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    return decode_share(data)
