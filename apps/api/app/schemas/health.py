"""Pydantic schemas for health check endpoints."""
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Standard health check response model."""
    status: str = Field(default="ok", description="Health status identifier")


class DatabaseHealthResponse(BaseModel):
    """Database connectivity health response model."""
    status: str = Field(default="ok", description="Database connectivity status identifier")
