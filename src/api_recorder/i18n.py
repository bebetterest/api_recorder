from __future__ import annotations

import locale
import os
from contextvars import ContextVar
from typing import Any

Language = str

LANG_EN = "en"
LANG_ZH = "zh"
SUPPORTED_LANGUAGES = {LANG_EN, LANG_ZH}
LANG_ENV_VAR = "API_RECORDER_LANG"

_LANGUAGE: ContextVar[Language | None] = ContextVar("api_recorder_language", default=None)

TRANSLATIONS: dict[str, dict[str, str]] = {
    "app.help": {
        "en": "Local API proxy, recorder, stats, and export CLI.",
        "zh": "本地 API 中转、记录、统计与导出命令行工具。",
    },
    "app.lang.help": {
        "en": "CLI language: en or zh.",
        "zh": "CLI 语言：en 或 zh。",
    },
    "app.config.help": {
        "en": "Path to the TOML config file.",
        "zh": "TOML 配置文件路径。",
    },
    "serve.help": {
        "en": "Run the proxy server in the foreground.",
        "zh": "以前台方式运行代理服务。",
    },
    "start.help": {
        "en": "Start the proxy server in the background.",
        "zh": "以后台守护方式启动代理服务。",
    },
    "stop.help": {
        "en": "Stop the background proxy server.",
        "zh": "停止后台代理服务。",
    },
    "status.help": {
        "en": "Show background service status.",
        "zh": "查看后台服务状态。",
    },
    "init.help": {
        "en": "Create a default config.toml if it does not exist.",
        "zh": "在不存在时创建默认 config.toml。",
    },
    "config.help": {
        "en": "Inspect config paths and current config content.",
        "zh": "查看配置路径和当前配置内容。",
    },
    "config.path.help": {
        "en": "Print the active config path.",
        "zh": "输出当前生效的配置路径。",
    },
    "config.show.help": {
        "en": "Print the active config content.",
        "zh": "输出当前生效的配置内容。",
    },
    "upstream.help": {
        "en": "Manage upstream definitions in config.toml.",
        "zh": "管理 config.toml 中的 upstream 定义。",
    },
    "upstream.list.help": {
        "en": "List configured upstreams.",
        "zh": "列出已配置的 upstream。",
    },
    "upstream.add.help": {
        "en": "Add a new upstream definition.",
        "zh": "新增 upstream 定义。",
    },
    "upstream.update.help": {
        "en": "Update an existing upstream definition.",
        "zh": "更新已有 upstream 定义。",
    },
    "upstream.remove.help": {
        "en": "Remove an upstream definition.",
        "zh": "删除 upstream 定义。",
    },
    "stats.help": {
        "en": "Summarize recorded traffic.",
        "zh": "汇总已记录流量。",
    },
    "stats.summary.help": {
        "en": "Show overall traffic summary.",
        "zh": "显示整体调用摘要。",
    },
    "stats.upstreams.help": {
        "en": "Show metrics grouped by upstream.",
        "zh": "按 upstream 展示指标。",
    },
    "export.help": {
        "en": "Export filtered raw records to JSONL.",
        "zh": "将筛选后的原始记录导出为 JSONL。",
    },
    "option.name.help": {
        "en": "Logical upstream name.",
        "zh": "upstream 逻辑名称。",
    },
    "option.route_prefix.help": {
        "en": "Route key under /proxy/<route_prefix>/...",
        "zh": "代理路径键，形如 /proxy/<route_prefix>/...。",
    },
    "option.base_url.help": {
        "en": "Upstream base URL.",
        "zh": "上游 API 基础地址。",
    },
    "option.auth_env.help": {
        "en": "Environment variable containing the upstream secret.",
        "zh": "保存上游密钥的环境变量名。",
    },
    "option.auth_header.help": {
        "en": "Header name used for auth injection.",
        "zh": "鉴权注入使用的头字段名。",
    },
    "option.auth_scheme.help": {
        "en": "Header prefix for auth injection, empty for raw secret.",
        "zh": "鉴权注入前缀，留空表示直接写入密钥。",
    },
    "option.header.help": {
        "en": "Static upstream header in KEY=VALUE form. Repeatable.",
        "zh": "上游固定请求头，格式 KEY=VALUE，可重复传入。",
    },
    "option.timeout.help": {
        "en": "Upstream timeout in milliseconds.",
        "zh": "上游超时时间，单位毫秒。",
    },
    "option.max_concurrency.help": {
        "en": "Max concurrent requests for the upstream.",
        "zh": "该 upstream 的最大并发数。",
    },
    "option.max_queue.help": {
        "en": "Max queued requests for the upstream.",
        "zh": "该 upstream 的最大排队数。",
    },
    "option.queue_timeout.help": {
        "en": "Max queue wait time in milliseconds.",
        "zh": "排队等待超时，单位毫秒。",
    },
    "option.output.help": {
        "en": "Output JSONL file path.",
        "zh": "导出 JSONL 文件路径。",
    },
    "option.since.help": {
        "en": "Only include records at or after this ISO8601 timestamp.",
        "zh": "仅包含该 ISO8601 时间及之后的记录。",
    },
    "option.until.help": {
        "en": "Only include records before or at this ISO8601 timestamp.",
        "zh": "仅包含该 ISO8601 时间及之前的记录。",
    },
    "option.upstream.help": {
        "en": "Filter by upstream name.",
        "zh": "按 upstream 名称过滤。",
    },
    "option.lang.help": {
        "en": "Override CLI language for this command.",
        "zh": "为本次命令覆盖 CLI 语言。",
    },
    "option.host.help": {
        "en": "Override bind host.",
        "zh": "覆盖绑定 host。",
    },
    "option.port.help": {
        "en": "Override bind port.",
        "zh": "覆盖绑定端口。",
    },
    "status.running": {
        "en": "Service is running.",
        "zh": "服务正在运行。",
    },
    "status.stopped": {
        "en": "Service is not running.",
        "zh": "服务未运行。",
    },
    "status.pid": {
        "en": "PID: {pid}",
        "zh": "进程号：{pid}",
    },
    "status.host": {
        "en": "Host: {host}",
        "zh": "地址：{host}",
    },
    "status.port": {
        "en": "Port: {port}",
        "zh": "端口：{port}",
    },
    "status.started_at": {
        "en": "Started at: {started_at}",
        "zh": "启动时间：{started_at}",
    },
    "status.config": {
        "en": "Config: {path}",
        "zh": "配置：{path}",
    },
    "init.created": {
        "en": "Created default config at {path}.",
        "zh": "已在 {path} 创建默认配置。",
    },
    "init.exists": {
        "en": "Config already exists at {path}.",
        "zh": "配置已存在：{path}。",
    },
    "config.path": {
        "en": "Active config path: {path}",
        "zh": "当前配置路径：{path}",
    },
    "upstream.added": {
        "en": "Added upstream {name}.",
        "zh": "已新增 upstream {name}。",
    },
    "upstream.updated": {
        "en": "Updated upstream {name}.",
        "zh": "已更新 upstream {name}。",
    },
    "upstream.removed": {
        "en": "Removed upstream {name}.",
        "zh": "已删除 upstream {name}。",
    },
    "upstream.none": {
        "en": "No upstreams configured.",
        "zh": "当前没有配置 upstream。",
    },
    "serve.starting": {
        "en": "Starting server on {host}:{port}.",
        "zh": "正在启动服务：{host}:{port}。",
    },
    "start.started": {
        "en": "Background service started.",
        "zh": "后台服务已启动。",
    },
    "stop.stopped": {
        "en": "Background service stopped.",
        "zh": "后台服务已停止。",
    },
    "stats.summary.title": {
        "en": "Traffic summary",
        "zh": "调用摘要",
    },
    "stats.total": {
        "en": "Total requests: {value}",
        "zh": "总请求数：{value}",
    },
    "stats.success": {
        "en": "Successful requests: {value}",
        "zh": "成功请求数：{value}",
    },
    "stats.failure": {
        "en": "Failed requests: {value}",
        "zh": "失败请求数：{value}",
    },
    "stats.success_rate": {
        "en": "Success rate: {value:.2f}%",
        "zh": "成功率：{value:.2f}%",
    },
    "stats.avg_latency": {
        "en": "Average latency: {value:.2f} ms",
        "zh": "平均时延：{value:.2f} ms",
    },
    "stats.p95_latency": {
        "en": "P95 latency: {value:.2f} ms",
        "zh": "P95 时延：{value:.2f} ms",
    },
    "stats.streamed": {
        "en": "Streamed requests: {value}",
        "zh": "流式请求数：{value}",
    },
    "stats.exported": {
        "en": "Exported {count} records to {path}.",
        "zh": "已导出 {count} 条记录到 {path}。",
    },
    "error.invalid_lang": {
        "en": "Unsupported language: {lang}",
        "zh": "不支持的语言：{lang}",
    },
    "error.invalid_header": {
        "en": "Header must use KEY=VALUE format: {value}",
        "zh": "请求头必须使用 KEY=VALUE 格式：{value}",
    },
    "error.config_missing": {
        "en": "Config file not found: {path}",
        "zh": "找不到配置文件：{path}",
    },
    "error.config_exists": {
        "en": "Config file already exists: {path}",
        "zh": "配置文件已存在：{path}",
    },
    "error.upstream_exists": {
        "en": "Upstream already exists: {name}",
        "zh": "upstream 已存在：{name}",
    },
    "error.upstream_missing": {
        "en": "Upstream not found: {name}",
        "zh": "未找到 upstream：{name}",
    },
    "error.service_running": {
        "en": "Background service is already running.",
        "zh": "后台服务已经在运行。",
    },
    "error.service_not_running": {
        "en": "Background service is not running.",
        "zh": "后台服务未运行。",
    },
    "error.start_timeout": {
        "en": "Timed out while waiting for the background service to start.",
        "zh": "等待后台服务启动超时。",
    },
    "error.stop_timeout": {
        "en": "Timed out while waiting for the background service to stop.",
        "zh": "等待后台服务停止超时。",
    },
    "error.invalid_timestamp": {
        "en": "Invalid ISO8601 timestamp: {value}",
        "zh": "无效的 ISO8601 时间：{value}",
    },
}


def normalize_language(value: str | None) -> Language:
    if not value:
        return LANG_EN
    normalized = value.lower().strip()
    if normalized.startswith("zh"):
        return LANG_ZH
    if normalized.startswith("en"):
        return LANG_EN
    raise ValueError(value)


def detect_language() -> Language:
    env_value = os.getenv(LANG_ENV_VAR)
    if env_value:
        try:
            return normalize_language(env_value)
        except ValueError:
            return LANG_EN
    locale_value = locale.getlocale()[0] if locale.getlocale() else None
    try:
        return normalize_language(locale_value)
    except ValueError:
        return LANG_EN


def set_language(language: str | None) -> Language:
    chosen = normalize_language(language) if language else detect_language()
    _LANGUAGE.set(chosen)
    return chosen


def get_language(default: str | None = None) -> Language:
    active = _LANGUAGE.get()
    if active:
        return active
    if default:
        try:
            return normalize_language(default)
        except ValueError:
            pass
    return detect_language()


def tr(key: str, **kwargs: Any) -> str:
    translations = TRANSLATIONS.get(key)
    if translations is None:
        return key.format(**kwargs) if kwargs else key
    language = get_language()
    template = translations.get(language) or translations[LANG_EN]
    return template.format(**kwargs)
