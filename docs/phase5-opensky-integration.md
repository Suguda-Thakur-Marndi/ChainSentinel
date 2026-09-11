# RiskWise 2.0 — Phase 5 Step 6: Air / OpenSky Integration

## 1. Executive Summary & Architecture Overview

Phase 5 Step 6 integrates real-time air traffic intelligence and ADS-B (Automatic Dependent Surveillance–Broadcast) state vectors into the RiskWise 2.0 supply chain risk platform using the official **OpenSky Network REST API** (`https://opensky-network.org/api`).

This integration strictly adheres to the provider-agnostic ingestion architecture established in Phase 5 Step 1 (Ingestion Foundation) and Step 2 (Canonical External Event Model):

```text
OpenSky Network (REST GET /states/all)
    │  (OAuth2 Client Credentials: POST /protocol/openid-connect/token)
    ▼
OpenSkyAdapter (api/app/integrations/providers/opensky.py)
    │
    ▼
RawEvent (Envelope with Raw Payload & Deterministic SHA-256 Fingerprint)
    │
    ▼
OpenSkyNormalizer
    │
    ▼
CanonicalExternalEvent (LOCATION_UPDATE, EventSeverity.INFO / CRITICAL, WGS84, SI Units)
    │
    ▼
Optional ShipmentEventBridge (ShipmentEvent persistence only when valid shipment_id correlation exists)
```

Provider-specific OpenSky array structures, index mappings, OAuth tokens, and client secrets **never leak** into downstream RiskWise engines (such as the Risk Engine, Digital Twin, or Control Tower).

---

## 2. Verified OpenSky Specifications & Protocols

Before implementation, official OpenSky Network API documentation was verified independently.

### 2.1 Verified REST Root & Official OAuth2 Token Endpoint
- **Official REST Root**: `https://opensky-network.org/api`
- **Official OAuth2 Token Endpoint**: `https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token`
- **Authentication Flow**: OAuth2 Client Credentials (`grant_type=client_credentials`).
  - *Critical Verification*: Basic authentication (username and password) has been retired by OpenSky and is no longer accepted.
- **Token Request**:
  - `POST` to token endpoint with `Content-Type: application/x-www-form-urlencoded`
  - Parameters:
    - `grant_type`: `client_credentials`
    - `client_id`: `<configured_client_id>`
    - `client_secret`: `<configured_client_secret>`
- **Token Response Envelope**:
  ```json
  {
    "access_token": "eyJhbGciOiJSUzI1NiIs...",
    "expires_in": 1800,
    "refresh_expires_in": 0,
    "token_type": "Bearer",
    "not-before-policy": 0,
    "scope": "email profile"
  }
  ```
- **API Request Authorization Header**:
  - `Authorization: Bearer <access_token>`

### 2.2 Verified State Vector Endpoint: `GET /states/all`
The primary Step 6 capability is real-time aircraft state-vector ingestion.

#### Supported Query Parameters
| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| **`time`** | integer | No | Unix timestamp in seconds since epoch. If omitted, current server time is used. |
| **`icao24`** | string (repeatable) | No | 24-bit ICAO transponder address in hex (e.g. `3c6444`). Can be repeated to filter multiple aircraft. |
| **`lamin`** | float | Optional (BBox) | Lower bound latitude in decimal degrees [-90.0, 90.0]. |
| **`lomin`** | float | Optional (BBox) | Lower bound longitude in decimal degrees [-180.0, 180.0]. |
| **`lamax`** | float | Optional (BBox) | Upper bound latitude in decimal degrees [-90.0, 90.0]. |
| **`lomax`** | float | Optional (BBox) | Upper bound longitude in decimal degrees [-180.0, 180.0]. |
| **`extended`** | integer | No | Set to `1` to include aircraft emitter category at index 17. |

*Rule*: If bounding-box filtering is used, all four coordinates (`lamin`, `lomin`, `lamax`, `lomax`) must be provided simultaneously.

#### Verified Response Structure
OpenSky returns a top-level JSON object containing a Unix timestamp and a two-dimensional array of state vectors:
```json
{
  "time": 1725800000,
  "states": [
    [
      "3c6444",
      "DLH123  ",
      "Germany",
      1725799995,
      1725799998,
      8.5678,
      50.0379,
      3200.4,
      false,
      180.2,
      245.5,
      -5.2,
      null,
      3310.0,
      "1000",
      false,
      0,
      4
    ]
  ]
}
```

#### State Vector Index Mapping
| Index | Field Name | Type | Verified Description & Units |
| :---: | :--- | :--- | :--- |
| **0** | `icao24` | `string` | Unique ICAO 24-bit transponder address in lowercase hex. |
| **1** | `callsign` | `string \| null` | 8-character callsign (trimmed of whitespace in normalization). |
| **2** | `origin_country` | `string` | Country name inferred from ICAO 24-bit allocation table. |
| **3** | `time_position` | `integer \| null` | Unix timestamp (seconds) of last position report. `null` if no position update within past 15s. |
| **4** | `last_contact` | `integer` | Unix timestamp (seconds) of any signal update received by OpenSky. |
| **5** | `longitude` | `float \| null` | WGS84 longitude in decimal degrees [-180.0, 180.0]. |
| **6** | `latitude` | `float \| null` | WGS84 latitude in decimal degrees [-90.0, 90.0]. |
| **7** | `baro_altitude` | `float \| null` | Barometric altitude in **meters**. |
| **8** | `on_ground` | `boolean` | `true` if position was emitted from a surface position report. |
| **9** | `velocity` | `float \| null` | Horizontal ground speed in **meters/second**. |
| **10** | `true_track` | `float \| null` | True track in decimal degrees clockwise from north (0° = North). |
| **11** | `vertical_rate` | `float \| null` | Vertical climb/descent speed in **meters/second** (+ = climbing, - = descending). |
| **12** | `sensors` | `int[] \| null` | Receiver IDs contributing to vector. `null` unless filtered by sensor. |
| **13** | `geo_altitude` | `float \| null` | Geometric (GNSS) altitude in **meters**. |
| **14** | `squawk` | `string \| null` | 4-digit transponder squawk code. |
| **15** | `spi` | `boolean` | Special Purpose Indicator (transponder IDENT). |
| **16** | `position_source`| `integer` | Source origin: `0`=ADS-B, `1`=ASTERIX, `2`=MLAT, `3`=FLARM. |
| **17** | `category` | `integer \| null`| Emitter category (`0-20`), present when `extended=1`. |

---

## 3. RiskWise Implementation Behavior

### 3.1 Dedicated Provider Adapter: `OpenSkyAdapter`
Located at `api/app/integrations/providers/opensky.py`:
- Inherits from `BaseProviderAdapter`.
- `provider_name = "opensky"`
- `provider_type = ProviderType.AIR`
- `capabilities = ProviderCapabilities(supports_polling=True, supports_webhook=False, supports_batch=True, supports_health_check=True, max_batch_size=500, supported_entities=["aircraft", "flight", "carrier", "shipment"], supported_modalities=["air", "adsb", "state_vector"])`

### 3.2 OAuth2 Token Lifecycle Manager: `OpenSkyOAuthTokenManager`
- Resolves credentials via `SecretResolver`:
  - `client_id`: from `extra_settings["client_id_ref"]` or `env:OPENSKY_CLIENT_ID`
  - `client_secret`: from `secret_ref` or `env:OPENSKY_CLIENT_SECRET`
- In-memory token caching using monotonic clock (`time.monotonic()`).
- Proactive token refresh with a 60-second safety window before expiration (`expires_at - 60.0`).
- Reactive recovery on HTTP 401: invalidates cached token and executes a single bounded token refresh before retrying the query.
- Security enforcement: access tokens and client secrets are never stored in `RawEvent`, `CanonicalExternalEvent`, or log statements.

### 3.3 Bounding Box & Spatial Validation
- Configuration class `OpenSkyBoundingBox` models `min_latitude`, `min_longitude`, `max_latitude`, `max_longitude`.
- Uses `CoordinateValidator.validate()`:
  - Latitude strictly bounded to `[-90.0, 90.0]`
  - Longitude strictly bounded to `[-180.0, 180.0]`
  - Requires `min_latitude <= max_latitude` and `min_longitude <= max_longitude`
- Coordinates violating bounds are rejected with `ProviderValidationError` *prior* to HTTP dispatch. Invalid bounds are never silently clamped.

### 3.4 Transponder Identifier (ICAO24) Validation
- Validates 24-bit transponder address representation (`^[0-9a-fA-F]{6}$`).
- Normalizes hex characters to lowercase.
- Preserves provider identifier without conflating ICAO24 with callsign or airline flight number.

### 3.5 Telemetry & Unit Preservation
- Units received from OpenSky are preserved directly:
  - Latitude / Longitude: WGS84 decimal degrees
  - Altitudes: meters (`baro_altitude_meters`, `geo_altitude_meters`)
  - Speeds: meters/second (`velocity_mps`, `vertical_rate_mps`)
  - Headings: degrees clockwise from north (`true_track_degrees`)
  - Timestamps: Unix epoch seconds converted to timezone-aware UTC datetime
- Nullability is preserved. No dummy coordinates (0.0, 0.0) or fake altitudes are fabricated when telemetry is missing.

### 3.6 Canonical Event Taxonomy Mapping
- Mapped to `CanonicalEventType.LOCATION_UPDATE` from the existing canonical taxonomy in `api/app/integrations/canonical.py`.
- **Informational Default**: Routine aircraft positions remain `EventSeverity.INFO` with operational status `"AIRBORNE"` or `"ON_GROUND"`. Routine aircraft movements are never artificially classified as supply chain risks.
- **Emergency Squawk Code Elevation**:
  - `squawk == "7700"`: General Emergency -> `EventSeverity.CRITICAL`, `status = "EMERGENCY"`
  - `squawk == "7600"`: Radio Failure (Lost Comm) -> `EventSeverity.HIGH`, `status = "RADIO_FAILURE"`
  - `squawk == "7500"`: Unlawful Interference (Hijack) -> `EventSeverity.CRITICAL`, `status = "UNLAWFUL_INTERFERENCE"`

### 3.7 Entity Correlation & ShipmentEventBridge
- `EntityCorrelation`:
  - `custom_identifiers["icao24"]`: 6-character hex transponder address
  - `custom_identifiers["callsign"]`: Trimmed callsign string
  - `custom_identifiers["origin_country"]`: Country of registration
  - `shipment_id`: Remains `None` for uncorrelated observations.
- `ShipmentEventBridge`:
  - `can_persist_to_shipment_event(canonical_event)` evaluates to `False` for raw observations. Uncorrelated aircraft state vectors do not trigger database writes to `ShipmentEvent`.
  - When downstream engines correlate an aircraft to a specific `shipment_id`, `ShipmentEventBridge.to_shipment_event_dict()` produces a valid dictionary with `mode: "AIR"`.

### 3.8 Deterministic Idempotency Fingerprinting
- Implements deterministic SHA-256 fingerprinting:
  ```text
  {org_prefix}opensky:state:{icao24}:ts:{time_pos or last_contact}:pos:{lat:.4f},{lon:.4f}:alt:{baro_alt:.1f}:vel:{velocity:.1f}:gnd:{on_ground}
  ```
- **Duplicate Prevention**: Re-ingesting the identical state vector yields the exact same fingerprint, allowing `IdempotencyEngine` to suppress redundant processing.
- **Consecutive Position Preservation**: Legitimate consecutive observations with different timestamps or updated coordinates produce distinct fingerprints and are never dropped.

### 3.9 Rate Limiting & Retry Policy
- Uses existing `ProviderRateLimiter` (sliding-window rate limiter) configured for OpenSky credit tiers (60 requests/minute default).
- Uses existing `RetryPolicy` with bounded exponential backoff and jitter.
- Transient 5xx errors (500, 502, 503, 504) and network timeouts trigger bounded retries.
- HTTP 429 Too Many Requests inspects `Retry-After` header and raises `ProviderRateLimitError`.
- Permanent authentication errors (HTTP 401 after refresh attempt, HTTP 403) fail immediately without endless retries.

### 3.10 Provider Health Checks
`OpenSkyAdapter.health_check()` executes non-destructive diagnostic probes and categorizes status into:
- **`UNCONFIGURED`**: Missing `client_id` or `client_secret`.
- **`HEALTHY`**: Successful OAuth2 token acquisition and successful probe query to `/states/all?icao24=3c6444`.
- **`DEGRADED`**: Rate limit reached (HTTP 429) or network probe timeout.
- **`UNHEALTHY`**: OAuth token failure, HTTP 401/403 authorization failure, or upstream HTTP 5xx.

### 3.11 Scheduler Integration
Provides reusable polling job constructor:
```python
job = create_opensky_polling_job(
    job_id="job_opensky_emea",
    cron_or_interval="interval:60",
    bounding_box=OpenSkyBoundingBox(min_latitude=35.0, min_longitude=-15.0, max_latitude=65.0, max_longitude=35.0),
    icao24=["3c6444"],
    enabled=True,
)
```

---

## 4. Unsupported & Commercial Data Limitations

OpenSky Network is a crowdsourced ADS-B receiver network. The following data categories are **not provided** by OpenSky state vectors and are **strictly excluded** from RiskWise normalization:
1. **Commercial Airline Schedules**: Departure/arrival scheduled gate times, schedule changes, or timetables.
2. **Passenger & Cargo Manifests**: Passenger counts, airway bill (AWB) identifiers, or cargo contents.
3. **Airline Delays & Cancellations**: Commercial airline flight delay classifications or cancellation notices.
4. **Historical Flight Track Endpoints (`/flights/*`, `/tracks/*`)**: These endpoints are historical, credit-intensive, and deferred from the real-time state-vector ingestion pipeline.

---

## 5. Verification & Test Suite Summary

The integration is verified by 57 focused unit tests in `api/tests/test_opensky_integration.py` using `httpx.MockTransport` (0 external network requests):

1. **Initialization & Capabilities**: Adapter instantiation, type verification, capability flags.
2. **Configuration & Credentials**: Client ID / secret resolution, missing credentials rejection.
3. **OAuth2 Lifecycle**: Form-urlencoded token requests, token parsing, in-memory caching, expiration detection, proactive refresh, 401 reactive recovery, auth failure handling.
4. **REST Endpoint & Filters**: `/states/all` querying, bounding-box parameters, ICAO24 parameter validation, invalid coordinate bounds rejection.
5. **Normalization & Units**: Timestamp normalization to UTC, WGS84 coordinate mapping, altitude in meters, velocity in m/s, true track in degrees, vertical rate in m/s, on-ground status.
6. **Emergency Squawks**: Severity elevation on 7700 (General Emergency), 7600 (Radio Failure), 7500 (Hijacking).
7. **Idempotency & Deduplication**: Deterministic SHA-256 fingerprint generation, duplicate rejection, preservation of legitimate consecutive position reports.
8. **Entity Correlation & Shipment Bridge**: Preservation of aircraft identity, unresolved shipment status, `ShipmentEventBridge` rejection of uncorrelated aircraft and acceptance of correlated aircraft.
9. **Observability & Security**: Source metadata capture, credential sanitization, multi-tenant isolation (`org_id`).
10. **Error Handling & Health**: Transient 5xx retry, 429 rate limit backoff, health check states (UNCONFIGURED, HEALTHY, DEGRADED, UNHEALTHY).
11. **Boundary Integrity**: Proving commercial airline delay/manifest data is excluded and never fabricated.
