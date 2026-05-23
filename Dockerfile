# ── Stage 1: Build the React frontend ────────────────────────────────────────
# Uses a lightweight Node image just to run `npm run build`
# The built output (frontend/dist) is copied into the final image
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install --frozen-lockfile
COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python backend + built frontend ──────────────────────────────────
# python:3.11-slim keeps the base image lean (~130 MB before deps)
FROM python:3.11-slim

WORKDIR /app

# System build tools needed to compile some Python packages (e.g. chromadb)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch CPU-only FIRST - avoids pulling the ~2 GB CUDA variant
# sentence-transformers and transformers require torch >= 2.4
RUN pip install --no-cache-dir \
    "torch>=2.4.0" \
    --index-url https://download.pytorch.org/whl/cpu

# Install remaining Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model during build so the first upload request doesn't stall waiting for a ~90 MB download from HuggingFace
# The model is cached in ~/.cache/huggingface inside the image layer
RUN pip install --no-cache-dir langchain-huggingface>=0.1.0

# Pre-download the embedding model during build so the first upload request doesn't stall. The model is cached in HuggingFace's default cache dir
RUN python -c "\
from langchain_huggingface import HuggingFaceEmbeddings; \
HuggingFaceEmbeddings(model_name='sentence-transformers/all-MiniLM-L6-v2'); \
print('Embedding model cached OK')"

# Copy application source
COPY rag/     ./rag/
COPY server.py .

# Copy the React build from stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# chroma_db is mounted as a volume at runtime so data persists across restarts
VOLUME ["/app/chroma_db"]

EXPOSE 8000

# Run with a single worker; scale horizontally via Docker Compose replicas if needed
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
