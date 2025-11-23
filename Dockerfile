# ============================================================
# BASE IMAGE
# ============================================================
FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files and buffer output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Security + timezone
ENV TZ=Europe/Sarajevo

# Create working directory
WORKDIR /app

# Install system deps (needed for FastAPI, httpx, notion-client)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libffi-dev \
        libssl-dev \
        wget \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# ============================================================
# INSTALL PYTHON DEPENDENCIES
# ============================================================
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ============================================================
# COPY APPLICATION CODE (excluding venv, cache, junk)
# ============================================================
COPY ./ ./

# ============================================================
# EXPOSE PORT
# ============================================================
EXPOSE 10000

# ============================================================
# FINAL CMD (single worker for Starter plan)
# ============================================================
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000", "--workers", "1"]