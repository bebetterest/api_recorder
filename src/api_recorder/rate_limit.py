from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import perf_counter


class QueueFullError(RuntimeError):
    pass


class QueueTimeoutError(RuntimeError):
    pass


@dataclass
class SlotAcquisition:
    queue_wait_ms: float


class UpstreamConcurrencyGate:
    def __init__(self, max_concurrency: int, max_queue: int, queue_timeout_ms: int) -> None:
        self.max_concurrency = max_concurrency
        self.max_queue = max_queue
        self.queue_timeout_ms = queue_timeout_ms
        self._active = 0
        self._waiting = 0
        self._lock = asyncio.Lock()
        self._condition = asyncio.Condition(self._lock)

    async def acquire(self) -> SlotAcquisition:
        started = perf_counter()
        async with self._condition:
            if self.max_concurrency == 0:
                raise QueueFullError("max_concurrency is zero")
            if self._active < self.max_concurrency:
                self._active += 1
                return SlotAcquisition(queue_wait_ms=0.0)
            if self._waiting >= self.max_queue:
                raise QueueFullError("queue is full")

            self._waiting += 1
            try:
                timeout_seconds = self.queue_timeout_ms / 1000.0
                while self._active >= self.max_concurrency:
                    try:
                        await asyncio.wait_for(self._condition.wait(), timeout=timeout_seconds)
                    except TimeoutError as exc:
                        raise QueueTimeoutError("queue wait timed out") from exc
                self._active += 1
            finally:
                self._waiting -= 1
        return SlotAcquisition(queue_wait_ms=(perf_counter() - started) * 1000.0)

    async def release(self) -> None:
        async with self._condition:
            if self._active > 0:
                self._active -= 1
            self._condition.notify(1)

    @asynccontextmanager
    async def slot(self):
        acquisition = await self.acquire()
        try:
            yield acquisition
        finally:
            await self.release()

