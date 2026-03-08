from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Callable

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .config import AppConfig, UpstreamConfig
from .rate_limit import QueueFullError, QueueTimeoutError, UpstreamConcurrencyGate
from .recorder import JsonlRecorder, capture_body, sanitize_headers, utcnow


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
}


def is_streaming_response(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    transfer_encoding = response.headers.get("transfer-encoding", "").lower()
    return "text/event-stream" in content_type or "chunked" in transfer_encoding


@dataclass
class ProxyRuntime:
    config: AppConfig
    transport_provider: Callable[[str], httpx.AsyncBaseTransport | None] | None = None

    def __post_init__(self) -> None:
        self.recorder = JsonlRecorder(self.config)
        self.limiters = {
            item.name: UpstreamConcurrencyGate(
                max_concurrency=item.max_concurrency,
                max_queue=item.max_queue,
                queue_timeout_ms=item.queue_timeout_ms,
            )
            for item in self.config.upstreams
        }
        self.upstreams_by_route = {item.route_prefix: item for item in self.config.upstreams}
        self.clients: dict[str, httpx.AsyncClient] = {}

    async def startup(self, host: str, port: int) -> None:
        for upstream in self.config.upstreams:
            transport = self.transport_provider(upstream.name) if self.transport_provider else None
            self.clients[upstream.name] = httpx.AsyncClient(
                timeout=httpx.Timeout(upstream.timeout_ms / 1000),
                transport=transport,
                trust_env=False,
            )

    async def shutdown(self) -> None:
        for client in self.clients.values():
            await client.aclose()

    def _build_target_url(self, upstream: UpstreamConfig, path: str, query: str) -> str:
        trimmed = path.lstrip("/")
        target = upstream.base_url
        if trimmed:
            target = f"{target}/{trimmed}"
        if query:
            target = f"{target}?{query}"
        return target

    def _forward_headers(self, request: Request, upstream: UpstreamConfig) -> dict[str, str]:
        headers = {key: value for key, value in request.headers.items() if key.lower() not in HOP_BY_HOP_HEADERS}
        for key, value in upstream.inject_headers.items():
            self._set_header(headers, key, value)
        if upstream.auth_env:
            secret = os.getenv(upstream.auth_env)
            if not secret:
                raise RuntimeError(f"missing_auth_env:{upstream.auth_env}")
            self._set_header(
                headers,
                upstream.auth_header,
                secret if not upstream.auth_scheme else f"{upstream.auth_scheme} {secret}"
            )
        return headers

    @staticmethod
    def _set_header(headers: dict[str, str], header_name: str, value: str) -> None:
        duplicates = [key for key in headers if key.lower() == header_name.lower()]
        for key in duplicates:
            headers.pop(key, None)
        headers[header_name] = value

    async def proxy(self, request: Request, route_prefix: str, path: str) -> Response:
        started_at = utcnow()
        upstream = self.upstreams_by_route.get(route_prefix)
        if upstream is None:
            return JSONResponse({"error": f"unknown upstream route: {route_prefix}"}, status_code=404)

        request_id = str(uuid.uuid4())
        limiter = self.limiters[upstream.name]
        raw_request_body = await request.body()
        request_capture = capture_body(
            raw_request_body,
            request.headers.get("content-type"),
            self.config.recording.max_body_bytes,
        )
        sanitized_request_headers = sanitize_headers(dict(request.headers.items()), self.config.recording.redact_headers)
        queue_wait_ms = 0.0
        target_url = self._build_target_url(upstream, path, request.url.query)

        try:
            async with limiter.slot() as acquisition:
                queue_wait_ms = acquisition.queue_wait_ms
                forwarded_headers = self._forward_headers(request, upstream)
                client = self.clients[upstream.name]
                upstream_request = client.build_request(
                    request.method,
                    target_url,
                    headers=forwarded_headers,
                    content=raw_request_body,
                )
                upstream_response = await client.send(upstream_request, stream=True)
                response_headers = {
                    key: value
                    for key, value in upstream_response.headers.items()
                    if key.lower() not in HOP_BY_HOP_HEADERS
                }
                sanitized_response_headers = sanitize_headers(response_headers, self.config.recording.redact_headers)
                if is_streaming_response(upstream_response):
                    chunks: list[bytes] = []

                    async def stream_generator():
                        nonlocal chunks
                        error_kind: str | None = None
                        try:
                            async for chunk in upstream_response.aiter_raw():
                                chunks.append(chunk)
                                yield chunk
                        except Exception:
                            error_kind = "stream_error"
                            raise
                        finally:
                            body_bytes = b"".join(chunks)
                            response_capture = capture_body(
                                body_bytes,
                                upstream_response.headers.get("content-type"),
                                self.config.recording.max_body_bytes,
                            )
                            finished_at = utcnow()
                            self.recorder.write_record(
                                {
                                    "record_id": request_id,
                                    "started_at": started_at.isoformat(),
                                    "finished_at": finished_at.isoformat(),
                                    "upstream_name": upstream.name,
                                    "route_prefix": upstream.route_prefix,
                                    "target_url": target_url,
                                    "method": request.method,
                                    "path": path,
                                    "query": request.url.query,
                                    "request_headers": sanitized_request_headers,
                                    "request_body": request_capture.body,
                                    "request_body_encoding": request_capture.encoding,
                                    "request_body_truncated": request_capture.truncated,
                                    "request_body_size": request_capture.original_size,
                                    "response_status": upstream_response.status_code,
                                    "response_headers": sanitized_response_headers,
                                    "response_body": response_capture.body,
                                    "response_body_encoding": response_capture.encoding,
                                    "response_body_truncated": response_capture.truncated,
                                    "response_body_size": response_capture.original_size,
                                    "duration_ms": (finished_at - started_at).total_seconds() * 1000,
                                    "queue_wait_ms": queue_wait_ms,
                                    "streamed": True,
                                    "success": error_kind is None and upstream_response.status_code < 400,
                                    "error_kind": error_kind,
                                }
                            )
                            await upstream_response.aclose()

                    return StreamingResponse(
                        stream_generator(),
                        status_code=upstream_response.status_code,
                        headers=response_headers,
                    )

                raw_response_body = await upstream_response.aread()
                response_capture = capture_body(
                    raw_response_body,
                    upstream_response.headers.get("content-type"),
                    self.config.recording.max_body_bytes,
                )
                finished_at = utcnow()
                self.recorder.write_record(
                    {
                        "record_id": request_id,
                        "started_at": started_at.isoformat(),
                        "finished_at": finished_at.isoformat(),
                        "upstream_name": upstream.name,
                        "route_prefix": upstream.route_prefix,
                        "target_url": target_url,
                        "method": request.method,
                        "path": path,
                        "query": request.url.query,
                        "request_headers": sanitized_request_headers,
                        "request_body": request_capture.body,
                        "request_body_encoding": request_capture.encoding,
                        "request_body_truncated": request_capture.truncated,
                        "request_body_size": request_capture.original_size,
                        "response_status": upstream_response.status_code,
                        "response_headers": sanitized_response_headers,
                        "response_body": response_capture.body,
                        "response_body_encoding": response_capture.encoding,
                        "response_body_truncated": response_capture.truncated,
                        "response_body_size": response_capture.original_size,
                        "duration_ms": (finished_at - started_at).total_seconds() * 1000,
                        "queue_wait_ms": queue_wait_ms,
                        "streamed": False,
                        "success": upstream_response.status_code < 400,
                        "error_kind": None,
                    }
                )
                return Response(
                    content=raw_response_body,
                    status_code=upstream_response.status_code,
                    headers=response_headers,
                    media_type=upstream_response.headers.get("content-type"),
                )
        except QueueFullError:
            finished_at = utcnow()
            self.recorder.write_record(
                {
                    "record_id": request_id,
                    "started_at": started_at.isoformat(),
                    "finished_at": finished_at.isoformat(),
                    "upstream_name": upstream.name,
                    "route_prefix": upstream.route_prefix,
                    "target_url": target_url,
                    "method": request.method,
                    "path": path,
                    "query": request.url.query,
                    "request_headers": sanitized_request_headers,
                    "request_body": request_capture.body,
                    "request_body_encoding": request_capture.encoding,
                    "request_body_truncated": request_capture.truncated,
                    "request_body_size": request_capture.original_size,
                    "response_status": 429,
                    "response_headers": {},
                    "response_body": "queue full",
                    "response_body_encoding": "utf-8",
                    "response_body_truncated": False,
                    "response_body_size": len("queue full"),
                    "duration_ms": (finished_at - started_at).total_seconds() * 1000,
                    "queue_wait_ms": 0.0,
                    "streamed": False,
                    "success": False,
                    "error_kind": "queue_full",
                }
            )
            return JSONResponse({"error": "queue full"}, status_code=429)
        except QueueTimeoutError:
            finished_at = utcnow()
            self.recorder.write_record(
                {
                    "record_id": request_id,
                    "started_at": started_at.isoformat(),
                    "finished_at": finished_at.isoformat(),
                    "upstream_name": upstream.name,
                    "route_prefix": upstream.route_prefix,
                    "target_url": target_url,
                    "method": request.method,
                    "path": path,
                    "query": request.url.query,
                    "request_headers": sanitized_request_headers,
                    "request_body": request_capture.body,
                    "request_body_encoding": request_capture.encoding,
                    "request_body_truncated": request_capture.truncated,
                    "request_body_size": request_capture.original_size,
                    "response_status": 429,
                    "response_headers": {},
                    "response_body": "queue timeout",
                    "response_body_encoding": "utf-8",
                    "response_body_truncated": False,
                    "response_body_size": len("queue timeout"),
                    "duration_ms": (finished_at - started_at).total_seconds() * 1000,
                    "queue_wait_ms": queue_wait_ms,
                    "streamed": False,
                    "success": False,
                    "error_kind": "queue_timeout",
                }
            )
            return JSONResponse({"error": "queue timeout"}, status_code=429)
        except RuntimeError as exc:
            error_kind = "missing_auth_env" if str(exc).startswith("missing_auth_env:") else "proxy_error"
            message = str(exc).split(":", 1)[-1] if error_kind == "missing_auth_env" else str(exc)
            finished_at = utcnow()
            self.recorder.write_record(
                {
                    "record_id": request_id,
                    "started_at": started_at.isoformat(),
                    "finished_at": finished_at.isoformat(),
                    "upstream_name": upstream.name,
                    "route_prefix": upstream.route_prefix,
                    "target_url": target_url,
                    "method": request.method,
                    "path": path,
                    "query": request.url.query,
                    "request_headers": sanitized_request_headers,
                    "request_body": request_capture.body,
                    "request_body_encoding": request_capture.encoding,
                    "request_body_truncated": request_capture.truncated,
                    "request_body_size": request_capture.original_size,
                    "response_status": 502 if error_kind == "proxy_error" else 500,
                    "response_headers": {},
                    "response_body": message,
                    "response_body_encoding": "utf-8",
                    "response_body_truncated": False,
                    "response_body_size": len(message),
                    "duration_ms": (finished_at - started_at).total_seconds() * 1000,
                    "queue_wait_ms": queue_wait_ms,
                    "streamed": False,
                    "success": False,
                    "error_kind": error_kind,
                }
            )
            return JSONResponse({"error": message}, status_code=500 if error_kind == "missing_auth_env" else 502)
        except httpx.HTTPError as exc:
            finished_at = utcnow()
            message = str(exc)
            self.recorder.write_record(
                {
                    "record_id": request_id,
                    "started_at": started_at.isoformat(),
                    "finished_at": finished_at.isoformat(),
                    "upstream_name": upstream.name,
                    "route_prefix": upstream.route_prefix,
                    "target_url": target_url,
                    "method": request.method,
                    "path": path,
                    "query": request.url.query,
                    "request_headers": sanitized_request_headers,
                    "request_body": request_capture.body,
                    "request_body_encoding": request_capture.encoding,
                    "request_body_truncated": request_capture.truncated,
                    "request_body_size": request_capture.original_size,
                    "response_status": 502,
                    "response_headers": {},
                    "response_body": message,
                    "response_body_encoding": "utf-8",
                    "response_body_truncated": False,
                    "response_body_size": len(message),
                    "duration_ms": (finished_at - started_at).total_seconds() * 1000,
                    "queue_wait_ms": queue_wait_ms,
                    "streamed": False,
                    "success": False,
                    "error_kind": "upstream_http_error",
                }
            )
            return JSONResponse({"error": message}, status_code=502)


def create_app(
    config: AppConfig,
    *,
    host: str | None = None,
    port: int | None = None,
    transport_provider: Callable[[str], httpx.AsyncBaseTransport | None] | None = None,
) -> FastAPI:
    runtime = ProxyRuntime(config=config, transport_provider=transport_provider)
    bind_host = host or config.server.host
    bind_port = port or config.server.port

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await runtime.startup(bind_host, bind_port)
        try:
            yield
        finally:
            await runtime.shutdown()

    app = FastAPI(title="api_recorder", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "upstreams": len(config.upstreams)}

    @app.api_route("/proxy/{route_prefix}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    @app.api_route(
        "/proxy/{route_prefix}/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    )
    async def proxy(request: Request, route_prefix: str, path: str = "") -> Response:
        return await runtime.proxy(request, route_prefix, path)

    return app
