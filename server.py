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
import uuid
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from rag import ingest, ingest_url, get_answer
from rag.retriever import _get_embeddings, _get_reranker, stream_answer
from rag.parents import drop_source_parents

load_dotenv()

app = FastAPI(title="RAG Chatbot API", version="2.0.0")


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

# Session persistence - stored in chroma_db/sessions.json.
# Each session has its own chroma_db/{session_id}/ directory for vectors.

CHROMA_BASE = Path("./chroma_db")
SESSIONS_FILE = CHROMA_BASE / "sessions.json"


def _load_sessions() -> list[dict]:
    if SESSIONS_FILE.exists():
        return json.loads(SESSIONS_FILE.read_text())
    return []


def _save_sessions(sessions: list[dict]) -> None:
    CHROMA_BASE.mkdir(parents=True, exist_ok=True)
    SESSIONS_FILE.write_text(json.dumps(sessions, indent=2))


def _session_chroma_dir(session_id: str) -> Path:
    return CHROMA_BASE / session_id


# Models

class CreateSessionRequest(BaseModel):
    name: str = "New Chat"

class RenameSessionRequest(BaseModel):
    name: str

class AutoNameRequest(BaseModel):
    question: str   # first user message, used to generate a title

class IngestUrlRequest(BaseModel):
    url: str

class ChatRequest(BaseModel):
    question: str
    session_id: str
    # Prior turns for conversational memory.
    # Each entry: {"role": "user"|"assistant", "content": str}
    history: list[dict] = []

class ChatResponse(BaseModel):
    answer: str
    sources: str


# Session endpoints

@app.get("/api/sessions")
async def list_sessions():
    """Return all sessions ordered by creation time (newest first)."""
    return {"sessions": _load_sessions()}


@app.post("/api/sessions", status_code=201)
async def create_session(req: CreateSessionRequest):
    """Create a new named session. Returns the new session object."""
    session = {
        "id": str(uuid.uuid4()),
        "name": req.name,
        "created_at": datetime.utcnow().isoformat(),
        "documents": [],
    }
    sessions = _load_sessions()
    sessions.insert(0, session)  # newest first
    _save_sessions(sessions)
    return session


@app.patch("/api/sessions/{session_id}")
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

        name = chain.invoke([
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
async def delete_session(session_id: str):
    """
    Delete a session and all documents indexed in it.
    Returns the updated sessions list so the frontend can sync in one round-trip.
    """
    sessions = _load_sessions()
    sessions = [s for s in sessions if s["id"] != session_id]
    _save_sessions(sessions)

    # Remove the session's ChromaDB directory
    chroma_dir = _session_chroma_dir(session_id)
    if chroma_dir.exists():
        shutil.rmtree(chroma_dir)

    return {"sessions": sessions}


# Document endpoints

@app.post("/api/upload")
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
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(allowed))}"
        )

    MAX_BYTES = 50 * 1024 * 1024  # 50 MB
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content) // (1024*1024)} MB). Max is 50 MB."
        )

    # Save to temp file, index, then delete
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        n_chunks = ingest(tmp_path, display_name=file.filename, session_id=session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)

    # Update document list in session
    if file.filename not in session["documents"]:
        session["documents"].append(file.filename)
        _save_sessions(sessions)

    return {"filename": file.filename, "chunks": n_chunks}


@app.post("/api/ingest-url")
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

    try:
        n_chunks, display_name = ingest_url(url, session_id=session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if display_name not in session["documents"]:
        session["documents"].append(display_name)
        _save_sessions(sessions)

    return {"display_name": display_name, "chunks": n_chunks}


@app.delete("/api/documents/{filename}")
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
    try:
        vectorstore = Chroma(
            persist_directory=chroma_dir,
            embedding_function=_get_embeddings(),
        )
        vectorstore.delete(where={"source": filename})
        drop_source_parents(session_id, filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete from vector store: {e}")

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
        result = get_answer(req.question, session_id=req.session_id, history=req.history)
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return ChatResponse(answer=result["answer"], sources=result["sources"])


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Streaming version of /api/chat — returns tokens via Server-Sent Events."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    sessions = _load_sessions()
    if not any(s["id"] == req.session_id for s in sessions):
        raise HTTPException(status_code=404, detail="Session not found.")

    async def generate():
        try:
            async for event in stream_answer(
                req.question, session_id=req.session_id, history=req.history
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except RuntimeError as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"

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
