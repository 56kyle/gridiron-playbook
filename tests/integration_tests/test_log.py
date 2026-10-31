from pathlib import Path

from pydantic import TypeAdapter
from typing_extensions import TypedDict

from gridiron_playbook.constants import APP_START_TIME
from gridiron_playbook.constants import FILE_SAFE_DATETIME_FORMAT


class LogLevel(TypedDict):
    name: str


class LogRecord(TypedDict):
    message: str
    level: LogLevel


class LogEntry(TypedDict):
    record: LogRecord


def test_log_path_with_configured_directory(temporary_log_path: Path, tmp_path: Path) -> None:
    timestamp: str = APP_START_TIME.strftime(FILE_SAFE_DATETIME_FORMAT)

    assert temporary_log_path == tmp_path / f"log_{timestamp}.log"


def test_log_record_with_json_serialization(temporary_log_path: Path) -> None:
    adapter: TypeAdapter[LogEntry] = TypeAdapter(LogEntry)
    entry: LogEntry = adapter.validate_json(temporary_log_path.read_text(encoding="utf-8"))

    assert (entry["record"]["message"], entry["record"]["level"]["name"]) == ("logging contract", "INFO")
