# api_recorder

`api_recorder` is a local HTTP proxy for AI and agent tooling. It forwards requests to configured upstream APIs, records raw request and response data, applies per-upstream concurrency limits, and exposes a CLI for service management, stats, and export.

Chinese documentation is available in [README_cn.md](README_cn.md).

## Current scope

- Generic HTTP proxying with route-prefix mapping: `/proxy/<route_prefix>/...`
- Full request and response recording to daily JSONL files
- Per-upstream concurrency limit, bounded queue, and queue timeout
- Foreground `serve` mode and background `start/stop/status`
- CLI config management, traffic stats, and raw JSONL export
- English and Chinese CLI output switching via `--lang` or `API_RECORDER_LANG`

## Environment

The project is designed to be developed in the conda environment named `api_recorder`.

```bash
conda env create -f environment.yml
conda activate api_recorder
```

Install updates after changes:

```bash
python -m pip install -e .[dev]
```

## Quick start

Initialize a default config:

```bash
api-recorder init
```

Add an upstream:

```bash
api-recorder upstream add \
  --name openai \
  --route-prefix openai \
  --base-url https://api.openai.com/v1 \
  --auth-env OPENAI_API_KEY \
  --max-concurrency 5 \
  --max-queue 25 \
  --queue-timeout-ms 30000
```

Run in the foreground:

```bash
api-recorder serve
```

Start as a background process:

```bash
api-recorder start
api-recorder status
api-recorder stop
```

Proxy traffic through the configured route:

```bash
curl http://127.0.0.1:8000/proxy/openai/chat/completions
```

### Example: call Gemini through a relay upstream

If Gemini is exposed through a relay base URL, add it as its own upstream:

```bash
export GEMINI_API_KEY=your-secret

api-recorder upstream add \
  --name gemini \
  --route-prefix gemini \
  --base-url https://your-gemini-relay.example/v1beta \
  --auth-env GEMINI_API_KEY
```

Then call the local proxy with the Gemini path appended after `/proxy/gemini/`:

```bash
curl \
  -X POST 'http://127.0.0.1:8000/proxy/gemini/models/gemini-2.0-flash:generateContent' \
  -H 'Content-Type: application/json' \
  -d '{
    "contents": [
      {
        "parts": [
          { "text": "Hello" }
        ]
      }
    ]
  }'
```

That request is forwarded to:

```text
https://your-gemini-relay.example/v1beta/models/gemini-2.0-flash:generateContent
```

## Full local walkthrough

This repository includes a bundled fake upstream app at [examples/fake_upstream.py](examples/fake_upstream.py), which is useful for validating the proxy end to end without calling a real vendor API.

### 1. Start the fake upstream

From the repository root:

```bash
conda activate api_recorder
python -m uvicorn examples.fake_upstream:app --host 127.0.0.1 --port 9101
```

The fake upstream exposes:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `GET /v1/stream`
- `GET /v1/binary`

### 2. Configure `api_recorder`

In another terminal:

```bash
conda activate api_recorder
export FAKE_UPSTREAM_KEY=demo-secret

api-recorder init
api-recorder upstream add \
  --name fakeai \
  --route-prefix fakeai \
  --base-url http://127.0.0.1:9101/v1 \
  --auth-env FAKE_UPSTREAM_KEY \
  --header X-Proxy-Marker=enabled \
  --max-concurrency 2 \
  --max-queue 4 \
  --queue-timeout-ms 5000

api-recorder config show
```

### 3. Run the proxy

Foreground mode:

```bash
api-recorder serve
```

Background mode:

```bash
api-recorder start
api-recorder status
```

### 4. Send requests through the proxy

List models:

```bash
curl http://127.0.0.1:8000/proxy/fakeai/models
```

Send a JSON request:

```bash
curl \
  -X POST 'http://127.0.0.1:8000/proxy/fakeai/chat/completions?trace_id=req-123' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: client-secret-that-will-be-redacted' \
  -H 'X-Client-Trace: client-trace-001' \
  -d '{
    "model": "fake-chat-model",
    "messages": [{"role": "user", "content": "hello fake upstream"}]
  }'
```

Read a streaming endpoint:

```bash
curl -N http://127.0.0.1:8000/proxy/fakeai/stream
```

Download a binary response:

```bash
curl http://127.0.0.1:8000/proxy/fakeai/binary --output /tmp/fake.bin
```

### 5. Inspect recorded data

Check where the config is loaded from:

```bash
api-recorder config path
```

Inspect recorded JSONL files:

```bash
find data/records -name 'records.jsonl' -print
tail -n 5 data/records/*/records.jsonl
```

What to look for in each record:

- `target_url` shows the real upstream URL that was called.
- `request_headers.authorization` is redacted to `***`.
- `response_body` stores JSON or streaming payload text.
- `response_body_encoding` becomes `base64` for binary responses.
- `queue_wait_ms`, `duration_ms`, `success`, and `error_kind` show runtime behavior.

### 6. Inspect stats and export

Overall summary:

```bash
api-recorder stats summary
```

Per-upstream summary:

```bash
api-recorder stats upstreams
```

Export raw records:

```bash
mkdir -p exports
api-recorder export --upstream fakeai --output ./exports/fakeai.jsonl
```

### 7. Stop the proxy

If you started the background daemon:

```bash
api-recorder stop
```

## CLI overview

```text
api-recorder init
api-recorder config path
api-recorder config show
api-recorder upstream add|update|remove|list
api-recorder serve
api-recorder start|stop|status
api-recorder stats summary|upstreams
api-recorder export --output ./exports/records.jsonl
```

Language control:

```bash
api-recorder --lang zh stats summary
API_RECORDER_LANG=zh api-recorder --help
```

Common config maintenance:

```bash
api-recorder upstream update --name fakeai --max-concurrency 4
api-recorder upstream list
api-recorder upstream remove --name fakeai
```

Runtime note:

- Outbound upstream requests intentionally ignore host `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` environment variables. `api_recorder` connects directly to each configured `base_url`.

## Config shape

The active config file defaults to `./config.toml` unless `--config` or `API_RECORDER_CONFIG` is set.

```toml
[server]
host = "127.0.0.1"
port = 8000
state_dir = ".api_recorder/state"

[recording]
output_dir = "data/records"
max_body_bytes = 4194304
redact_headers = ["authorization", "proxy-authorization", "x-api-key", "api-key", "x-goog-api-key"]

[i18n]
default_lang = "en"

[[upstreams]]
name = "openai"
route_prefix = "openai"
base_url = "https://api.openai.com/v1"
auth_env = "OPENAI_API_KEY"
auth_header = "Authorization"
auth_scheme = "Bearer"
timeout_ms = 60000
max_concurrency = 5
max_queue = 25
queue_timeout_ms = 30000

[upstreams.inject_headers]
OpenAI-Organization = "org_example"
```

## Recorded data

Records are stored under `data/records/YYYY-MM-DD/records.jsonl`. Each JSON object includes:

- `record_id`, `started_at`, `finished_at`
- `upstream_name`, `route_prefix`, `target_url`
- `method`, `path`, `query`
- sanitized `request_headers` and `response_headers`
- captured `request_body` and `response_body`
- body encodings, sizes, and truncation markers
- `response_status`, `duration_ms`, `queue_wait_ms`
- `streamed`, `success`, `error_kind`

Sensitive request headers are redacted by name. Bodies are recorded up to `recording.max_body_bytes`; non-text bodies are stored as base64.

## Stats and export

Summary statistics:

```bash
api-recorder stats summary --since 2026-03-08T00:00:00+00:00
api-recorder stats upstreams --upstream openai
```

Export filtered raw records:

```bash
api-recorder export \
  --upstream openai \
  --since 2026-03-08T00:00:00+00:00 \
  --output ./exports/openai.jsonl
```

## Development

Run tests:

```bash
conda run -n api_recorder python -m pytest
```

The test suite includes a full fake-upstream integration path:

- `tests/test_fake_upstream_integration.py`
  - creates a fake target API
  - proxies JSON, streaming, and binary responses through `api_recorder`
  - validates recorded JSONL content, summary stats, and export output

Optional live localhost integration test:

```bash
API_RECORDER_RUN_LIVE_TESTS=1 \
conda run -n api_recorder python -m pytest tests/test_live_http_integration.py
```

This test starts the fake upstream and the proxy on real `127.0.0.1` ports and verifies round-trips over actual HTTP sockets.

Important repo docs:

- [docs/architecture.md](docs/architecture.md)
- [docs/architecture_cn.md](docs/architecture_cn.md)
- [docs/progress.md](docs/progress.md)
- [docs/progress_cn.md](docs/progress_cn.md)
- [AGENTS.md](AGENTS.md)
