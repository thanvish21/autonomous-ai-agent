"""Smoke tests for the tool layer (no Anthropic calls)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from backend.agent.tools import SMTPConfig, TaskContext, execute_tool


@pytest.fixture()
def ctx(tmp_path: Path) -> TaskContext:
    return TaskContext(
        task_id="t-test",
        workspace=tmp_path,
        smtp=SMTPConfig(),
        confirm=None,
    )


def test_file_write_then_read(ctx):
    async def run():
        w = await execute_tool(
            "file_manager",
            {"action": "write", "path": "hello.txt", "content": "hi there"},
            ctx,
        )
        assert w["ok"], w
        r = await execute_tool(
            "file_manager", {"action": "read", "path": "hello.txt"}, ctx
        )
        assert r["ok"]
        assert r["data"]["content"] == "hi there"

    asyncio.run(run())


def test_path_traversal_rejected(ctx):
    async def run():
        r = await execute_tool(
            "file_manager",
            {"action": "write", "path": "../escape.txt", "content": "x"},
            ctx,
        )
        assert not r["ok"]
        assert "escape" in (r["error"] or "")

    asyncio.run(run())


def test_code_executor_runs_simple_python(ctx):
    async def run():
        r = await execute_tool(
            "code_executor", {"code": "print(2 + 2)"}, ctx
        )
        assert r["ok"], r
        assert "4" in r["data"]["stdout"]
        assert r["data"]["exit_code"] == 0

    asyncio.run(run())


def test_code_executor_timeout(ctx):
    async def run():
        r = await execute_tool(
            "code_executor",
            {"code": "while True: pass", "timeout": 2},
            ctx,
        )
        assert not r["ok"]
        assert "exceeded" in (r["error"] or "")

    asyncio.run(run())


def test_http_request_rejects_non_http(ctx):
    async def run():
        r = await execute_tool(
            "http_request", {"method": "GET", "url": "file:///etc/passwd"}, ctx
        )
        assert not r["ok"]

    asyncio.run(run())


def test_submit_final_answer(ctx):
    async def run():
        r = await execute_tool(
            "submit_final_answer",
            {"answer": "done", "artifacts": ["hello.txt"]},
            ctx,
        )
        assert r["ok"] and r["data"]["final"] is True

    asyncio.run(run())
