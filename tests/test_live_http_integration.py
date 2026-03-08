from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

from api_recorder.config import AppConfig, ConfigManager, ServerConfig, UpstreamConfig
from tests.support import LiveProcessServer, pick_free_port, read_records


LIVE_TEST_ENV = "API_RECORDER_RUN_LIVE_TESTS"


def test_live_http_proxy_round_trip(tmp_path, monkeypatch) -> None:
    if os.getenv(LIVE_TEST_ENV) != "1":
        pytest.skip(f"set {LIVE_TEST_ENV}=1 to run live localhost integration tests")

    monkeypatch.setenv("FAKE_UPSTREAM_KEY", "live-secret")
    upstream_port = pick_free_port()
    proxy_port = pick_free_port()
    config_path = tmp_path / "config.toml"
    repo_root = Path(__file__).resolve().parents[1]

    config = AppConfig(
        server=ServerConfig(port=proxy_port),
        upstreams=[
            UpstreamConfig(
                name="fakeai",
                route_prefix="fakeai",
                base_url=f"http://127.0.0.1:{upstream_port}/v1",
                auth_env="FAKE_UPSTREAM_KEY",
                inject_headers={"X-Proxy-Marker": "live"},
                timeout_ms=5_000,
                max_concurrency=2,
                max_queue=4,
                queue_timeout_ms=2_000,
            )
        ],
    ).attach_source(config_path)
    ConfigManager(config_path).save(config)

    upstream_server = LiveProcessServer(
        command=[
            sys.executable,
            "-m",
            "uvicorn",
            "examples.fake_upstream:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(upstream_port),
            "--log-level",
            "warning",
        ],
        cwd=repo_root,
        health_url=f"http://127.0.0.1:{upstream_port}/health",
    )
    proxy_server = LiveProcessServer(
        command=[
            sys.executable,
            "-m",
            "api_recorder",
            "--config",
            str(config_path),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(proxy_port),
        ],
        cwd=repo_root,
        health_url=f"http://127.0.0.1:{proxy_port}/health",
        env={"FAKE_UPSTREAM_KEY": "live-secret"},
    )

    upstream_server.start()
    proxy_server.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{proxy_port}", timeout=5.0, trust_env=False) as client:
            models_response = client.get("/proxy/fakeai/models")
            assert models_response.status_code == 200
            assert models_response.json()["data"][0]["id"] == "fake-chat-model"

            chat_response = client.post(
                "/proxy/fakeai/chat/completions?trace_id=live-001",
                headers={
                    "Authorization": "client-visible-only-to-recorder",
                    "X-Client-Trace": "live-trace-001",
                },
                json={
                    "model": "fake-chat-model",
                    "messages": [{"role": "user", "content": "live http integration"}],
                },
            )
            assert chat_response.status_code == 200
            body = chat_response.json()
            assert body["auth_header"] == "Bearer live-secret"
            assert body["proxy_marker"] == "live"
            assert body["query"] == {"trace_id": "live-001"}

            with client.stream("GET", "/proxy/fakeai/stream") as stream_response:
                assert stream_response.status_code == 200
                stream_body = b"".join(stream_response.iter_bytes())
            assert b"data: [DONE]" in stream_body

            binary_response = client.get("/proxy/fakeai/binary")
            assert binary_response.status_code == 200
            assert binary_response.content == b"FAKE-BINARY-\x00\x01"
    finally:
        proxy_server.stop()
        upstream_server.stop()

    records = read_records(config)
    assert len(records) == 4

    chat_record = next(record for record in records if record["path"] == "chat/completions")
    stream_record = next(record for record in records if record["path"] == "stream")
    binary_record = next(record for record in records if record["path"] == "binary")

    assert chat_record["target_url"] == f"http://127.0.0.1:{upstream_port}/v1/chat/completions?trace_id=live-001"
    assert chat_record["request_headers"]["authorization"] == "***"
    assert json.loads(chat_record["response_body"])["auth_header"] == "Bearer live-secret"
    assert stream_record["streamed"] is True
    assert base64.b64decode(binary_record["response_body"]) == b"FAKE-BINARY-\x00\x01"
