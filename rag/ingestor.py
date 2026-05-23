"""
ingestor.py — Document loading and indexing pipeline.

Flow:
  file path → DocumentLoader → TextSplitter → Embeddings → ChromaDB

Each session gets its own isolated ChromaDB directory:
  chroma_db/{session_id}/
This means uploading a file to one chat never affects another chat.
"""

import os
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

# Free local embeddings model — no API key required.
# Must match the model used in retriever.py so vectors are compatible.
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Root directory for all ChromaDB data.
# Each session lives in CHROMA_BASE_DIR/{session_id}/
CHROMA_BASE_DIR = "./chroma_db"

# Chunk configuration
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# Module-level singleton — loaded once, reused across all requests.
_embeddings: HuggingFaceEmbeddings | None = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    return _embeddings


def _chroma_dir(session_id: str) -> str:
    """Return the ChromaDB directory for a given session."""
    return f"{CHROMA_BASE_DIR}/{session_id}"


def _load_document(file_path: str):
    """
    Load a document using the appropriate LangChain loader.
    Supports PDF and plain-text files.
    """
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
    elif ext in (".txt", ".md"):
        loader = TextLoader(file_path, encoding="utf-8")
    else:
        raise ValueError(f"Unsupported file type: {ext}. Supported: .pdf, .txt, .md")
    return loader.load()


def ingest(file_path: str, display_name: str | None = None, session_id: str = "default") -> int:
    """
    Index a document into the ChromaDB collection for the given session.

    Args:
        file_path:    Path to the file on disk (may be a temp path).
        display_name: Human-readable filename shown in source citations.
        session_id:   ID of the chat session — determines which ChromaDB
                      sub-directory the chunks are stored in.

    Returns the number of chunks stored.
    """
    label = display_name or Path(file_path).name

    # 1. Load
    docs = _load_document(file_path)

    # Overwrite 'source' metadata with the friendly display name so citations
    # show "resume.pdf p.1" instead of a temp path like /var/folders/…
    for doc in docs:
        doc.metadata["source"] = label

    # 2. Split
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", " ", ""],
    )
    chunks = splitter.split_documents(docs)

    if not chunks:
        raise ValueError("No text could be extracted from the document.")

    # 3 & 4. Embed and store in this session's ChromaDB directory.
    # Chroma 0.4+ auto-persists - no need to call .persist() manually.
    Chroma.from_documents(
        documents=chunks,
        embedding=_get_embeddings(),
        persist_directory=_chroma_dir(session_id),
    )

    return len(chunks)
