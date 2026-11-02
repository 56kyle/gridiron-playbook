import subprocess
import sys
from pathlib import Path

import gridiron_playbook


def test_import_playbook_from_package_directory() -> None:
    package_directory: Path = Path(gridiron_playbook.__file__).parent
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [
            sys.executable,
            "-c",
            "import gridiron_playbook.playbook; from gridiron_playbook.save import json_to_sav, sav_to_json",
        ],
        cwd=package_directory,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
