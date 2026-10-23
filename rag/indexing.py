"""Document identity, replacement, and recoverable index updates."""

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from .limits import MAX_CHUNKS_PER_SESSION, MAX_DOCUMENTS_PER_SESSION, ResourceLimitError
from .storage import write_json


class DocumentNotFound(ValueError):
    pass


class DocumentConflict(ValueError):
    def __init__(self, source):
        self.source = source
        super().__init__(f"A different version of '{source}' is already indexed.")


@dataclass
class IngestionResult:
    chunks: int
    source: str
    status: str
    document_id: str


def _read(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def document_names(directory: Path):
    journal = directory / "index-journal.json"
    documents = (_read(journal, {})["previous_documents"] if journal.exists()
                 else _read(directory / "documents.json", None))
    return list(dict.fromkeys(record["source"] for record in documents.values())) if documents is not None else None


def recover_index(store, directory: Path):
    journal_path = directory / "index-journal.json"
    if not journal_path.exists():
        return
    journal = _read(journal_path, {})
    if journal["new_ids"]:
        store.delete(ids=journal["new_ids"])
    old = journal["old_vectors"]
    if old["ids"]:
        store._collection.upsert(**old)
    write_json(directory / "parents.json", journal["previous_parents"])
    write_json(directory / "documents.json", journal["previous_documents"])
    journal_path.unlink()


def load_manifest(store, directory):
    existing = _read(directory / "documents.json", None)
    if existing is not None:
        return existing
    documents = {}
    for metadata in store.get(include=["metadatas"])["metadatas"]:
        metadata = metadata or {}
        source = metadata.get("source", "unknown")
        key = metadata.get("source_key") or ("url:" + metadata["url"] if metadata.get("url") else "file:" + source)
        record = documents.setdefault(key, {
            "id": metadata.get("document_id") or str(uuid.uuid4()), "source": source,
            "hash": metadata.get("content_hash"), "chunks": 0, "legacy": not metadata.get("document_id"),
            "legacy_url": metadata.get("url"),
        })
        record["chunks"] += 1
    return documents


def find_existing(documents, key, fingerprint):
    existing = documents.get(key)
    if existing:
        return existing, existing.get("hash") == fingerprint
    # Different URLs remain distinct references, even when their text is identical.
    if key.startswith("file:"):
        for other_key, record in documents.items():
            if other_key.startswith("file:") and record.get("hash") == fingerprint:
                return record, True
    return None, False


def _snapshot(store, record):
    if not record:
        return {"ids": [], "documents": [], "metadatas": [], "embeddings": []}
    if record.get("legacy"):
        where = {"source": record["source"]}
        if record.get("legacy_url"):
            where = {"$and": [where, {"url": record["legacy_url"]}]}
    else:
        where = {"document_id": record["id"]}
    data = store.get(where=where, include=["documents", "metadatas", "embeddings"])
    embeddings = data["embeddings"]
    return {"ids": data["ids"], "documents": data["documents"], "metadatas": data["metadatas"],
            "embeddings": embeddings.tolist() if hasattr(embeddings, "tolist") else embeddings}


def _commit(store, directory, documents, parents, old, new_ids, write_vectors):
    journal = directory / "index-journal.json"
    write_json(journal, {"previous_documents": load_manifest(store, directory),
                        "previous_parents": _read(directory / "parents.json", {}),
                        "old_vectors": old, "new_ids": new_ids})
    try:
        if old["ids"]:
            store.delete(ids=old["ids"])
        write_vectors()
        write_json(directory / "parents.json", parents)
        write_json(directory / "documents.json", documents)
        journal.unlink()
    except Exception:
        # A failed rollback leaves the journal for recovery before the next operation.
        recover_index(store, directory)
        raise


def replace_document(store, directory, key, source, fingerprint, children, parents, *, replace=False):
    recover_index(store, directory)
    documents = load_manifest(store, directory)
    previous, unchanged = find_existing(documents, key, fingerprint)
    if unchanged:
        return IngestionResult(previous["chunks"], previous["source"], "skipped", previous["id"])
    if previous and not replace:
        raise DocumentConflict(previous["source"])
    if not previous and len(documents) >= MAX_DOCUMENTS_PER_SESSION:
        raise ResourceLimitError("Maximum of 20 documents per session reached.")
    old = _snapshot(store, previous)
    if store._collection.count() - len(old["ids"]) + len(children) > MAX_CHUNKS_PER_SESSION:
        raise ResourceLimitError("Session exceeds the 10,000 chunk limit.")
    document_id = previous["id"] if previous else str(uuid.uuid4())
    if previous:
        source = previous["source"]
    if any(other_key != key and record["source"] == source for other_key, record in documents.items()):
        source = f"{source} ({key.removeprefix('url:')})"
    metadata = {"document_id": document_id, "source_key": key, "source": source, "content_hash": fingerprint}
    for child in children:
        child.metadata.update(metadata)
    for parent in parents.values():
        parent["metadata"].update(metadata)
    existing_parents = _read(directory / "parents.json", {})
    if previous:
        existing_parents = {pid: entry for pid, entry in existing_parents.items()
                            if not _belongs_to(entry["metadata"], previous)}
    existing_parents.update(parents)
    updated = {**documents, key: {"id": document_id, "source": source,
                                 "hash": fingerprint, "chunks": len(children), "legacy": False}}
    ids = [str(uuid.uuid4()) for _ in children]
    _commit(store, directory, updated, existing_parents, old, ids,
            lambda: store.add_documents(children, ids=ids))
    return IngestionResult(len(children), source, "replaced" if previous else "created", document_id)


def _belongs_to(metadata, record):
    if record.get("legacy"):
        return (metadata.get("source") == record["source"] and
                (not record.get("legacy_url") or metadata.get("url") == record["legacy_url"]))
    return metadata.get("document_id") == record["id"]


def delete_document(store, directory, source):
    recover_index(store, directory)
    documents = load_manifest(store, directory)
    matches = [(key, record) for key, record in documents.items() if record["source"] == source]
    if not matches:
        raise DocumentNotFound("Document not found.")
    if len(matches) != 1:
        raise ValueError("Ambiguous legacy document name. Rename or reindex the documents first.")
    key, record = matches[0]
    parents = {pid: entry for pid, entry in _read(directory / "parents.json", {}).items()
               if not _belongs_to(entry["metadata"], record)}
    updated = {k: value for k, value in documents.items() if k != key}
    _commit(store, directory, updated, parents, _snapshot(store, record), [], lambda: None)
