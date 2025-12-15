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

ARG CACHE_BREAK=1

ENV TZ=Europe/Sarajevo
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# COPY BUILT PYTHON PACKAGES
COPY --from=builder /install /usr/local

# COPY APP CODE
COPY ./ ./

# EXPOSE RENDER PORT
EXPOSE $PORT

# ===========================
# CANONICAL ENTRYPOINT
# ===========================
CMD ["python", "main.py"]
