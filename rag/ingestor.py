"""
ingestor.py - Document loading and indexing pipeline.

Flow:
  file path -> DocumentLoader -> parent split -> child split -> Embeddings -> ChromaDB
                                      |
                                      v
                               parents.json (per session)

Each session gets its own isolated ChromaDB directory:
  chroma_db/{session_id}/

Child chunks (CHILD_CHUNK_SIZE chars) are stored in ChromaDB for precise
similarity search. Each child carries a parent_id pointing to a larger
parent chunk (PARENT_CHUNK_SIZE chars) saved in parents.json.
On retrieval, child results are expanded to their parents so the LLM
gets more context than the narrow search window provides.
"""

import os
import uuid
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

from .parents import load_parents, save_parents

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHROMA_BASE_DIR = "./chroma_db"

# Parent chunks - larger context window passed to the LLM.
PARENT_CHUNK_SIZE = 2000

# Child chunks - smaller units indexed in ChromaDB for precise retrieval.
CHILD_CHUNK_SIZE = 400
CHILD_CHUNK_OVERLAP = 50

_embeddings: HuggingFaceEmbeddings | None = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    return _embeddings


def _chroma_dir(session_id: str) -> str:
    return f"{CHROMA_BASE_DIR}/{session_id}"


def _load_document(file_path: str) -> list[Document]:
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return PyPDFLoader(file_path).load()
    elif ext in (".txt", ".md"):
        return TextLoader(file_path, encoding="utf-8").load()
    elif ext == ".docx":
        from langchain_community.document_loaders import Docx2txtLoader
        return Docx2txtLoader(file_path).load()
    elif ext in (".csv", ".xls", ".xlsx"):
        return _load_tabular(file_path, ext)
    else:
        raise ValueError(
            f"Unsupported file type: {ext}. "
            "Supported: .pdf, .txt, .md, .docx, .csv, .xls, .xlsx"
        )


def _load_tabular(file_path: str, ext: str) -> list[Document]:
    """Convert a CSV or Excel file into one Document per row (column-aware)."""
    import pandas as pd

    df = pd.read_csv(file_path) if ext == ".csv" else pd.read_excel(file_path)
    docs = []
    for i, row in df.iterrows():
        content = "\n".join(
            f"{col}: {val}"
            for col, val in row.items()
            if pd.notna(val) and str(val).strip()
        )
        if content:
            docs.append(Document(page_content=content, metadata={"row": i + 1}))
    return docs


_parent_splitter = RecursiveCharacterTextSplitter(
    chunk_size=PARENT_CHUNK_SIZE,
    chunk_overlap=0,
    separators=["\n\n", "\n", ".", " ", ""],
)

_child_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHILD_CHUNK_SIZE,
    chunk_overlap=CHILD_CHUNK_OVERLAP,
    separators=["\n\n", "\n", ".", " ", ""],
)


def _split_with_parents(docs: list[Document]) -> tuple[list[Document], dict[str, dict]]:
    """
    Split docs into parent chunks (for LLM context) and child chunks (for search).
    Returns (child_chunks, parents_dict) where parents_dict maps parent_id -> {text, metadata}.
    """
    child_chunks = []
    parents_dict = {}

    for parent in _parent_splitter.split_documents(docs):
        parent_id = str(uuid.uuid4())
        parents_dict[parent_id] = {
            "text": parent.page_content,
            "metadata": parent.metadata,
        }
        for child in _child_splitter.split_documents([parent]):
            child.metadata["parent_id"] = parent_id
            child_chunks.append(child)

    return child_chunks, parents_dict


def ingest(file_path: str, display_name: str | None = None, session_id: str = "default") -> int:
    """
    Index a document into the ChromaDB collection for the given session.

    Args:
        file_path:    Path to the file on disk (may be a temp path).
        display_name: Human-readable filename shown in source citations.
        session_id:   ID of the chat session.

    Returns the number of child chunks stored.
    """
    label = display_name or Path(file_path).name

    docs = _load_document(file_path)
    for doc in docs:
        doc.metadata["source"] = label

    child_chunks, parents_dict = _split_with_parents(docs)

    if not child_chunks:
        raise ValueError("No text could be extracted from the document.")

    # Merge new parents into the session store
    existing = load_parents(session_id)
    existing.update(parents_dict)
    save_parents(session_id, existing)

    Chroma.from_documents(
        documents=child_chunks,
        embedding=_get_embeddings(),
        persist_directory=_chroma_dir(session_id),
    )

    return len(child_chunks)


def ingest_url(url: str, session_id: str = "default") -> tuple[int, str]:
    """Fetch a web page and index it. Returns (n_chunks, display_name)."""
    from langchain_community.document_loaders import WebBaseLoader

    loader = WebBaseLoader(web_path=url)
    docs = loader.load()

    if not docs:
        raise ValueError("No content could be extracted from the URL.")

    display_name = (docs[0].metadata.get("title") or "").strip() or url
    for doc in docs:
        doc.metadata["source"] = display_name

    child_chunks, parents_dict = _split_with_parents(docs)

    if not child_chunks:
        raise ValueError("No text content found at the given URL.")

    existing = load_parents(session_id)
    existing.update(parents_dict)
    save_parents(session_id, existing)

    Chroma.from_documents(
        documents=child_chunks,
        embedding=_get_embeddings(),
        persist_directory=_chroma_dir(session_id),
    )

    return len(child_chunks), display_name
