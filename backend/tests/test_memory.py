from pathlib import Path

from backend.agent.memory import MemoryStore


def test_keyword_fallback_when_no_chroma(tmp_path: Path, monkeypatch):
    store = MemoryStore(persist_dir=tmp_path)
    # Force fallback path even if chromadb is installed in dev env.
    store._collection = None
    store.add("t1", "Researched python web frameworks fastapi flask django", ["web"])
    store.add("t2", "Analyzed sales csv for anomalies via pandas", ["data"])
    hits = store.search("python frameworks comparison", k=2)
    assert hits
    assert hits[0]["task_id"] == "t1"
