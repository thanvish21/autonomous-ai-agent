"""Agent package.

Imports are lazy so that lightweight consumers (tools, memory) don't pull in
heavy deps (anthropic, langgraph) unless the full Agent is actually used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Agent, AgentEvent

from .memory import MemoryStore

__all__ = ["Agent", "AgentEvent", "MemoryStore"]


def __getattr__(name: str):
    if name in ("Agent", "AgentEvent"):
        from . import core

        return getattr(core, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
