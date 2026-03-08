from __future__ import annotations

import json
from datetime import datetime, timezone

from typer.testing import CliRunner

from api_recorder.cli import app


runner = CliRunner()


def _write_record(directory, record: dict) -> None:
    day_dir = directory / datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    with (day_dir / "records.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False))
        handle.write("\n")


def test_init_and_upstream_commands(tmp_path) -> None:
    config_path = tmp_path / "config.toml"

    result = runner.invoke(app, ["--lang", "zh", "--config", str(config_path), "init"])
    assert result.exit_code == 0, result.output
    assert "默认配置" in result.output
    assert config_path.exists()

    result = runner.invoke(
        app,
        [
            "--config",
            str(config_path),
            "upstream",
            "add",
            "--name",
            "openai",
            "--route-prefix",
            "openai",
            "--base-url",
            "https://api.openai.com/v1",
            "--auth-env",
            "OPENAI_API_KEY",
            "--max-concurrency",
            "3",
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["--config", str(config_path), "upstream", "list"])
    assert result.exit_code == 0, result.output
    assert '"name": "openai"' in result.output
    assert '"max_concurrency": 3' in result.output


def test_help_switches_with_lang_flag() -> None:
    result = runner.invoke(app, ["--lang", "zh", "init", "--help"])
    assert result.exit_code == 0, result.output
    assert "创建默认 config.toml" in result.output


def test_stats_summary_and_export(tmp_path) -> None:
    config_path = tmp_path / "config.toml"

    result = runner.invoke(app, ["--config", str(config_path), "init"])
    assert result.exit_code == 0, result.output

    records_dir = tmp_path / "data" / "records"
    sample_records = [
        {
            "record_id": "1",
            "started_at": "2026-03-08T10:00:00+00:00",
            "finished_at": "2026-03-08T10:00:00.100000+00:00",
            "upstream_name": "openai",
            "success": True,
            "duration_ms": 100.0,
            "streamed": False,
        },
        {
            "record_id": "2",
            "started_at": "2026-03-08T10:05:00+00:00",
            "finished_at": "2026-03-08T10:05:00.400000+00:00",
            "upstream_name": "anthropic",
            "success": False,
            "duration_ms": 400.0,
            "streamed": True,
        },
    ]
    for record in sample_records:
        _write_record(records_dir, record)

    result = runner.invoke(app, ["--config", str(config_path), "stats", "summary"])
    assert result.exit_code == 0, result.output
    assert "Total requests: 2" in result.output
    assert "Successful requests: 1" in result.output
    assert "Streamed requests: 1" in result.output

    export_path = tmp_path / "exports" / "records.jsonl"
    result = runner.invoke(
        app,
        [
            "--config",
            str(config_path),
            "export",
            "--output",
            str(export_path),
            "--upstream",
            "openai",
        ],
    )
    assert result.exit_code == 0, result.output
    exported_lines = export_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(exported_lines) == 1
    assert json.loads(exported_lines[0])["upstream_name"] == "openai"
