from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from api_recorder.config import AppConfig


def read_records(config: AppConfig) -> list[dict]:
    files = sorted(config.resolved_output_dir().rglob("*.jsonl"))
    output: list[dict] = []
    for file_path in files:
        for line in file_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                output.append(json.loads(line))
    return output


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.getsockname()[1]


def wait_for_http_ready(
    url: str,
    timeout_seconds: float = 10.0,
    process: subprocess.Popen | None = None,
    log_path: Path | None = None,
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if process is not None and process.poll() is not None:
            break
        try:
            response = httpx.get(url, timeout=0.5, trust_env=False)
            if response.status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    details = ""
    if log_path and log_path.exists():
        tail = "\n".join(log_path.read_text(encoding="utf-8").splitlines()[-20:])
        if tail:
            details = f"\n{tail}"
    raise RuntimeError(f"HTTP service failed to become ready: {url}{details}")


@dataclass
class LiveProcessServer:
    command: list[str]
    cwd: Path
    health_url: str
    env: dict[str, str] | None = None

    def __post_init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._log_handle = tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", delete=False)
        self.log_path = Path(self._log_handle.name)

    def start(self, timeout_seconds: float = 10.0) -> None:
        env = os.environ.copy()
        if self.env:
            env.update(self.env)
        self._process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            env=env,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
        )
        wait_for_http_ready(
            self.health_url,
            timeout_seconds=timeout_seconds,
            process=self._process,
            log_path=self.log_path,
        )

    def stop(self, timeout_seconds: float = 10.0) -> None:
        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            self._process.kill()
            self._process.wait(timeout=timeout_seconds)
            raise RuntimeError(f"server failed to stop: {' '.join(self.command)}") from exc
        finally:
            self._log_handle.close()
