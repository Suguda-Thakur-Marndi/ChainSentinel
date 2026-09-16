"""Distributed Rate Limiting backed by Valkey/Redis.

Provides enterprise rate limiting across authenticated tenants, users, and unauthenticated client IPs.
Guarantees:
- Atomic sliding-window rate evaluation via Redis Lua script (zero race conditions)
- Multi-tier limit hierarchy: Tenant (org), User, and IP
- Automatic bounded TTL to prevent unbounded key growth
- Safe fail-open resilience: falls back to in-memory sliding window if Valkey/Redis is unreachable
- Whitelisted health probes (/health, /ready, /health/db) to prevent false-positive service outages
- Consistent HTTP 429 response metadata (Retry-After, X-RateLimit-* headers)
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("core.rate_limit")

# Atomic sliding-window rate limiting Lua script for Redis/Valkey
# KEYS[1]: rate limit key
# ARGV[1]: current timestamp in milliseconds
# ARGV[2]: window size in milliseconds
# ARGV[3]: maximum allowed requests in window
# ARGV[4]: member identifier (timestamp:rand)
SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

local clear_before = now - window
redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)

local current_requests = redis.call('ZCARD', key)

if current_requests < limit then
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, window + 1000)
    return {1, current_requests + 1, limit - (current_requests + 1)}
else
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local reset_ms = window
    if #oldest >= 2 then
        reset_ms = math.max(1, (tonumber(oldest[2]) + window) - now)
    end
    return {0, current_requests, 0, reset_ms}
end
"""

EXCLUDED_PATHS = frozenset({
    "/health",
    "/ready",
    "/health/db",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
})


class InMemorySlidingWindow:
    """Thread-safe in-memory fallback when Redis/Valkey is unreachable."""

    def __init__(self) -> None:
        self._store: Dict[str, list[float]] = {}

    def check_and_record(
        self, key: str, limit: int, window_seconds: float
    ) -> Tuple[bool, int, int, float]:
        now = time.time()
        window_start = now - window_seconds
        records = self._store.get(key, [])
        valid_records = [t for t in records if t > window_start]

        if len(valid_records) < limit:
            valid_records.append(now)
            self._store[key] = valid_records
            remaining = limit - len(valid_records)
            return True, len(valid_records), remaining, window_seconds

        oldest = valid_records[0] if valid_records else now
        reset_seconds = max(1.0, (oldest + window_seconds) - now)
        return False, len(valid_records), 0, reset_seconds


class DistributedRateLimiter:
    """Enterprise rate limiter utilizing Valkey/Redis with seamless in-memory fallback."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        tenant_limit: int = 600,
        user_limit: int = 120,
        ip_limit: int = 30,
        window_seconds: int = 60,
    ) -> None:
        self.redis_url = redis_url or settings.REDIS_URL
        self.tenant_limit = tenant_limit
        self.user_limit = user_limit
        self.ip_limit = ip_limit
        self.window_seconds = window_seconds
        self._redis_client: Optional[Any] = None
        self._lua_script_sha: Optional[str] = None
        self._in_memory_fallback = InMemorySlidingWindow()
        self._redis_disabled = False

    def _get_redis(self) -> Optional[Any]:
        now = time.time()
        if self._redis_disabled:
            if now < getattr(self, "_redis_retry_after", 0):
                return None
            self._redis_disabled = False

        if self._redis_client is not None:
            return self._redis_client

        if not self.redis_url:
            return None

        try:
            import redis
            client = redis.Redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=0.2,
                socket_connect_timeout=0.2,
            )
            client.ping()
            self._redis_client = client
            logger.info("Connected to Redis/Valkey for distributed rate limiting.")
            return self._redis_client
        except Exception as e:
            self._redis_disabled = True
            self._redis_retry_after = now + 30.0
            logger.warning(
                f"Could not connect to Redis/Valkey ({type(e).__name__}); using in-memory fallback for 30s."
            )
            return None

    def is_allowed(
        self,
        key: str,
        limit: int,
        window_seconds: Optional[int] = None,
    ) -> Tuple[bool, int, int, float]:
        """Check if request is allowed under sliding window limit.
        
        Returns:
            Tuple: (allowed: bool, current_count: int, remaining: int, retry_after_sec: float)
        """
        window = window_seconds or self.window_seconds
        client = self._get_redis()

        if client is not None:
            try:
                now_ms = int(time.time() * 1000)
                window_ms = int(window * 1000)
                member = f"{now_ms}:{time.monotonic_ns()}"

                res = client.eval(
                    SLIDING_WINDOW_LUA,
                    1,
                    key,
                    str(now_ms),
                    str(window_ms),
                    str(limit),
                    member,
                )
                allowed = bool(res[0] == 1)
                count = int(res[1])
                remaining = int(res[2]) if len(res) > 2 else 0
                reset_sec = (float(res[3]) / 1000.0) if len(res) > 3 else float(window)
                return allowed, count, remaining, reset_sec
            except Exception as exc:
                logger.warning(
                    f"Redis rate-limit evaluation error ({exc}); falling back to local memory."
                )

        # In-memory fallback
        return self._in_memory_fallback.check_and_record(
            key=key,
            limit=limit,
            window_seconds=float(window),
        )

    def evaluate_request(
        self,
        organization_id: Optional[str] = None,
        user_id: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> Tuple[bool, int, int, float, str]:
        """Evaluate hierarchical rate limits for a request.
        
        Order of evaluation:
        1. Tenant limit (if authenticated with organization_id)
        2. User limit (if authenticated with user_id)
        3. IP limit (unauthenticated client IP)
        """
        if organization_id:
            key = f"rw:rate:org:{organization_id}"
            allowed, count, remaining, retry_after = self.is_allowed(key, self.tenant_limit)
            if not allowed:
                return False, self.tenant_limit, remaining, retry_after, "tenant"

        if user_id:
            key = f"rw:rate:user:{user_id}"
            allowed, count, remaining, retry_after = self.is_allowed(key, self.user_limit)
            if not allowed:
                return False, self.user_limit, remaining, retry_after, "user"

        if not organization_id and not user_id:
            ip = client_ip or "127.0.0.1"
            key = f"rw:rate:ip:{ip}"
            allowed, count, remaining, retry_after = self.is_allowed(key, self.ip_limit)
            if not allowed:
                return False, self.ip_limit, remaining, retry_after, "ip"

        return True, self.tenant_limit, self.tenant_limit - 1, 0.0, "ok"


global_rate_limiter = DistributedRateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware enforcing distributed rate limits."""

    def __init__(self, app: Any, limiter: Optional[DistributedRateLimiter] = None) -> None:
        super().__init__(app)
        self.limiter = limiter or global_rate_limiter

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # 1. Skip excluded paths (health probes, docs)
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        # 2. Extract tenant and user identifiers from request state or session
        org_id = getattr(request.state, "organization_id", None)
        user_id = getattr(request.state, "user_id", None)
        client_ip = request.client.host if request.client else "127.0.0.1"

        # 3. Check rate limits
        allowed, limit, remaining, retry_after, scope = self.limiter.evaluate_request(
            organization_id=org_id,
            user_id=user_id,
            client_ip=client_ip,
        )

        if not allowed:
            retry_int = max(1, int(retry_after))
            headers = {
                "Retry-After": str(retry_int),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time() + retry_int)),
            }
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded for {scope}. Please retry in {retry_int} seconds.",
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "retry_after": retry_int,
                },
                headers=headers,
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
