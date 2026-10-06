# ==============================================================================
# Production Dockerfile for Food Delivery Platform Backend API
# Multi-stage security hardened container with non-root user and healthchecks
# ==============================================================================

FROM python:3.13-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Build wheels for fast, clean runtime installation
RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --no-deps --wheel-dir /build/wheels -r requirements.txt


# ------------------------------------------------------------------------------
# Runtime Image
# ------------------------------------------------------------------------------
FROM python:3.13-slim AS runner

WORKDIR /app

# Install runtime system dependencies (curl for container healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated unprivileged non-root user
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser

# Copy pre-built wheels from builder stage
COPY --from=builder /build/wheels /wheels
COPY --from=builder /build/requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir /wheels/* && \
    rm -rf /wheels

# Copy application source code
COPY --chown=appuser:appgroup app /app/app

# Set production environment flags
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000

# Switch to non-root user
USER appuser

EXPOSE 8000

# Docker Healthcheck targeting Kubernetes-compliant Liveness probe
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health/live || exit 1

# Production WSGI/ASGI entrypoint
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--access-log"]
