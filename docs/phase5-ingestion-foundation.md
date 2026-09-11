# RiskWise 2.0 — Phase 5 Step 1
# External Data Ingestion Foundation & Provider Architecture

**Status**: Production Foundation Complete & Verified  
**Scope**: Provider-Agnostic Ingestion Framework (Phase 5 Step 1)  
**PostgreSQL Schema**: Zero Migrations, Zero DDL, 34 Models / 26 Enums Unchanged  
**Test Suite**: 305 tests collected, 304 passed, 1 skipped (RDS live network), 0 failed  
**OpenAPI Contract**: 60 paths, 96 operations, 104 schemas (Unchanged)  

---

## 1. Ingestion Architecture

RiskWise ingests dynamic real-world signals (weather disruptions, traffic congestion, ocean AIS movements, flight delays, rail bottlenecks, telematics/tracking events, and global risk intelligence) to evaluate supply chain vulnerabilities.

To prevent tight coupling between external data formats and internal risk models, Step 1 establishes a strict layered pipeline:

```
External Provider (e.g. Weather, Traffic, AIS, Logistics)
                      ↓
           Provider Adapter Interface
       (BaseProviderAdapter + Capabilities)
                      ↓
               Provider Registry
            (Factory & Configuration)
                      ↓
              Ingestion Service
    (Rate Limiting & Secret Resolution)
                      ↓
             Safe Retry Policy
     (Bounded Exponential Backoff + Jitter)
                      ↓
            Idempotency Engine
    (Native ID + Fallback SHA-256 Fingerprint)
                      ↓
             Raw Event Boundary
  (Preserved Raw Payloads + Sensitive Redaction)
                      ↓
          Persistence / Queue Boundary
        (Storage, Scheduling, Webhooks)
                      ↓
        [Future Step: Normalization]
                      ↓
           [Future: Risk Engine]
```

> [!IMPORTANT]
> **Scope Clarification**:
> - Step 1 establishes the provider-agnostic infrastructure.
> - Provider-specific integrations (OpenWeather, TomTom, AISStream, OpenSky, Karrio, GTFS-RT, Tavily, etc.) begin in later Phase 5 steps.
> - Canonical event normalization and Risk Engine ingestion are **NOT** implemented in this step.

---

## 2. Provider Adapter Interface

The adapter layer decouples transport protocols (REST, WebSockets, Polling, Webhooks) from internal services using `BaseProviderAdapter`:

- **Location**: [`api/app/integrations/base.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/base.py)
- **Primary Properties**:
  - `provider_name: str`: Unique provider identifier (e.g. `mock_weather`, `tomtom`, `aisstream`).
  - `provider_type: ProviderType`: Domain enum (`WEATHER`, `ROAD_TRAFFIC`, `OCEAN_AIS`, `AIR`, `RAIL`, `LOGISTICS_TRACKING`, `NEWS_RESEARCH`, `CUSTOM`).
  - `capabilities: ProviderCapabilities`: Declares polling, webhooks, streaming, batch support, and modal capabilities.
- **Contract Methods**:
  - `fetch(**kwargs) -> IngestionBatch`: Retrieves raw signals without performing canonical normalization.
  - `health_check() -> ProviderHealthResult`: Executes active or passive diagnostic probes.
  - `parse_webhook(headers, payload, correlation_id) -> RawEvent`: Standardized push parser.
  - `close()`: Lifecycle tear-down hook.

---

## 3. Provider Registry

The registry provides thread-safe lifecycle and adapter factory capabilities:

- **Location**: [`api/app/integrations/registry.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/registry.py)
- **Responsibilities**:
  - Registers adapter classes and default configurations.
  - Rejects duplicate provider registrations unless explicit `overwrite=True` is supplied.
  - Raises `ProviderNotFoundError` with clear diagnostic context upon unknown provider lookup.
  - Provides inspection via `list_providers()` and `get_capabilities(name)`.
  - Exposes `default_provider_registry` as an application-wide singleton.

---

## 4. Provider Configuration

Provider behavior is strongly typed via Pydantic v2 schemas:

- **Location**: [`api/app/integrations/config.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/config.py)
- **Fields**:
  - `provider_name: str`: Validated non-empty string.
  - `provider_type: ProviderType`: Classification enum.
  - `enabled: bool = True`: Kill-switch flag; disabled providers raise `ProviderDisabledError`.
  - `base_url: Optional[str]`: API endpoint base URL.
  - `timeout_seconds: float`: Positive bounded timeout.
  - `retry: RetryConfig`: Bounded retry parameters.
  - `rate_limit: RateLimitConfig`: Quota windows and burst limits.
  - `auth_mode: AuthMode`: Authentication scheme (`NONE`, `API_KEY_HEADER`, `API_KEY_QUERY`, `BEARER_TOKEN`, `OAUTH2`, `BASIC_AUTH`).
  - `secret_ref: Optional[str]`: Reference pointer to runtime secret store (e.g. `env:TOMTOM_API_KEY`).

---

## 5. Secret Management

RiskWise enforces a zero-trust credential architecture:

- **Rule 1**: API secrets are never stored in source code, committed files, or database records.
- **Rule 2**: `ProviderConfig.secret_ref` stores only pointers (e.g., `env:OPENWEATHER_KEY` or AWS Secrets Manager ARN).
- **Rule 3**: `SecretResolver.resolve_secret()` dynamically evaluates credentials in-memory at call time.
- **Rule 4**: `SecretResolver.sanitize_payload()` recursively scrubs API keys, auth tokens, passwords, and client secrets from payloads before raw persistence.

---

## 6. Retry Policy

Transient network failures and rate limits are managed via bounded exponential backoff:

- **Location**: [`api/app/integrations/retry.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/retry.py)
- **Retryable Errors**: `ProviderTimeoutError`, `ProviderConnectionError`, transient `ProviderResponseError` (HTTP 502/503/504), OS/Socket errors.
- **Non-Retryable Errors**: `ProviderAuthenticationError`, `ProviderValidationError`, `ProviderPermanentError`, `ProviderDisabledError`, `DuplicateEventError`.
- **Delay Calculation**: $delay = \min(initial \times factor^{attempt}, max\_delay)$ with full random jitter ($\pm 25\%$).
- **`Retry-After` Support**: Respects explicit provider rate-limit wait hints, clamping to `max_delay_seconds`.

---

## 7. Idempotency Strategy

Providers frequently redeliver duplicate events during polling or webhook retries:

- **Location**: [`api/app/integrations/idempotency.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/idempotency.py)
- **Primary Deduplication**: If `provider_event_id` is present:
  $$\text{key} = \text{provider} + \text{provider\_event\_id}$$
- **Deterministic Fallback**: If no provider event ID exists:
  $$\text{key} = \text{provider} + \text{source\_timestamp} + \text{CanonicalJSON}(\text{payload})$$
- **Hashing**: Generates 256-bit SHA-256 fingerprints with sorted JSON keys.
- **Multi-Tenant Isolation**: Tenant-specific streams prepend `org:{org_id}` to ensure distinct organizations do not collide.
- **TTL Purge**: Thread-safe in-memory cache with configurable TTL (default 24h) and automated expired entry pruning.

---

## 8. Raw Data Boundary

Preserving un-normalized raw data is critical for auditability, bug replay, and downstream algorithmic tuning:

- **Model**: `RawEvent` in [`api/app/integrations/base.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/base.py).
- **Attributes**: `event_id`, `provider_name`, `provider_type`, `provider_event_id`, `fingerprint`, `source_timestamp`, `ingested_at`, `raw_payload`, `metadata`, `org_id`, `event_type`.
- **Abstraction**: `RawEventStorage` / `InMemoryRawEventStorage` in [`api/app/integrations/boundaries.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/boundaries.py).
- **Strict Boundary**: No canonical normalization (e.g. mapping to `ShipmentEvent` or `Incident`) occurs at this boundary.

---

## 9. Ingestion Service & Metadata

The central coordinator is `IngestionService`:

- **Location**: [`api/app/integrations/service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/service.py)
- **Execution Lifecycle**:
  1. Generates `ingestion_run_id`, `request_id`, and `correlation_id`.
  2. Resolves provider adapter and active configuration.
  3. Verifies provider enablement status.
  4. Checks rate limits and acquires quota tokens.
  5. Executes fetch through bounded `RetryPolicy`.
  6. Recursively redacts sensitive payload fields.
  7. Deduplicates events via `IdempotencyEngine`.
  8. Commits fresh events to `RawEventStorage`.
  9. Compiles execution metrics into `IngestionMetadata`.
- **Metadata Fields**:
  - `request_id`, `correlation_id`, `ingestion_run_id`, `provider`, `duration_ms`, `retry_count`, `items_fetched`, `items_ingested`, `items_deduplicated`, `timestamp`, `error_class`, `error_message`.

---

## 10. Ingestion Status Outcomes

Internal outcomes are tracked via `IngestionStatus`:

| Status | Condition |
| :--- | :--- |
| `SUCCESS` | All retrieved events were new and successfully stored. |
| `PARTIAL` | Some events were stored, while others were skipped as duplicates. |
| `SKIPPED_DUPLICATE` | All fetched events were identified as duplicates; none stored. |
| `RETRYING` | Intermediate state during bounded transient backoff attempts. |
| `FAILED` | Invocation failed permanently or exhausted all retries. |

---

## 11. Error Classification Hierarchy

External communication failures are categorized cleanly under `IngestionError`:

```
IngestionError
  ├── ProviderConfigurationError
  ├── ProviderNotFoundError
  ├── ProviderDisabledError
  ├── ProviderAuthenticationError  (Non-retriable)
  ├── ProviderValidationError      (Non-retriable)
  ├── ProviderPermanentError       (Non-retriable)
  ├── DuplicateEventError          (Non-retriable)
  ├── ProviderRateLimitError       (Retriable with backoff)
  ├── ProviderTimeoutError         (Retriable)
  ├── ProviderConnectionError      (Retriable)
  └── ProviderResponseError        (Retriable if 5xx)
```

Every exception provides safe serialization via `.to_safe_dict()` to prevent leaking internal socket traces or secret references.

---

## 12. Observability

Structured logging is implemented via standard Python logging under `riskwise.integrations.*`:

- Ingestion run lifecycles are logged with `req_id`, `corr_id`, `run_id`, and `provider`.
- Transient retries log attempt number, delay, and exception type.
- Payload contents are never dumped with unsanitized credentials.
- Future CloudWatch integration is supported via correlation ID propagation.

---

## 13. Health Checks

Diagnostics are supported via `check_health(provider_name)`:

- Evaluates adapter reachability, credentials, and network latency.
- Returns `ProviderHealthResult` with `status`: `HEALTHY`, `DEGRADED`, `UNHEALTHY`, or `UNCONFIGURED`.
- Tracks `latency_ms` and `last_successful_check`.

---

## 14. Scheduling Boundary

Periodic data retrieval is decoupled from provider business logic:

- **Location**: [`api/app/integrations/boundaries.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/boundaries.py)
- **Interface**: `IngestionScheduler` with job descriptor `ScheduledIngestionJob`.
- **Future Integration**: Seamlessly maps to EventBridge scheduled rules, SQS queues, or ECS Fargate workers without requiring Celery.

---

## 15. Webhook Boundary

Push-based signal ingestion is abstracted via `WebhookReceiver`:

- **Interface**: `verify_signature(payload_bytes, signature, secret) -> bool` and `parse_payload(raw_body, headers) -> dict`.
- **Separation of Concerns**: Cryptographic verification is isolated from ingestion orchestration.

---

## 16. Rate Limiting

Client-side rate limiting and provider quota enforcement are managed by `ProviderRateLimiter`:

- **Location**: [`api/app/integrations/rate_limiter.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/rate_limiter.py)
- **Design**: Thread-safe sliding window and token bucket algorithm.
- **Windows**: Supports per-minute and per-hour windows.
- **Cooldown**: Supports explicit provider backoff cooldowns when `Retry-After` headers are received.

---

## 17. Multi-Tenant Security

- **Public vs Tenant Data**: Global data (e.g. ambient weather or public AIS) has `org_id = None`. Tenant-specific logistics streams are tagged with `org_id`.
- **Tenant Idempotency**: Deduplication keys are scoped by `org:{org_id}` for tenant-specific events, preventing cross-tenant collision.
- **Zero Secrets in Persistence**: Secrets are resolved dynamically at runtime and never persisted.

---

## 18. Testing Strategy & Validation

A dedicated unit test suite validates all 25 core foundation requirements:

- **Test Suite**: [`api/tests/test_ingestion_foundation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_ingestion_foundation.py)
- **Coverage**:
  1. Provider registration
  2. Duplicate registration rejection
  3. Unknown provider lookup error
  4. Provider configuration validation
  5. Disabled provider refusal
  6. Provider adapter invocation
  7. Timeout handling
  8. Connection failure handling
  9. Authentication failure handling (fatal, non-retried)
  10. Rate limit detection and token acquisition
  11. Retry-After compliance
  12. Bounded exponential retry with recovery
  13. Permanent error non-retry behavior
  14. Idempotency deduplication
  15. Duplicate event status transitions (`SKIPPED_DUPLICATE`, `PARTIAL`)
  16. Fallback SHA-256 payload fingerprinting
  17. Raw event boundary storage
  18. Sensitive field redaction
  19. Ingestion status enum coverage
  20. Ingestion metadata auditing
  21. Correlation & request ID propagation
  22. Health check evaluation
  23. Multi-tenant isolation
  24. Secret non-exposure
  25. Boundary and regression compatibility
- **Execution**: 25 passed in 0.25s with 100% isolation (zero live AWS or external network calls).

---

## 19. Future Provider Integration Model

In subsequent Phase 5 steps, real providers will plug into this foundation by subclassing `BaseProviderAdapter`:

| Step | Provider Domain | Adapter Implementation |
| :--- | :--- | :--- |
| Phase 5 Step 2 | Road Traffic | TomTom Traffic / Incidents Adapter |
| Phase 5 Step 3 | Weather | OpenWeather Disruption Adapter |
| Phase 5 Step 4 | Ocean AIS | AISStream Maritime Tracking Adapter |
| Phase 5 Step 5 | Air Freight | OpenSky Network Flight Disruption Adapter |
| Phase 5 Step 6 | Multimodal Tracking | Karrio / Carrier Telematics Adapter |
| Phase 5 Step 7 | Global Intelligence | Tavily News & Geopolitical Risk Adapter |
| Phase 5 Step 8 | Canonical Normalization | Transformation into `ShipmentEvent` & `Risk` pipeline |
