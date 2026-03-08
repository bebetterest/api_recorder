from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import tomli_w
from pydantic import BaseModel, Field, PrivateAttr, field_validator


def default_config_path() -> Path:
    override = os.getenv("API_RECORDER_CONFIG")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.cwd() / "config.toml").resolve()


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    state_dir: str = ".api_recorder/state"


class RecordingConfig(BaseModel):
    output_dir: str = "data/records"
    max_body_bytes: int = 4 * 1024 * 1024
    redact_headers: list[str] = Field(
        default_factory=lambda: [
            "authorization",
            "proxy-authorization",
            "x-api-key",
            "api-key",
            "x-goog-api-key",
        ]
    )


class I18nConfig(BaseModel):
    default_lang: str = "en"

    @field_validator("default_lang")
    @classmethod
    def validate_default_lang(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"en", "zh", "auto"}:
            raise ValueError("default_lang must be en, zh, or auto")
        return normalized


class UpstreamConfig(BaseModel):
    name: str
    route_prefix: str
    base_url: str
    auth_env: str | None = None
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    inject_headers: dict[str, str] = Field(default_factory=dict)
    timeout_ms: int = 60_000
    max_concurrency: int = 5
    max_queue: int = 25
    queue_timeout_ms: int = 30_000

    @field_validator("name", "route_prefix")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be empty")
        if "/" in cleaned or cleaned.startswith("."):
            raise ValueError("value cannot contain slash or start with dot")
        return cleaned

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return cleaned.rstrip("/")

    @field_validator("timeout_ms", "max_concurrency", "max_queue", "queue_timeout_ms")
    @classmethod
    def validate_positive(cls, value: int) -> int:
        if value < 0:
            raise ValueError("value must be >= 0")
        return value


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    i18n: I18nConfig = Field(default_factory=I18nConfig)
    upstreams: list[UpstreamConfig] = Field(default_factory=list)

    _config_path: Path | None = PrivateAttr(default=None)

    def attach_source(self, config_path: Path) -> "AppConfig":
        self._config_path = config_path.resolve()
        return self

    @property
    def config_path(self) -> Path:
        if self._config_path is None:
            return default_config_path()
        return self._config_path

    @property
    def config_dir(self) -> Path:
        return self.config_path.parent

    def resolve_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = (self.config_dir / path).resolve()
        return path

    def resolved_state_dir(self) -> Path:
        return self.resolve_path(self.server.state_dir)

    def resolved_output_dir(self) -> Path:
        return self.resolve_path(self.recording.output_dir)

    def upstream_by_name(self, name: str) -> UpstreamConfig | None:
        return next((item for item in self.upstreams if item.name == name), None)

    def upstream_by_route(self, route_prefix: str) -> UpstreamConfig | None:
        return next((item for item in self.upstreams if item.route_prefix == route_prefix), None)

    def to_toml_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ConfigManager:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = (config_path or default_config_path()).expanduser().resolve()

    def exists(self) -> bool:
        return self.config_path.exists()

    def create_default(self) -> AppConfig:
        config = AppConfig().attach_source(self.config_path)
        self.save(config)
        return config

    def load(self) -> AppConfig:
        if not self.config_path.exists():
            raise FileNotFoundError(self.config_path)
        data = tomllib.loads(self.config_path.read_text(encoding="utf-8"))
        return AppConfig.model_validate(data).attach_source(self.config_path)

    def save(self, config: AppConfig) -> None:
        config.attach_source(self.config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(tomli_w.dumps(config.to_toml_dict()), encoding="utf-8")

