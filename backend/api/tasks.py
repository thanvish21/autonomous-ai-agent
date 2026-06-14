"""Task store + pub/sub bridge backed by Redis with an in-memory fallback.

Each task has:
  - state: queued | running | awaiting_confirmation | completed | failed
  - events: ordered list of AgentEvent dicts
  - result: final answer + artifacts
  - confirmations: dict[tool_use_id] -> approved bool

Streaming: callers subscribe to a queue that receives every new event for the
task. The SSE endpoint replays history first, then tails the live stream.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:  # noqa: BLE001
    aioredis = None  # type: ignore


@dataclass
class Task:
    id: str
    prompt: str
    state: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[dict] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    pending_confirmation: dict | None = None


class TaskStore:
    """Hybrid in-memory + Redis store with pub/sub for live streaming."""

    def __init__(self, redis_url: str | None) -> None:
        self.redis_url = redis_url
        self._redis = None
        self._tasks: dict[str, Task] = {}
        self._subscribers: dict[str, list[asyncio.Queue[dict]]] = {}
        self._confirmations: dict[str, dict[str, asyncio.Future[bool]]] = {}

    async def connect(self) -> None:
        if aioredis is None or not self.redis_url:
            return
        try:
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
            await self._redis.ping()
        except Exception:  # noqa: BLE001
            self._redis = None

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create(self, prompt: str) -> Task:
        task = Task(id=uuid.uuid4().hex[:12], prompt=prompt)
        self._tasks[task.id] = task
        await self._persist(task)
        return task

    async def get(self, task_id: str) -> Task | None:
        task = self._tasks.get(task_id)
        if task is not None:
            return task
        if self._redis is None:
            return None
        raw = await self._redis.get(f"task:{task_id}")
        if raw is None:
            return None
        data = json.loads(raw)
        task = Task(**data)
        self._tasks[task_id] = task
        return task

    async def list_recent(self, limit: int = 25) -> list[Task]:
        tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    async def update_state(
        self,
        task_id: str,
        *,
        state: str | None = None,
        result: dict | None = None,
        error: str | None = None,
        pending_confirmation: dict | None = None,
    ) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        if state is not None:
            task.state = state
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        task.pending_confirmation = pending_confirmation
        task.updated_at = time.time()
        await self._persist(task)

    async def append_event(self, task_id: str, event: dict) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        task.events.append(event)
        task.updated_at = time.time()
        await self._persist(task)
        for queue in list(self._subscribers.get(task_id, [])):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def subscribe(self, task_id: str) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=512)
        self._subscribers.setdefault(task_id, []).append(queue)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue[dict]) -> None:
        subs = self._subscribers.get(task_id) or []
        if queue in subs:
            subs.remove(queue)

    async def stream(self, task_id: str) -> AsyncIterator[dict]:
        task = await self.get(task_id)
        if task is None:
            return
        # Replay buffered events first.
        for event in list(task.events):
            yield event
        if task.state in ("completed", "failed"):
            return
        queue = self.subscribe(task_id)
        try:
            while True:
                event = await queue.get()
                yield event
                if event.get("kind") in ("task_completed", "task_failed"):
                    return
        finally:
            self.unsubscribe(task_id, queue)

    # ------------------------------------------------------------------
    # Human-in-the-loop confirmation
    # ------------------------------------------------------------------

    def register_confirmation(self, task_id: str, key: str) -> asyncio.Future[bool]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._confirmations.setdefault(task_id, {})[key] = future
        return future

    def resolve_confirmation(self, task_id: str, key: str, approved: bool) -> bool:
        bucket = self._confirmations.get(task_id, {})
        future = bucket.pop(key, None)
        if future and not future.done():
            future.set_result(approved)
            return True
        return False

    def pending_confirmations(self, task_id: str) -> list[str]:
        return list((self._confirmations.get(task_id) or {}).keys())

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist(self, task: Task) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(
                f"task:{task.id}",
                json.dumps(task.__dict__, default=str),
                ex=60 * 60 * 24,
            )
            await self._redis.zadd("tasks:recent", {task.id: task.created_at})
        except Exception:  # noqa: BLE001
            pass
