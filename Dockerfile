# ============================
# 1) BUILDER STAGE
# ============================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /build

COPY requirements.txt .

# Install dependencies in builder layer
RUN pip install --upgrade pip wheel setuptools && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt


# ============================
# 2) RUNTIME STAGE
# ============================
FROM python:3.11-slim

ENV TZ=Europe/Sarajevo
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install OS dependencies only if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed python packages from builder
COPY --from=builder /install /usr/local

# Copy application source code
COPY . .

EXPOSE 10000

# Uvicorn production command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]