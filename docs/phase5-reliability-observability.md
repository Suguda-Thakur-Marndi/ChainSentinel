# RiskWise 2.0 — Phase 5 Step 10: Reliability & Observability Documentation

Production-grade reliability, fault tolerance, and observability infrastructure for external data ingestion in RiskWise 2.0.

---

## 1. Observability Architecture

The Phase 5 ingestion observability architecture hardens and extends RiskWise 2.0's existing service layer without introducing external monitoring agent dependencies or competing subsystems.

```
                    ┌──────────────────────────────────────────────┐
                    │            Ingestion Request                 │
                    │  (request_id, correlation_id, trace_id, org) │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │          ProviderCircuitBreaker              │
                    │         (CLOSED / OPEN / HALF_OPEN)          │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │          ProviderRateLimiter                 │
                    │        (Sliding Window & Cooldowns)          │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │         Bounded RetryPolicy                  │
                    │         (Exponential Backoff+Jitter)         │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │               RawEvent                       │
                    │   (Secret Scrubbing & Freshness Tagging)     │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │           IdempotencyEngine                  │
                    │      (Deterministic SHA-256 Hashes)          │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │         NormalizationPipeline                │
                    │        (Batch Error Isolation)               │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │        CanonicalExternalEvent                │
                    │    (Traceability & Quality Assessment)       │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │          ShipmentEventBridge                 │
                    │  (Correlated Persistence Dictionary Mapping) │
                    └──────────────────────────────────────────────┘
```

Telemetry hooks emit into:
- **`IngestionStructuredLogger`**: Key-value telemetry records with monotonic timings and zero secret/PII exposure.
- **`IngestionMetricsCollector`**: Thread-safe counters, gauges, and duration distributions.
- **`InMemoryIngestionAuditLedger`**: Append-only lifecycle audit trail.

---

## 2. Correlation Identifiers

Every ingestion operation binds six distinct correlation and tenancy identifiers:
1. `request_id`: Identifies the client or HTTP caller invocation.
2. `correlation_id`: Binds operations across distributed supply-chain flows.
3. `trace_id`: Distributed trace identifier (`trc-...`) propagated across downstream components.
4. `ingestion_run_id`: Unique run UUID assigned per `ingest()` cycle.
5. `provider`: External provider identifier (e.g. `openweather`, `tomtom`, `aisstream`, `opensky`, `rail`, `karrio`, `tavily`).
6. `organization_id`: Tenant context ensuring strict multi-tenant boundary isolation.

### Pipeline Propagation
All identifiers flow unaltered through:
$$\text{Provider Request} \longrightarrow \text{RawEvent.metadata} \longrightarrow \text{CanonicalExternalEvent} \longrightarrow \text{ShipmentEventBridge} \longrightarrow \text{ShipmentEvent.metadata\_json}$$

---

## 3. Structured Logging

Implemented in `IngestionStructuredLogger` under the `riskwise.integrations.structured` logger namespace.

Key fields included in every structured log record:
- `timestamp`: ISO-8601 UTC timestamp
- `log_level`: Severity name (INFO, WARNING, ERROR)
- `provider`: Provider adapter name
- `operation`: Target operation (e.g. `ingest`, `health_check`)
- `status`: Outcome status (`SUCCESS`, `PARTIAL`, `SKIPPED_DUPLICATE`, `FAILED`)
- `duration_ms`: Total execution time using monotonic clock
- `retry_count`: Retries executed during the run
- `event_count`: Total events received from provider
- `normalized_count`: Valid events normalized
- `rejected_count`: Malformed events rejected
- `duplicate_count`: Duplicates identified by idempotency
- `request_id`, `correlation_id`, `trace_id`, `organization_id`
- `error_type` & `error_message`: Sanitized error details when failures occur

Raw provider payload blobs are stripped before logging to prevent high volume logs and accidental leaks.

---

## 4. Secret & PII Redaction

Security scrubbing operates at multiple layers (`SecretResolver`, `sanitize_for_logging`, and `sanitize_payload`):
- **Credentials Scrubbed**: Any field containing `api_key`, `secret`, `token`, `password`, `auth`, `credentials`, `authorization`, or `cookie` is replaced with `[REDACTED_SECRET]`.
- **Customer PII Scrubbed**: Keys matching `email`, `phone`, `ssn`, `credit_card`, `date_of_birth` are replaced with `[REDACTED_PII]`.
- **Logistics PII Scrubbed**: `consignee_name`, `customer_name`, `billing_address` replaced with `[REDACTED_LOGISTICS_PII]`.
- **Tracking Identifiers Masked**: Identifiers masked via `mask_sensitive_identifier` (e.g. `TRK-9876543210` $\rightarrow$ `TR****3210`).

---

## 5. Provider Health System

`ProviderHealthStatus` defines explicit health states:
- `HEALTHY`: Connectivity, authentication, and responses verified; circuit closed.
- `DEGRADED`: Provider is rate-limited (in cooldown), circuit is HALF_OPEN, or recent transient errors occurred.
- `UNAVAILABLE`: Circuit is OPEN, credentials rejected (401/403), provider disabled, or gateway unreachable.
- `UNCONFIGURED`: Provider is unregistered.

`ProviderHealthResult` fields:
- `provider_name`: str
- `status`: ProviderHealthStatus
- `latency_ms`: Monotonic probe duration in ms
- `circuit_state`: CLOSED, OPEN, or HALF_OPEN
- `consecutive_failures`: Recent failure count
- `rate_limited`: Boolean indicating active cooldown
- `failure_category`: Categorized reason when unhealthy
- `last_successful_check`: Timestamp of last healthy probe

---

## 6. Failure Classification

Deterministic classification mapping in `classify_failure(exc)`:

| FailureCategory | Triggers | Retriable |
|---|---|---|
| `TRANSIENT_NETWORK` | `ConnectionResetError`, `ProviderConnectionError`, DNS drops | Yes |
| `TIMEOUT` | `ProviderTimeoutError`, `TimeoutError`, read/connect timeouts | Yes |
| `RATE_LIMITED` | `ProviderRateLimitError`, HTTP 429 | Yes (with backoff) |
| `AUTHENTICATION` | `ProviderAuthenticationError`, HTTP 401 | No |
| `AUTHORIZATION` | HTTP 403 Forbidden | No |
| `INVALID_REQUEST` | `ProviderValidationError`, HTTP 400, 422 | No |
| `PROVIDER_UNAVAILABLE` | HTTP 502, 503, 504, disabled adapter | Yes (transient 5xx) |
| `MALFORMED_RESPONSE` | HTTP 500, corrupt JSON, Protobuf DecodeError | Conditional |
| `NORMALIZATION_ERROR` | Schema mismatch, invalid coordinates | No (isolated per event) |
| `IDEMPOTENCY_ERROR` | `DuplicateEventError`, hash collision | No |
| `CONFIGURATION_ERROR` | Missing required config fields | No |
| `CIRCUIT_OPEN` | Fast-failed by circuit breaker | No |
| `INTERNAL_ERROR` | Unhandled fallback exceptions | No |

All exceptions preserve root-cause exceptions via `original_exception` and `__cause__`.

---

## 7. Retry Instrumentation

`RetryPolicy` enhancements:
- Evaluates `is_retriable(exc)` with strict exclusion of `CircuitBreakerOpenError`, `ProviderAuthenticationError`, `ProviderValidationError`, and permanent errors.
- Records each attempt in `RetryAttempt` (attempt number, max retries, backoff delay, reason, `retry_after`, timestamp, `error_type`).
- Emits `IngestionAuditAction.RETRY_ATTEMPTED` audit records and increments `provider_retry_total` metric.

---

## 8. Rate Limit Instrumentation

`ProviderRateLimiter` enhancements:
- Sliding minute and hour windows tracked using monotonic timestamps.
- Cooldown durations set upon receipt of HTTP 429 or `Retry-After`.
- Rejections increment `provider_rate_limit_total` metric and emit `RATE_LIMITED` audit events.
- Safe diagnostic inspection available via `get_provider_status(provider_name)` without exposing credentials.

---

## 9. Ingestion Metrics

`IngestionMetricsCollector` tracks application-level telemetry:
- **Counters**:
  - `ingestion_requests_total` (tagged by `provider`, `org_id`)
  - `ingestion_success_total` (tagged by `provider`, `status`)
  - `ingestion_failure_total` (tagged by `provider`, `reason`)
  - `ingestion_events_received_total` (tagged by `provider`)
  - `ingestion_events_normalized_total` (tagged by `provider`)
  - `ingestion_duplicates_total` (tagged by `provider`)
  - `provider_retry_total` (tagged by `provider`)
  - `provider_rate_limit_total` (tagged by `provider`)
- **Gauges**:
  - `provider_health_status` (1.0 = HEALTHY, 0.5 = DEGRADED, 0.0 = UNAVAILABLE)
- **Durations**:
  - `provider_request_duration` (tracks count, total, min, max, average)
- **Extensibility**:
  - `add_hook(callable)` allows streaming metrics to external sinks without code changes.

---

## 10. Latency Measurement

All latency metrics utilize high-resolution monotonic clocks (`time.perf_counter()`):
- `total_duration_ms`: End-to-end ingestion cycle duration.
- `provider_request_duration_ms`: Duration of remote provider network fetch.
- `normalization_duration_ms`: Processing and schema normalization duration.
- `storage_duration_ms`: Raw boundary storage write duration.

Duration calculation from wall-clock timestamps is strictly avoided.

---

## 11. Partial Success & Normalization Isolation

`NormalizationPipeline.normalize_batch(events)` implements granular error boundaries:
- Malformed events raise exceptions within their individual try-catch boundary.
- Erroneous events are appended to `rejected_events` with detailed reasons and raw IDs.
- Valid events continue to be processed and appended to `normalized_events`.
- Batches with a mix of valid, duplicate, or rejected events return `IngestionStatus.PARTIAL`.

---

## 12. Stale Data Detection

`StaleDataDetector` configures provider-specific freshness expectations:
- OpenSky / AIS: 1 hour (high dynamic mobility)
- TomTom Road: 2 hours
- Rail GTFS-RT: 1 hour
- OpenWeather: 6 hours
- Karrio Tracking: 7 days
- Tavily News: 30 days
- Default: 24 hours

Events exceeding thresholds are flagged with `is_stale = True` and `stale_age_seconds` in event metadata. They are **not blindly dropped**, preserving auditability and historical replay capabilities.

---

## 13. Data Quality vs Provider Health

Data quality and provider health are decoupled:
- **Provider Health**: Diagnostic operational state of the adapter (`HEALTHY`, `DEGRADED`, `UNAVAILABLE`).
- **Data Quality**: Completeness and structural validity of an individual event (`VALID`, `PARTIAL`, `INVALID`).
A healthy provider may return partial or invalid events; an unhealthy provider might have historic valid events.

---

## 14. Ingestion Audit Trail

`InMemoryIngestionAuditLedger` maintains an immutable append-only record of lifecycle events:
- `INGESTION_STARTED`
- `PROVIDER_REQUESTED`
- `PROVIDER_SUCCEEDED`
- `PROVIDER_FAILED`
- `RETRY_ATTEMPTED`
- `RATE_LIMITED`
- `EVENT_NORMALIZED`
- `DUPLICATE_DISCARDED`
- `EVENT_REJECTED`
- `INGESTION_COMPLETED`

Filtered retrieval is supported by `provider_name`, `action`, `org_id`, and `correlation_id`.

---

## 15. Scheduler Reliability

`InMemoryIngestionScheduler` improvements:
- **Bounded Execution**: Bounded execution lifecycle tracking (`execute_job`).
- **Failure Isolation**: Job exceptions are caught, recorded in `last_error` and `last_status = "FAILED"`, incrementing `consecutive_failures` without crashing the scheduler.
- **Cancellation**: Supports cooperative cancellation via `request_cancel(job_id)`.
- **Concurrency**: Thread-safe job registry and run state tracking.

---

## 16. Provider Circuit Breaker

`ProviderCircuitBreaker` implements a state machine per provider:
- **CLOSED**: Requests pass through. Repeated failures increment failure counter.
- **OPEN**: Trips when failures $\ge$ `failure_threshold` (default 5). Calls immediately fail with `CircuitBreakerOpenError` without hitting the network.
- **HALF_OPEN**: After `cooldown_seconds` (default 30s), a single probe call is permitted.
- **Recovery**: Successful probe transitions to `CLOSED`. Failure immediately reopens to `OPEN`.

---

## 17. Concurrency & Thread Safety

Thread safety verified across:
- `ProviderRegistry`: Mutex locked registration and adapter lookup.
- `ProviderRateLimiter`: Mutex locked sliding windows and cooldown state.
- `IdempotencyEngine`: Mutex locked deduplication hash store.
- `InMemoryRawEventStorage` & `InMemoryCanonicalEventStorage`: Thread-safe dictionary eviction.
- `ProviderCircuitBreaker`: Thread-safe per-provider state machine.
- `InMemoryIngestionAuditLedger` & `IngestionMetricsCollector`: Thread-safe record appending and counter updates.

---

## 18. Multi-Tenant Isolation

Tenant boundaries are strictly preserved:
- Idempotency hashing scopes keys with `org:{org_id}:...`.
- Raw event storage filtering supports `org_id` filtering.
- Audit ledger queries support `org_id` filtering.
- Metrics collector tags dimensions by `org_id`.
- Correlation IDs are scoped per organization.

---

## 19. Provider Failure Isolation

Failure in one provider cannot compromise unrelated providers:
- `OpenWeather` failure does not affect `TomTom`.
- `AISStream` failure does not affect `OpenSky`.
- `Tavily` failure does not affect `Karrio`.
Circuit breaker state, rate limiter windows, and failure counts are strictly isolated per provider key.

---

## 20. Testing Verification

Comprehensive verification in `test_ingestion_reliability_observability.py`:
- 50 dedicated test cases covering all 50 target reliability criteria.
- 471 cumulative Phase 5 integration tests passing 100%.
- Database schema verified at exactly 34 tables with zero migrations.
- Public FastAPI OpenAPI schema verified intact (60 paths, 96 operations, 104 schemas).

---

## 21. Limitations

1. **In-Memory Volatility**: Schedulers, circuit breaker states, and rate limits reside in-memory; restarts reset transient counters.
2. **Local Metric Sink**: Metrics are collected in-memory with hook dispatch; integration with external APM/CloudWatch is deferred to production infrastructure deployment.
3. **Provider Modality Independence**: Ingestion error isolation prevents cross-provider substitution; semantic fallbacks must be explicitly governed by business domain rules.
