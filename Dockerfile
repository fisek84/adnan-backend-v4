# =========================
# 1) Frontend build (Vite)
# =========================
FROM node:20-alpine AS frontend-build

WORKDIR /app

COPY gateway/frontend/package.json gateway/frontend/package-lock.json ./gateway/frontend/
WORKDIR /app/gateway/frontend
RUN npm ci

COPY gateway/frontend/ ./
RUN npm run build

# Fail build if index.html missing/empty
RUN test -s /app/gateway/frontend/dist/index.html


# =========================
# 2) Backend runtime
# =========================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip wheel setuptools \
  && pip install --no-cache-dir -r requirements.txt

COPY . .

# Copy built frontend dist into the expected path used by gateway_server.py
COPY --from=frontend-build /app/gateway/frontend/dist ./gateway/frontend/dist

# Fail build if dist/index.html missing/empty in final image too
RUN test -s ./gateway/frontend/dist/index.html

EXPOSE 8000

# START THE ACTUAL GATEWAY APP (no main.py indirection)
CMD ["bash", "-lc", "uvicorn gateway.gateway_server:app --host 0.0.0.0 --port ${PORT:-8000}"]
