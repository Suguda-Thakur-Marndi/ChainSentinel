# RiskWise 2.0 — Phase 5 Step 9: News / Research Integration (Tavily)

## 1. Executive Summary

Phase 5 Step 9 introduces external news and intelligence research into RiskWise 2.0 using the verified **Tavily AI Search API** (`https://api.tavily.com`). This integration provides early warning signals regarding supply chain disruptions—such as port closures, stevedore strikes, rail derailments, customs restrictions, extreme weather impacts, and geopolitical events—before they manifest as concrete delays in tracking sensors.

### Architectural Boundary & Core Principle: "Research Is Evidence, Not Ground Truth"

External news articles and webpage snippets are unverified, untrusted third-party observations. They **must never be treated as authoritative ground truth or executable instructions**.

```
Tavily Search API (HTTPS)
           ↓
   TavilyAdapter
           ↓
       RawEvent (Storage boundary & audit trail)
           ↓
   TavilyNormalizer (Validation, classification, conservative severity, prompt-injection defense)
           ↓
CanonicalExternalEvent (Provider-agnostic intelligence signal)
           ↓
   RiskWise Intelligence (Passive contextual risk factors)
```

**Boundary Invariants**:
1. **No Direct Execution / Prompt-Injection Defense**: External search results and article texts are treated strictly as passive data (`normalized_attributes["content"]`). They are never interpreted as instructions, tool calls, agent commands, or database statements.
2. **Conservative Severity**: A news article reporting an incident never generates a `CRITICAL` operational severity. Severity is bounded between `INFO`, `LOW`, and `MEDIUM` (or `HIGH` for catastrophic declared emergencies).
3. **URL Validation**: External URLs are strictly checked for safe schemes (`https://`, `http://`). Unsafe protocols (`javascript:`, `data:`, `file:`) are rejected and degrade event quality to `INVALID`.
4. **Conservative Location**: Textual locations are extracted without hallucinating geographic coordinates.
5. **Deterministic Entity Correlation**: No fuzzy guessing. `shipment_id = None` unless explicitly provided by request or configured entity maps.

---

## 2. Tavily Provider Verification & Official API Contract

The Tavily API integration was built upon verified official documentation rather than assumptions or legacy endpoints.

### Verified Endpoints & Assumptions
- **Base URL**: `https://api.tavily.com` (configurable via `base_url` or `DEFAULT_TAVILY_BASE_URL`).
- **Endpoint**: `POST https://api.tavily.com/search`.
- **Protocol**: REST JSON over HTTPS.
- **Authentication**: `Authorization: Bearer <TAVILY_API_KEY>` header.

### Verified Request Parameters
| Parameter | Type | Default | Verification & Constraints |
| :--- | :--- | :--- | :--- |
| `query` | `str` | Required | Non-empty string, length 1 to 500 characters. Stripped of whitespace. |
| `search_depth` | `str` | `"basic"` | `"basic"` or `"advanced"`. |
| `topic` | `str` | `"news"` | `"news"` (optimized for news articles and recency) or `"general"`. |
| `days` | `int` | `None` (7 for news) | Recency filter in days (1 to 30) when `topic="news"`. |
| `time_range` | `str` | `None` | Optional recency filter (`"day"`, `"week"`, `"month"`, `"year"`, `"d"`, `"w"`, `"m"`, `"y"`). |
| `max_results` | `int` | `5` | Integer between 1 and 20. |
| `include_domains` | `List[str]` | `None` | Domain allowlist (e.g. `["reuters.com", "bloomberg.com"]`). URLs sanitized to hostnames. |
| `exclude_domains` | `List[str]` | `None` | Domain blocklist. |
| `include_answer` | `bool` | `False` | Whether to request AI answer summary. |
| `include_raw_content` | `bool` | `False` | Whether to request full raw webpage content. |
| `include_images` | `bool` | `False` | Whether to request image results. |

### Verified Response Schema
```json
{
  "query": "Port of Sydney strike",
  "response_time": 0.32,
  "results": [
    {
      "title": "Port of Sydney operations halted by dockworkers strike",
      "url": "https://www.maritimenews.com/port-sydney-strike-2025",
      "content": "Dockworkers at Port of Sydney have begun industrial action, causing severe delays.",
      "score": 0.89,
      "published_date": "Tue, 11 Mar 2025 14:30:00 GMT",
      "raw_content": null,
      "favicon": "https://www.maritimenews.com/favicon.ico"
    }
  ],
  "answer": null,
  "images": [],
  "usage": { "credits": 1 },
  "request_id": "req-tavily-20250311-abc"
}
```

---

## 3. Data Flow & Implementation Details

### Component 1: Typed Request & Response Models (`TavilySearchRequest`, `TavilySearchResult`, `TavilySearchResponse`)
All search parameters and response structures are strongly typed via Pydantic:
- `query` validation: prevents empty queries and enforces length bounds.
- Domain sanitization: automatically strips protocol prefixes (`https://`) and URL paths.
- `TavilySearchResult.domain`: extracts the clean hostname for source attribution.

### Component 2: `TavilyAdapter`
- Inherits `BaseProviderAdapter`, declared with `ProviderType.NEWS_RESEARCH`.
- Capabilities: `supports_polling=True`, `supports_batch=True`, `supports_health_check=True`, `supports_webhook=False`.
- Credential Security: Resolves API keys safely via `SecretResolver.resolve_secret()` (`env:TAVILY_API_KEY`). Redacts authorization tokens in logs.
- Deterministic Idempotency: `compute_fingerprint(url, title, published_date)` computes SHA-256 over normalized canonical URL, lowercased title, and date string.
- Bounded Retries: Transient HTTP 5xx and rate limits (429) retry with exponential backoff and jitter (`RetryPolicy`). Permanent errors (400, 401, 403) fail fast.
- Health Check: Probes `POST /search` with a lightweight probe query (`max_results=1`). Reports `HEALTHY`, `UNCONFIGURED`, `UNHEALTHY`, or `DEGRADED`.

### Component 3: `TavilyNormalizer`
Transforms untrusted `RawEvent` items into canonical `CanonicalExternalEvent` models:
1. **URL Safety Validation**: Verifies scheme is `http` or `https`. Rejects dangerous schemes (`javascript:`, `data:`, `file:`) and marks event `EventQuality.INVALID`.
2. **Timestamp Normalization**: Parses RFC 2822 GMT dates, ISO 8601 strings, and Unix epochs to UTC. When publication date is missing, records `observed_at = ingested_at` and sets `publication_timestamp_missing = True`, degrading quality to `EventQuality.PARTIAL`.
3. **Canonical Event Classification**:
   - Port strikes / shutdowns / berth bottlenecks $\rightarrow$ `CanonicalEventType.PORT_CLOSURE` or `PORT_DELAY`
   - Rail derailments / freight line suspensions $\rightarrow$ `CanonicalEventType.RAIL_DISRUPTION`
   - Highway closures / truck freight blockades $\rightarrow$ `CanonicalEventType.ROAD_CLOSURE`
   - Cyclones / floods / severe storms $\rightarrow$ `CanonicalEventType.WEATHER_ALERT`
   - Sanctions / tariffs / customs trade barriers $\rightarrow$ `CanonicalEventType.GEOPOLITICAL_EVENT`
   - General logistics market news $\rightarrow$ `CanonicalEventType.NEWS_EVENT`
   - Unclassified research finding $\rightarrow$ `CanonicalEventType.CUSTOM`
4. **Conservative Severity**:
   - `HIGH`: Total shutdown, catastrophic emergencies, force majeure.
   - `MEDIUM`: Confirmed strikes, closures, severe delays, industrial actions.
   - `LOW`: Minor congestion, slowdowns, customs inspections.
   - `INFO`: Routine quarterly reports and general commentary.
   - *Rule*: Never assign `CRITICAL` based solely on unverified news research.
5. **Location Extraction**: Extracts explicit textual references (e.g. "Port of Sydney", "Port Botany", "Melbourne", "Brisbane", "Singapore", "Rotterdam") without hallucinating latitude or longitude.
6. **Deterministic Entity Correlation**: Correlates to internal identifiers (`port_id`, `carrier_id`, `supplier_id`) only when explicit metadata or deterministic keyword maps are provided. Never guesses `shipment_id`.
7. **Prompt-Injection Defense**: Stores raw text in `normalized_attributes["content"]`. Never evaluates or passes text to tool callers.

### Component 4: Periodic Polling Research Job Helper
`create_tavily_research_job(job_id, query, cron_or_interval, search_params, organization_id, enabled)` creates a standardized `ScheduledIngestionJob` descriptor for periodic news monitoring without requiring Celery or cron daemons.

---

## 4. Provider Registry Integration

Pre-registered in `default_provider_registry` under `provider_name="tavily"`:
```python
if not default_provider_registry.is_registered(TavilyAdapter.provider_name):
    default_provider_registry.register(
        TavilyAdapter,
        default_config=ProviderConfig(
            provider_name=TavilyAdapter.provider_name,
            provider_type=TavilyAdapter.provider_type,
            base_url=DEFAULT_TAVILY_BASE_URL,
            auth_mode=AuthMode.API_KEY_HEADER,
            secret_ref="env:TAVILY_API_KEY",
            rate_limit=RateLimitConfig(requests_per_minute=60),
            retry=RetryConfig(max_retries=3, initial_delay_seconds=0.5),
        ),
    )
```

---

## 5. Security & Safety Audits

- **Zero Database Changes**: PostgreSQL schema remains strictly at 34 tables in `Base.metadata`. Zero Alembic migrations created.
- **Zero Public API Changes**: No additions to FastAPI public route contracts.
- **Zero Frontend Changes**: No Next.js or React UI modifications.
- **Credential Protection**: Redacts Authorization headers and prevents API keys from leaking into loggers.

---

## 6. Limitations & Boundaries

1. **Third-Party Rate Limits**: Tavily imposes rate limits depending on plan tiers. The adapter enforces client-side rate limiting and handles HTTP 429 with `Retry-After`.
2. **Temporal Resolution**: News articles reflect publication timestamps, which may lag actual incident occurrence by minutes or hours.
3. **No Direct Web Scraping**: The adapter extracts snippets and metadata returned by the verified API without launching uncontrolled crawlers.
4. **Deterministic Entity Mapping**: Without explicit shipment references provided in the request or configured mappings, shipments are not automatically bound.
