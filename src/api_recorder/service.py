from __future__ import annotations

import http.client
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig


STATE_FILE_NAME = "service.json"
LOG_FILE_NAME = "service.log"


@dataclass
class ServiceState:
    pid: int
    host: str
    port: int
    started_at: str
    config_path: str

    @classmethod
    def from_file(cls, state_file: Path) -> "ServiceState":
        return cls(**json.loads(state_file.read_text(encoding="utf-8")))

    def to_dict(self) -> dict[str, object]:
        return {
            "pid": self.pid,
            "host": self.host,
            "port": self.port,
            "started_at": self.started_at,
            "config_path": self.config_path,
        }


def state_file_path(config: AppConfig) -> Path:
    return config.resolved_state_dir() / STATE_FILE_NAME


def log_file_path(config: AppConfig) -> Path:
    return config.resolved_state_dir() / LOG_FILE_NAME


def ensure_state_dir(config: AppConfig) -> Path:
    state_dir = config.resolved_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def write_state(config: AppConfig, pid: int, host: str, port: int) -> Path:
    ensure_state_dir(config)
    state = ServiceState(
        pid=pid,
        host=host,
        port=port,
        started_at=datetime.now(timezone.utc).isoformat(),
        config_path=str(config.config_path),
    )
    target = state_file_path(config)
    target.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    return target


def read_state(config: AppConfig) -> ServiceState | None:
    target = state_file_path(config)
    if not target.exists():
        return None
    state = ServiceState.from_file(target)
    if not is_process_running(state.pid):
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return None
    return state


def remove_state(config: AppConfig) -> None:
    target = state_file_path(config)
    if target.exists():
        target.unlink()


def is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def spawn_background_process(config: AppConfig, host: str, port: int, lang: str) -> subprocess.Popen:
    ensure_state_dir(config)
    log_path = log_file_path(config)
    log_handle = log_path.open("a", encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "api_recorder",
        "--config",
        str(config.config_path),
        "--lang",
        lang,
        "serve",
        "--host",
        host,
        "--port",
        str(port),
    ]
    creationflags = 0
    kwargs: dict[str, object] = {
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, creationflags=creationflags, **kwargs)
    return process


def stop_process(pid: int) -> None:
    if os.name == "nt":
        os.kill(pid, signal.SIGTERM)
    else:
        os.kill(pid, signal.SIGTERM)


def wait_for_state(config: AppConfig, timeout_seconds: float) -> ServiceState | None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        state = read_state(config)
        if state:
            return state
        time.sleep(0.1)
    return None


def wait_for_service_ready(process: subprocess.Popen, host: str, port: int, timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            connection = http.client.HTTPConnection(host, port, timeout=0.5)
            connection.request("GET", "/health")
            response = connection.getresponse()
            response.read()
            connection.close()
            if response.status == 200:
                return True
        except OSError:
            pass
        time.sleep(0.1)
    return False


def wait_for_stop(pid: int, timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not is_process_running(pid):
            return True
        time.sleep(0.1)
    return False


def read_log_tail(config: AppConfig, max_lines: int = 20) -> str:
    log_path = log_file_path(config)
    if not log_path.exists():
        return ""
    lines = log_path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-max_lines:])
