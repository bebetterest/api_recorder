from __future__ import annotations

import base64
import json

import httpx
import pytest
from typer.testing import CliRunner

from api_recorder.app import create_app
from api_recorder.cli import app as cli_app
from api_recorder.config import AppConfig, ConfigManager, UpstreamConfig
from api_recorder.stats import build_summary
from examples.fake_upstream import create_fake_upstream_app
from tests.support import read_records


runner = CliRunner()


@pytest.mark.asyncio
async def test_fake_upstream_round_trip_and_record_validation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_UPSTREAM_KEY", "demo-secret")

    config_path = tmp_path / "config.toml"
    config = AppConfig(
        upstreams=[
            UpstreamConfig(
                name="fakeai",
                route_prefix="fakeai",
                base_url="https://fake.local/v1",
                auth_env="FAKE_UPSTREAM_KEY",
                inject_headers={"X-Proxy-Marker": "enabled"},
                timeout_ms=5_000,
                max_concurrency=2,
                max_queue=4,
                queue_timeout_ms=2_000,
            )
        ]
    ).attach_source(config_path)
    ConfigManager(config_path).save(config)

    upstream_app = create_fake_upstream_app()
    proxy_app = create_app(config, transport_provider=lambda _name: httpx.ASGITransport(app=upstream_app))

    transport = httpx.ASGITransport(app=proxy_app)
    async with proxy_app.router.lifespan_context(proxy_app):
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy.local") as client:
            models_response = await client.get("/proxy/fakeai/models")
            assert models_response.status_code == 200
            assert models_response.json()["data"][0]["id"] == "fake-chat-model"

            chat_response = await client.post(
                "/proxy/fakeai/chat/completions?trace_id=req-123",
                headers={
                    "Authorization": "client-should-be-hidden",
                    "X-Client-Trace": "client-trace-001",
                },
                json={
                    "model": "fake-chat-model",
                    "messages": [{"role": "user", "content": "hello fake upstream"}],
                },
            )
            assert chat_response.status_code == 200
            assert chat_response.json()["auth_header"] == "Bearer demo-secret"
            assert chat_response.json()["proxy_marker"] == "enabled"
            assert chat_response.json()["client_trace"] == "client-trace-001"
            assert chat_response.json()["query"] == {"trace_id": "req-123"}

            async with client.stream("GET", "/proxy/fakeai/stream") as stream_response:
                assert stream_response.status_code == 200
                stream_body = await stream_response.aread()
            assert b'{"index":0,"delta":"hello"}' in stream_body
            assert b"data: [DONE]" in stream_body

            binary_response = await client.get("/proxy/fakeai/binary")
            assert binary_response.status_code == 200
            assert binary_response.content == b"FAKE-BINARY-\x00\x01"

    records = read_records(config)
    assert len(records) == 4

    chat_record = next(record for record in records if record["path"] == "chat/completions")
    stream_record = next(record for record in records if record["path"] == "stream")
    binary_record = next(record for record in records if record["path"] == "binary")

    assert chat_record["target_url"] == "https://fake.local/v1/chat/completions?trace_id=req-123"
    assert chat_record["request_headers"]["authorization"] == "***"
    assert chat_record["request_headers"]["x-client-trace"] == "client-trace-001"
    assert json.loads(chat_record["request_body"])["messages"][0]["content"] == "hello fake upstream"
    assert json.loads(chat_record["response_body"])["auth_header"] == "Bearer demo-secret"
    assert chat_record["success"] is True
    assert chat_record["streamed"] is False

    assert stream_record["streamed"] is True
    assert "data: [DONE]" in stream_record["response_body"]
    assert stream_record["response_status"] == 200

    assert binary_record["response_body_encoding"] == "base64"
    assert base64.b64decode(binary_record["response_body"]) == b"FAKE-BINARY-\x00\x01"
    assert binary_record["response_headers"]["content-type"] == "application/octet-stream"

    summary = build_summary(records)
    assert summary.total_requests == 4
    assert summary.successful_requests == 4
    assert summary.streamed_requests == 1

    stats_result = runner.invoke(cli_app, ["--config", str(config_path), "stats", "summary"])
    assert stats_result.exit_code == 0, stats_result.output
    assert "Total requests: 4" in stats_result.output
    assert "Successful requests: 4" in stats_result.output
    assert "Streamed requests: 1" in stats_result.output

    export_path = tmp_path / "exports" / "fakeai.jsonl"
    export_result = runner.invoke(
        cli_app,
        [
            "--config",
            str(config_path),
            "export",
            "--upstream",
            "fakeai",
            "--output",
            str(export_path),
        ],
    )
    assert export_result.exit_code == 0, export_result.output
    exported_lines = export_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(exported_lines) == 4
