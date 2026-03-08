from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api_recorder.app import create_app
from api_recorder.config import AppConfig, UpstreamConfig


def _build_config(tmp_path, **upstream_overrides) -> AppConfig:
    upstream = UpstreamConfig(
        name="mock",
        route_prefix="mock",
        base_url="https://mock.local",
        auth_env="UPSTREAM_SECRET",
        max_concurrency=upstream_overrides.pop("max_concurrency", 5),
        max_queue=upstream_overrides.pop("max_queue", 25),
        queue_timeout_ms=upstream_overrides.pop("queue_timeout_ms", 30000),
        **upstream_overrides,
    )
    return AppConfig(upstreams=[upstream]).attach_source(tmp_path / "config.toml")


def _read_records(config: AppConfig) -> list[dict]:
    files = sorted(config.resolved_output_dir().rglob("*.jsonl"))
    output: list[dict] = []
    for file_path in files:
        for line in file_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                output.append(json.loads(line))
    return output


@pytest.mark.asyncio
async def test_proxy_records_regular_and_streaming(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UPSTREAM_SECRET", "super-secret")

    upstream_app = FastAPI()

    @upstream_app.post("/echo")
    async def echo(request: Request):
        return JSONResponse(
            {
                "body": await request.json(),
                "auth": request.headers.get("authorization"),
            }
        )

    @upstream_app.get("/stream")
    async def stream():
        async def body():
            yield b"data: one\n\n"
            yield b"data: two\n\n"

        return StreamingResponse(body(), media_type="text/event-stream")

    config = _build_config(tmp_path)
    proxy_app = create_app(config, transport_provider=lambda _name: httpx.ASGITransport(app=upstream_app))

    transport = httpx.ASGITransport(app=proxy_app)
    async with proxy_app.router.lifespan_context(proxy_app):
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy.local") as client:
            response = await client.post(
                "/proxy/mock/echo?foo=bar",
                headers={"Authorization": "should-hide"},
                json={"message": "hello"},
            )
            assert response.status_code == 200
            assert response.json() == {
                "body": {"message": "hello"},
                "auth": "Bearer super-secret",
            }

            async with client.stream("GET", "/proxy/mock/stream") as stream_response:
                assert stream_response.status_code == 200
                body = await stream_response.aread()
            assert b"data: one" in body
            assert b"data: two" in body

    records = _read_records(config)
    assert len(records) == 2
    regular = next(record for record in records if record["path"] == "echo")
    streamed = next(record for record in records if record["path"] == "stream")
    assert regular["request_headers"]["authorization"] == "***"
    assert regular["target_url"] == "https://mock.local/echo?foo=bar"
    assert regular["success"] is True
    assert streamed["streamed"] is True
    assert streamed["response_body"].startswith("data: one")


@pytest.mark.asyncio
async def test_queue_limit_returns_429_and_records_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UPSTREAM_SECRET", "super-secret")
    started = asyncio.Event()
    release = asyncio.Event()

    upstream_app = FastAPI()

    @upstream_app.get("/wait")
    async def wait():
        started.set()
        await release.wait()
        return JSONResponse({"ok": True})

    config = _build_config(tmp_path, max_concurrency=1, max_queue=0, queue_timeout_ms=100)
    proxy_app = create_app(config, transport_provider=lambda _name: httpx.ASGITransport(app=upstream_app))

    transport = httpx.ASGITransport(app=proxy_app)
    async with proxy_app.router.lifespan_context(proxy_app):
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy.local") as client:
            first_request = asyncio.create_task(client.get("/proxy/mock/wait"))
            await started.wait()
            second_response = await client.get("/proxy/mock/wait")
            release.set()
            first_response = await first_request

    assert first_response.status_code == 200
    assert second_response.status_code == 429

    records = _read_records(config)
    assert any(record["error_kind"] == "queue_full" for record in records)
