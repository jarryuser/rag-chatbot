"""
retriever.py — Retrieval and answer generation using LCEL.

Each session has its own ChromaDB directory (chroma_db/{session_id}/),
so queries are always scoped to the documents uploaded in that session.

Flow:
  question + session_id + history
    → load session's ChromaDB collection
    → cosine similarity search → top-k Document objects
    → format context string
    → build message list: [SystemMessage] + prior turns + HumanMessage
    → ChatGroq / Llama 3.3 70B
    → StrOutputParser → answer string
"""

from langchain_groq import ChatGroq
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser

from .prompts import SYSTEM_MESSAGE

CHROMA_BASE_DIR = "./chroma_db"

# How many chunks to retrieve per query.
TOP_K = 4

# Maximum number of prior messages to include for conversational memory.
# 10 messages = ~5 conversation turns. Keeps token usage predictable.
MAX_HISTORY = 10

# Groq LLM — free tier, no credit card required.
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_TEMPERATURE = 0.0

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Singleton — shared with ingestor.py, loaded once at startup.
_embeddings: HuggingFaceEmbeddings | None = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    return _embeddings


def _chroma_dir(session_id: str) -> str:
    return f"{CHROMA_BASE_DIR}/{session_id}"


def _load_vectorstore(session_id: str) -> Chroma:
    """Load the ChromaDB collection for a specific session."""
    return Chroma(
        persist_directory=_chroma_dir(session_id),
        embedding_function=_get_embeddings(),
    )


def _format_docs(docs: list) -> str:
    return "\n\n---\n\n".join(doc.page_content for doc in docs)


def _build_sources(docs: list) -> str:
    seen = set()
    parts = []
    for doc in docs:
        ref = (
            f"{doc.metadata.get('source', 'unknown')} "
            f"p.{doc.metadata.get('page', '?')}"
        )
        if ref not in seen:
            seen.add(ref)
            parts.append(ref)
    return ", ".join(parts)


def get_answer(
    question: str,
    session_id: str = "default",
    history: list[dict] | None = None,
) -> dict:
    """
    Retrieve relevant chunks and generate an answer, incorporating prior turns.

    Args:
        question:   The user's natural-language question.
        session_id: The chat session to query documents from.
        history:    Prior messages as [{"role": "user"|"assistant", "content": str}].
                    The last MAX_HISTORY entries are injected before the current
                    question so the model can answer follow-up questions correctly.

    Returns a dict with "answer", "sources", and "source_documents".
    Raises RuntimeError if no documents have been indexed for this session.
    """
    vectorstore = _load_vectorstore(session_id)

    if vectorstore._collection.count() == 0:
        raise RuntimeError(
            "No documents indexed in this chat yet. Please upload a file first."
        )

    retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": TOP_K},
    )

    # Step 1: retrieve relevant chunks
    source_docs = retriever.invoke(question)
    context = _format_docs(source_docs)

    # Step 2: build message list.
    # Using concrete message objects instead of a prompt template so that
    # user-provided text (which may contain curly braces) never causes errors.
    lc_messages: list = [SystemMessage(content=SYSTEM_MESSAGE.format(context=context))]

    # Inject the tail of the conversation history for memory.
    for msg in (history or [])[-MAX_HISTORY:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        else:
            lc_messages.append(AIMessage(content=content))

    # Current turn
    lc_messages.append(HumanMessage(content=question))

    # Step 3: LCEL chain - messages | llm | parser
    llm = ChatGroq(model=LLM_MODEL, temperature=LLM_TEMPERATURE)
    chain = llm | StrOutputParser()

    answer = chain.invoke(lc_messages)

    return {
        "answer": answer.strip(),
        "sources": _build_sources(source_docs),
        "source_documents": source_docs,
    }
