# ==============================================================================
# RiskWise 2.0 — Backend Production Dockerfile (riskwise-api)
# Multi-stage, minimal runtime, non-root user, hardened security posture
# ==============================================================================

# Stage 1: Build & Dependencies
FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Hardened Production Runtime
FROM python:3.13-slim AS runtime

# Install minimal runtime utility for container health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root system user and group
RUN groupadd -g 10001 riskwise && \
    useradd -u 10001 -g riskwise -s /bin/false -m riskwise

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder --chown=riskwise:riskwise /root/.local /home/riskwise/.local

# Copy application source code
COPY --chown=riskwise:riskwise app/ /app/app/

# Environment configuration
ENV PATH="/home/riskwise/.local/bin:${PATH}" \
    PYTHONUNBUFFERED="1" \
    PYTHONDONTWRITEBYTECODE="1" \
    APP_ENV="production" \
    PORT="8000"

# Switch to non-root user
USER riskwise

EXPOSE 8000

# Docker/ECS Container Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Production ASGI server with graceful shutdown and connection draining
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--timeout-graceful-shutdown", "15"]
