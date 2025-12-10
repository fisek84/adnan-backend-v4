# ===========================
# 1) BUILDER STAGE
# ===========================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /build

COPY requirements.txt .

# Install packages into /install (standard)
RUN pip install --upgrade pip wheel setuptools && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt


# ===========================
# 2) RUNTIME STAGE
# ===========================
FROM python:3.11-slim

ENV TZ=Europe/Sarajevo
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install OS tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# COPY BUILT PYTHON PACKAGES
COPY --from=builder /install /usr/local

# COPY APP CODE
COPY . .

# Render provides $PORT — do not hardcode
EXPOSE $PORT

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
