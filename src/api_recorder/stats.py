from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from pathlib import Path
from typing import Iterable

from .config import AppConfig


def parse_iso8601(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)


def iter_record_files(config: AppConfig) -> Iterable[Path]:
    output_dir = config.resolved_output_dir()
    if not output_dir.exists():
        return []
    return sorted(output_dir.rglob("*.jsonl"))


def iter_records(config: AppConfig) -> Iterable[dict]:
    for file_path in iter_record_files(config):
        with file_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    yield json.loads(stripped)


@dataclass
class RecordFilter:
    since: datetime | None = None
    until: datetime | None = None
    upstream: str | None = None

    def matches(self, record: dict) -> bool:
        started_at = parse_iso8601(record["started_at"])
        if self.since and started_at and started_at < self.since:
            return False
        if self.until and started_at and started_at > self.until:
            return False
        if self.upstream and record.get("upstream_name") != self.upstream:
            return False
        return True


@dataclass
class SummaryMetrics:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    average_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    streamed_requests: int = 0


def build_summary(records: Iterable[dict]) -> SummaryMetrics:
    latencies: list[float] = []
    success = 0
    failure = 0
    streamed = 0
    total = 0
    for record in records:
        total += 1
        if record.get("success"):
            success += 1
        else:
            failure += 1
        if record.get("streamed"):
            streamed += 1
        duration = record.get("duration_ms")
        if isinstance(duration, (int, float)):
            latencies.append(float(duration))
    average = sum(latencies) / len(latencies) if latencies else 0.0
    p95 = 0.0
    if latencies:
        ordered = sorted(latencies)
        index = max(0, ceil(len(ordered) * 0.95) - 1)
        p95 = ordered[index]
    return SummaryMetrics(
        total_requests=total,
        successful_requests=success,
        failed_requests=failure,
        average_latency_ms=average,
        p95_latency_ms=p95,
        streamed_requests=streamed,
    )


def group_by_upstream(records: Iterable[dict]) -> dict[str, SummaryMetrics]:
    grouped: dict[str, list[dict]] = {}
    for record in records:
        grouped.setdefault(record.get("upstream_name", "unknown"), []).append(record)
    return {key: build_summary(value) for key, value in grouped.items()}

