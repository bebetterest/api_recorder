from __future__ import annotations

import base64
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig


TEXTUAL_CONTENT_TYPES = (
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-www-form-urlencoded",
    "text/",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_textual_content_type(content_type: str | None) -> bool:
    if not content_type:
        return True
    lowered = content_type.lower()
    return lowered.startswith(TEXTUAL_CONTENT_TYPES) or "json" in lowered or "xml" in lowered


@dataclass
class CapturedBody:
    body: str
    encoding: str
    truncated: bool
    original_size: int


def capture_body(data: bytes, content_type: str | None, max_body_bytes: int) -> CapturedBody:
    limited = data[:max_body_bytes]
    truncated = len(data) > max_body_bytes
    if is_textual_content_type(content_type):
        body = limited.decode("utf-8", errors="replace")
        encoding = "utf-8"
    else:
        body = base64.b64encode(limited).decode("ascii")
        encoding = "base64"
    return CapturedBody(body=body, encoding=encoding, truncated=truncated, original_size=len(data))


def sanitize_headers(headers: dict[str, str], redact_headers: list[str]) -> dict[str, str]:
    hidden = {item.lower() for item in redact_headers}
    return {key: ("***" if key.lower() in hidden else value) for key, value in headers.items()}


class JsonlRecorder:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.output_dir = config.resolved_output_dir()
        self._lock = threading.Lock()

    def _target_file(self, started_at: datetime) -> Path:
        day_dir = self.output_dir / started_at.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir / "records.jsonl"

    def write_record(self, record: dict[str, Any]) -> Path:
        started_at = datetime.fromisoformat(record["started_at"])
        target_file = self._target_file(started_at)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self._lock:
            with target_file.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")
        return target_file

