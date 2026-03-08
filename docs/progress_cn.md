# 进度

## 当前状态

当前里程碑：v1 首版代码和仓库级交付已经完成。

## 已完成

- 已在 README 中补充 Gemini 独立中转 upstream 的配置方法，以及通过 `/proxy/gemini/...` 调用的示例。
- 从空仓库搭建了可编辑安装的 Python 项目骨架。
- 添加了 conda 环境定义 `environment.yml`。
- 增加了仓库内置假上游示例 `examples/fake_upstream.py`，用于本地手工联调。
- 实现了配置模型、TOML 持久化、CLI 入口以及 upstream 管理。
- 实现了基于路由前缀的 FastAPI 代理、按 upstream 的鉴权注入和请求头脱敏。
- 将上游 HTTP 客户端固定为直连模式（`trust_env=False`），避免宿主机代理环境变量干扰转发。
- 实现了普通响应与流式响应的请求/响应记录。
- 实现了按 upstream 的并发门控和有界排队。
- 实现了按日分片 JSONL 记录、统计摘要、按 upstream 聚合以及原始 JSONL 导出。
- 实现了带就绪检查和 PID/state 文件的后台进程控制。
- 补齐了中英文仓库文档。
- 增加了覆盖 CLI、代理记录、流式、排队饱和、统计、导出、完整假上游链路，以及可选真实端口 live HTTP 验证的测试。

## 验证情况

- 本次仅更新文档，没有改动代码路径，因此未增加新的运行时验证。
- `conda run -n api_recorder python -m pytest`
  - 结果：通过（`6` 个通过，`1` 个 live test 被跳过）
- 已在 `api_recorder` 环境中检查 CLI 帮助和命令面。
- 已检查仓库内置假上游示例可以正常导入，并确认路由完整。
- 已在非沙箱环境下完成后台守护链路验证：
  - `init -> start -> status -> stop -> status`
  - 结果：在本地 `127.0.0.1:8000` 上通过
- 已在非沙箱环境下完成真实 localhost 集成验证：
  - `API_RECORDER_RUN_LIVE_TESTS=1 conda run -n api_recorder python -m pytest tests/test_live_http_integration.py`
  - 结果：通过

## 后续待办

- 在通用 HTTP 路由被真实工具验证稳定之后，再扩展厂商专用协议适配层。
