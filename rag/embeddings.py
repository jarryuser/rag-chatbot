"""One embedding model shared by ingestion and retrieval."""

from threading import Lock

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_embeddings = None
_lock = Lock()


def _get_embeddings():
    global _embeddings
    with _lock:
        if _embeddings is None:
            from langchain_huggingface import HuggingFaceEmbeddings
            _embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        return _embeddings
