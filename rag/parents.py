"""
Shared helpers for the parent-chunk store.

Parent chunks are saved alongside ChromaDB in:
  chroma_db/{session_id}/parents.json

Format: {parent_id: {"text": str, "metadata": dict}}

Child chunks in ChromaDB carry a "parent_id" metadata field pointing here.
On retrieval, child chunks are swapped for their parent to give the LLM
more context than the narrow search window provides.
"""

import json
from pathlib import Path

CHROMA_BASE_DIR = "./chroma_db"


def _parents_path(session_id: str) -> Path:
    return Path(f"{CHROMA_BASE_DIR}/{session_id}/parents.json")


def load_parents(session_id: str) -> dict[str, dict]:
    path = _parents_path(session_id)
    return json.loads(path.read_text()) if path.exists() else {}


def save_parents(session_id: str, parents: dict[str, dict]) -> None:
    path = _parents_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(parents))


def drop_source_parents(session_id: str, source: str) -> None:
    """Remove all parent entries whose source metadata matches the given filename."""
    parents = load_parents(session_id)
    pruned = {
        pid: p for pid, p in parents.items()
        if p["metadata"].get("source") != source
    }
    save_parents(session_id, pruned)
