# 技术架构

## 目标

`api_recorder` 是一个面向 AI 工具的本地优先代理层。它负责把 HTTP 请求转发到配置好的上游 API，记录完整的请求/响应元数据和正文，并提供 CLI 来管理配置、生命周期、统计和导出。

## 核心设计

- 运行时栈：FastAPI + Uvicorn + HTTPX + Typer + Pydantic
- 配置真源：TOML 文件
- 存储：按日分片的 JSONL
- 路由方式：`/proxy/<route_prefix>/...`
- 限流方式：按 upstream 的并发门控和有界排队
- 发往上游的 HTTP 客户端使用 `trust_env=False`，不会被系统代理环境变量改写转发路径。
- 本地化：CLI 支持中英文输出

## 主要模块

- `src/api_recorder/config.py`
  - 定义配置模型、校验规则，以及 TOML 读写。
  - 把相对路径解析为相对于配置文件目录的绝对路径。
- `src/api_recorder/app.py`
  - 构建 FastAPI 应用、共享上游客户端以及代理逻辑。
  - 处理普通响应与流式响应，并写入原始记录。
- `src/api_recorder/rate_limit.py`
  - 实现按 upstream 的并发与排队控制。
- `src/api_recorder/recorder.py`
  - 负责正文捕获、请求头脱敏和 JSONL 落盘。
- `src/api_recorder/cli.py`
  - 提供 `init`、配置管理、upstream 管理、服务控制、统计与导出命令。
- `src/api_recorder/service.py`
  - 管理后台进程拉起、PID/state 文件、就绪检查和停止逻辑。
- `src/api_recorder/stats.py`
  - 扫描 JSONL 并计算摘要指标与按 upstream 的聚合结果。

## 请求流转

1. CLI 或调用方加载 `config.toml`。
2. 请求进入 `/proxy/<route_prefix>/...`。
3. 根据 `route_prefix` 选择对应 upstream。
4. 并发门控执行并发限制和排队控制。
5. 代理把请求转发到上游，并注入鉴权头和固定头。
6. 普通响应或流式响应被透传回调用方。
7. 请求完成或失败后写入一条 JSONL 记录。

## 记录模型

单条记录是自描述的，包含：

- 请求标识：`record_id`、`started_at`、`finished_at`
- 目标信息：`upstream_name`、`route_prefix`、`target_url`
- HTTP 上下文：`method`、`path`、`query`
- 脱敏后的请求头与响应头
- 捕获后的请求体与响应体，以及编码、大小、截断标记
- 指标：`duration_ms`、`queue_wait_ms`
- 状态：`response_status`、`streamed`、`success`、`error_kind`

## 后台服务模型

- `serve` 以前台方式运行代理。
- `start` 拉起后台 Python 进程，等待 `/health` 可达后再写入 `service.json`。
- `status` 读取 `service.json`，并校验 PID 仍然存活。
- `stop` 发送 `SIGTERM`，等待进程退出，并删除状态文件。

## v1 已知边界

- 还没有做厂商专用协议适配，当前只支持通用 HTTP 路由。
- 没有 UI，也没有内建本地认证。
- Linux 和 Windows 以代码层兼容为目标，首轮实际验证以 macOS 为主。
