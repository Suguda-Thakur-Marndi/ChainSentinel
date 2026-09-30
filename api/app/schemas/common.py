"""Common and reusable Pydantic schemas for pagination, sorting, and standardized errors."""
from __future__ import annotations
from enum import Enum
from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class SortOrder(str, Enum):
    """Sort direction enumeration."""
    ASC = "asc"
    DESC = "desc"


class PaginationParams(BaseModel):
    """Standard query parameters for paginated endpoints."""
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    limit: int = Field(default=20, ge=1, le=100, description="Page size (max 100)")


class PaginationMeta(BaseModel):
    """Metadata block returned in all paginated responses."""
    model_config = ConfigDict(from_attributes=True)

    total: int = Field(..., ge=0, description="Total number of items matching criteria")
    page: int = Field(..., ge=1, description="Current page number")
    limit: int = Field(..., ge=1, le=100, description="Number of items per page")
    pages: int = Field(..., ge=0, description="Total number of pages")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic wrapper for all paginated collection responses."""
    model_config = ConfigDict(from_attributes=True)

    items: list[T] = Field(..., description="List of items for current page")
    pagination: PaginationMeta = Field(..., description="Pagination metadata")
    total: int = Field(default=0, description="Total number of items matching criteria")
    limit: int = Field(default=20, description="Number of items per page")
    offset: int = Field(default=0, description="Item offset for current page")

    @model_validator(mode="after")
    def sync_flat_pagination(self) -> PaginatedResponse[T]:
        if self.pagination:
            self.total = self.pagination.total
            self.limit = self.pagination.limit
            self.offset = (self.pagination.page - 1) * self.pagination.limit
        return self


class ErrorDetail(BaseModel):
    """Standard machine-readable error payload."""
    code: str = Field(..., description="Stable machine-readable error code")
    message: str = Field(..., description="Human-readable error description")
    details: Optional[Any] = Field(None, description="Optional validation or context details")


class ErrorResponse(BaseModel):
    """Standard top-level error response envelope."""
    error: ErrorDetail = Field(..., description="Error detail container")
