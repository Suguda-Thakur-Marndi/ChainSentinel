"""Pydantic schemas for health check endpoints."""
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Standard health check response model."""
    status: str = Field(default="ok", description="Health status identifier")


class DatabaseHealthResponse(BaseModel):
    """Database connectivity health response model."""
    status: str = Field(default="ok", description="Database connectivity status identifier")


class ComponentHealth(BaseModel):
    """Component status detail."""
    status: str = Field(default="ok", description="Component status")
    latency_ms: Optional[float] = Field(default=None, description="Latency in milliseconds")


class SystemHealthResponse(BaseModel):
    """Detailed system health check response matching frontend contracts."""
    status: str = Field(default="ok", description="Overall health status")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 timestamp",
    )
    version: Optional[str] = Field(default="1.0.0", description="Application version")
    components: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Component health breakdown",
    )
