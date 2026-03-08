from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse


def create_fake_upstream_app() -> FastAPI:
    app = FastAPI(title="api_recorder fake upstream", version="1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def list_models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {"id": "fake-chat-model", "object": "model"},
                {"id": "fake-embedding-model", "object": "model"},
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> JSONResponse:
        payload = await request.json()
        return JSONResponse(
            {
                "object": "chat.completion",
                "model": payload.get("model", "fake-chat-model"),
                "received_messages": payload.get("messages", []),
                "auth_header": request.headers.get("authorization"),
                "proxy_marker": request.headers.get("x-proxy-marker"),
                "client_trace": request.headers.get("x-client-trace"),
                "query": dict(request.query_params),
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 7,
                    "total_tokens": 19,
                },
            }
        )

    @app.get("/v1/stream")
    async def stream() -> StreamingResponse:
        async def events():
            yield b'data: {"index":0,"delta":"hello"}\n\n'
            yield b'data: {"index":1,"delta":"world"}\n\n'
            yield b"data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/v1/binary")
    async def binary() -> Response:
        return Response(content=b"FAKE-BINARY-\x00\x01", media_type="application/octet-stream")

    return app


app = create_fake_upstream_app()

