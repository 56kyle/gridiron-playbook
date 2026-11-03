"""File size and encoding checks for the local playbook editor."""

from pathlib import Path

from gridiron_playbook.editor import PlaybookEditor
from gridiron_playbook.playbook import GridironPlaybook
from gridiron_playbook.playbook import json_to_playbook
from gridiron_playbook.playbook import playbook_to_sav
from gridiron_playbook.playbook import sav_to_playbook
from gridiron_playbook.quickshare.snapshot import ShareSnapshot


_MIB: int = 1024 * 1024
MAX_SAVE_BYTES: int = 64 * _MIB
MAX_JSON_BYTES: int = 16 * _MIB


class PlaybookFileError(ValueError):
    """The editor cannot accept a playbook file."""


def validate_upload_size(name: str, size: int) -> None:
    """Check the upload against its format's size limit before decoding."""
    suffix: str = Path(name).suffix.lower()
    if suffix == ".sav":
        limit: int = MAX_SAVE_BYTES
    elif suffix == ".json":
        limit = MAX_JSON_BYTES
    else:
        raise PlaybookFileError("Choose a .sav or .json playbook.")
    if size > limit:
        raise PlaybookFileError(f"Choose a {suffix} playbook up to {limit // _MIB} MiB.")


def validate_import_size(recipient: GridironPlaybook, snapshot: ShareSnapshot) -> None:
    """Check that the combined document can be downloaded and reopened before applying an import."""
    prospective = PlaybookEditor(recipient)
    _ = prospective.import_plays(snapshot.plays)
    try:
        size: int = len(playbook_to_sav(prospective.playbook))
    except ValueError as error:
        raise PlaybookFileError("The combined playbook could not be encoded as a .sav file.") from error
    if size > MAX_SAVE_BYTES:
        raise PlaybookFileError(f"The combined playbook exceeds the {MAX_SAVE_BYTES // _MIB} MiB .sav limit.")


def decode_uploaded_playbook(name: str, contents: bytes) -> GridironPlaybook:
    """Load a playbook and check that all its plays can be displayed on the field."""
    from gridiron_playbook.web.play_diagram import FieldTransform

    validate_upload_size(name, len(contents))
    suffix: str = Path(name).suffix.lower()
    document: GridironPlaybook = (
        sav_to_playbook(contents) if suffix == ".sav" else json_to_playbook(contents.decode("utf-8-sig"))
    )
    for play in document.root.properties.custom_plays:
        _ = FieldTransform.for_play(play)
    return document
