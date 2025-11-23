##############################################
# 1) BUILDER STAGE — install dependencies
##############################################

FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies for compiling wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    curl \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip + install wheel to speed up builds
RUN pip install --upgrade pip wheel

# Copy requirements and install into isolated venv
COPY requirements.txt .
RUN python -m venv /builder_venv && \
    /builder_venv/bin/pip install --no-cache-dir -r requirements.txt


##############################################
# 2) FINAL STAGE — lightweight production image
##############################################

FROM python:3.11-slim

# Prevent pyc files and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Europe/Sarajevo

WORKDIR /app

# Copy venv from builder stage
COPY --from=builder /builder_venv /venv

# Add venv to PATH
ENV PATH="/venv/bin:$PATH"

# Copy actual application code
COPY . .

# Expose FastAPI port
EXPOSE 10000

# Run Uvicorn — single worker (Render free/starter)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]