# Stage 1: Builder
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY app/ app/
COPY alembic.ini .

# pip's 15s socket timeout aborts the whole install when a large wheel stalls
# mid-download, which failed three consecutive prod deploys (2026-07-31).
RUN pip install --no-cache-dir --timeout 120 --retries 10 \
    --extra-index-url https://download.pytorch.org/whl/cpu .

# Stage 2: Production
FROM python:3.12-slim

WORKDIR /app
ARG GIT_SHA=""
ARG GIT_DIRTY="false"
ENV GIT_SHA=${GIT_SHA}
ENV GIT_DIRTY=${GIT_DIRTY}

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    ffmpeg \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# T-Bank's production acquiring endpoint is served by the Russian Trusted
# Root CA chain, which is not included in Debian's default trust store.
COPY certs/russian_trusted_root_ca.crt /usr/local/share/ca-certificates/russian_trusted_root_ca.crt
COPY certs/russian_trusted_sub_ca.crt /usr/local/share/ca-certificates/russian_trusted_sub_ca.crt
RUN update-ca-certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

RUN npm install -g wrangler@4.79.0

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

# Pre-create writable runtime directories so Docker named volumes inherit
# appuser ownership on first mount.
RUN mkdir -p /var/lib/waicomputer/uploads /var/lib/waicomputer/summary-audio

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY app/ app/
COPY alembic.ini .

RUN chown -R appuser:appuser /app /var/lib/waicomputer
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["gunicorn", "app.main:app", \
    "--worker-class", "uvicorn.workers.UvicornWorker", \
    "--workers", "1", \
    "--bind", "0.0.0.0:8000", \
    "--timeout", "600", \
    "--keep-alive", "65", \
    "--forwarded-allow-ips", "*"]
