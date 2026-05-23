# RAG Chatbot - rag package
# Exposes the two main entry points: ingest() and get_answer()

from .ingestor import ingest
from .retriever import get_answer

__all__ = ["ingest", "get_answer"]
