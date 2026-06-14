"""FastAPI app — task submission, SSE streaming, confirmations, history."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from anthropic import AsyncAnthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ..agent.core import Agent, AgentConfig, AgentEvent
from ..agent.memory import MemoryStore
from ..agent.tools import SMTPConfig, TaskContext
from .settings import settings
from .tasks import TaskStore


# ---------------------------------------------------------------------------
# Lifespan / DI
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.anthropic_api_key:
        # Fail loud at boot so misconfig isn't silently ignored.
        print("[warn] ANTHROPIC_API_KEY is unset — API will reject task submissions.")

    store = TaskStore(redis_url=settings.redis_url)
    await store.connect()
    memory = MemoryStore(persist_dir=settings.chroma_dir)
    anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key or "missing")
    http = httpx.AsyncClient(follow_redirects=True, timeout=20.0)
    agent = Agent(
        anthropic=anthropic,
        memory=memory,
        config=AgentConfig(
            model=settings.model, max_iterations=settings.max_iterations
        ),
    )

    app.state.store = store
    app.state.memory = memory
    app.state.agent = agent
    app.state.http = http

    try:
        yield
    finally:
        await http.aclose()
        await store.close()


app = FastAPI(title="Autonomous Agent API", version="0.1.0", lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class TaskCreate(BaseModel):
    prompt: str = Field(min_length=4, max_length=8_000)
    auto_confirm: bool | None = None


class TaskCreateResponse(BaseModel):
    task_id: str
    stream_url: str


class TaskInfo(BaseModel):
    id: str
    prompt: str
    state: str
    created_at: float
    updated_at: float
    result: dict | None = None
    error: str | None = None
    pending_confirmation: dict | None = None


class ConfirmRequest(BaseModel):
    tool_use_id: str
    approved: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        "model": settings.model,
        "redis": app.state.store._redis is not None,
        "smtp": settings.smtp_enabled,
    }


@app.get("/tools")
async def list_tools() -> dict:
    from ..agent.tools import TOOL_SCHEMAS

    return {"tools": [{"name": t["name"], "description": t["description"]} for t in TOOL_SCHEMAS]}


@app.post("/tasks", response_model=TaskCreateResponse)
async def create_task(body: TaskCreate) -> TaskCreateResponse:
    if not settings.anthropic_api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not configured on server")

    store: TaskStore = app.state.store
    task = await store.create(body.prompt)

    auto_confirm = body.auto_confirm if body.auto_confirm is not None else settings.auto_confirm
    asyncio.create_task(_run_task(task.id, auto_confirm=auto_confirm))

    return TaskCreateResponse(task_id=task.id, stream_url=f"/tasks/{task.id}/stream")


@app.get("/tasks", response_model=list[TaskInfo])
async def list_tasks() -> list[TaskInfo]:
    store: TaskStore = app.state.store
    tasks = await store.list_recent(25)
    return [
        TaskInfo(
            id=t.id,
            prompt=t.prompt,
            state=t.state,
            created_at=t.created_at,
            updated_at=t.updated_at,
            result=t.result,
            error=t.error,
            pending_confirmation=t.pending_confirmation,
        )
        for t in tasks
    ]


@app.get("/tasks/{task_id}", response_model=TaskInfo)
async def get_task(task_id: str) -> TaskInfo:
    store: TaskStore = app.state.store
    task = await store.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    return TaskInfo(
        id=task.id,
        prompt=task.prompt,
        state=task.state,
        created_at=task.created_at,
        updated_at=task.updated_at,
        result=task.result,
        error=task.error,
        pending_confirmation=task.pending_confirmation,
    )


@app.get("/tasks/{task_id}/result")
async def get_result(task_id: str) -> dict:
    store: TaskStore = app.state.store
    task = await store.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    if task.state not in ("completed", "failed"):
        raise HTTPException(425, f"task is {task.state}")
    return {"state": task.state, "result": task.result, "error": task.error}


@app.get("/tasks/{task_id}/events")
async def get_events(task_id: str) -> dict:
    store: TaskStore = app.state.store
    task = await store.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    return {"events": task.events}


@app.get("/tasks/{task_id}/stream")
async def stream_task(task_id: str, request: Request) -> EventSourceResponse:
    store: TaskStore = app.state.store
    task = await store.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")

    async def generator():
        async for event in store.stream(task_id):
            if await request.is_disconnected():
                break
            yield {"event": event.get("kind", "message"), "data": json.dumps(event)}

    return EventSourceResponse(generator(), ping=15)


@app.post("/tasks/{task_id}/confirm")
async def confirm(task_id: str, body: ConfirmRequest) -> dict:
    store: TaskStore = app.state.store
    task = await store.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    resolved = store.resolve_confirmation(task_id, body.tool_use_id, body.approved)
    if not resolved:
        raise HTTPException(409, "no pending confirmation matches that id")
    return {"ok": True, "approved": body.approved}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def _run_task(task_id: str, *, auto_confirm: bool) -> None:
    store: TaskStore = app.state.store
    agent: Agent = app.state.agent
    task = await store.get(task_id)
    if task is None:
        return

    await store.update_state(task_id, state="running")

    workspace = Path(settings.workspace_root) / task_id
    workspace.mkdir(parents=True, exist_ok=True)

    async def confirm_cb(action: str, payload: dict) -> bool:
        if auto_confirm:
            return True
        key = payload.get("tool_use_id") or payload.get("path") or action
        future = store.register_confirmation(task_id, key)
        await store.update_state(
            task_id,
            state="awaiting_confirmation",
            pending_confirmation={"action": action, "payload": payload, "key": key},
        )
        try:
            approved = await asyncio.wait_for(future, timeout=600)
        except asyncio.TimeoutError:
            approved = False
        await store.update_state(task_id, state="running", pending_confirmation=None)
        return approved

    smtp = SMTPConfig(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_addr=settings.smtp_from,
        enabled=settings.smtp_enabled,
    )

    ctx = TaskContext(
        task_id=task_id,
        workspace=workspace,
        smtp=smtp,
        confirm=confirm_cb,
        http=app.state.http,
    )

    async def emit(event: AgentEvent) -> None:
        payload = event.to_dict()
        await store.append_event(task_id, payload)

        # Mirror human-input requests into a pending_confirmation marker so the
        # frontend has a stable thing to render even after a reconnect.
        if event.kind == "human_input_required":
            await store.update_state(
                task_id,
                state="awaiting_confirmation",
                pending_confirmation={
                    "action": event.payload.get("tool"),
                    "payload": event.payload,
                    "key": event.payload.get("tool_use_id"),
                },
            )

    try:
        outcome = await agent.run(task.prompt, ctx, emit)
        if outcome.get("error"):
            await store.update_state(task_id, state="failed", error=outcome["error"])
        else:
            await store.update_state(
                task_id,
                state="completed",
                result={
                    "final_answer": outcome.get("final_answer"),
                    "artifacts": outcome.get("artifacts", []),
                    "iterations": outcome.get("iterations"),
                },
            )
    except Exception as exc:  # noqa: BLE001
        await store.update_state(task_id, state="failed", error=str(exc))
