"""Main FastAPI application entrypoint for RiskWise API."""
from contextlib import asynccontextmanager
import uuid
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.logging import get_logger, setup_logging
from app.core.rate_limit import RateLimitMiddleware
from app.core.telemetry import TelemetryMiddleware
from app.db.session import check_db_connection, dispose_db_engine
from app.schemas.health import DatabaseHealthResponse, HealthResponse

# Initialize application logging
setup_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager handling startup readiness and graceful resource draining on SIGTERM."""
    logger.info(f"Initializing {settings.PROJECT_NAME} v{settings.VERSION} [{settings.APP_ENV}]...")
    yield
    logger.info("Service shutting down. Gracefully draining database connection pools and resources...")
    dispose_db_engine()
    logger.info("Shutdown complete.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    description="RiskWise API — Supply Chain Risk Intelligence & Decision Platform",
    lifespan=lifespan,
)

# Centralized error handlers
register_error_handlers(app)

# CORS configuration (environment-driven, strictly controlled origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Distributed rate limiting middleware (Valkey/Redis with safe fallback)
app.add_middleware(RateLimitMiddleware)

# Distributed OpenTelemetry tracing middleware
app.add_middleware(TelemetryMiddleware)


@app.middleware("http")
async def request_context_middleware(request, call_next):
    """Correlate and propagate request ID for end-to-end operational observability."""
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# Mount Versioned API Router (/api/v1)
app.include_router(api_router, prefix=settings.API_PREFIX)


# Top-level health endpoints for infrastructure and container probes
@app.get("/health", tags=["Health"], response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Root health check verifying service liveness."""
    return HealthResponse(status="ok")


@app.get("/ready", tags=["Health"])
def readiness_check():
    """Root readiness probe verifying platform operational readiness."""
    return {"status": "ready"}


@app.get("/health/db", tags=["Health"], response_model=DatabaseHealthResponse)
def db_health_check() -> DatabaseHealthResponse:
    """Root database connectivity check executing SELECT 1 against PostgreSQL."""
    from fastapi import HTTPException, status
    connected, _ = check_db_connection()
    if not connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unavailable"},
        )
    return DatabaseHealthResponse(status="ok")


@app.get("/", tags=["Root"])
def root():
    """Service metadata endpoint."""
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "openapi": "/openapi.json",
        "api_v1": settings.API_PREFIX,
    }
