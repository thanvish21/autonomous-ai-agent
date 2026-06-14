"""Autonomous agent loop built on top of the Anthropic Messages API.

LangGraph orchestrates the plan → act → observe → reflect cycle. Each state
transition emits an `AgentEvent` so the API layer can stream the trace as SSE.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Literal

from anthropic import AsyncAnthropic
from anthropic.types import Message, ToolUseBlock, TextBlock
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from .memory import MemoryStore
from .prompts import SYSTEM_PROMPT
from .tools import TOOL_SCHEMAS, TaskContext, execute_tool


# ---------------------------------------------------------------------------
# Event model — what we stream to the frontend
# ---------------------------------------------------------------------------


EventKind = Literal[
    "task_started",
    "thought",
    "tool_call",
    "tool_result",
    "human_input_required",
    "iteration",
    "final_answer",
    "task_failed",
    "task_completed",
]


@dataclass
class AgentEvent:
    kind: EventKind
    payload: dict
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "payload": self.payload, "ts": self.ts}


EmitFn = Callable[[AgentEvent], Awaitable[None]]


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------


class AgentState(TypedDict, total=False):
    messages: list[dict]
    iteration: int
    final_answer: str | None
    artifacts: list[str]
    error: str | None
    stop_reason: str | None


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


@dataclass
class AgentConfig:
    model: str = "claude-sonnet-4-6"
    max_iterations: int = 16
    max_tokens: int = 4096
    temperature: float = 0.2


class Agent:
    def __init__(
        self,
        anthropic: AsyncAnthropic,
        memory: MemoryStore,
        config: AgentConfig | None = None,
    ) -> None:
        self.client = anthropic
        self.memory = memory
        self.config = config or AgentConfig()
        self._graph = self._build_graph()

    # ------------------------------------------------------------------
    # Graph wiring
    # ------------------------------------------------------------------

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("reason", self._reason_node)
        graph.add_node("act", self._act_node)
        graph.set_entry_point("reason")
        graph.add_conditional_edges(
            "reason",
            self._route_after_reason,
            {"act": "act", "done": END, "limit": END},
        )
        graph.add_edge("act", "reason")
        return graph.compile()

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    async def run(
        self,
        prompt: str,
        ctx: TaskContext,
        emit: EmitFn,
    ) -> dict:
        ctx.metadata["memory_store"] = self.memory

        # Seed short-term memory with relevant long-term snippets.
        recalls = await asyncio.to_thread(self.memory.search, prompt, 3)
        recall_blob = ""
        if recalls:
            recall_blob = "\n\nRelevant prior tasks:\n" + "\n".join(
                f"- ({h['task_id']}) {h['summary'][:240]}" for h in recalls
            )

        state: AgentState = {
            "messages": [
                {
                    "role": "user",
                    "content": f"{prompt}{recall_blob}",
                }
            ],
            "iteration": 0,
            "final_answer": None,
            "artifacts": [],
            "error": None,
            "stop_reason": None,
        }

        await emit(
            AgentEvent(
                "task_started",
                {"task_id": ctx.task_id, "prompt": prompt, "recalls": len(recalls)},
            )
        )

        # We drive the graph manually so we can inject emit + ctx + cancellation.
        try:
            while True:
                state = await self._reason_node(state, ctx, emit)
                decision = self._route_after_reason(state)
                if decision == "done":
                    break
                if decision == "limit":
                    state["error"] = state.get("error") or "max_iterations exceeded"
                    break
                state = await self._act_node(state, ctx, emit)
        except asyncio.CancelledError:
            await emit(AgentEvent("task_failed", {"error": "cancelled"}))
            raise
        except Exception as exc:  # noqa: BLE001
            state["error"] = f"{exc.__class__.__name__}: {exc}"
            await emit(AgentEvent("task_failed", {"error": state["error"]}))

        if state.get("final_answer"):
            # Persist a summary for future recall.
            summary = self._summarise(prompt, state["final_answer"])
            try:
                await asyncio.to_thread(self.memory.add, ctx.task_id, summary)
            except Exception:  # noqa: BLE001
                pass
            await emit(
                AgentEvent(
                    "task_completed",
                    {
                        "final_answer": state["final_answer"],
                        "artifacts": state.get("artifacts", []),
                        "iterations": state["iteration"],
                    },
                )
            )
        elif state.get("error"):
            await emit(AgentEvent("task_failed", {"error": state["error"]}))

        return {
            "final_answer": state.get("final_answer"),
            "artifacts": state.get("artifacts", []),
            "iterations": state.get("iteration", 0),
            "error": state.get("error"),
        }

    # ------------------------------------------------------------------
    # Graph nodes
    # ------------------------------------------------------------------

    async def _reason_node(
        self, state: AgentState, ctx: TaskContext, emit: EmitFn
    ) -> AgentState:
        iteration = state.get("iteration", 0) + 1
        state["iteration"] = iteration
        await emit(
            AgentEvent("iteration", {"n": iteration, "max": self.config.max_iterations})
        )

        if iteration > self.config.max_iterations:
            state["stop_reason"] = "max_iterations"
            return state

        message = await self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=state["messages"],
        )

        # Append the assistant turn to the running conversation.
        assistant_blocks: list[dict] = []
        tool_uses: list[ToolUseBlock] = []
        for block in message.content:
            if isinstance(block, TextBlock):
                assistant_blocks.append({"type": "text", "text": block.text})
                if block.text.strip():
                    await emit(AgentEvent("thought", {"text": block.text}))
            elif isinstance(block, ToolUseBlock):
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
                tool_uses.append(block)

        state["messages"].append({"role": "assistant", "content": assistant_blocks})
        state["stop_reason"] = message.stop_reason
        state["_pending_tool_uses"] = tool_uses  # type: ignore[typeddict-item]
        return state

    async def _act_node(
        self, state: AgentState, ctx: TaskContext, emit: EmitFn
    ) -> AgentState:
        tool_uses: list[ToolUseBlock] = state.get("_pending_tool_uses", [])  # type: ignore[assignment]
        if not tool_uses:
            return state

        tool_results: list[dict] = []
        for tu in tool_uses:
            await emit(
                AgentEvent("tool_call", {"id": tu.id, "name": tu.name, "input": tu.input})
            )
            result = await execute_tool(tu.name, tu.input or {}, ctx)

            if result.get("requires_confirmation"):
                await emit(
                    AgentEvent(
                        "human_input_required",
                        {"tool": tu.name, "args": tu.input, "tool_use_id": tu.id},
                    )
                )

            await emit(
                AgentEvent(
                    "tool_result",
                    {
                        "id": tu.id,
                        "name": tu.name,
                        "ok": result.get("ok"),
                        "error": result.get("error"),
                        "data": result.get("data"),
                    },
                )
            )

            if tu.name == "submit_final_answer" and result.get("ok"):
                data = result["data"]
                state["final_answer"] = data["answer"]
                state["artifacts"] = data.get("artifacts", [])

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(
                        {
                            "ok": result.get("ok"),
                            "error": result.get("error"),
                            "data": result.get("data"),
                        },
                        default=str,
                    )[:30_000],
                    "is_error": not result.get("ok"),
                }
            )

        state["messages"].append({"role": "user", "content": tool_results})
        state["_pending_tool_uses"] = []  # type: ignore[typeddict-item]
        return state

    def _route_after_reason(self, state: AgentState) -> str:
        if state.get("final_answer"):
            return "done"
        if state.get("iteration", 0) >= self.config.max_iterations:
            return "limit"
        pending = state.get("_pending_tool_uses") or []  # type: ignore[assignment]
        if state.get("stop_reason") == "tool_use" and pending:
            return "act"
        # Model ended without calling a tool — treat its text as the final answer.
        last = state["messages"][-1]
        if last["role"] == "assistant":
            text = "".join(
                b["text"] for b in last["content"] if b.get("type") == "text"
            ).strip()
            if text:
                state["final_answer"] = text
                return "done"
        return "limit"

    # ------------------------------------------------------------------

    def _summarise(self, prompt: str, answer: str) -> str:
        head = prompt.strip().splitlines()[0][:180]
        body = answer.strip()
        if len(body) > 600:
            body = body[:600] + "…"
        return f"Goal: {head}\nOutcome: {body}"
