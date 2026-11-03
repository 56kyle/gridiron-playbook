from base64 import urlsafe_b64decode

import pytest

from gridiron_playbook.play import GridironPlay
from gridiron_playbook.quickshare.codec import encode_share
from gridiron_playbook.quickshare.links import decode_link
from gridiron_playbook.quickshare.links import make_link
from gridiron_playbook.quickshare.links import warning_level
from gridiron_playbook.quickshare.snapshot import ShareSnapshot


_BAD_LINK = "Quickshare"


@pytest.fixture
def single_play() -> ShareSnapshot:
    play = GridironPlay(FormationName_0="Spread", PlayName_0="Drag", Routes_0=())
    return ShareSnapshot(version=1, kind="play", plays=(play,))


def test_decode_link_without_network(single_play: ShareSnapshot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRIDIRON_QUICKSHARE_URL", raising=False)
    viewer: str = "https://offline.invalid/subsite/"
    link: str = make_link(viewer, encode_share(single_play))
    assert link.startswith(viewer + "#v1/")
    assert decode_link(link) == single_play


@pytest.mark.parametrize(
    ("characters", "warning"), [(1999, None), (2000, None), (2001, "standard"), (4000, "standard"), (4001, "nitro")]
)
def test_warning_level_for_entire_url(single_play: ShareSnapshot, characters: int, warning: str | None) -> None:
    encoded: bytes = encode_share(single_play)
    viewer: str = "https://playbook.example/"
    extra: int = characters - len(make_link(viewer, encoded))
    link = make_link(viewer + "a" * (extra - 1) + "/", encoded)
    assert len(link) == characters
    assert warning_level(len(link)) == warning
    assert decode_link(link) == single_play


@pytest.mark.parametrize(
    "link",
    [
        "https://viewer.example/s/legacy-id",
        "https://viewer.example/#v2/abc",
        "https://viewer.example/#v1/",
        "https://viewer.example/#v1/a%20b",
        "https://viewer.example/#v1/not+a+portable+payload",
    ],
)
def test_decode_link_with_invalid_fragment(link: str) -> None:
    with pytest.raises(ValueError, match=_BAD_LINK):
        _ = decode_link(link)


@pytest.mark.parametrize(
    ("payload", "altered_tail", "play_name"),
    [
        ("eNpzDwxmZGBkCy4oSk1MYWRgcSlKTGcAADNFBNY", "Z", "Drag"),
        ("eNpzDwxmZGBkCy4oSk1MYWRgcylKTC9WZAAAPpwFbA", "B", "Drags!"),
    ],
    ids=["two-unused-bits", "four-unused-bits"],
)
def test_decode_link_rejects_nonzero_padding_bits(payload: str, altered_tail: str, play_name: str) -> None:
    base: str = "https://viewer.example/#v1/"
    altered: str = payload[:-1] + altered_tail
    assert decode_link(base + payload).plays[0].play_name == play_name
    assert urlsafe_b64decode(payload + "==") == urlsafe_b64decode(altered + "==")
    with pytest.raises(ValueError, match=_BAD_LINK):
        _ = decode_link(base + altered)
