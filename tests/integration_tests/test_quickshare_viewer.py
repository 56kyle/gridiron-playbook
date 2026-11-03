import re
from pathlib import Path

import pytest

from gridiron_playbook.quickshare.__main__ import main
from gridiron_playbook.quickshare.preview import export_viewer


def test_main_with_export(tmp_path: Path) -> None:
    destination = tmp_path / "hosting" / "quickshare"
    main(export=destination)
    html: str = (destination / "index.html").read_text(encoding="utf-8")
    resources: list[str] = re.findall(r"""<(?:script|link)\b[^>]*?\b(?:src|href)=["']([^"']+)["']""", html)
    assert resources
    assert all(not resource.startswith("/") and ":" not in resource for resource in resources)
    assert all((destination / resource).is_file() for resource in resources)
    assert (destination / "decode.js").is_file()


def test_export_viewer_preserves_existing_files(tmp_path: Path) -> None:
    existing = tmp_path / "index.html"
    _ = existing.write_text("Existing site", encoding="utf-8")
    with pytest.raises(FileExistsError):
        export_viewer(tmp_path)
    assert existing.read_text(encoding="utf-8") == "Existing site"
