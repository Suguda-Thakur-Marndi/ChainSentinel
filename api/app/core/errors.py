"""Centralized error handling and exception definitions for RiskWise API."""
from typing import Any, Optional
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("errors")


class AppError(Exception):
    """Base application exception supporting standard RiskWise error envelope."""

    def __init__(
        self,
        message: str = "An error occurred",
        status_code: int = status.HTTP_400_BAD_REQUEST,
        code: str = "BAD_REQUEST",
        details: Optional[Any] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details


class NotFoundError(AppError):
    """Resource not found or cross-tenant resource masked."""

    def __init__(
        self,
        message: str = "Resource not found",
        code: str = "RESOURCE_NOT_FOUND",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            code=code,
            details=details,
        )


class ConflictError(AppError):
    """Resource state or unique constraint conflict."""

    def __init__(
        self,
        message: str = "Resource conflict",
        code: str = "CONFLICT",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            code=code,
            details=details,
        )


class ValidationDomainError(AppError):
    """Domain-level business validation failure."""

    def __init__(
        self,
        message: str = "Validation failed",
        code: str = "VALIDATION_ERROR",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            code=code,
            details=details,
        )


class InvalidSortFieldError(AppError):
    """Client provided an unapproved sort field outside the allowlist."""

    def __init__(self, field: str, allowed_fields: list[str]):
        super().__init__(
            message=f"Invalid sort field '{field}'. Allowed fields: {', '.join(sorted(allowed_fields))}",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_SORT_FIELD",
            details={"field": field, "allowed_fields": sorted(allowed_fields)},
        )


class InvalidFilterFieldError(AppError):
    """Client provided an unapproved filter field outside the allowlist."""

    def __init__(self, field: str, allowed_fields: list[str]):
        super().__init__(
            message=f"Invalid filter field '{field}'. Allowed fields: {', '.join(sorted(allowed_fields))}",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_FILTER_FIELD",
            details={"field": field, "allowed_fields": sorted(allowed_fields)},
        )


class AuthenticationError(AppError):
    """Authentication failure or session invalid/expired."""

    def __init__(
        self,
        message: str = "Authentication failed",
        code: str = "UNAUTHORIZED",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=code,
            details=details,
        )


class AuthorizationError(AppError):
    """User lacks sufficient permissions or role."""

    def __init__(
        self,
        message: str = "Permission denied",
        code: str = "FORBIDDEN",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            code=code,
            details=details,
        )


class ForbiddenError(AuthorizationError):
    """Alias for AuthorizationError."""
    pass


class DatabaseError(AppError):
    """Database operation failed. Details are sanitized to avoid SQL leakage."""

    def __init__(
        self,
        message: str = "Database operation failed",
        code: str = "DATABASE_ERROR",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code=code,
            details=details,
        )


class ImmutableResourceError(AppError):
    """Operation attempted to modify or delete an immutable ledger entity."""

    def __init__(
        self,
        message: str = "Resource is immutable and cannot be modified or deleted",
        code: str = "IMMUTABLE_RESOURCE",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            code=code,
            details=details,
        )


class LifecycleStateError(AppError):
    """Operation violates domain lifecycle status rules."""

    def __init__(
        self,
        message: str = "Invalid lifecycle state transition or operation",
        code: str = "INVALID_STATE_TRANSITION",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            code=code,
            details=details,
        )


def register_error_handlers(app: FastAPI) -> None:
    """Register centralized exception handlers on the FastAPI application."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        logger.warning("Application error: [%s] %s (path: %s)", exc.code, exc.message, request.url)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
                "detail": exc.message,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        logger.warning("Validation error on path %s: %s", request.url, exc.errors())
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": exc.errors(),
                },
                "detail": exc.errors(),
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, (str, dict, list)) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": detail},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled internal exception on %s: %s", request.url, exc)
        # Strictly sanitize internal exceptions: never leak SQL, passwords, or stack traces
        message = "Internal server error"
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": message,
                    "details": None,
                },
                "detail": message,
            },
        )
