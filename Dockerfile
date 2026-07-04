# Stage 1: build the React frontend
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install --frozen-lockfile
COPY frontend/ ./
RUN npm run build


# Stage 2: Python backend + built frontend
FROM python:3.11-slim

WORKDIR /app

# Build tools needed to compile some Python packages (e.g. chromadb)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch CPU-only first to avoid pulling the ~2 GB CUDA variant
RUN pip install --no-cache-dir \
    "torch>=2.4.0" \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download models during build so the first request doesn't stall
RUN python -c "\
from langchain_huggingface import HuggingFaceEmbeddings; \
HuggingFaceEmbeddings(model_name='sentence-transformers/all-MiniLM-L6-v2'); \
print('Embedding model cached OK')"

RUN python -c "\
from sentence_transformers import CrossEncoder; \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2'); \
print('Re-ranker model cached OK')"

COPY rag/     ./rag/
COPY server.py start.sh ./
RUN chmod +x start.sh

COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

EXPOSE 8000

CMD ["./start.sh"]
