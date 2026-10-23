# RAG Chatbot

A document question-answering chatbot with a custom React frontend and FastAPI backend. Upload PDFs or text files, ask questions - the bot retrieves the most relevant passages and answers using only the content of your documents

Embeddings run **locally** (no API key needed). The LLM uses **Groq's free tier** (Qwen 3.8 27B). The whole stack runs in a single Docker container

---

## How It Works

```
Upload PDF / TXT / MD
        |
        v
DocumentLoader (PyPDFLoader / TextLoader)
        |
        v
RecursiveCharacterTextSplitter (parents=2000 chars, children=400 chars, overlap=50)
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
Cross-encoder re-ranking (ms-marco-MiniLM-L-6-v2) -> top-4 child chunks
        |
        v
Expand child chunks -> parent chunks (parents.json)
        |
        v
Build message list: system prompt + conversation history + current question
        |
        v
ChatGroq / Qwen 3.8 27B  OR  Ollama (local, fully offline)
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
| LLM | Qwen 3.8 27B via Groq (default, free, no card) or any Ollama model (fully offline) |
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
│   ├── ingestor.py            # load -> parent/child split -> embed -> store in ChromaDB
│   ├── retriever.py           # hybrid search + re-ranking + parent expansion -> Groq LLM
│   ├── parents.py             # shared helpers for parents.json (per-session parent store)
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

### Option A - Docker with Groq (recommended, zero setup)

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

### Option B - Docker fully offline (Ollama, no API key)

```bash
cp .env.example .env
# Edit .env:
#   LLM_PROVIDER=ollama
#   OLLAMA_HOST=http://ollama:11434
#   OLLAMA_MODEL=llama3.2

docker compose --profile offline up --build

# Pull a model on first run (in a separate terminal)
docker exec -it $(docker ps -qf name=ollama) ollama pull llama3.2
```

> Ollama model downloads happen at runtime, not during build.
> `llama3.2` is ~2 GB. Larger models like `llama3.1:8b` give better answers but need more RAM

### Option C - Local development

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
| `POST` | `/api/chat/stream` | Same, but streams tokens via Server-Sent Events |

---

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Description |
|---|---|
| `LLM_PROVIDER` | `groq` (default) or `ollama` |
| `LLM_MODEL` | Optional Groq model override (default: `qwen/qwen3.8-27b`) |
| `GROQ_API_KEY` | **Required when `LLM_PROVIDER=groq`.** Free key from [console.groq.com](https://console.groq.com) |
| `OLLAMA_HOST` | Ollama base URL. Use `http://ollama:11434` in Docker, `http://localhost:11434` locally |
| `OLLAMA_MODEL` | Ollama model name (default: `llama3.2`). Any model available via `ollama pull` |

Tunable constants (edit source files directly):

| File | Constant | Default | Effect |
|---|---|---|---|
| `ingestor.py` | `PARENT_CHUNK_SIZE` | `2000` | Parent chunk size passed to the LLM |
| `ingestor.py` | `CHILD_CHUNK_SIZE` | `400` | Child chunk size indexed in ChromaDB for search |
| `ingestor.py` | `CHILD_CHUNK_OVERLAP` | `50` | Overlap between adjacent child chunks |
| `retriever.py` | `TOP_K` | `4` | Chunks passed to the LLM after re-ranking |
| `retriever.py` | `RERANK_CANDIDATES` | `12` | Candidates per search method (vector + BM25) before RRF and re-ranking |
| `retriever.py` | `MAX_HISTORY` | `10` | Prior messages sent to the LLM |
| `retriever.py` | `LLM_MODEL` | `qwen/qwen3.8-27b` | Groq model name |
| `retriever.py` | `LLM_TEMPERATURE` | `0.0` | 0 = factual, 1 = creative |

---

## Roadmap

### Done
- [x] RAG pipeline: load -> split -> embed -> retrieve -> answer
- [x] Local embeddings - `all-MiniLM-L6-v2`, no API key, runs on CPU
- [x] Free LLM - Groq (Qwen 3.8 27B), no credit card required
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
- [x] Parent-document retrieval - search small chunks, pass larger parent paragraphs to the LLM

### Phase 5 - Fully offline mode
- [x] Replace Groq with a local LLM via Ollama (Llama 3, Mistral, Phi-3)
- [x] GPU support flag in docker-compose for faster inference

### Phase 6 - Production
- [ ] JWT-based user authentication
- [ ] Per-user document namespaces in ChromaDB
- [x] Streaming responses (Server-Sent Events)
- [ ] Deploy to Railway / Render / Hugging Face Spaces
- [x] GitHub Actions CI - lint + Docker build check on every PR

---

## License

MIT


## Reliability and resource limits

Run a single Uvicorn worker, as configured by `start.sh`; mutation and processing limits are per process

- Chat history is saved in this browser's local storage, with up to 200 recent messages per session restored after reload
- History is not synchronized between browsers or devices and is removed when browser site data is cleared
- Stop cancels the active response and keeps the partial text; interrupted replies are excluded from subsequent model context
- A CPU task already running at cancellation may finish in the background; its processing slot stays reserved until it finishes
- Document mutations already started finish even if the requesting client disconnects
- Session deletion accepts only existing UUID sessions and rejects symlink directories
- Uploads are copied in bounded blocks with a 50 MB file limit; incoming request bodies are also bounded
- Each document is limited to 2 million extracted characters; each session is limited to 20 document entries and 10,000 indexed child chunks
- The application allows up to 50 sessions, one heavy processing task at a time, and two streaming answers
- Questions are limited to 4,000 characters, history to 10 messages of up to 12,000 characters each, and generated answers to 1,024 tokens
- Streaming answers have a 120-second timeout
- URL import accepts public HTTP(S) pages on standard ports, checks every redirect, pins connections to a validated public IP, and limits downloads to 2 MB
- URL import accepts HTML and plain text with uncompressed responses, up to three redirects, a 10-second socket timeout, and a 30-second download budget

These limits target personal use; authentication and per-user authorization are still required before sharing private documents through a public deployment

## Regression tests

The regression suite uses temporary data and substitutes model calls, so it requires neither model downloads nor provider credentials

```bash
pip install -r requirements-test.txt
python -m unittest discover -s tests -v
cd frontend
npm test
npm run build
```

Real document parsing, embedding inference, and provider integration still require the full dependencies from `requirements.txt` and a separate end-to-end check


## Source passages

Answers include numbered references such as `[1]`; selecting a reference opens the corresponding source passage below the answer

Each passage includes the exact text supplied to the model, the source name, and a page or row number where available; PDF pages use one-based numbering

Source passages are saved with chat history and remain available after reload, including for stopped replies once retrieval has finished

The source panel shows retrieved evidence, not an independent verification that every generated claim is correct; older saved answers retain their original source labels without fabricated excerpts

## Live integration check

The optional live check creates a synthetic three-page PDF in a temporary directory, indexes it with the real embedding and reranking models, checks streaming and regular provider answers, and closes an active stream

```bash
python scripts/check_live.py
```

This check requires full project dependencies, model downloads on the first run, and a working configured provider; it sends only synthetic test content and uses the provider's existing quota

`npm test` also checks the React workflow in a simulated DOM: upload, answer, source inspection, Stop, clearing, and restoring the selected conversation and its passages after remount


## Document updates

- Uploading the same bytes with the same file extension again returns `status: skipped` without new vectors, even under a different filename
- Different content under an existing filename returns HTTP 409; the interface asks before resending with `replace=true`
- Replacement preserves the document ID and replaces its child chunks and parent passages
- Reimporting an unchanged web page is skipped; changed content requires the same replacement confirmation
- Pages are identified by their final URL, so matching page titles do not merge unrelated documents
- A journal stores the previous vectors and metadata before an update; failed writes roll back, and interrupted updates recover before the next index operation or retrieval
- A failed recovery keeps the journal and blocks that operation instead of serving a partially updated index
- The document manifest provides the current document list; older indexes are registered when first modified
- Legacy entries without a fingerprint need one confirmed replacement before byte-level duplicate detection is available

Recovery targets a single-process deployment and needs temporary disk space for the previous version; existing chat answers keep their saved source passages after replacement or deletion

To check duplicate handling, replacement, rollback, and interrupted-update recovery against real ChromaDB using temporary data:

```bash
python scripts/check_documents.py
```

## Quality benchmark

The synthetic benchmark contains 36 questions over 12 short documents in English, Russian, and Slovak: 24 direct facts or identifiers, 8 questions without an answer, and 4 conversational follow-ups

```bash
# Local retrieval only, without provider calls
python scripts/evaluate.py --output /tmp/rag-retrieval.json

# Also evaluate generated answers using the existing provider quota
python scripts/evaluate.py --answers --delay 10 --output /tmp/rag-answers.json
```

The report compares vector search, hybrid search, and reranking using evidence hit rate in the first four passages and mean reciprocal rank; a hit requires both the expected source and the supporting text

Questions without an answer are excluded from retrieval hit rates; follow-up cases check whether the search includes the relevant conversation topic

Generated answers are retained for review alongside answer-alias checks, reference checks, and abstention markers. These are diagnostics, not a semantic correctness judge or a claim of production accuracy

The corpus is deliberately small and does not represent long PDFs, OCR, or real user documents; extend it with held-out examples before using the results to choose retrieval settings


The initial measured results and manual review are recorded in [evaluation/RESULTS.md](evaluation/RESULTS.md), with individual answers in [evaluation/baseline.json](evaluation/baseline.json)


Retrieval now adds recent user questions to referential follow-ups in English, Russian, and Slovak, with at most 1,600 characters of historical context and no extra provider call; assistant assertions are excluded from search hints

The same contextual query is used by vector search, BM25, and reranking. This is a bounded heuristic, not a semantic rewrite: ambiguous references and topic changes can still require clarification

The answer instructions require explicit acknowledgement of missing information and distinguish facts absent from the excerpts from events that never happened; these instructions reduce risk but cannot guarantee factual correctness

The additional checks use three new synthetic documents and 12 questions, including chained follow-ups, topic changes, and unsupported claims in conversation history:

```bash
python scripts/evaluate.py --dataset evaluation/followup-check.json --answers --delay 10 --output /tmp/rag-followups.json
```

The repeated benchmark and additional scenario results are recorded in [evaluation/IMPROVEMENTS.md](evaluation/IMPROVEMENTS.md), with case-level answers in `evaluation/after.json` and `evaluation/followup-results.json`
