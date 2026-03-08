from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import click
import typer
import uvicorn

from .app import create_app
from .config import AppConfig, ConfigManager, UpstreamConfig, default_config_path
from .i18n import set_language, tr
from .service import (
    read_log_tail,
    read_state,
    remove_state,
    spawn_background_process,
    stop_process,
    wait_for_service_ready,
    wait_for_stop,
    write_state,
)
from .stats import RecordFilter, build_summary, group_by_upstream, iter_records, parse_iso8601


app = typer.Typer(help=tr("app.help"), no_args_is_help=True)
config_app = typer.Typer(help=tr("config.help"))
upstream_app = typer.Typer(help=tr("upstream.help"))
stats_app = typer.Typer(help=tr("stats.help"))
app.add_typer(config_app, name="config")
app.add_typer(upstream_app, name="upstream")
app.add_typer(stats_app, name="stats")

COMMAND_HELP_KEYS: dict[tuple[str, ...], str] = {
    (): "app.help",
    ("init",): "init.help",
    ("serve",): "serve.help",
    ("start",): "start.help",
    ("stop",): "stop.help",
    ("status",): "status.help",
    ("export",): "export.help",
    ("config",): "config.help",
    ("config", "path"): "config.path.help",
    ("config", "show"): "config.show.help",
    ("upstream",): "upstream.help",
    ("upstream", "list"): "upstream.list.help",
    ("upstream", "add"): "upstream.add.help",
    ("upstream", "update"): "upstream.update.help",
    ("upstream", "remove"): "upstream.remove.help",
    ("stats",): "stats.help",
    ("stats", "summary"): "stats.summary.help",
    ("stats", "upstreams"): "stats.upstreams.help",
}

GLOBAL_OPTION_HELP_KEYS: dict[str, str] = {
    "config": "app.config.help",
    "lang": "app.lang.help",
    "name": "option.name.help",
    "route_prefix": "option.route_prefix.help",
    "base_url": "option.base_url.help",
    "auth_env": "option.auth_env.help",
    "auth_header": "option.auth_header.help",
    "auth_scheme": "option.auth_scheme.help",
    "headers": "option.header.help",
    "timeout_ms": "option.timeout.help",
    "max_concurrency": "option.max_concurrency.help",
    "max_queue": "option.max_queue.help",
    "queue_timeout_ms": "option.queue_timeout.help",
    "output": "option.output.help",
    "since": "option.since.help",
    "until": "option.until.help",
    "upstream": "option.upstream.help",
    "host": "option.host.help",
    "port": "option.port.help",
}


@dataclass
class AppContext:
    config_path: Path
    language: str


def _parse_headers(items: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise typer.BadParameter(tr("error.invalid_header", value=item))
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _get_context(ctx: typer.Context) -> AppContext:
    if isinstance(ctx.obj, AppContext):
        return ctx.obj
    config_path = default_config_path()
    language = set_language(None)
    ctx.obj = AppContext(config_path=config_path, language=language)
    return ctx.obj


def _manager_from_ctx(ctx: typer.Context) -> ConfigManager:
    return ConfigManager(_get_context(ctx).config_path)


def _load_config(ctx: typer.Context) -> AppConfig:
    manager = _manager_from_ctx(ctx)
    try:
        return manager.load()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fail(tr("error.config_missing", path=exc.filename or exc.args[0])))


def _fail(message: str) -> int:
    typer.echo(message, err=True)
    return 1


def _localize_command_tree(command: click.Command, path: tuple[str, ...] = ()) -> None:
    help_key = COMMAND_HELP_KEYS.get(path)
    if help_key:
        localized = tr(help_key)
        command.help = localized
        command.short_help = localized
    for param in getattr(command, "params", []):
        key = GLOBAL_OPTION_HELP_KEYS.get(getattr(param, "name", ""))
        if key and hasattr(param, "help"):
            param.help = tr(key)
    subcommands = getattr(command, "commands", None)
    if isinstance(subcommands, dict):
        for name, subcommand in subcommands.items():
            _localize_command_tree(subcommand, path + (name,))


def _lang_callback(ctx: click.Context, _param: click.Parameter, value: str | None) -> str:
    set_language(value)
    _localize_command_tree(ctx.find_root().command)
    return value or ""


@app.callback()
def main_callback(
    ctx: typer.Context,
    config: Annotated[Path, typer.Option("--config", help=tr("app.config.help"))] = default_config_path(),
    lang: Annotated[
        str | None,
        typer.Option("--lang", help=tr("app.lang.help"), callback=_lang_callback, is_eager=True),
    ] = None,
) -> None:
    language = set_language(lang)
    _localize_command_tree(ctx.command)
    ctx.obj = AppContext(config_path=config.expanduser().resolve(), language=language)


@app.command("init", help=tr("init.help"))
def init_command(ctx: typer.Context) -> None:
    manager = _manager_from_ctx(ctx)
    if manager.exists():
        raise typer.Exit(code=_fail(tr("init.exists", path=manager.config_path)))
    manager.create_default()
    typer.echo(tr("init.created", path=manager.config_path))


@config_app.command("path", help=tr("config.path.help"))
def config_path_command(ctx: typer.Context) -> None:
    manager = _manager_from_ctx(ctx)
    typer.echo(tr("config.path", path=manager.config_path))


@config_app.command("show", help=tr("config.show.help"))
def config_show_command(ctx: typer.Context) -> None:
    manager = _manager_from_ctx(ctx)
    if not manager.exists():
        raise typer.Exit(code=_fail(tr("error.config_missing", path=manager.config_path)))
    typer.echo(manager.config_path.read_text(encoding="utf-8"))


@upstream_app.command("list", help=tr("upstream.list.help"))
def upstream_list_command(ctx: typer.Context) -> None:
    config = _load_config(ctx)
    if not config.upstreams:
        typer.echo(tr("upstream.none"))
        return
    for upstream in config.upstreams:
        typer.echo(
            json.dumps(
                {
                    "name": upstream.name,
                    "route_prefix": upstream.route_prefix,
                    "base_url": upstream.base_url,
                    "auth_env": upstream.auth_env,
                    "timeout_ms": upstream.timeout_ms,
                    "max_concurrency": upstream.max_concurrency,
                    "max_queue": upstream.max_queue,
                    "queue_timeout_ms": upstream.queue_timeout_ms,
                },
                ensure_ascii=False,
            )
        )


@upstream_app.command("add", help=tr("upstream.add.help"))
def upstream_add_command(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help=tr("option.name.help"))],
    route_prefix: Annotated[str, typer.Option("--route-prefix", help=tr("option.route_prefix.help"))],
    base_url: Annotated[str, typer.Option("--base-url", help=tr("option.base_url.help"))],
    auth_env: Annotated[str | None, typer.Option("--auth-env", help=tr("option.auth_env.help"))] = None,
    auth_header: Annotated[str, typer.Option("--auth-header", help=tr("option.auth_header.help"))] = "Authorization",
    auth_scheme: Annotated[str, typer.Option("--auth-scheme", help=tr("option.auth_scheme.help"))] = "Bearer",
    headers: Annotated[list[str], typer.Option("--header", help=tr("option.header.help"))] = [],
    timeout_ms: Annotated[int, typer.Option("--timeout-ms", help=tr("option.timeout.help"))] = 60000,
    max_concurrency: Annotated[int, typer.Option("--max-concurrency", help=tr("option.max_concurrency.help"))] = 5,
    max_queue: Annotated[int, typer.Option("--max-queue", help=tr("option.max_queue.help"))] = 25,
    queue_timeout_ms: Annotated[int, typer.Option("--queue-timeout-ms", help=tr("option.queue_timeout.help"))] = 30000,
) -> None:
    manager = _manager_from_ctx(ctx)
    config = manager.load() if manager.exists() else AppConfig().attach_source(manager.config_path)
    if config.upstream_by_name(name):
        raise typer.Exit(code=_fail(tr("error.upstream_exists", name=name)))
    config.upstreams.append(
        UpstreamConfig(
            name=name,
            route_prefix=route_prefix,
            base_url=base_url,
            auth_env=auth_env,
            auth_header=auth_header,
            auth_scheme=auth_scheme,
            inject_headers=_parse_headers(headers),
            timeout_ms=timeout_ms,
            max_concurrency=max_concurrency,
            max_queue=max_queue,
            queue_timeout_ms=queue_timeout_ms,
        )
    )
    manager.save(config)
    typer.echo(tr("upstream.added", name=name))


@upstream_app.command("update", help=tr("upstream.update.help"))
def upstream_update_command(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help=tr("option.name.help"))],
    route_prefix: Annotated[str | None, typer.Option("--route-prefix", help=tr("option.route_prefix.help"))] = None,
    base_url: Annotated[str | None, typer.Option("--base-url", help=tr("option.base_url.help"))] = None,
    auth_env: Annotated[str | None, typer.Option("--auth-env", help=tr("option.auth_env.help"))] = None,
    auth_header: Annotated[str | None, typer.Option("--auth-header", help=tr("option.auth_header.help"))] = None,
    auth_scheme: Annotated[str | None, typer.Option("--auth-scheme", help=tr("option.auth_scheme.help"))] = None,
    headers: Annotated[list[str] | None, typer.Option("--header", help=tr("option.header.help"))] = None,
    timeout_ms: Annotated[int | None, typer.Option("--timeout-ms", help=tr("option.timeout.help"))] = None,
    max_concurrency: Annotated[int | None, typer.Option("--max-concurrency", help=tr("option.max_concurrency.help"))] = None,
    max_queue: Annotated[int | None, typer.Option("--max-queue", help=tr("option.max_queue.help"))] = None,
    queue_timeout_ms: Annotated[int | None, typer.Option("--queue-timeout-ms", help=tr("option.queue_timeout.help"))] = None,
) -> None:
    manager = _manager_from_ctx(ctx)
    config = _load_config(ctx)
    upstream = config.upstream_by_name(name)
    if upstream is None:
        raise typer.Exit(code=_fail(tr("error.upstream_missing", name=name)))
    updated = upstream.model_copy(
        update={
            "route_prefix": route_prefix if route_prefix is not None else upstream.route_prefix,
            "base_url": base_url if base_url is not None else upstream.base_url,
            "auth_env": auth_env if auth_env is not None else upstream.auth_env,
            "auth_header": auth_header if auth_header is not None else upstream.auth_header,
            "auth_scheme": auth_scheme if auth_scheme is not None else upstream.auth_scheme,
            "inject_headers": _parse_headers(headers) if headers is not None else upstream.inject_headers,
            "timeout_ms": timeout_ms if timeout_ms is not None else upstream.timeout_ms,
            "max_concurrency": max_concurrency if max_concurrency is not None else upstream.max_concurrency,
            "max_queue": max_queue if max_queue is not None else upstream.max_queue,
            "queue_timeout_ms": queue_timeout_ms if queue_timeout_ms is not None else upstream.queue_timeout_ms,
        }
    )
    config.upstreams = [updated if item.name == name else item for item in config.upstreams]
    manager.save(config)
    typer.echo(tr("upstream.updated", name=name))


@upstream_app.command("remove", help=tr("upstream.remove.help"))
def upstream_remove_command(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help=tr("option.name.help"))],
) -> None:
    manager = _manager_from_ctx(ctx)
    config = _load_config(ctx)
    upstream = config.upstream_by_name(name)
    if upstream is None:
        raise typer.Exit(code=_fail(tr("error.upstream_missing", name=name)))
    config.upstreams = [item for item in config.upstreams if item.name != name]
    manager.save(config)
    typer.echo(tr("upstream.removed", name=name))


@app.command("serve", help=tr("serve.help"))
def serve_command(
    ctx: typer.Context,
    host: Annotated[str | None, typer.Option("--host", help=tr("option.host.help"))] = None,
    port: Annotated[int | None, typer.Option("--port", help=tr("option.port.help"))] = None,
) -> None:
    config = _load_config(ctx)
    bind_host = host or config.server.host
    bind_port = port or config.server.port
    typer.echo(tr("serve.starting", host=bind_host, port=bind_port))
    uvicorn.run(create_app(config, host=bind_host, port=bind_port), host=bind_host, port=bind_port, log_level="info")


@app.command("start", help=tr("start.help"))
def start_command(ctx: typer.Context) -> None:
    config = _load_config(ctx)
    language = _get_context(ctx).language
    existing = read_state(config)
    if existing:
        raise typer.Exit(code=_fail(tr("error.service_running")))
    process = spawn_background_process(config, config.server.host, config.server.port, language)
    if not wait_for_service_ready(process, config.server.host, config.server.port, timeout_seconds=10.0):
        process.terminate()
        log_tail = read_log_tail(config)
        if log_tail:
            raise typer.Exit(code=_fail(f"{tr('error.start_timeout')}\n{log_tail}"))
        raise typer.Exit(code=_fail(tr("error.start_timeout")))
    write_state(config, process.pid, config.server.host, config.server.port)
    typer.echo(tr("start.started"))


@app.command("stop", help=tr("stop.help"))
def stop_command(ctx: typer.Context) -> None:
    config = _load_config(ctx)
    state = read_state(config)
    if state is None:
        raise typer.Exit(code=_fail(tr("error.service_not_running")))
    stop_process(state.pid)
    if not wait_for_stop(state.pid, timeout_seconds=10.0):
        raise typer.Exit(code=_fail(tr("error.stop_timeout")))
    remove_state(config)
    typer.echo(tr("stop.stopped"))


@app.command("status", help=tr("status.help"))
def status_command(ctx: typer.Context) -> None:
    config = _load_config(ctx)
    state = read_state(config)
    if state is None:
        typer.echo(tr("status.stopped"))
        return
    typer.echo(tr("status.running"))
    typer.echo(tr("status.pid", pid=state.pid))
    typer.echo(tr("status.host", host=state.host))
    typer.echo(tr("status.port", port=state.port))
    typer.echo(tr("status.started_at", started_at=state.started_at))
    typer.echo(tr("status.config", path=state.config_path))


def _build_record_filter(
    since: str | None,
    until: str | None,
    upstream: str | None,
) -> RecordFilter:
    try:
        return RecordFilter(
            since=parse_iso8601(since),
            until=parse_iso8601(until),
            upstream=upstream,
        )
    except ValueError as exc:
        raise typer.BadParameter(tr("error.invalid_timestamp", value=str(exc))) from exc


def _filtered_records(config: AppConfig, record_filter: RecordFilter) -> list[dict]:
    return [record for record in iter_records(config) if record_filter.matches(record)]


@stats_app.command("summary", help=tr("stats.summary.help"))
def stats_summary_command(
    ctx: typer.Context,
    since: Annotated[str | None, typer.Option("--since", help=tr("option.since.help"))] = None,
    until: Annotated[str | None, typer.Option("--until", help=tr("option.until.help"))] = None,
    upstream: Annotated[str | None, typer.Option("--upstream", help=tr("option.upstream.help"))] = None,
) -> None:
    config = _load_config(ctx)
    record_filter = _build_record_filter(since, until, upstream)
    summary = build_summary(_filtered_records(config, record_filter))
    success_rate = (summary.successful_requests / summary.total_requests * 100) if summary.total_requests else 0.0
    typer.echo(tr("stats.summary.title"))
    typer.echo(tr("stats.total", value=summary.total_requests))
    typer.echo(tr("stats.success", value=summary.successful_requests))
    typer.echo(tr("stats.failure", value=summary.failed_requests))
    typer.echo(tr("stats.success_rate", value=success_rate))
    typer.echo(tr("stats.avg_latency", value=summary.average_latency_ms))
    typer.echo(tr("stats.p95_latency", value=summary.p95_latency_ms))
    typer.echo(tr("stats.streamed", value=summary.streamed_requests))


@stats_app.command("upstreams", help=tr("stats.upstreams.help"))
def stats_upstreams_command(
    ctx: typer.Context,
    since: Annotated[str | None, typer.Option("--since", help=tr("option.since.help"))] = None,
    until: Annotated[str | None, typer.Option("--until", help=tr("option.until.help"))] = None,
    upstream: Annotated[str | None, typer.Option("--upstream", help=tr("option.upstream.help"))] = None,
) -> None:
    config = _load_config(ctx)
    record_filter = _build_record_filter(since, until, upstream)
    grouped = group_by_upstream(_filtered_records(config, record_filter))
    if not grouped:
        typer.echo(tr("upstream.none"))
        return
    for name, summary in grouped.items():
        typer.echo(
            json.dumps(
                {
                    "upstream": name,
                    "total_requests": summary.total_requests,
                    "successful_requests": summary.successful_requests,
                    "failed_requests": summary.failed_requests,
                    "average_latency_ms": round(summary.average_latency_ms, 2),
                    "p95_latency_ms": round(summary.p95_latency_ms, 2),
                    "streamed_requests": summary.streamed_requests,
                },
                ensure_ascii=False,
            )
        )


@app.command("export", help=tr("export.help"))
def export_command(
    ctx: typer.Context,
    output: Annotated[Path, typer.Option("--output", help=tr("option.output.help"))],
    since: Annotated[str | None, typer.Option("--since", help=tr("option.since.help"))] = None,
    until: Annotated[str | None, typer.Option("--until", help=tr("option.until.help"))] = None,
    upstream: Annotated[str | None, typer.Option("--upstream", help=tr("option.upstream.help"))] = None,
) -> None:
    config = _load_config(ctx)
    record_filter = _build_record_filter(since, until, upstream)
    records = _filtered_records(config, record_filter)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    typer.echo(tr("stats.exported", count=len(records), path=output))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
