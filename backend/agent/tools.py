"""Tool implementations for the autonomous agent.

Each tool exposes:
  - SCHEMA: Anthropic tool-use JSON schema
  - run(args, ctx) -> dict: async executor returning a result envelope

The result envelope shape is:
  {"ok": bool, "data": Any, "error": str | None, "requires_confirmation": bool}

`ctx` is a TaskContext with task_id, workspace dir, confirmation callback,
http client, and SMTP config.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shlex
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx


# ---------------------------------------------------------------------------
# Task context
# ---------------------------------------------------------------------------


ConfirmCallback = Callable[[str, dict], Awaitable[bool]]


@dataclass
class SMTPConfig:
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_addr: str = ""
    enabled: bool = False


@dataclass
class TaskContext:
    task_id: str
    workspace: Path
    smtp: SMTPConfig
    confirm: ConfirmCallback | None = None
    http: httpx.AsyncClient | None = None
    metadata: dict = field(default_factory=dict)

    def safe_path(self, name: str) -> Path:
        """Resolve a path inside the workspace, rejecting traversal."""
        candidate = (self.workspace / name).resolve()
        workspace = self.workspace.resolve()
        if not str(candidate).startswith(str(workspace)):
            raise ValueError(f"path escapes workspace: {name}")
        return candidate


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


TOOL_SCHEMAS: list[dict] = [
    {
        "name": "web_search",
        "description": (
            "Search the public web with DuckDuckGo and return the top N results "
            "(title, url, snippet). Use for fresh facts, news, comparisons."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 15,
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "http_request",
        "description": (
            "Issue an HTTP request and return status, headers, and body (text "
            "truncated to 20KB). Supports GET/POST/PUT/DELETE."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"],
                },
                "url": {"type": "string"},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                "body": {"type": "string"},
                "timeout": {"type": "integer", "minimum": 1, "maximum": 60, "default": 20},
            },
            "required": ["method", "url"],
        },
    },
    {
        "name": "code_executor",
        "description": (
            "Run a Python 3 script in a sandboxed subprocess with a 30s wall-"
            "clock limit, no network, and access only to the task workspace. "
            "Use for data analysis, csv/json wrangling, computation. Returns "
            "stdout, stderr, and exit code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python source to execute."},
                "stdin": {"type": "string", "default": ""},
                "timeout": {"type": "integer", "minimum": 1, "maximum": 60, "default": 30},
            },
            "required": ["code"],
        },
    },
    {
        "name": "file_manager",
        "description": (
            "Read, write, append, list, or delete files inside the task "
            "workspace. Writes/deletes that touch non-empty files require "
            "human confirmation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write", "append", "list", "delete"],
                },
                "path": {"type": "string", "description": "Relative path inside workspace."},
                "content": {"type": "string", "description": "Required for write/append."},
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200_000,
                    "default": 20_000,
                },
            },
            "required": ["action", "path"],
        },
    },
    {
        "name": "send_email",
        "description": (
            "Send an email via the configured SMTP server. Always requires "
            "human confirmation before sending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "html": {"type": "boolean", "default": False},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "recall_memory",
        "description": (
            "Search long-term memory for summaries of past tasks similar to "
            "the given query. Returns up to K relevant snippets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
            },
            "required": ["query"],
        },
    },
    {
        "name": "submit_final_answer",
        "description": (
            "Submit the final answer to the user and end the agent loop. "
            "Use this exactly once when the goal is complete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": "Markdown final answer.",
                },
                "artifacts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of workspace files produced.",
                },
            },
            "required": ["answer"],
        },
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None, "requires_confirmation": False}


def _err(msg: str) -> dict:
    return {"ok": False, "data": None, "error": msg, "requires_confirmation": False}


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncated {len(text) - limit} chars]"


async def _confirm(ctx: TaskContext, action: str, payload: dict) -> bool:
    if ctx.confirm is None:
        return True  # auto-approve in headless/test contexts
    return await ctx.confirm(action, payload)


# ---------------------------------------------------------------------------
# Tool runners
# ---------------------------------------------------------------------------


async def _run_web_search(args: dict, ctx: TaskContext) -> dict:
    query = args["query"].strip()
    max_results = int(args.get("max_results", 5))
    if not query:
        return _err("empty query")

    def _search() -> list[dict]:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = []
            for r in ddgs.text(query, max_results=max_results):
                results.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href") or r.get("url", ""),
                        "snippet": r.get("body", ""),
                    }
                )
            return results

    try:
        results = await asyncio.to_thread(_search)
        return _ok({"query": query, "results": results})
    except Exception as exc:  # noqa: BLE001
        return _err(f"search failed: {exc}")


async def _run_http_request(args: dict, ctx: TaskContext) -> dict:
    method = args["method"].upper()
    url = args["url"]
    if not re.match(r"^https?://", url):
        return _err("only http(s) URLs are allowed")
    headers = args.get("headers") or {}
    body = args.get("body")
    timeout = int(args.get("timeout", 20))

    client = ctx.http or httpx.AsyncClient(follow_redirects=True, timeout=timeout)
    try:
        resp = await client.request(method, url, headers=headers, content=body, timeout=timeout)
        try:
            text = resp.text
        except Exception:  # noqa: BLE001
            text = base64.b64encode(resp.content).decode("ascii")
        return _ok(
            {
                "status": resp.status_code,
                "headers": dict(resp.headers),
                "body": _truncate(text, 20_000),
                "final_url": str(resp.url),
            }
        )
    except httpx.HTTPError as exc:
        return _err(f"http error: {exc}")
    finally:
        if ctx.http is None:
            await client.aclose()


SANDBOX_PREAMBLE = textwrap.dedent(
    """
    import os, sys, resource, builtins
    # Drop network access in subprocess by removing socket module references.
    for mod in ("socket", "urllib.request", "http.client"):
        sys.modules.pop(mod, None)
    # Cap memory + CPU.
    try:
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
    except (ValueError, OSError):
        pass
    os.chdir(os.environ["AGENT_WORKSPACE"])
    """
).strip()


async def _run_code_executor(args: dict, ctx: TaskContext) -> dict:
    code = args["code"]
    stdin = args.get("stdin", "")
    timeout = int(args.get("timeout", 30))

    full_code = SANDBOX_PREAMBLE + "\n\n" + code
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "AGENT_WORKSPACE": str(ctx.workspace),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    try:
        proc = await asyncio.create_subprocess_exec(
            "python3",
            "-I",
            "-c",
            full_code,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(ctx.workspace),
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(stdin.encode("utf-8")), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return _err(f"execution exceeded {timeout}s wall clock")
    except FileNotFoundError:
        return _err("python3 not available in sandbox")
    except Exception as exc:  # noqa: BLE001
        return _err(f"sandbox failed: {exc}")

    return _ok(
        {
            "exit_code": proc.returncode,
            "stdout": _truncate(stdout_b.decode("utf-8", "replace"), 20_000),
            "stderr": _truncate(stderr_b.decode("utf-8", "replace"), 10_000),
        }
    )


async def _run_file_manager(args: dict, ctx: TaskContext) -> dict:
    action = args["action"]
    rel = args["path"]
    try:
        path = ctx.safe_path(rel)
    except ValueError as exc:
        return _err(str(exc))

    if action == "list":
        target = path if path.is_dir() else path.parent
        if not target.exists():
            return _err(f"no such directory: {rel}")
        entries = []
        for child in sorted(target.iterdir()):
            entries.append(
                {
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                    "size": child.stat().st_size if child.is_file() else None,
                }
            )
        return _ok({"path": str(target.relative_to(ctx.workspace)), "entries": entries})

    if action == "read":
        if not path.exists() or not path.is_file():
            return _err(f"no such file: {rel}")
        max_bytes = int(args.get("max_bytes", 20_000))
        data = path.read_bytes()[:max_bytes]
        try:
            text = data.decode("utf-8")
            return _ok({"path": rel, "content": text, "bytes": len(data)})
        except UnicodeDecodeError:
            return _ok(
                {
                    "path": rel,
                    "content_b64": base64.b64encode(data).decode("ascii"),
                    "bytes": len(data),
                    "binary": True,
                }
            )

    if action in ("write", "append"):
        content = args.get("content")
        if content is None:
            return _err(f"{action} requires `content`")
        if path.exists() and path.is_file() and path.stat().st_size > 0:
            approved = await _confirm(
                ctx,
                f"file_{action}",
                {"path": rel, "preview": content[:300], "existing_bytes": path.stat().st_size},
            )
            if not approved:
                return {
                    "ok": False,
                    "data": None,
                    "error": "user declined confirmation",
                    "requires_confirmation": True,
                }
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if action == "append" else "w"
        with path.open(mode, encoding="utf-8") as fh:
            fh.write(content)
        return _ok({"path": rel, "bytes_written": len(content)})

    if action == "delete":
        if not path.exists():
            return _err(f"no such path: {rel}")
        approved = await _confirm(ctx, "file_delete", {"path": rel})
        if not approved:
            return {
                "ok": False,
                "data": None,
                "error": "user declined confirmation",
                "requires_confirmation": True,
            }
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    child.unlink()
            for child in sorted(path.rglob("*"), reverse=True):
                if child.is_dir():
                    child.rmdir()
            path.rmdir()
        else:
            path.unlink()
        return _ok({"path": rel, "deleted": True})

    return _err(f"unknown action: {action}")


async def _run_send_email(args: dict, ctx: TaskContext) -> dict:
    to = args["to"].strip()
    subject = args["subject"]
    body = args["body"]
    html = bool(args.get("html", False))

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", to):
        return _err(f"invalid recipient: {to}")

    approved = await _confirm(
        ctx,
        "send_email",
        {"to": to, "subject": subject, "preview": body[:300]},
    )
    if not approved:
        return {
            "ok": False,
            "data": None,
            "error": "user declined confirmation",
            "requires_confirmation": True,
        }

    if not ctx.smtp.enabled:
        return _ok(
            {
                "delivered": False,
                "reason": "SMTP disabled — dry run",
                "to": to,
                "subject": subject,
            }
        )

    import aiosmtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = ctx.smtp.from_addr or ctx.smtp.username
    msg["To"] = to
    msg["Subject"] = subject
    if html:
        msg.set_content("This message is HTML — view in an HTML-capable client.")
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)

    try:
        await aiosmtplib.send(
            msg,
            hostname=ctx.smtp.host,
            port=ctx.smtp.port,
            username=ctx.smtp.username,
            password=ctx.smtp.password,
            start_tls=ctx.smtp.port == 587,
            use_tls=ctx.smtp.port == 465,
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"smtp failure: {exc}")

    return _ok({"delivered": True, "to": to, "subject": subject})


async def _run_recall_memory(args: dict, ctx: TaskContext) -> dict:
    from .memory import MemoryStore

    store: MemoryStore | None = ctx.metadata.get("memory_store")
    if store is None:
        return _ok({"hits": []})
    hits = await asyncio.to_thread(store.search, args["query"], int(args.get("k", 3)))
    return _ok({"hits": hits})


async def _run_submit_final_answer(args: dict, ctx: TaskContext) -> dict:
    return _ok(
        {
            "final": True,
            "answer": args["answer"],
            "artifacts": args.get("artifacts", []),
        }
    )


TOOL_RUNNERS: dict[str, Callable[[dict, TaskContext], Awaitable[dict]]] = {
    "web_search": _run_web_search,
    "http_request": _run_http_request,
    "code_executor": _run_code_executor,
    "file_manager": _run_file_manager,
    "send_email": _run_send_email,
    "recall_memory": _run_recall_memory,
    "submit_final_answer": _run_submit_final_answer,
}


async def execute_tool(name: str, args: dict, ctx: TaskContext) -> dict:
    runner = TOOL_RUNNERS.get(name)
    if runner is None:
        return _err(f"unknown tool: {name}")
    try:
        return await runner(args or {}, ctx)
    except Exception as exc:  # noqa: BLE001
        return _err(f"tool crashed: {exc.__class__.__name__}: {exc}")
