# ============================================================
# Stage 1: Builder — install system deps + pip packages
# ============================================================
FROM python:3.13-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libxml2-dev libxslt-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ============================================================
# Stage 2: Runtime — lean image without build tools
# ============================================================
FROM python:3.13-slim

# Runtime-only system libraries (no gcc/g++)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1.1 curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application scripts only (no data, models, or secrets)
COPY *.py ./

# Use unbuffered output for real-time Cloud Logging
ENV PYTHONUNBUFFERED=1

# Default command: run the orchestrator with auto-detection
CMD ["python", "orchestrator.py", "--profile", "auto"]
