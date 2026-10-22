"""
FastAPI backend for the RAG Chatbot.

Run with:
    uvicorn server:app --reload --port 8000

Endpoints:
    GET    /api/sessions - list all sessions
    POST   /api/sessions - create a new session
    PATCH  /api/sessions/{id} - rename a session
    POST   /api/sessions/{id}/auto-name - generate a title from the first message
    DELETE /api/sessions/{id} - delete session and its documents
    POST   /api/upload?session_id= - upload and index a document
    POST   /api/chat - ask a question (session_id + optional history)
    POST   /api/chat/stream - same, but streams tokens via Server-Sent Events
    DELETE /api/documents/{filename}?session_id= - remove a document from a session
"""

import os
import asyncio
import logging
from contextlib import aclosing
from functools import wraps
from threading import BoundedSemaphore
from typing import Literal
import uuid
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from rag import ingest, ingest_url, get_answer
from rag.retriever import _get_embeddings, _get_reranker, stream_answer
from rag.parents import drop_source_parents
from rag.storage import session_directory, write_json
from rag.http_limits import RequestSizeLimit
from rag.limits import (MAX_UPLOAD_BYTES, MAX_DOCUMENTS_PER_SESSION, MAX_SESSIONS,
                        ResourceLimitError, run_work)

load_dotenv()

app = FastAPI(title="RAG Chatbot API", version="2.0.0")
logger = logging.getLogger(__name__)
_mutation_lock = asyncio.Lock()
_chat_slots = BoundedSemaphore(2)
_mutation_tasks = set()


def serialized_mutation(endpoint):
    @wraps(endpoint)
    async def guarded(*args, **kwargs):
        if _mutation_lock.locked():
            raise HTTPException(status_code=429, detail="Another update is in progress. Try again shortly.")
        await _mutation_lock.acquire()

        async def execute():
            try:
                return await endpoint(*args, **kwargs)
            except ResourceLimitError as exc:
                raise HTTPException(status_code=429, detail=str(exc)) from exc
            finally:
                _mutation_lock.release()

        task = asyncio.create_task(execute())
        _mutation_tasks.add(task)

        def completed(done):
            _mutation_tasks.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(completed)
        return await asyncio.shield(task)
    return guarded


@app.on_event("startup")
async def warmup():
    """Pre-load models so the first request doesn't stall."""
    _get_embeddings()
    _get_reranker()
    print("Embedding model and re-ranker loaded and ready.")


_cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestSizeLimit)

# Session persistence - stored in chroma_db/sessions.json.
# Each session has its own chroma_db/{session_id}/ directory for vectors.

CHROMA_BASE = Path("./chroma_db")
SESSIONS_FILE = CHROMA_BASE / "sessions.json"


def _load_sessions() -> list[dict]:
    if SESSIONS_FILE.exists():
        return json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
    return []


def _save_sessions(sessions: list[dict]) -> None:
    write_json(SESSIONS_FILE, sessions)


def _session_chroma_dir(session_id: str) -> Path:
    try:
        return session_directory(CHROMA_BASE, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Models

class CreateSessionRequest(BaseModel):
    name: str = Field(default="New Chat", min_length=1, max_length=100)

class RenameSessionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)

class AutoNameRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)

class IngestUrlRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)

class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=12000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: str
    # Prior turns for conversational memory.
    # Each entry: {"role": "user"|"assistant", "content": str}
    history: list[HistoryMessage] = Field(default_factory=list, max_length=10)

class SourceExcerpt(BaseModel):
    id: int
    source: str
    text: str
    page: int | None = None
    page_label: str | None = None
    row: int | None = None
    url: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: str
    citations: list[SourceExcerpt] = Field(default_factory=list)


# Session endpoints

@app.get("/api/sessions")
async def list_sessions():
    """Return all sessions ordered by creation time (newest first)."""
    return {"sessions": _load_sessions()}


@app.post("/api/sessions", status_code=201)
@serialized_mutation
async def create_session(req: CreateSessionRequest):
    """Create a new named session. Returns the new session object."""
    session = {
        "id": str(uuid.uuid4()),
        "name": req.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "documents": [],
    }
    sessions = _load_sessions()
    if len(sessions) >= MAX_SESSIONS:
        raise HTTPException(status_code=429, detail="Maximum of 50 sessions reached.")
    sessions.insert(0, session)  # newest first
    _save_sessions(sessions)
    return session


@app.patch("/api/sessions/{session_id}")
@serialized_mutation
async def rename_session(session_id: str, req: RenameSessionRequest):
    """Rename an existing session."""
    sessions = _load_sessions()
    for s in sessions:
        if s["id"] == session_id:
            s["name"] = req.name
            _save_sessions(sessions)
            return s
    raise HTTPException(status_code=404, detail="Session not found.")


@app.post("/api/sessions/{session_id}/auto-name")
@serialized_mutation
async def auto_name_session(session_id: str, req: AutoNameRequest):
    """
    Generate a short title (3-5 words) for a session using the LLM,
    based on the user's first message. Falls back to truncating the
    question if the LLM call fails.
    """
    sessions = _load_sessions()
    session = next((s for s in sessions if s["id"] == session_id), None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_core.output_parsers import StrOutputParser
        from rag.retriever import _build_llm

        llm = _build_llm()
        chain = llm | StrOutputParser()

        name = await chain.ainvoke([
            SystemMessage(content=(
                "Create a very short chat title (3-5 words, no quotes, "
                "no trailing punctuation) that captures the topic of the user's question. "
                "Reply with ONLY the title, nothing else."
            )),
            HumanMessage(content=f"User question: {req.question[:300]}"),
        ])
        name = name.strip().strip('"\'').strip()[:60]
    except Exception:
        # Fallback: use the first 40 characters of the question
        name = req.question[:40].rstrip() + ("…" if len(req.question) > 40 else "")

    session["name"] = name
    _save_sessions(sessions)
    return session


@app.delete("/api/sessions/{session_id}")
@serialized_mutation
async def delete_session(session_id: str):
    """
    Delete a session and all documents indexed in it.
    Returns the updated sessions list so the frontend can sync in one round-trip.
    """
    chroma_dir = _session_chroma_dir(session_id)
    sessions = _load_sessions()
    if not any(s["id"] == session_id for s in sessions):
        raise HTTPException(status_code=404, detail="Session not found.")
    if chroma_dir.exists():
        await run_work(shutil.rmtree, chroma_dir)
    sessions = [s for s in sessions if s["id"] != session_id]
    _save_sessions(sessions)

    return {"sessions": sessions}


# Document endpoints

@app.post("/api/upload")
@serialized_mutation
async def upload_document(
    file: UploadFile = File(...),
    session_id: str = Query(..., description="Target session ID"),
):
    """Upload and index a document into the specified session."""
    # Validate session exists
    sessions = _load_sessions()
    session = next((s for s in sessions if s["id"] == session_id), None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    allowed = {".pdf", ".txt", ".md", ".docx", ".csv", ".xls", ".xlsx"}
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(allowed))}"
        )

    if len(session["documents"]) >= MAX_DOCUMENTS_PER_SESSION:
        raise HTTPException(status_code=429, detail="Maximum of 20 documents per session reached.")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp_path = tmp.name
            size = 0
            while content := await file.read(64 * 1024):
                size += len(content)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File too large. Maximum is 50 MB.")
                tmp.write(content)
        n_chunks = await run_work(ingest, tmp_path, display_name=file.filename, session_id=session_id)
    except ResourceLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Document indexing failed")
        raise HTTPException(status_code=500, detail="Could not index the document.") from exc
    finally:
        await file.close()
        if tmp_path:
            os.unlink(tmp_path)

    # Update document list in session
    if file.filename not in session["documents"]:
        session["documents"].append(file.filename)
        _save_sessions(sessions)

    return {"filename": file.filename, "chunks": n_chunks}


@app.post("/api/ingest-url")
@serialized_mutation
async def ingest_url_endpoint(
    req: IngestUrlRequest,
    session_id: str = Query(..., description="Target session ID"),
):
    """Fetch a web page by URL and index its content into the specified session."""
    sessions = _load_sessions()
    session = next((s for s in sessions if s["id"] == session_id), None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    if len(session["documents"]) >= MAX_DOCUMENTS_PER_SESSION:
        raise HTTPException(status_code=429, detail="Maximum of 20 documents per session reached.")
    try:
        n_chunks, display_name = await run_work(ingest_url, url, session_id=session_id)
    except ResourceLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("URL indexing failed")
        raise HTTPException(status_code=500, detail="Could not index the web page.") from exc

    if display_name not in session["documents"]:
        session["documents"].append(display_name)
        _save_sessions(sessions)

    return {"display_name": display_name, "chunks": n_chunks}


@app.delete("/api/documents/{filename}")
@serialized_mutation
async def delete_document(
    filename: str,
    session_id: str = Query(..., description="Session the document belongs to"),
):
    """Remove a document and all its chunks from the specified session."""
    from langchain_community.vectorstores import Chroma

    sessions = _load_sessions()
    session = next((s for s in sessions if s["id"] == session_id), None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    chroma_dir = str(_session_chroma_dir(session_id))
    def remove_document():
        vectorstore = Chroma(
            persist_directory=chroma_dir,
            embedding_function=_get_embeddings(),
        )
        vectorstore.delete(where={"source": filename})
        drop_source_parents(session_id, filename)

    try:
        await run_work(remove_document)
    except ResourceLimitError:
        raise
    except Exception as exc:
        logger.exception("Document deletion failed")
        raise HTTPException(status_code=500, detail="Could not delete the document.") from exc

    session["documents"] = [d for d in session["documents"] if d != filename]
    _save_sessions(sessions)

    return {"documents": session["documents"]}


# Chat endpoint

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Ask a question scoped to a specific session's documents."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    sessions = _load_sessions()
    if not any(s["id"] == req.session_id for s in sessions):
        raise HTTPException(status_code=404, detail="Session not found.")

    try:
        result = await run_work(get_answer, req.question, session_id=req.session_id,
                                history=[msg.model_dump() for msg in req.history])
    except ResourceLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as exc:
        logger.exception("Chat failed")
        raise HTTPException(status_code=500, detail="Could not generate an answer.") from exc

    return ChatResponse(answer=result["answer"], sources=result["sources"],
                        citations=result.get("citations", []))


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Streaming version of /api/chat — returns tokens via Server-Sent Events."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    sessions = _load_sessions()
    if not any(s["id"] == req.session_id for s in sessions):
        raise HTTPException(status_code=404, detail="Session not found.")

    async def generate():
        if not _chat_slots.acquire(blocking=False):
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Too many active answers. Try again shortly.'})}\n\n"
            return
        try:
            async with asyncio.timeout(120):
                async with aclosing(stream_answer(
                    req.question, session_id=req.session_id,
                    history=[msg.model_dump() for msg in req.history]
                )) as events:
                    async for event in events:
                        yield f"data: {json.dumps(event)}\n\n"
        except TimeoutError:
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Answer timed out. Please try again.'})}\n\n"
        except RuntimeError as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"
        except ResourceLimitError as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"
        except Exception:
            logger.exception("Streaming answer failed")
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Could not generate an answer.'})}\n\n"
        finally:
            _chat_slots.release()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Serve built React frontend

frontend_dist = Path(__file__).parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        return FileResponse(frontend_dist / "index.html")
