"""Long-term memory backed by ChromaDB.

Stores per-task summaries and exposes a semantic search. Falls back to a
naive in-memory keyword store if ChromaDB cannot be initialised (e.g. during
unit tests with no native deps).
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MemoryRecord:
    task_id: str
    summary: str
    tags: list[str]
    created_at: float


class MemoryStore:
    """Vector-search memory with a graceful fallback."""

    def __init__(self, persist_dir: str | Path = "./chroma") -> None:
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._fallback: list[MemoryRecord] = []
        self._collection = None
        self._init_chroma()

    def _init_chroma(self) -> None:
        try:
            import chromadb
            from chromadb.config import Settings

            client = chromadb.PersistentClient(
                path=str(self.persist_dir),
                settings=Settings(anonymized_telemetry=False, allow_reset=True),
            )
            self._collection = client.get_or_create_collection("task_memory")
        except Exception:  # noqa: BLE001
            # Library missing or native dep failure — fall back to keyword search.
            self._collection = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, task_id: str, summary: str, tags: list[str] | None = None) -> None:
        tags = tags or []
        record = MemoryRecord(
            task_id=task_id, summary=summary, tags=tags, created_at=time.time()
        )
        if self._collection is not None:
            self._collection.upsert(
                ids=[task_id],
                documents=[summary],
                metadatas=[{"tags": ",".join(tags), "created_at": record.created_at}],
            )
        else:
            self._fallback = [r for r in self._fallback if r.task_id != task_id]
            self._fallback.append(record)

    def search(self, query: str, k: int = 3) -> list[dict[str, Any]]:
        if self._collection is not None:
            try:
                res = self._collection.query(query_texts=[query], n_results=k)
                hits: list[dict[str, Any]] = []
                ids = (res.get("ids") or [[]])[0]
                docs = (res.get("documents") or [[]])[0]
                metas = (res.get("metadatas") or [[]])[0]
                dists = (res.get("distances") or [[None] * len(ids)])[0]
                for tid, doc, meta, dist in zip(ids, docs, metas, dists):
                    hits.append(
                        {
                            "task_id": tid,
                            "summary": doc,
                            "tags": (meta or {}).get("tags", ""),
                            "score": None if dist is None else 1.0 - dist,
                        }
                    )
                return hits
            except Exception:  # noqa: BLE001
                pass
        return self._keyword_search(query, k)

    def _keyword_search(self, query: str, k: int) -> list[dict[str, Any]]:
        terms = {t.lower() for t in re.findall(r"\w+", query) if len(t) > 2}
        scored: list[tuple[float, MemoryRecord]] = []
        for record in self._fallback:
            words = {t.lower() for t in re.findall(r"\w+", record.summary)}
            overlap = len(terms & words)
            if overlap:
                scored.append((overlap / max(len(terms), 1), record))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "task_id": r.task_id,
                "summary": r.summary,
                "tags": ",".join(r.tags),
                "score": s,
            }
            for s, r in scored[:k]
        ]

    def reset(self) -> None:
        self._fallback.clear()
        if self._collection is not None:
            try:
                self._collection.delete(where={})
            except Exception:  # noqa: BLE001
                pass
