"""Tavily news and research integration provider adapter and normalizer.

Ingests external supply chain intelligence, port closures, labor strikes, transportation
disruptions, customs restrictions, extreme weather impacts, and geopolitical events from
the verified Tavily Search API. Maps provider responses into strongly typed RawEvent
and CanonicalExternalEvent models without schema leakage or unvalidated execution.

Boundary invariants:
- Research results are treated strictly as UNTRUSTED EVIDENCE, never as authoritative ground truth.
- Content text is treated strictly as PASSIVE DATA; it is NEVER executed as instructions.
- External URLs are strictly validated; unsafe protocols (javascript:, data:, file:) are rejected.
- Location extraction is conservative and text-based; coordinates are NEVER hallucinated.
- Entity correlation is deterministic; fuzzy guessing is strictly forbidden.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.integrations.base import (
    BaseProviderAdapter,
    IngestionBatch,
    ProviderCapabilities,
    ProviderHealthResult,
    ProviderHealthStatus,
    ProviderType,
    RawEvent,
)
from app.integrations.boundaries import ScheduledIngestionJob
from app.integrations.canonical import (
    CanonicalEventType,
    CanonicalExternalEvent,
    EntityCorrelation,
    EventLocation,
    EventQuality,
    EventSeverity,
    EventSourceType,
)
from app.integrations.config import (
    AuthMode,
    ProviderConfig,
    RateLimitConfig,
    RetryConfig,
    SecretResolver,
)
from app.integrations.errors import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderConnectionError,
    ProviderPermanentError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderValidationError,
)
from app.integrations.normalizers import BaseEventNormalizer, TimestampNormalizer
from app.integrations.rate_limiter import ProviderRateLimiter
from app.integrations.retry import RetryPolicy

logger = logging.getLogger("riskwise.integrations.providers.tavily")

# Verified Tavily Defaults
DEFAULT_TAVILY_BASE_URL = "https://api.tavily.com"
DEFAULT_TAVILY_SEARCH_ENDPOINT = "/search"
MAX_QUERY_LENGTH = 500
DEFAULT_MAX_RESULTS = 5
SAFE_URL_SCHEMES = ("https", "http")


# =====================================================================
# Request & Response Models (Verified Tavily Search API)
# =====================================================================

class TavilySearchTopic(str, Enum):
    """Supported search topic domains in Tavily API."""
    GENERAL = "general"
    NEWS = "news"


class TavilySearchDepth(str, Enum):
    """Search depth modes supported by Tavily API."""
    BASIC = "basic"
    ADVANCED = "advanced"


class TavilySearchTimeRange(str, Enum):
    """Predefined recency time ranges supported by Tavily API."""
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    D = "d"
    W = "w"
    M = "m"
    Y = "y"


class TavilySearchRequest(BaseModel):
    """Typed search request model validated against verified Tavily API constraints."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH, description="Search query string")
    search_depth: TavilySearchDepth = Field(default=TavilySearchDepth.BASIC, description="Search depth mode")
    topic: TavilySearchTopic = Field(default=TavilySearchTopic.NEWS, description="Search topic domain")
    days: Optional[int] = Field(None, ge=1, le=30, description="Recency filter in days for news topic")
    time_range: Optional[Union[TavilySearchTimeRange, str]] = Field(None, description="Optional time range filter")
    max_results: int = Field(default=DEFAULT_MAX_RESULTS, ge=1, le=20, description="Number of results (1-20)")
    include_domains: Optional[List[str]] = Field(None, description="Domain allowlist")
    exclude_domains: Optional[List[str]] = Field(None, description="Domain blocklist")
    include_answer: bool = Field(default=False, description="Whether to include AI answer summary")
    include_raw_content: bool = Field(default=False, description="Whether to include raw webpage content")
    include_images: bool = Field(default=False, description="Whether to include image results")

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Search query cannot be empty or whitespace only.")
        if len(stripped) > MAX_QUERY_LENGTH:
            raise ValueError(f"Search query exceeds maximum length of {MAX_QUERY_LENGTH} characters.")
        return stripped

    @field_validator("include_domains", "exclude_domains")
    @classmethod
    def validate_domains(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        cleaned = []
        for domain in v:
            clean = domain.strip().lower()
            # Strip protocol if accidentally included
            clean = re.sub(r"^https?://", "", clean).split("/")[0]
            if clean:
                cleaned.append(clean)
        return cleaned or None

    def to_api_payload(self) -> Dict[str, Any]:
        """Serialize into verified Tavily JSON request payload."""
        payload: Dict[str, Any] = {
            "query": self.query,
            "search_depth": self.search_depth.value if isinstance(self.search_depth, TavilySearchDepth) else self.search_depth,
            "topic": self.topic.value if isinstance(self.topic, TavilySearchTopic) else self.topic,
            "max_results": self.max_results,
            "include_answer": self.include_answer,
            "include_raw_content": self.include_raw_content,
            "include_images": self.include_images,
        }
        if self.days is not None:
            payload["days"] = self.days
        if self.time_range is not None:
            val = self.time_range.value if isinstance(self.time_range, TavilySearchTimeRange) else str(self.time_range)
            payload["time_range"] = val
        if self.include_domains:
            payload["include_domains"] = self.include_domains
        if self.exclude_domains:
            payload["exclude_domains"] = self.exclude_domains
        return payload


class TavilySearchResult(BaseModel):
    """Individual article or webpage result item returned by Tavily search."""

    model_config = ConfigDict(extra="allow")

    title: str = Field(default="")
    url: str = Field(...)
    content: str = Field(default="")
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    published_date: Optional[str] = None
    raw_content: Optional[str] = None
    favicon: Optional[str] = None

    @property
    def domain(self) -> str:
        """Extract domain host from URL safely."""
        try:
            parsed = urlparse(self.url)
            return (parsed.netloc or "").lower()
        except Exception:
            return ""


class TavilySearchResponse(BaseModel):
    """Top-level response envelope returned by Tavily Search API."""

    model_config = ConfigDict(extra="allow")

    query: str
    response_time: Optional[float] = None
    results: List[TavilySearchResult] = Field(default_factory=list)
    answer: Optional[str] = None
    images: Optional[List[Any]] = None
    usage: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None


# =====================================================================
# URL Safety Validation
# =====================================================================

def is_safe_url(url: Optional[str]) -> bool:
    """Validate that a URL uses safe HTTP or HTTPS protocols and is well-formed."""
    if not url or not isinstance(url, str):
        return False
    clean = url.strip()
    try:
        parsed = urlparse(clean)
        return parsed.scheme.lower() in SAFE_URL_SCHEMES and bool(parsed.netloc)
    except Exception:
        return False


def normalize_source_url(url: str) -> str:
    """Normalize a source URL for deterministic deduplication."""
    try:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        normalized = f"{scheme}://{netloc}{path}"
        if parsed.query:
            normalized = f"{normalized}?{parsed.query}"
        return normalized
    except Exception:
        return url.strip()


# =====================================================================
# Tavily Provider Adapter
# =====================================================================

class TavilyAdapter(BaseProviderAdapter):
    """External intelligence and news research adapter interfacing the Tavily Search API.

    Executes authenticated searches against Tavily, enforces rate limits, bounds retries,
    handles network faults, and emits raw research events without executing untrusted text.
    """

    provider_name: str = "tavily"
    provider_type: ProviderType = ProviderType.NEWS_RESEARCH
    capabilities: ProviderCapabilities = ProviderCapabilities(
        supports_polling=True,
        supports_webhook=False,
        supports_streaming=False,
        supports_batch=True,
        supports_health_check=True,
        max_batch_size=20,
        supported_entities=["news_article", "supply_chain_intelligence"],
        supported_modalities=["search", "news"],
    )

    def __init__(
        self,
        config: Optional[ProviderConfig] = None,
        secret: Optional[str] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(config=config, secret=secret)
        self.config = config or self._default_config()
        self._secret = secret
        self.base_url = (self.config.base_url or DEFAULT_TAVILY_BASE_URL).rstrip("/")
        self.rate_limiter = ProviderRateLimiter()
        self.retry_policy = RetryPolicy(self.config.retry)
        self._client = client or httpx.Client(timeout=self.config.timeout_seconds)

    @classmethod
    def _default_config(cls) -> ProviderConfig:
        return ProviderConfig(
            provider_name=cls.provider_name,
            provider_type=cls.provider_type,
            base_url=DEFAULT_TAVILY_BASE_URL,
            auth_mode=AuthMode.API_KEY_HEADER,
            secret_ref="env:TAVILY_API_KEY",
            rate_limit=RateLimitConfig(requests_per_minute=60),
            retry=RetryConfig(max_retries=3, initial_delay_seconds=0.5),
            timeout_seconds=15.0,
        )

    def resolve_api_key(self) -> Optional[str]:
        """Resolve Tavily API key from secret, configuration, or environment."""
        if self._secret:
            return self._secret
        if self.config and self.config.secret_ref:
            resolved = SecretResolver.resolve_secret(self.config.secret_ref)
            if resolved:
                return resolved
        return SecretResolver.resolve_secret("env:TAVILY_API_KEY")

    def _build_headers(self, api_key: Optional[str]) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "RiskWise/2.0 NewsResearchIntegration",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def compute_fingerprint(
        self,
        url: str,
        title: str,
        published_date: Optional[str] = None,
    ) -> str:
        """Construct a deterministic SHA-256 fingerprint for a search result."""
        clean_url = normalize_source_url(url)
        clean_title = (title or "").strip().lower()
        clean_date = (published_date or "").strip()
        identity_string = f"{self.provider_name}:{clean_url}:{clean_title}:{clean_date}"
        return hashlib.sha256(identity_string.encode("utf-8")).hexdigest()

    def search(
        self,
        request: Union[TavilySearchRequest, Dict[str, Any]],
        org_id: Optional[str] = None,
    ) -> TavilySearchResponse:
        """Execute a validated search query against the Tavily Search API."""
        if isinstance(request, dict):
            req_model = TavilySearchRequest(**request)
        else:
            req_model = request

        api_key = self.resolve_api_key()
        if not api_key:
            raise ProviderAuthenticationError(
                "Tavily API key is missing or unconfigured.",
                provider=self.provider_name,
            )

        endpoint_url = f"{self.base_url}{DEFAULT_TAVILY_SEARCH_ENDPOINT}"
        headers = self._build_headers(api_key)
        payload = req_model.to_api_payload()

        def _execute_request() -> httpx.Response:
            if self.config and self.config.rate_limit:
                allowed, wait_time = self.rate_limiter.check_limit(
                    self.provider_name, self.config.rate_limit
                )
                if not allowed:
                    raise ProviderRateLimitError(
                        f"Tavily rate limit exceeded. Wait {wait_time:.1f}s",
                        provider_name=self.provider_name,
                        retry_after=wait_time,
                    )
                self.rate_limiter.acquire(self.provider_name, self.config.rate_limit)
            try:
                response = self._client.post(
                    endpoint_url,
                    json=payload,
                    headers=headers,
                )
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(
                    f"Tavily search request timed out: {exc}",
                    provider=self.provider_name,
                ) from exc
            except httpx.NetworkError as exc:
                raise ProviderConnectionError(
                    f"Tavily search network connection failed: {exc}",
                    provider=self.provider_name,
                ) from exc

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                msg = f"Tavily rate limit exceeded (HTTP 429). Retry-After: {retry_after}"
                logger.warning(msg)
                raise ProviderRateLimitError(msg, provider=self.provider_name)

            if response.status_code in (401, 403):
                raise ProviderAuthenticationError(
                    f"Tavily authentication failed (HTTP {response.status_code}): {response.text}",
                    provider=self.provider_name,
                )

            if response.status_code in (400, 422):
                raise ProviderValidationError(
                    f"Tavily invalid search request (HTTP {response.status_code}): {response.text}",
                    provider=self.provider_name,
                )

            if response.status_code >= 500:
                raise ProviderResponseError(
                    f"Tavily upstream server error (HTTP {response.status_code}): {response.text}",
                    status_code=response.status_code,
                    provider_name=self.provider_name,
                )

            if response.is_error:
                raise ProviderPermanentError(
                    f"Tavily permanent error (HTTP {response.status_code}): {response.text}",
                    provider=self.provider_name,
                )

            return response

        try:
            http_resp = self.retry_policy.execute(_execute_request)
        except (
            ProviderAuthenticationError,
            ProviderValidationError,
            ProviderPermanentError,
            ProviderRateLimitError,
            ProviderTimeoutError,
            ProviderConnectionError,
            ProviderResponseError,
        ):
            raise
        except Exception as exc:
            raise ProviderResponseError(
                f"Unexpected error executing Tavily search: {exc}",
                provider=self.provider_name,
            ) from exc

        try:
            data = http_resp.json()
        except Exception as exc:
            raise ProviderResponseError(
                f"Failed to parse Tavily response as JSON: {exc}",
                provider=self.provider_name,
            ) from exc

        try:
            return TavilySearchResponse(**data)
        except Exception as exc:
            raise ProviderResponseError(
                f"Tavily response schema mismatch: {exc}",
                provider=self.provider_name,
            ) from exc

    def fetch(
        self,
        query: Optional[str] = None,
        search_request: Optional[Union[TavilySearchRequest, Dict[str, Any]]] = None,
        org_id: Optional[str] = None,
        **kwargs: Any,
    ) -> IngestionBatch:
        """Fetch raw research signals from Tavily and package them into an IngestionBatch."""
        if search_request is not None:
            req = (
                search_request
                if isinstance(search_request, TavilySearchRequest)
                else TavilySearchRequest(**search_request)
            )
        elif query:
            merged_params: Dict[str, Any] = {"query": query}
            for k in [
                "search_depth",
                "topic",
                "days",
                "time_range",
                "max_results",
                "include_domains",
                "exclude_domains",
                "include_answer",
                "include_raw_content",
                "include_images",
            ]:
                if k in kwargs:
                    merged_params[k] = kwargs[k]
            req = TavilySearchRequest(**merged_params)
        else:
            raise ProviderValidationError(
                "Either 'query' or 'search_request' must be provided to fetch from Tavily.",
                provider=self.provider_name,
            )

        fetched_at = datetime.now(timezone.utc)
        search_resp = self.search(req, org_id=org_id)

        raw_events: List[RawEvent] = []
        for result in search_resp.results:
            fingerprint = self.compute_fingerprint(
                url=result.url,
                title=result.title,
                published_date=result.published_date,
            )
            raw_event = RawEvent(
                provider_name=self.provider_name,
                provider_type=self.provider_type,
                provider_event_id=result.url,
                fingerprint=fingerprint,
                source_timestamp=None,  # Handled during normalization
                ingested_at=fetched_at,
                org_id=org_id,
                event_type="NEWS_ARTICLE",
                raw_payload={
                    "title": result.title,
                    "url": result.url,
                    "content": result.content,
                    "score": result.score,
                    "published_date": result.published_date,
                    "raw_content": result.raw_content,
                    "favicon": result.favicon,
                    "domain": result.domain,
                    "query": search_resp.query,
                },
                metadata={
                    "query": req.query,
                    "topic": req.topic.value if isinstance(req.topic, TavilySearchTopic) else str(req.topic),
                    "search_depth": req.search_depth.value if isinstance(req.search_depth, TavilySearchDepth) else str(req.search_depth),
                    "response_time": search_resp.response_time,
                    "request_id": search_resp.request_id,
                    "relevance_score": result.score,
                    "source_url": result.url,
                    "source_domain": result.domain,
                },
            )
            raw_events.append(raw_event)

        return IngestionBatch(
            provider_name=self.provider_name,
            events=raw_events,
            metadata={
                "query": req.query,
                "result_count": len(raw_events),
                "response_time": search_resp.response_time,
            },
            source_metadata={
                "provider": self.provider_name,
                "endpoint": f"{self.base_url}{DEFAULT_TAVILY_SEARCH_ENDPOINT}",
                "query": req.query,
            },
            fetched_at=fetched_at,
        )

    def health_check(self) -> ProviderHealthResult:
        """Execute a diagnostic health probe against Tavily API."""
        api_key = self.resolve_api_key()
        if not api_key:
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNCONFIGURED,
                message="Tavily API key is not configured.",
                checked_at=datetime.now(timezone.utc),
            )

        start = datetime.now(timezone.utc)
        endpoint_url = f"{self.base_url}{DEFAULT_TAVILY_SEARCH_ENDPOINT}"
        headers = self._build_headers(api_key)
        # Minimal probe query
        probe_payload = {"query": "ping", "max_results": 1, "search_depth": "basic"}

        try:
            response = self._client.post(endpoint_url, json=probe_payload, headers=headers)
            latency = (datetime.now(timezone.utc) - start).total_seconds() * 1000.0

            if response.status_code == 200:
                data = response.json()
                if "results" in data:
                    return ProviderHealthResult(
                        provider_name=self.provider_name,
                        status=ProviderHealthStatus.HEALTHY,
                        latency_ms=round(latency, 2),
                        message="Tavily search API is reachable and authenticated.",
                        checked_at=datetime.now(timezone.utc),
                        details={"endpoint": endpoint_url, "latency_ms": round(latency, 2)},
                    )
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.DEGRADED,
                    latency_ms=round(latency, 2),
                    message="Tavily returned 200 but payload format was unexpected.",
                    checked_at=datetime.now(timezone.utc),
                )

            if response.status_code in (401, 403):
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.UNHEALTHY,
                    latency_ms=round(latency, 2),
                    message=f"Tavily authentication failed (HTTP {response.status_code}).",
                    checked_at=datetime.now(timezone.utc),
                )

            if response.status_code == 429:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.DEGRADED,
                    latency_ms=round(latency, 2),
                    message="Tavily rate limit exceeded.",
                    checked_at=datetime.now(timezone.utc),
                )

            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                message=f"Tavily returned HTTP {response.status_code}.",
                checked_at=datetime.now(timezone.utc),
            )

        except httpx.TimeoutException:
            latency = (datetime.now(timezone.utc) - start).total_seconds() * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.DEGRADED,
                latency_ms=round(latency, 2),
                message="Tavily health check timed out.",
                checked_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            latency = (datetime.now(timezone.utc) - start).total_seconds() * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                message=f"Tavily health probe failed: {exc}",
                checked_at=datetime.now(timezone.utc),
            )

    def close(self) -> None:
        """Release HTTP client connection pool."""
        try:
            self._client.close()
        except Exception:
            pass


# =====================================================================
# Canonical Event Normalizer
# =====================================================================

class TavilyNormalizer(BaseEventNormalizer):
    """Normalizes raw Tavily search events into canonical supply chain events.

    Implements:
    - Conservative taxonomy classification (port closures, strikes, rail, weather, geopolitical)
    - Untrusted data boundary and prompt-injection defense (passive text treatment)
    - Safe URL scheme enforcement
    - Strict UTC timestamp normalization
    - Deterministic entity correlation (no fuzzy guessing)
    - Conservative severity and quality assessment
    """

    # Lexical patterns for canonical event classification
    _PORT_TERMS = {
        "port", "dock", "terminal", "harbour", "harbor", "wharf", "berth",
        "stevedore", "container terminal", "shipping terminal", "vessel traffic",
    }
    _RAIL_TERMS = {
        "rail", "freight train", "railway", "locomotive", "track", "freight rail",
        "intermodal train", "rail line", "rail network",
    }
    _ROAD_TERMS = {
        "highway", "freeway", "motorway", "interstate", "road", "trucking",
        "haulage", "freight corridor", "bridge", "tunnel",
    }
    _WEATHER_TERMS = {
        "cyclone", "hurricane", "typhoon", "flood", "flooding", "storm",
        "blizzard", "wildfire", "bushfire", "tornado", "severe weather",
        "heavy rain", "gale",
    }
    _GEOPOLITICAL_TERMS = {
        "sanction", "sanctions", "tariff", "tariffs", "trade war", "embargo",
        "customs restriction", "border closure", "export ban", "import ban",
        "geopolitical", "blockade", "maritime security",
    }

    _CLOSURE_TERMS = {"close", "closed", "closure", "shut", "shutdown", "halt", "halted", "suspended"}
    _DELAY_TERMS = {"delay", "delayed", "delays", "congestion", "congested", "slowdown", "bottleneck", "backlog"}
    _STRIKE_TERMS = {"strike", "strikes", "walkout", "industrial action", "labor dispute", "labour dispute", "picket"}

    def __init__(
        self,
        default_org_id: Optional[str] = None,
        known_entity_map: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> None:
        self.default_org_id = default_org_id
        # Optional deterministic lookup mapping: lowercase keyword -> dict of entity IDs
        # Example: {"port of sydney": {"port_id": "PORT-SYD"}}
        self.known_entity_map = {k.lower(): v for k, v in (known_entity_map or {}).items()}

    def can_normalize(self, raw_event: RawEvent) -> bool:
        """Check if this normalizer handles the given raw event."""
        return (
            raw_event.provider_name == "tavily"
            or raw_event.provider_type == ProviderType.NEWS_RESEARCH
        )

    def normalize_timestamp(
        self,
        date_str: Optional[str],
        retrieval_time: datetime,
    ) -> tuple[datetime, bool]:
        """Parse publication date string to UTC datetime.

        Returns (parsed_datetime, was_parsed_from_source).
        If date_str is missing or unparseable, returns (retrieval_time, False).
        """
        if not date_str or not isinstance(date_str, str):
            return retrieval_time, False

        clean = date_str.strip()
        # 1. Try RFC 2822 (e.g. "Tue, 11 Mar 2025 17:00:00 GMT")
        try:
            dt = parsedate_to_datetime(clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc), True
        except Exception:
            pass

        # 2. Try ISO 8601 via TimestampNormalizer
        try:
            parsed = TimestampNormalizer.parse_to_utc(clean)
            if parsed:
                return parsed, True
        except Exception:
            pass

        return retrieval_time, False

    def classify_event_type(self, title: str, content: str) -> CanonicalEventType:
        """Classify research finding into existing canonical event taxonomy."""
        title_lower = title.lower()
        combined = f"{title} {content}".lower()

        # If title is explicitly about severe weather and not a port facility title
        if any(term in title_lower for term in self._WEATHER_TERMS) and not any(term in title_lower for term in self._PORT_TERMS):
            return CanonicalEventType.WEATHER_ALERT

        # Check Port / Maritime (port closures/strikes take priority over general road/rail delays)
        if any(term in combined for term in self._PORT_TERMS):
            if any(act in combined for act in self._CLOSURE_TERMS):
                return CanonicalEventType.PORT_CLOSURE
            if any(act in combined for act in (self._DELAY_TERMS | self._STRIKE_TERMS)):
                return CanonicalEventType.PORT_DELAY

        # Check Rail
        if any(term in combined for term in self._RAIL_TERMS):
            if any(act in combined for act in (self._CLOSURE_TERMS | self._DELAY_TERMS | self._STRIKE_TERMS)):
                return CanonicalEventType.RAIL_DISRUPTION

        # Check Road
        if any(term in combined for term in self._ROAD_TERMS):
            if any(act in combined for act in self._CLOSURE_TERMS):
                return CanonicalEventType.ROAD_CLOSURE
            if any(act in combined for act in self._DELAY_TERMS):
                return CanonicalEventType.ROAD_INCIDENT

        # Check Weather
        if any(term in combined for term in self._WEATHER_TERMS):
            return CanonicalEventType.WEATHER_ALERT

        # Check Geopolitical / Regulatory
        if any(term in combined for term in self._GEOPOLITICAL_TERMS):
            return CanonicalEventType.GEOPOLITICAL_EVENT

        # General logistics news
        if any(term in combined for term in {"supply chain", "logistics", "freight", "cargo", "carrier", "warehouse"}):
            return CanonicalEventType.NEWS_EVENT

        return CanonicalEventType.CUSTOM

    def assess_severity(self, title: str, content: str, event_type: CanonicalEventType) -> EventSeverity:
        """Assess conservative operational severity.

        Invariants:
        - Research findings are unconfirmed evidence, not operational ground truth.
        - NEVER assign CRITICAL from news alone without verified operational sensor data.
        """
        combined = f"{title} {content}".lower()

        # Check high-impact indicators
        high_indicators = [
            "closed indefinitely", "total shutdown", "catastrophic", "force majeure",
            "declared emergency", "major port shutdown", "complete halt",
        ]
        if any(ind in combined for ind in high_indicators):
            return EventSeverity.HIGH

        # Significant disruption indicators
        medium_indicators = [
            "closure", "closed", "shut down", "strike", "strikes", "walkout", "blocked",
            "disruption", "severe delay", "delays", "suspended operations",
            "industrial action", "labor dispute", "labour dispute", "bottleneck", "backlog",
        ]
        if any(ind in combined for ind in medium_indicators):
            return EventSeverity.MEDIUM

        # Minor or moderate indicators
        low_indicators = [
            "delay", "slowdown", "congestion", "picket", "protest", "restriction",
            "warning", "expected delay",
        ]
        if any(ind in combined for ind in low_indicators):
            return EventSeverity.LOW

        return EventSeverity.INFO

    def extract_location(self, title: str, content: str, raw_payload: Dict[str, Any]) -> Optional[EventLocation]:
        """Extract explicit textual location information without hallucinating coordinates."""
        combined = f"{title} {content}"

        # Conservative list of known supply chain locations
        locations_to_check = [
            ("Port of Sydney", "AUS", "NSW"),
            ("Port Botany", "AUS", "NSW"),
            ("Port of Melbourne", "AUS", "VIC"),
            ("Port of Brisbane", "AUS", "QLD"),
            ("Port of Fremantle", "AUS", "WA"),
            ("Port of Newcastle", "AUS", "NSW"),
            ("Sydney", "AUS", "NSW"),
            ("Melbourne", "AUS", "VIC"),
            ("Brisbane", "AUS", "QLD"),
            ("Perth", "AUS", "WA"),
            ("New South Wales", "AUS", "NSW"),
            ("Australia", "AUS", None),
            ("Singapore", "SGP", None),
            ("Rotterdam", "NLD", None),
            ("Shanghai", "CHN", None),
            ("Los Angeles", "USA", "CA"),
            ("Long Beach", "USA", "CA"),
        ]

        for loc_name, country, region in locations_to_check:
            # Case-insensitive substring match with boundary
            pattern = rf"\b{re.escape(loc_name)}\b"
            if re.search(pattern, combined, re.IGNORECASE):
                return EventLocation(
                    location_name=loc_name,
                    country_code=country,
                    region=region,
                    latitude=None,  # NEVER invent coordinates
                    longitude=None,
                )

        return None

    def correlate_entities(
        self,
        raw_event: RawEvent,
        title: str,
        content: str,
    ) -> EntityCorrelation:
        """Deterministically correlate research signals to RiskWise entities.

        Invariants:
        - NEVER perform fuzzy guessing or hallucinate shipment correlation.
        - shipment_id is bound ONLY if explicitly provided in request context or metadata.
        """
        correlation = EntityCorrelation()

        # 1. Explicit bindings from raw event context / metadata
        meta = raw_event.metadata or {}
        if meta.get("shipment_id"):
            correlation.shipment_id = str(meta["shipment_id"])
        if meta.get("carrier_id"):
            correlation.carrier_id = str(meta["carrier_id"])
        if meta.get("port_id"):
            correlation.port_id = str(meta["port_id"])
        if meta.get("supplier_id"):
            correlation.supplier_id = str(meta["supplier_id"])

        # 2. Deterministic keyword lookup against caller-provided entity map
        combined = f"{title} {content}".lower()
        for keyword, ids in self.known_entity_map.items():
            if keyword in combined:
                if "port_id" in ids and not correlation.port_id:
                    correlation.port_id = ids["port_id"]
                if "carrier_id" in ids and not correlation.carrier_id:
                    correlation.carrier_id = ids["carrier_id"]
                if "supplier_id" in ids and not correlation.supplier_id:
                    correlation.supplier_id = ids["supplier_id"]

        return correlation

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        """Normalize a single raw Tavily research event into a CanonicalExternalEvent."""
        payload = raw_event.raw_payload or {}
        title = str(payload.get("title") or "").strip()
        raw_url = str(payload.get("url") or "").strip()
        # Ensure prompt-injection defense: content is treated strictly as passive text data
        content = str(payload.get("content") or "").strip()
        score = float(payload.get("score") or 0.0)
        published_date_str = payload.get("published_date")

        validation_errors: List[str] = []
        quality = EventQuality.VALID

        # 1. URL Safety Check
        if not is_safe_url(raw_url):
            validation_errors.append(f"Unsafe or malformed source URL rejected: '{raw_url}'")
            quality = EventQuality.INVALID
            clean_url = None
        else:
            clean_url = normalize_source_url(raw_url)

        # 2. Timestamp Normalization
        event_time, was_parsed = self.normalize_timestamp(
            published_date_str,
            retrieval_time=raw_event.ingested_at,
        )
        if not was_parsed:
            # Missing publication timestamp degrades quality to PARTIAL
            if quality != EventQuality.INVALID:
                quality = EventQuality.PARTIAL

        # 3. Canonical Event Classification
        event_type = self.classify_event_type(title, content)

        # 4. Severity Assessment
        severity = self.assess_severity(title, content, event_type)

        # 5. Location Extraction
        location = self.extract_location(title, content, payload)

        # 6. Deterministic Entity Correlation
        correlation = self.correlate_entities(raw_event, title, content)

        # 7. Attributes & Metadata
        normalized_attrs: Dict[str, Any] = {
            "title": title,
            "content": content,
            "source_domain": payload.get("domain") or (urlparse(clean_url).netloc if clean_url else ""),
            "relevance_score": score,
            "publication_timestamp_missing": not was_parsed,
            "query": payload.get("query") or raw_event.metadata.get("query"),
        }
        if payload.get("raw_content"):
            normalized_attrs["has_raw_content"] = True

        return CanonicalExternalEvent(
            provider=raw_event.provider_name,
            source_event_id=clean_url or raw_event.provider_event_id,
            event_type=event_type,
            event_timestamp=event_time,
            observed_at=raw_event.ingested_at,
            received_at=datetime.now(timezone.utc),
            location=location,
            correlation=correlation,
            status="REPORTED",
            severity=severity,
            source_type=EventSourceType.REAL,
            source_url=clean_url,
            confidence=score if 0.0 <= score <= 1.0 else None,
            raw_event_id=raw_event.event_id,
            normalized_attributes=normalized_attrs,
            provider_metadata=raw_event.metadata,
            payload_fingerprint=raw_event.fingerprint,
            org_id=raw_event.org_id or self.default_org_id,
            quality=quality,
            validation_errors=validation_errors,
        )


# =====================================================================
# Periodic Polling Research Job Helper
# =====================================================================

def create_tavily_research_job(
    job_id: str,
    query: str,
    cron_or_interval: str = "interval:60",
    search_params: Optional[Dict[str, Any]] = None,
    organization_id: Optional[str] = None,
    enabled: bool = True,
) -> ScheduledIngestionJob:
    """Create a standardized ScheduledIngestionJob descriptor for periodic news intelligence search."""
    params: Dict[str, Any] = {"query": query.strip()}
    if search_params:
        params.update(search_params)
    return ScheduledIngestionJob(
        job_id=job_id,
        provider_name="tavily",
        cron_or_interval=cron_or_interval,
        enabled=enabled,
        parameters=params,
        organization_id=organization_id,
    )
