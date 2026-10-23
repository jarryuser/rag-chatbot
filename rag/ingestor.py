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

import uuid
import hashlib
from urllib.parse import urldefrag
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma

from .indexing import (DocumentConflict, IngestionResult, recover_index, load_manifest,
                       find_existing, replace_document, delete_document)
from .embeddings import _get_embeddings
from .limits import MAX_DOCUMENT_CHARS, ResourceLimitError
from .storage import session_directory
from .web import fetch_page

CHROMA_BASE_DIR = "./chroma_db"

# Parent chunks - larger context window passed to the LLM.
PARENT_CHUNK_SIZE = 2000

# Child chunks - smaller units indexed in ChromaDB for precise retrieval.
CHILD_CHUNK_SIZE = 400
CHILD_CHUNK_OVERLAP = 50


def _chroma_dir(session_id: str) -> str:
    return str(session_directory(Path(CHROMA_BASE_DIR), session_id, allow_default=True))


def _check_document(docs):
    if sum(len(doc.page_content) for doc in docs) > MAX_DOCUMENT_CHARS:
        raise ResourceLimitError("Document exceeds the 2 million character limit.")


def _store(session_id):
    directory = Path(_chroma_dir(session_id))
    store = Chroma(persist_directory=str(directory), embedding_function=_get_embeddings())
    recover_index(store, directory)
    return store, directory


def remove_document(session_id, source):
    store, directory = _store(session_id)
    delete_document(store, directory, source)


def _existing(store, directory, key, fingerprint, replace):
    previous, unchanged = find_existing(load_manifest(store, directory), key, fingerprint)
    if unchanged:
        return IngestionResult(previous["chunks"], previous["source"], "skipped", previous["id"])
    if previous and not replace:
        raise DocumentConflict(previous["source"])
    return None


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


def ingest(file_path: str, display_name: str | None = None, session_id: str = "default",
           *, replace=False, return_result=False):
    label = display_name or Path(file_path).name
    fingerprint = hashlib.sha256()
    fingerprint.update(Path(file_path).suffix.lower().encode())
    with open(file_path, "rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            fingerprint.update(block)
    fingerprint = fingerprint.hexdigest()
    key = "file:" + label
    store, directory = _store(session_id)
    result = _existing(store, directory, key, fingerprint, replace)
    if result is None:
        docs = _load_document(file_path)
        for doc in docs:
            doc.metadata["source"] = label
        _check_document(docs)
        children, parents = _split_with_parents(docs)
        if not children:
            raise ValueError("No text could be extracted from the document.")
        result = replace_document(store, directory, key, label, fingerprint, children, parents, replace=replace)
    return result if return_result else result.chunks


def ingest_url(url: str, session_id: str = "default", *, replace=False, return_result=False):
    from bs4 import BeautifulSoup

    content, final_url = fetch_page(url)
    final_url = urldefrag(final_url)[0]
    key = "url:" + final_url
    fingerprint = hashlib.sha256(content).hexdigest()
    store, directory = _store(session_id)
    result = _existing(store, directory, key, fingerprint, replace)
    if result is None:
        soup = BeautifulSoup(content, "html.parser")
        label = (soup.title.get_text(strip=True) if soup.title else final_url)[:255] or final_url
        for element in soup(["script", "style", "nav", "footer"]):
            element.decompose()
        docs = [Document(page_content=soup.get_text(separator="\n", strip=True),
                         metadata={"source": label, "url": final_url})]
        _check_document(docs)
        children, parents = _split_with_parents(docs)
        if not children:
            raise ValueError("No text content found at the given URL.")
        result = replace_document(store, directory, key, label, fingerprint, children, parents, replace=replace)
    return result if return_result else (result.chunks, result.source)
