# RAG Chatbot

A document question-answering chatbot with a custom React frontend and FastAPI backend. Upload PDFs or text files, ask questions - the bot retrieves the most relevant passages and answers using only the content of your documents

Embeddings run **locally** (no API key needed). The LLM uses **Groq's free tier** (Llama 3.3 70B). The whole stack runs in a single Docker container

---

## How It Works

```
Upload PDF / TXT / MD
        |
        v
DocumentLoader (PyPDFLoader / TextLoader)
        |
        v
RecursiveCharacterTextSplitter (chunk_size=1000, overlap=200)
        |
        v
HuggingFaceEmbeddings (all-MiniLM-L6-v2, runs on CPU, free)
        |
        v
ChromaDB - persisted to disk, scoped per chat session
        |
   on each question
        |
        v
Embed question -> vector search (top-12) + BM25 keyword search (top-12)
        |
        v
Reciprocal Rank Fusion -> merged candidate list (top-12)
        |
        v
Cross-encoder re-ranking (ms-marco-MiniLM-L-6-v2) -> top-4 chunks
        |
        v
Build message list: system prompt + conversation history + current question
        |
        v
ChatGroq / Llama 3.3 70B (free tier, 30 req/min)
        |
        v
Answer + source citations
```

---

## Tech Stack

| Layer | Library / Tool |
|---|---|
| Frontend | React 18 + Vite |
| Backend | FastAPI + Uvicorn |
| LLM orchestration | LangChain 0.3 (LCEL) |
| LLM | Llama 3.3 70B via Groq (free, no card) |
| Embeddings | `all-MiniLM-L6-v2` via langchain-huggingface (local, free) |
| Re-ranker | `ms-marco-MiniLM-L-6-v2` cross-encoder (local, free) |
| Keyword search | BM25 via `rank-bm25`, fused with vector search using RRF |
| Vector store | ChromaDB (persisted on disk, one directory per session) |
| Document parsing | pypdf, docx2txt, pandas + openpyxl, beautifulsoup4 |
| Containerisation | Docker + docker-compose |

---

## Project Structure

```
rag-chatbot/
├── server.py                  # FastAPI app - REST API + serves built frontend
├── rag/
│   ├── __init__.py            # exposes ingest() and get_answer()
│   ├── ingestor.py            # load -> split -> embed -> store in ChromaDB
│   ├── retriever.py           # hybrid search + re-ranking -> Groq LLM -> answer (LCEL)
│   └── prompts.py             # system message template
├── frontend/
│   ├── src/
│   │   ├── App.jsx            # state management, API calls
│   │   ├── index.css          # dark theme, design tokens
│   │   └── components/
│   │       ├── Sidebar.jsx    # sessions, file upload, document list
│   │       ├── ChatWindow.jsx # message list + auto-scroll + clear button
│   │       ├── MessageBubble.jsx  # markdown rendering, source citations
│   │       └── ChatInput.jsx  # auto-growing textarea, Enter to send
│   ├── vite.config.js         # /api proxy for local dev
│   └── package.json
├── Dockerfile                 # multi-stage: Node builds React, Python runs API
├── docker-compose.yml
├── .env.example
├── requirements.txt
└── .gitignore
```

---

## Quick Start

### Option A - Docker (recommended, zero setup)

```bash
git clone https://github.com/jarryuser/rag-chatbot.git && cd rag-chatbot

# Add your free Groq API key (get one at https://console.groq.com)
cp .env.example .env
# Edit .env: GROQ_API_KEY=gsk_...

docker compose up --build
```

Open [http://localhost:8000](http://localhost:8000). The React frontend and API are both served from the same port

> First build takes ~5-10 min (downloads PyTorch CPU and both local models)
> Subsequent builds are fast due to Docker layer caching

### Option B - Local development

**Backend:**
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add GROQ_API_KEY
uvicorn server:app --reload --port 8000
```

**Frontend** (separate terminal):
```bash
cd frontend
npm install
npm run dev   # opens http://localhost:5173 with hot reload
```

---

## API Reference

**Sessions**

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/sessions` | List all sessions |
| `POST` | `/api/sessions` | Create a new session |
| `PATCH` | `/api/sessions/{id}` | Rename a session |
| `POST` | `/api/sessions/{id}/auto-name` | Generate a title from the first message |
| `DELETE` | `/api/sessions/{id}` | Delete session and all its documents |

**Documents**

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/upload?session_id=` | Upload and index a document (PDF, DOCX, TXT, MD, CSV, XLS/XLSX, max 50 MB) |
| `POST` | `/api/ingest-url?session_id=` | Fetch a web page by URL and index its content |
| `DELETE` | `/api/documents/{filename}?session_id=` | Remove a document and all its chunks |

**Chat**

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/chat` | Ask a question - body: `{question, session_id, history[]}` |

---

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | **Required.** Free key from [console.groq.com](https://console.groq.com) |

Tunable constants (edit source files directly):

| File | Constant | Default | Effect |
|---|---|---|---|
| `ingestor.py` | `CHUNK_SIZE` | `1000` | Max characters per chunk |
| `ingestor.py` | `CHUNK_OVERLAP` | `200` | Overlap between adjacent chunks |
| `retriever.py` | `TOP_K` | `4` | Chunks passed to the LLM after re-ranking |
| `retriever.py` | `RERANK_CANDIDATES` | `12` | Candidates per search method (vector + BM25) before RRF and re-ranking |
| `retriever.py` | `MAX_HISTORY` | `10` | Prior messages sent to the LLM |
| `retriever.py` | `LLM_MODEL` | `llama-3.3-70b-versatile` | Groq model name |
| `retriever.py` | `LLM_TEMPERATURE` | `0.0` | 0 = factual, 1 = creative |

---

## Roadmap

### Done
- [x] RAG pipeline: load -> split -> embed -> retrieve -> answer
- [x] Local embeddings - `all-MiniLM-L6-v2`, no API key, runs on CPU
- [x] Free LLM - Groq (Llama 3.3 70B), no credit card required
- [x] Custom React + FastAPI frontend (replaced Streamlit)
- [x] Multi-document support per session
- [x] Per-file delete - removes chunks from ChromaDB by source metadata
- [x] Source citations in every answer
- [x] Docker - single container, works out of the box
- [x] 50 MB file size limit with a clear error message
- [x] Multiple chat sessions with isolated document namespaces
- [x] Session management - create, rename, delete from the sidebar
- [x] Conversational memory - last 10 messages sent as context on each request
- [x] Auto-naming - session title generated by the LLM after the first message
- [x] Clear conversation button

### Phase 3 - More file formats
- [x] DOCX support via `Docx2txtLoader`
- [x] Web page ingestion - paste a URL, the page gets indexed
- [x] CSV / Excel with column-aware chunking

### Phase 4 - Retrieval quality
- [x] Re-ranking - cross-encoder (`ms-marco-MiniLM-L-6-v2`) to re-score top-k chunks before the LLM sees them
- [x] Hybrid search - combine ChromaDB vector search with BM25 keyword search
- [ ] Parent-document retrieval - search small chunks, pass larger parent paragraphs to the LLM

### Phase 5 - Fully offline mode
- [ ] Replace Groq with a local LLM via Ollama (Llama 3, Mistral, Phi-3)
- [ ] GPU support flag in docker-compose for faster inference

### Phase 6 - Production
- [ ] JWT-based user authentication
- [ ] Per-user document namespaces in ChromaDB
- [ ] Streaming responses (Server-Sent Events)
- [ ] Deploy to Railway / Render / Hugging Face Spaces
- [ ] GitHub Actions CI - lint + Docker build check on every PR

---

## License

MIT
