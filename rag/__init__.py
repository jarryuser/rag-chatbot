# RAG Chatbot - rag package
# Exposes the two main entry points: ingest() and get_answer()

from .ingestor import ingest, ingest_url
from .retriever import get_answer

__all__ = ["ingest", "ingest_url", "get_answer"]
