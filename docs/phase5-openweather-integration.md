# RiskWise 2.0 — Phase 5 Step 3: OpenWeather Weather Data Integration

This document defines the production integration architecture, data contracts, normalization logic, operational boundaries, and security standards for integrating **OpenWeather** into RiskWise 2.0.

---

## 1. Executive Summary & Context

Phase 5 Step 3 integrates OpenWeather as the primary external meteorological provider within the RiskWise 2.0 signal ingestion ecosystem. It strictly builds upon:
- **Phase 5 Step 1 (`api/app/integrations/base.py`, `boundaries.py`, `service.py`)**: Provider abstractions, raw boundaries, secret resolution, bounded exponential retry, token rate-limiting, and deterministic idempotency deduplication.
- **Phase 5 Step 2 (`api/app/integrations/canonical.py`, `normalizers.py`)**: The provider-agnostic `CanonicalExternalEvent` taxonomy, quality evaluation (`VALID`, `PARTIAL`, `INVALID`), and `ShipmentEventBridge`.

### Core Architectural Invariant
Provider-specific OpenWeather JSON response structures are **strictly confined** to the provider adapter and `RawEvent` storage boundaries. Downstream risk scoring engines, supply chain graph resolvers, and analytics services **never** consume OpenWeather payloads directly; they interact exclusively with normalized `CanonicalExternalEvent` models.

```
OpenWeather HTTP API
         ↓
OpenWeatherAdapter (api/app/integrations/providers/openweather.py)
         ↓
RawEvent (Stored in RawEventStorage with sanitized raw_payload)
         ↓
OpenWeatherNormalizer (NormalizationPipeline)
         ↓
CanonicalExternalEvent (Validated, strongly typed, quality-scored)
         ↓
Optional ShipmentEventBridge / Downstream Subsystems
```

---

## 2. Verified OpenWeather API & Capabilities

### Verified Provider Endpoints

| Capability | Official OpenWeather Endpoint | HTTP Method | Plan / Access Requirement |
|---|---|---|---|
| **Current Weather Data 2.5** | `https://api.openweathermap.org/data/2.5/weather` | `GET` | All plans (Free tier inclusive) |
| **One Call API 3.0** | `https://api.openweathermap.org/data/3.0/onecall` | `GET` | "One Call by Call" subscription (1,000 free calls/day) |

### Current Weather Data 2.5 (Primary Integration Endpoint)
The primary endpoint utilized for location-based weather observations is `https://api.openweathermap.org/data/2.5/weather`.

#### Query Parameters
- `lat` (float, required): Latitude of observation point [-90.0, +90.0].
- `lon` (float, required): Longitude of observation point [-180.0, +180.0].
- `appid` (string, required): OpenWeather API key.
- `units` (string, optional): Units of measurement (`metric` [Celsius, m/s], `standard` [Kelvin], `imperial` [Fahrenheit]). RiskWise defaults to `metric`.
- `lang` (string, optional): Language code for condition output.

#### Verified JSON Response Structure
```json
{
  "coord": { "lon": -0.1278, "lat": 51.5074 },
  "weather": [
    {
      "id": 800,
      "main": "Clear",
      "description": "clear sky",
      "icon": "01d"
    }
  ],
  "base": "stations",
  "main": {
    "temp": 18.5,
    "feels_like": 18.1,
    "temp_min": 17.0,
    "temp_max": 20.0,
    "pressure": 1016,
    "humidity": 55,
    "sea_level": 1016,
    "grnd_level": 1012
  },
  "visibility": 10000,
  "wind": {
    "speed": 3.6,
    "deg": 210,
    "gust": 5.2
  },
  "clouds": { "all": 10 },
  "rain": { "1h": 8.5, "3h": 15.0 },
  "snow": { "1h": 2.1 },
  "dt": 1661870592,
  "sys": {
    "country": "GB",
    "sunrise": 1661834187,
    "sunset": 1661882025
  },
  "timezone": 3600,
  "id": 2643743,
  "name": "London",
  "cod": 200
}
```

---

## 3. Weather Alert Capabilities & Limitations

### Verified Provider Capability Distinction

| Feature | Current Weather Data 2.5 (`/data/2.5/weather`) | One Call API 3.0 (`/data/3.0/onecall`) |
|---|---|---|
| **Government Weather Alerts** | ❌ **Not Supported** (No `alerts` block exists in response schema) | ✅ **Supported** (Returns `alerts` array with `sender_name`, `event`, `start`, `end`, `description`, `tags`) |
| **Severe Weather Indicators** | ✅ **Supported** via condition codes (Thunderstorm 2xx, Tornado 781, Squall 771) and physical metric thresholds | ✅ **Supported** via condition codes and government warning alerts |
| **Subscription Requirement** | Universal Free / Developer tier | Requires credit card registration |

### RiskWise Operational Policy on Weather Alerts
1. **No Fabrication**: RiskWise never fabricates synthetic alerts when calling the standard Current Weather 2.5 endpoint.
2. **Normal Weather Non-Inflation**: Normal ambient weather observations (clear skies, cloudy days, light rain, moderate breezes) remain classified as `EventSeverity.INFO` or `EventSeverity.LOW` under `CanonicalEventType.CUSTOM` (`event_classification="WEATHER_OBSERVATION"`). Normal weather **never** triggers artificial critical-risk alerts.
3. **Severe Weather Physical Justification**:
   - Severe conditions explicitly verified in observation data map to justified canonical types:
     - Tornado (Condition 781): `CanonicalEventType.EXTREME_WEATHER`, `EventSeverity.CRITICAL`
     - Hurricane-force winds ($\ge 32\text{ m/s}$) or Squalls (771): `CanonicalEventType.STORM`, `EventSeverity.CRITICAL`
     - Thunderstorms (Condition 200–232): `CanonicalEventType.STORM`, `EventSeverity.MEDIUM` (or `HIGH` for violent thunderstorms / gale winds)
     - Extreme Temperature ($\ge 45^\circ\text{C}$ or $\le -25^\circ\text{C}$): `CanonicalEventType.EXTREME_WEATHER`, `EventSeverity.HIGH`
     - Torrential Rain ($\ge 50\text{ mm/1h}$): `CanonicalEventType.EXTREME_WEATHER`, `EventSeverity.HIGH`
4. **One Call 3.0 Alert Ingestion**: When One Call 3.0 payloads with an `alerts` array are processed, the normalizer maps them to `CanonicalEventType.WEATHER_ALERT` with all documented fields (`alert_event`, `alert_sender`, `alert_description`, `alert_tags`, `alert_start`, `alert_end`).

---

## 4. Authentication, Configuration & Secrets

### Secure Credential Resolution
API keys are resolved strictly at runtime using the existing `SecretResolver` architecture. Keys are **never** committed, logged, or serialized into database rows.

1. **Resolution Hierarchy**:
   1. Explicit runtime parameter `secret` passed to `OpenWeatherAdapter`.
   2. Secret reference specified in `config.secret_ref` (e.g. `env:OPENWEATHER_API_KEY`) resolved via `SecretResolver.resolve_secret()`.
   3. Direct environment variable fallback: `os.environ["OPENWEATHER_API_KEY"]`.
   4. If unconfigured: raises `ProviderConfigurationError` during fetch, or returns `ProviderHealthStatus.UNCONFIGURED` during health check.

2. **Zero Leakage Mandate**:
   - Query URLs logged for debugging automatically redact query parameter values: `appid=[REDACTED]`.
   - `SecretResolver.sanitize_payload()` is executed on raw payloads and normalized attributes.
   - Any `appid` key inadvertently returned in provider JSON is actively pruned before `RawEvent` storage.

### Provider Configuration Model (`ProviderConfig`)
```python
ProviderConfig(
    provider_name="openweather",
    provider_type=ProviderType.WEATHER,
    base_url="https://api.openweathermap.org/data/2.5/weather",
    auth_mode=AuthMode.API_KEY_QUERY,
    secret_ref="env:OPENWEATHER_API_KEY",
    timeout_seconds=10.0,
    rate_limit=RateLimitConfig(requests_per_minute=60, requests_per_hour=1000),
    retry=RetryConfig(max_retries=3, initial_delay_seconds=0.5, max_delay_seconds=10.0, backoff_factor=2.0),
    extra_settings={"units": "metric"},
)
```

---

## 5. Coordinate & Timestamp Normalization

### Coordinate Validation (`CoordinateValidator`)
- Pre-request enforcement: Geographic coordinates are strictly validated against WGS84 bounding limits ($-90.0 \le \text{lat} \le +90.0$, $-180.0 \le \text{lon} \le +180.0$) **before** any HTTP request is issued.
- Out-of-bounds inputs raise `ProviderValidationError` (HTTP 400 equivalent, non-retriable), preventing invalid outbound API requests and wasted quota.

### Timestamp Normalization (`TimestampNormalizer`)
- OpenWeather returns observation time as a Unix epoch integer in seconds (`dt`).
- The normalizer converts `dt` into a timezone-aware UTC `datetime` object (`datetime.fromtimestamp(dt, tz=timezone.utc)`).
- All canonical event timestamps (`event_timestamp`, `observed_at`, `received_at`) are guaranteed to have `tzinfo == timezone.utc`.

---

## 6. Canonical Mapping Specification

### Attribute Extraction Matrix

| OpenWeather Field | Canonical External Event Field | Target Type | Validation / Note |
|---|---|---|---|
| `dt` | `event_timestamp`, `observed_at` | `datetime` (UTC) | Unix epoch $\to$ ISO UTC |
| `coord.lat` | `location.latitude` | `float` | WGS84 $[-90.0, +90.0]$ |
| `coord.lon` | `location.longitude` | `float` | WGS84 $[-180.0, +180.0]$ |
| `name` | `location.location_name` | `str` | City / station name |
| `sys.country` | `location.country_code` | `str` | ISO 3166-1 alpha-2 / 3 |
| `main.temp` | `normalized_attributes["temperature_celsius"]` | `float` | Metric unit $\left(^\circ\text{C}\right)$ |
| `main.feels_like` | `normalized_attributes["feels_like_celsius"]` | `float` | Apparent temperature |
| `main.pressure` | `normalized_attributes["pressure_hpa"]` | `float` | Atmospheric pressure in hPa |
| `main.humidity` | `normalized_attributes["humidity_percent"]` | `float` | Relative humidity percentage |
| `visibility` | `normalized_attributes["visibility_meters"]` | `float` | Optional; extracted when present |
| `wind.speed` | `normalized_attributes["wind_speed_mps"]` | `float` | Wind speed in meters/second |
| `wind.deg` | `normalized_attributes["wind_deg"]` | `float` | Meteorological direction in degrees |
| `wind.gust` | `normalized_attributes["wind_gust_mps"]` | `float` | Optional gust speed |
| `rain.1h` / `rain.3h` | `normalized_attributes["rain_1h_mm"]` | `float` | Optional precipitation depth |
| `snow.1h` / `snow.3h` | `normalized_attributes["snow_1h_mm"]` | `float` | Optional snowfall depth |
| `weather[0].id` | `normalized_attributes["weather_id"]` | `int` | Condition code (e.g. 800=Clear) |
| `weather[0].main` | `normalized_attributes["weather_main"]`, `status` | `str` | Condition group (Rain, Clear, etc.) |
| `weather[0].description` | `normalized_attributes["weather_description"]` | `str` | Detailed textual description |
| `alerts` | `normalized_attributes["alert_*"]` | `dict` / `str` | Only present in One Call 3.0 |

### EventQuality Evaluation
- **`VALID`**: Coordinate validation passes AND entity correlation is established (e.g. `shipment_id`, `route_id`, `facility_id`, or `port_id` bound).
- **`PARTIAL`**: Observation has valid coordinates and timestamps but represents ambient weather without bound entity correlation.
- **`INVALID`**: Coordinates out of bounds, missing observation timestamp, or unparseable payload structure.

---

## 7. Deterministic Idempotency Strategy

Weather observations at fixed stations are frequently polled at regular intervals. To prevent duplicated storage or redundant alert triggers:

### Observation Fingerprint Strategy
The fingerprint is computed via collision-resistant SHA-256 using normalized spatial and temporal attributes:
$$\text{Payload} = \left\{\text{lat}: \text{round}(\text{lat}, 4),\, \text{lon}: \text{round}(\text{lon}, 4),\, \text{dt}: \text{str}(\text{dt}),\, \text{weather\_id}: \text{id}\right\}$$
$$\text{Fingerprint} = \text{SHA-256}\left(\text{"org:"} + \text{org\_id} + \text{":openweather:ts:"} + \text{ts} + \text{":payload:"} + \text{canonical\_json}(\text{Payload})\right)$$

- **Spatial stability**: Rounding coordinates to 4 decimal places ($\sim 11\text{ meters}$) prevents floating-point jitter across queries.
- **Temporal stability**: Keyed on the observation epoch `dt` rather than local polling reception time.
- **Tenant isolation**: Scoped to `org_id`; public data without `org_id` is globally deduplicated.

---

## 8. Error Handling, Rate Limiting & Retries

### HTTP Status Code Mapping

| Status Code | RiskWise Exception | Retriable | Operational Action |
|---|---|---|---|
| **401 / 403** | `ProviderAuthenticationError` | ❌ No | Log alert; do not retry; mark health check UNHEALTHY |
| **429** | `ProviderRateLimitError` | ✅ Yes | Parse `Retry-After` header; apply backoff cooldown |
| **400** | `ProviderValidationError` | ❌ No | Reject invalid coordinates/parameters |
| **404** | `ProviderPermanentError` | ❌ No | Non-retriable resource error |
| **500, 502, 503, 504** | `ProviderResponseError` | ✅ Yes | Bounded exponential retry with jitter |
| **Timeout** | `ProviderTimeoutError` | ✅ Yes | Bounded retry with backoff |
| **Connection Drop** | `ProviderConnectionError` | ✅ Yes | Bounded retry with backoff |

---

## 9. Provider Health Check Specification

The `OpenWeatherAdapter.health_check()` method executes a non-destructive probe against reference coordinates (London `51.5074, -0.1278`):
- **`HEALTHY`**: HTTP 200 returned with valid JSON structure containing `main` and `weather`.
- **`UNCONFIGURED`**: No API key configured in secret or environment variables.
- **`UNHEALTHY`**: HTTP 401/403 (invalid key), HTTP 5xx, timeout, or DNS/TCP failure.
- **`DEGRADED`**: HTTP 429 quota exhaustion or active rate limiting.

Credentials are never exposed in error or health-check result messages.

---

## 10. Observability & Auditing

Every invocation orchestrated via `IngestionService.ingest("openweather", ...)` emits structured `IngestionMetadata`:
- `request_id`, `correlation_id`, `ingestion_run_id`
- `provider`: `"openweather"`
- `duration_ms`: Total execution time in milliseconds
- `items_fetched`, `items_ingested`, `items_deduplicated`
- `retry_count`: Retries executed during transient errors
- Sanitized error classification without secret exposure

---

## 11. Testing & Validation Summary

The OpenWeather integration is verified by 35 focused, deterministic unit tests in `api/tests/test_openweather_integration.py` using `httpx.MockTransport` with zero live network calls:
1. Adapter initialization & capability inspection
2. Configuration loading and overrides
3. Missing API key rejection
4. Successful weather observation fetch
5. Coordinate validation
6. Invalid latitude rejection before request
7. Invalid longitude rejection before request
8. UTC timestamp normalization
9. Temperature metric mapping
10. Precipitation extraction when present
11. Wind speed, direction, and gust extraction
12. Barometric pressure extraction
13. Humidity percentage extraction
14. Visibility in meters extraction
15. Weather condition mapping
16. Missing optional fields robustness
17. Malformed provider JSON response handling
18. Authentication failure (HTTP 401/403) handling
19. Rate limit response (HTTP 429) & `Retry-After` parsing
20. Transient provider failure (HTTP 502/503) handling
21. Bounded retry behavior
22. `Retry-After` delay enforcement
23. Deterministic idempotency fingerprinting
24. Duplicate observation skipping
25. Canonical event generation
26. `EventQuality` assessment (`VALID`, `PARTIAL`, `INVALID`)
27. Normal weather non-inflation (never becomes critical risk)
28. Alert behavior according to supported capabilities
29. Health check status reporting
30. Raw payload preservation in `RawEvent`
31. Secret redaction from payloads and logs
32. `IngestionScheduler` job integration
33. Observability and audit metadata tracking
34. Multi-tenant `org_id` isolation
35. Severe weather condition code mapping (Thunderstorm/Storm)

---

## 12. Known Provider Limitations

1. **No Weather Alerts in 2.5**: Standard Current Weather Data 2.5 does not provide official government weather warning text. RiskWise detects severe conditions exclusively from verified meteorological readings and condition codes.
2. **Polling Latency**: Current Weather observations are updated every 10–30 minutes upstream by OpenWeather depending on station broadcast frequency.
3. **Coordinate Precision**: Minor GPS drift within 11 meters is normalized via 4-decimal coordinate rounding to guarantee idempotent deduplication.
