# Architecture

## Goal

`api_recorder` is a local-first proxy layer for AI tooling. The service forwards HTTP traffic to configured upstream APIs, records complete request and response metadata and bodies, and provides CLI-level management for config, lifecycle, stats, and export.

## Core design

- Runtime stack: FastAPI + Uvicorn + HTTPX + Typer + Pydantic
- Config source of truth: TOML file
- Storage: daily JSONL shards under the configured output directory
- Routing: `/proxy/<route_prefix>/...`
- Each upstream can point at a different vendor or relay base URL; for example, `/proxy/gemini/...` can forward to a Gemini relay rooted at `/v1beta`.
- Limits: per-upstream concurrency gate with bounded queue
- Outbound upstream HTTP clients run with `trust_env=False`, so system proxy environment variables do not rewrite proxy-to-upstream traffic.
- Localization: English and Chinese CLI output

## Main modules

- `src/api_recorder/config.py`
  - Defines validated config models and TOML load/save behavior.
  - Resolves relative paths against the config file directory.
- `src/api_recorder/app.py`
  - Builds the FastAPI app, shared upstream clients, and proxy behavior.
  - Handles ordinary and streaming responses and writes raw records.
- `src/api_recorder/rate_limit.py`
  - Implements per-upstream concurrency and queue control.
- `src/api_recorder/recorder.py`
  - Captures bodies, redacts headers, and appends JSONL records.
- `src/api_recorder/cli.py`
  - Exposes `init`, config commands, upstream commands, service lifecycle, stats, and export.
- `src/api_recorder/service.py`
  - Manages background process spawning, PID/state files, readiness checks, and stop behavior.
- `src/api_recorder/stats.py`
  - Scans JSONL records and computes summary metrics and upstream groupings.

## Request flow

1. CLI or a caller loads `config.toml`.
2. Requests arrive at `/proxy/<route_prefix>/...`.
3. The route prefix selects an upstream definition.
4. The upstream gate enforces concurrency and queue rules.
5. The proxy forwards the request with injected auth and static headers.
6. The response is streamed or buffered back to the caller.
7. A single JSONL record is written when the request finishes or fails.

## Recording model

Each record is self-contained and includes:

- request identity: `record_id`, `started_at`, `finished_at`
- target metadata: `upstream_name`, `route_prefix`, `target_url`
- HTTP context: `method`, `path`, `query`
- sanitized request/response headers
- captured request/response bodies with encoding, size, and truncation flags
- metrics: `duration_ms`, `queue_wait_ms`
- status: `response_status`, `streamed`, `success`, `error_kind`

## Background lifecycle model

- `serve` runs the proxy in the foreground.
- `start` spawns a background Python process and waits for `/health` to become reachable before writing `service.json`.
- `status` reads `service.json` and validates the PID is still alive.
- `stop` sends `SIGTERM`, waits for the process to exit, and removes the state file.

## Known limits in v1

- No vendor-specific protocol adaptation yet; routing is generic HTTP only.
- No UI and no built-in local auth.
- Linux and Windows compatibility is a code-level goal; first hands-on verification is on macOS.
