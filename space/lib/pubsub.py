from __future__ import annotations

import asyncio
import contextlib
from typing import TypeVar

T = TypeVar("T")

MAX_QUEUE_SIZE = 1000


class Registry[T]:
    def __init__(self, max_size: int = MAX_QUEUE_SIZE) -> None:
        self._queues: dict[str, list[tuple[asyncio.Queue[T], asyncio.AbstractEventLoop]]] = {}
        self._max_size = max_size

    def subscribe(self, key: str) -> asyncio.Queue[T]:
        queue: asyncio.Queue[T] = asyncio.Queue(maxsize=self._max_size)
        loop = asyncio.get_event_loop()
        self._queues.setdefault(key, []).append((queue, loop))
        return queue

    def unsubscribe(self, key: str, queue: asyncio.Queue[T]) -> None:
        if key in self._queues:
            self._queues[key] = [(q, ev_loop) for q, ev_loop in self._queues[key] if q is not queue]
            if not self._queues[key]:
                del self._queues[key]

    def publish(self, key: str, item: T) -> None:
        for q, loop in list(self._queues.get(key, [])):
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(self._put_item, q, item)

    def _put_item(self, q: asyncio.Queue[T], item: T) -> None:
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            with contextlib.suppress(Exception):
                q.get_nowait()
                q.put_nowait(item)

    def clear(self, key: str) -> None:
        self._queues.pop(key, None)
