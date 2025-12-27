# 1) Build frontend (Vite)
FROM node:20-alpine AS frontend-build
WORKDIR /app/gateway/frontend
COPY gateway/frontend/package.json gateway/frontend/package-lock.json ./
RUN npm ci
COPY gateway/frontend/ ./
RUN npm run build

# 2) Backend runtime
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

# Copy built dist into final image so FastAPI can serve it
COPY --from=frontend-build /app/gateway/frontend/dist ./gateway/frontend/dist

EXPOSE $PORT

CMD ["python", "main.py"]
