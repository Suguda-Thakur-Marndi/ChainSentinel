"""Main FastAPI application entrypoint for RiskWise API."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.logging import setup_logging
from app.db.session import check_db_connection
from app.schemas.health import DatabaseHealthResponse, HealthResponse

# Initialize application logging
setup_logging()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    description="RiskWise API — Supply Chain Risk Intelligence & Decision Platform",
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


@app.middleware("http")
async def add_security_headers(request, call_next):
    """Inject standard protective security headers on all responses."""
    response = await call_next(request)
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
