"""Health check endpoints for RiskWise API v1."""
from fastapi import APIRouter, HTTPException, status
from app.db.session import check_db_connection
from app.schemas.health import DatabaseHealthResponse, HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Application health check endpoint verifying service liveness."""
    return HealthResponse(status="ok")


@router.get(
    "/health/db",
    response_model=DatabaseHealthResponse,
    responses={
        503: {
            "description": "Database connection unavailable",
            "content": {"application/json": {"example": {"detail": {"status": "unavailable"}}}},
        }
    },
)
def get_db_health() -> DatabaseHealthResponse:
    """Database health check endpoint executing SELECT 1 against PostgreSQL.

    Returns 200 {"status": "ok"} when connectivity is verified.
    Returns 503 {"status": "unavailable"} when unreachable.
    Never leaks passwords, connection strings, or credentials.
    """
    connected, _ = check_db_connection()
    if not connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unavailable"},
        )
    return DatabaseHealthResponse(status="ok")
