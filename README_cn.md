# api_recorder

`api_recorder` 是一个面向 AI / agent 工具的本地 HTTP 中转代理。它可以把请求转发到配置好的上游 API，记录完整的请求和响应数据，按上游做并发限流，并提供 CLI 用于配置、启动、停止、统计和导出。

英文主文档见 [README.md](README.md)。

## 当前能力

- 按路由前缀映射的通用 HTTP 代理：`/proxy/<route_prefix>/...`
- 按日分片的 JSONL 请求/响应记录
- 按 upstream 的并发上限、排队上限和排队超时
- 前台 `serve` 与后台 `start/stop/status`
- CLI 配置管理、调用统计与原始数据导出
- 通过 `--lang` 或 `API_RECORDER_LANG` 切换 CLI 中英文输出

## 环境

项目约定在 conda 环境 `api_recorder` 中开发：

```bash
conda env create -f environment.yml
conda activate api_recorder
```

代码更新后重新安装：

```bash
python -m pip install -e .[dev]
```

## 快速开始

初始化默认配置：

```bash
api-recorder init
```

新增一个 upstream：

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

前台运行：

```bash
api-recorder serve
```

后台运行：

```bash
api-recorder start
api-recorder status
api-recorder stop
```

通过代理访问上游：

```bash
curl http://127.0.0.1:8000/proxy/openai/chat/completions
```

## 完整本地演示

仓库内置了一个假上游服务 [examples/fake_upstream.py](examples/fake_upstream.py)。你可以不用真实厂商 API，直接完成一整套本地中转、记录、统计和导出验证。

### 1. 启动假上游服务

在仓库根目录执行：

```bash
conda activate api_recorder
python -m uvicorn examples.fake_upstream:app --host 127.0.0.1 --port 9101
```

这个假上游提供：

- `GET /v1/models`
- `POST /v1/chat/completions`
- `GET /v1/stream`
- `GET /v1/binary`

### 2. 配置 `api_recorder`

打开另一个终端：

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

### 3. 启动代理

前台运行：

```bash
api-recorder serve
```

后台运行：

```bash
api-recorder start
api-recorder status
```

### 4. 通过代理发请求

查看模型列表：

```bash
curl http://127.0.0.1:8000/proxy/fakeai/models
```

发送 JSON 请求：

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

读取流式响应：

```bash
curl -N http://127.0.0.1:8000/proxy/fakeai/stream
```

下载二进制响应：

```bash
curl http://127.0.0.1:8000/proxy/fakeai/binary --output /tmp/fake.bin
```

### 5. 检查记录数据

先确认当前配置路径：

```bash
api-recorder config path
```

查看记录文件：

```bash
find data/records -name 'records.jsonl' -print
tail -n 5 data/records/*/records.jsonl
```

重点关注：

- `target_url`：实际调用的上游地址
- `request_headers.authorization`：应被脱敏为 `***`
- `response_body`：JSON 或流式正文内容
- `response_body_encoding`：二进制响应会变成 `base64`
- `queue_wait_ms`、`duration_ms`、`success`、`error_kind`：运行时状态和结果

### 6. 查看统计和导出

整体摘要：

```bash
api-recorder stats summary
```

按 upstream 汇总：

```bash
api-recorder stats upstreams
```

导出原始记录：

```bash
mkdir -p exports
api-recorder export --upstream fakeai --output ./exports/fakeai.jsonl
```

### 7. 停止代理

如果是后台运行：

```bash
api-recorder stop
```

## CLI 概览

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

语言切换：

```bash
api-recorder --lang zh stats summary
API_RECORDER_LANG=zh api-recorder --help
```

常见配置维护：

```bash
api-recorder upstream update --name fakeai --max-concurrency 4
api-recorder upstream list
api-recorder upstream remove --name fakeai
```

运行时说明：

- 发往上游的 HTTP 请求不会继承宿主机上的 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` 环境变量。`api_recorder` 会直接连接到配置中的 `base_url`。

## 配置结构

当前配置文件默认是 `./config.toml`，也可以通过 `--config` 或 `API_RECORDER_CONFIG` 指定。

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

## 记录数据

记录文件位于 `data/records/YYYY-MM-DD/records.jsonl`。单条 JSON 记录包含：

- `record_id`、`started_at`、`finished_at`
- `upstream_name`、`route_prefix`、`target_url`
- `method`、`path`、`query`
- 脱敏后的 `request_headers` 与 `response_headers`
- 捕获后的 `request_body` 与 `response_body`
- 正文编码、原始大小、截断标记
- `response_status`、`duration_ms`、`queue_wait_ms`
- `streamed`、`success`、`error_kind`

敏感请求头会按名称脱敏；正文默认记录到 `recording.max_body_bytes` 上限，非文本正文会以 base64 保存。

## 统计与导出

查看摘要：

```bash
api-recorder stats summary --since 2026-03-08T00:00:00+00:00
api-recorder stats upstreams --upstream openai
```

导出原始数据：

```bash
api-recorder export \
  --upstream openai \
  --since 2026-03-08T00:00:00+00:00 \
  --output ./exports/openai.jsonl
```

## 开发

运行测试：

```bash
conda run -n api_recorder python -m pytest
```

测试中包含完整的假上游集成链路：

- `tests/test_fake_upstream_integration.py`
  - 创建假目标 API
  - 通过 `api_recorder` 中转 JSON、流式和二进制响应
  - 校验 JSONL 记录内容、统计摘要和导出结果

可选的真实 localhost 集成测试：

```bash
API_RECORDER_RUN_LIVE_TESTS=1 \
conda run -n api_recorder python -m pytest tests/test_live_http_integration.py
```

这组测试会把假上游和代理都启动在真实的 `127.0.0.1` 端口上，并通过真实 HTTP socket 验证整条链路。

重要文档：

- [docs/architecture.md](docs/architecture.md)
- [docs/architecture_cn.md](docs/architecture_cn.md)
- [docs/progress.md](docs/progress.md)
- [docs/progress_cn.md](docs/progress_cn.md)
- [AGENTS.md](AGENTS.md)
