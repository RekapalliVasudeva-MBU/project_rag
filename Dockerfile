# =============================================================================
# Multi-stage Dockerfile for AetherMind RAG Backend (project_rag)
# Uses python:3.11-slim with CPU-only PyTorch index
# =============================================================================

# ---- Stage 1: Build dependencies ----
FROM python:3.11-slim AS builder

# Install only essential system deps for building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment for clean dependency isolation
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install Python deps with CPU-only PyTorch index
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# ---- Stage 2: Runtime image ----
FROM python:3.11-slim AS runtime

# Install only runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libgomp1 \
    libpq5 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser -m -d /home/appuser -s /bin/bash appuser

# Set working directory
WORKDIR /app

# Copy application code (respects .dockerignore)
COPY --chown=appuser:appuser . .

# Create directories for data persistence
RUN mkdir -p /app/rag_vector_db /app/rag_pdfs /app/dashboard_log \
    && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Environment variables for production
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    RAG_PDF_SOURCE=local \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    ANONYMIZED_TELEMETRY=False

# Health check endpoint (lightweight, no DB connection)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=5)" || exit 1

# Expose port
EXPOSE 8000

# Use gunicorn for production
CMD ["gunicorn", "server:app", "--workers", "1", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "120", "--keep-alive", "5", "--max-requests", "1000", "--max-requests-jitter", "50", "--preload"]