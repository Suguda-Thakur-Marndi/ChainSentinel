"""Session service and storage abstraction for RiskWise 2.0 (Phase 3 Step 4).

Provides:
- Cryptographically secure session generation using secrets.token_urlsafe(32)
- Server-side TTL-based session storage (Valkey/Redis with Thread-safe In-Memory fallback)
- Session retrieval, validation, expiration, revocation, and rotation
- HttpOnly, Secure, SameSite cookie management
"""
import abc
import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Response

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.session import SessionData

logger = get_logger("session")


class BaseSessionStore(abc.ABC):
    """Abstract interface for server-side session persistence."""

    @abc.abstractmethod
    def get(self, session_id: str) -> Optional[SessionData]:
        """Retrieve session data by session ID."""
        pass

    @abc.abstractmethod
    def set(self, session_id: str, data: SessionData, ttl_seconds: int) -> None:
        """Store session data with a specified time-to-live."""
        pass

    @abc.abstractmethod
    def delete(self, session_id: str) -> bool:
        """Delete/revoke a session by session ID."""
        pass


class MemorySessionStore(BaseSessionStore):
    """Thread-safe in-memory session store with TTL enforcement."""

    def __init__(self):
        self._lock = threading.Lock()
        self._store: dict[str, SessionData] = {}

    def get(self, session_id: str) -> Optional[SessionData]:
        with self._lock:
            data = self._store.get(session_id)
            if not data:
                return None
            # Check expiration
            if datetime.now(timezone.utc) >= data.expires_at:
                del self._store[session_id]
                return None
            return data

    def set(self, session_id: str, data: SessionData, ttl_seconds: int) -> None:
        with self._lock:
            self._store[session_id] = data

    def delete(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._store:
                del self._store[session_id]
                return True
            return False

    def clear(self) -> None:
        """Clear all stored sessions (useful for tests)."""
        with self._lock:
            self._store.clear()


class RedisSessionStore(BaseSessionStore):
    """Redis / Valkey backed session store with native key TTL."""

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._client = None
        self._fallback = MemorySessionStore()
        try:
            import redis
            self._client = redis.Redis.from_url(redis_url, decode_responses=True, socket_timeout=3)
            # Test connectivity
            self._client.ping()
            logger.info("Connected to Redis/Valkey session store at %s", redis_url.split("@")[-1])
        except Exception as exc:
            logger.warning("Could not connect to Redis/Valkey (%s); using in-memory fallback", exc)
            self._client = None

    def get(self, session_id: str) -> Optional[SessionData]:
        if not self._client:
            return self._fallback.get(session_id)
        try:
            raw = self._client.get(f"session:{session_id}")
            if not raw:
                return None
            return SessionData.model_validate_json(raw)
        except Exception as exc:
            logger.warning("Redis read error (%s); falling back to memory store", exc)
            return self._fallback.get(session_id)

    def set(self, session_id: str, data: SessionData, ttl_seconds: int) -> None:
        if not self._client:
            self._fallback.set(session_id, data, ttl_seconds)
            return
        try:
            self._client.setex(
                f"session:{session_id}",
                ttl_seconds,
                data.model_dump_json(),
            )
        except Exception as exc:
            logger.warning("Redis write error (%s); falling back to memory store", exc)
            self._fallback.set(session_id, data, ttl_seconds)

    def delete(self, session_id: str) -> bool:
        if not self._client:
            return self._fallback.delete(session_id)
        try:
            deleted = self._client.delete(f"session:{session_id}")
            return bool(deleted)
        except Exception as exc:
            logger.warning("Redis delete error (%s); falling back to memory store", exc)
            return self._fallback.delete(session_id)


def create_session_store() -> BaseSessionStore:
    """Instantiate the configured session store (Redis/Valkey if configured, else Memory)."""
    if settings.REDIS_URL:
        return RedisSessionStore(settings.REDIS_URL)
    return MemorySessionStore()


# Default singleton instance
_default_session_store = create_session_store()


class SessionService:
    """High-level application session lifecycle coordinator."""

    def __init__(self, store: Optional[BaseSessionStore] = None):
        self.store = store or _default_session_store
        self.default_ttl = settings.SESSION_MAX_AGE_SECONDS

    @staticmethod
    def generate_session_id() -> str:
        """Generate a cryptographically secure 256-bit URL-safe session token (43 characters)."""
        return secrets.token_urlsafe(32)

    def create_session(
        self,
        user_id: str,
        role: str,
        organization_id: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> SessionData:
        """Create and persist a new application session with a random session ID."""
        session_id = self.generate_session_id()
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl)

        session_data = SessionData(
            session_id=session_id,
            user_id=user_id,
            organization_id=organization_id,
            role=role,
            created_at=now,
            expires_at=expires_at,
        )
        self.store.set(session_id, session_data, ttl_seconds=ttl)
        return session_data

    def get_session(self, session_id: str) -> Optional[SessionData]:
        """Retrieve and validate an active session. Returns None if invalid or expired."""
        if not session_id or not isinstance(session_id, str):
            return None
        session_data = self.store.get(session_id)
        if not session_data:
            return None
        if session_data.is_expired:
            self.delete_session(session_id)
            return None
        return session_data

    def delete_session(self, session_id: str) -> bool:
        """Revoke a session immediately."""
        if not session_id:
            return False
        return self.store.delete(session_id)

    def rotate_session(self, old_session_id: str) -> Optional[SessionData]:
        """Rotate session ID to prevent session fixation upon state change or re-authentication."""
        old_data = self.get_session(old_session_id)
        if not old_data:
            return None
        self.delete_session(old_session_id)
        now = datetime.now(timezone.utc)
        remaining_ttl = max(1, int((old_data.expires_at - now).total_seconds()))
        new_session = self.create_session(
            user_id=old_data.user_id,
            role=old_data.role,
            organization_id=old_data.organization_id,
            ttl_seconds=remaining_ttl,
        )
        return new_session

    @staticmethod
    def set_session_cookie(response: Response, session_id: str) -> None:
        """Set the secure HttpOnly session cookie on the outgoing HTTP response."""
        response.set_cookie(
            key=settings.SESSION_COOKIE_NAME,
            value=session_id,
            max_age=settings.SESSION_MAX_AGE_SECONDS,
            httponly=True,
            secure=settings.session_cookie_secure,
            samesite=settings.SESSION_SAME_SITE,
            path="/",
        )

    @staticmethod
    def clear_session_cookie(response: Response) -> None:
        """Delete/clear the session cookie from the client browser."""
        response.delete_cookie(
            key=settings.SESSION_COOKIE_NAME,
            path="/",
            httponly=True,
            secure=settings.session_cookie_secure,
            samesite=settings.SESSION_SAME_SITE,
        )


_session_service_instance = SessionService()


def get_session_service() -> SessionService:
    """FastAPI dependency for accessing the active SessionService."""
    return _session_service_instance


def set_session_cookie(response: Response, session_id: str) -> None:
    """Module-level helper to set session cookie on response."""
    SessionService.set_session_cookie(response, session_id)


def clear_session_cookie(response: Response) -> None:
    """Module-level helper to delete session cookie on response."""
    SessionService.clear_session_cookie(response)

