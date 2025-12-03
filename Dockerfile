# ============================
# 1) BUILDER STAGE
# ============================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /build

COPY requirements.txt .

RUN pip install --upgrade pip wheel setuptools && \
    pip install --no-cache-dir --target=/packages -r requirements.txt


# ============================
# 2) RUNTIME STAGE
# ============================
FROM python:3.11-slim

ENV TZ=Europe/Sarajevo
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="/app"

WORKDIR /app

# Optional tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages
COPY --from=builder /packages /usr/local/lib/python3.11/site-packages

# Copy app code
COPY . .

# Render handles the real port internally,
# EXPOSE cannot use env vars — so we expose a neutral port.
EXPOSE 8000

# Start server
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
