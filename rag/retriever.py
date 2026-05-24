"""
retriever.py - Retrieval and answer generation using LCEL.

Each session has its own ChromaDB directory (chroma_db/{session_id}/),
so queries are always scoped to the documents uploaded in that session.

Flow:
  question + session_id + history
    -> load session's ChromaDB collection
    -> vector search (top RERANK_CANDIDATES) + BM25 keyword search
    -> Reciprocal Rank Fusion -> merged candidate list
    -> cross-encoder re-ranking -> top TOP_K chunks
    -> format context string
    -> build message list: [SystemMessage] + prior turns + HumanMessage
    -> ChatGroq / Llama 3.3 70B
    -> StrOutputParser -> answer string
"""

from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder
from langchain_groq import ChatGroq
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser

from .prompts import SYSTEM_MESSAGE
from .parents import load_parents

CHROMA_BASE_DIR = "./chroma_db"

# Final number of chunks passed to the LLM after re-ranking.
TOP_K = 4

# How many candidates to fetch from ChromaDB before re-ranking.
# More candidates = better recall for the cross-encoder to work with.
RERANK_CANDIDATES = TOP_K * 3

# Maximum number of prior messages to include for conversational memory.
# 10 messages = ~5 conversation turns. Keeps token usage predictable.
MAX_HISTORY = 10

# Groq LLM - free tier, no credit card required.
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_TEMPERATURE = 0.0

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Singletons loaded once at startup.
_embeddings: HuggingFaceEmbeddings | None = None
_reranker: CrossEncoder | None = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    return _embeddings


def _get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(RERANKER_MODEL)
    return _reranker


def _chroma_dir(session_id: str) -> str:
    return f"{CHROMA_BASE_DIR}/{session_id}"


def _load_vectorstore(session_id: str) -> Chroma:
    """Load the ChromaDB collection for a specific session."""
    return Chroma(
        persist_directory=_chroma_dir(session_id),
        embedding_function=_get_embeddings(),
    )


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


def _bm25_search(question: str, vectorstore: Chroma) -> list[Document]:
    """Keyword search over all chunks in the session using BM25Okapi."""
    data = vectorstore.get()
    texts = data["documents"]
    metadatas = data["metadatas"]

    if not texts:
        return []

    bm25 = BM25Okapi([_tokenize(t) for t in texts])
    scores = bm25.get_scores(_tokenize(question))
    top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:RERANK_CANDIDATES]
    return [Document(page_content=texts[i], metadata=metadatas[i]) for i in top_idx]


def _rrf(lists: list[list[Document]], k: int = 60) -> list[Document]:
    """
    Reciprocal Rank Fusion over multiple ranked lists.
    score(d) = sum(1 / (k + rank)) across all lists that contain d.
    """
    scores: dict[str, float] = {}
    doc_map: dict[str, Document] = {}

    for ranked in lists:
        for rank, doc in enumerate(ranked):
            key = doc.page_content
            if key not in doc_map:
                scores[key] = 0.0
                doc_map[key] = doc
            scores[key] += 1.0 / (k + rank + 1)

    merged = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [doc_map[key] for key in merged[:RERANK_CANDIDATES]]


def _hybrid_retrieve(question: str, vectorstore: Chroma) -> list[Document]:
    """Combine vector search and BM25, merge with RRF."""
    vector_docs = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": RERANK_CANDIDATES},
    ).invoke(question)

    bm25_docs = _bm25_search(question, vectorstore)
    return _rrf([vector_docs, bm25_docs])


def _rerank(question: str, docs: list) -> list:
    """Re-score docs with a cross-encoder and return the top TOP_K by relevance."""
    pairs = [(question, doc.page_content) for doc in docs]
    scores = _get_reranker().predict(pairs)
    ranked = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)
    return [doc for _, doc in ranked[:TOP_K]]


def _resolve_parents(docs: list[Document], session_id: str) -> list[Document]:
    """
    Swap child chunks for their parent chunks where available.
    Deduplicates by parent_id so the same parent isn't passed twice.
    Falls back to the child chunk for sessions ingested before parent-child was added.
    """
    parents = load_parents(session_id)
    result = []
    seen: set[str] = set()

    for doc in docs:
        parent_id = doc.metadata.get("parent_id")
        if parent_id and parent_id in parents and parent_id not in seen:
            seen.add(parent_id)
            entry = parents[parent_id]
            result.append(Document(page_content=entry["text"], metadata=entry["metadata"]))
        elif not parent_id or parent_id not in parents:
            result.append(doc)

    return result


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

    # Step 1: hybrid retrieval (vector + BM25 via RRF), re-rank, then expand to parents.
    candidates = _hybrid_retrieve(question, vectorstore)
    reranked = _rerank(question, candidates) if len(candidates) > TOP_K else candidates
    source_docs = _resolve_parents(reranked, session_id)
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
