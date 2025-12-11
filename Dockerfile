# ===========================
# 1) BUILDER STAGE
# ===========================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /build

COPY requirements.txt .

RUN pip install --upgrade pip wheel setuptools && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt


# ===========================
# 2) RUNTIME STAGE
# ===========================
FROM python:3.11-slim

# FORCE DOCKER TO REBUILD (cache breaker)
ARG CACHE_BREAK=1

ENV TZ=Europe/Sarajevo
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# COPY BUILT PYTHON PACKAGES
COPY --from=builder /install /usr/local

# COPY APP CODE — FIXED
COPY ./ ./

# expose Render port
EXPOSE $PORT

# START FASTAPI
CMD ["sh", "-c", "uvicorn gateway.gateway_server:app --host 0.0.0.0 --port $PORT"]
