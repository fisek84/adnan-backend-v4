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

# DEBUG: pokaži šta je stvarno u dist/
RUN echo "===== FRONTEND DIST LIST =====" \
 && ls -la /app/gateway/frontend/dist || true \
 && echo "===== FRONTEND DIST/ASSETS LIST =====" \
 && (ls -la /app/gateway/frontend/dist/assets || true) \
 && echo "===== FRONTEND dist/index.html (first 200 lines) =====" \
 && (sed -n '1,200p' /app/gateway/frontend/dist/index.html || true) \
 && echo "===== END DEBUG ====="

# Fail build if this is NOT a Vite/React build output
RUN test -s /app/gateway/frontend/dist/index.html \
 && grep -qi "<!doctype html" /app/gateway/frontend/dist/index.html \
 && grep -qi 'id="root"' /app/gateway/frontend/dist/index.html \
 && grep -qi '/assets/.*\.js' /app/gateway/frontend/dist/index.html


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

# DEBUG: potvrdi šta je došlo u final image
RUN echo "===== FINAL IMAGE DIST LIST =====" \
 && ls -la ./gateway/frontend/dist || true \
 && echo "===== FINAL IMAGE DIST/ASSETS LIST =====" \
 && (ls -la ./gateway/frontend/dist/assets || true) \
 && echo "===== FINAL IMAGE dist/index.html (first 200 lines) =====" \
 && (sed -n '1,200p' ./gateway/frontend/dist/index.html || true) \
 && echo "===== END DEBUG ====="

# Fail build if dist/index.html missing/empty or not Vite/React
RUN test -s ./gateway/frontend/dist/index.html \
 && grep -qi "<!doctype html" ./gateway/frontend/dist/index.html \
 && grep -qi 'id="root"' ./gateway/frontend/dist/index.html \
 && grep -qi '/assets/.*\.js' ./gateway/frontend/dist/index.html

EXPOSE 8000

CMD ["bash", "-lc", "uvicorn gateway.gateway_server:app --host 0.0.0.0 --port ${PORT:-8000}"]
