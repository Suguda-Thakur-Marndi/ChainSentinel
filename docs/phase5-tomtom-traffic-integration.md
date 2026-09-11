# RiskWise 2.0 — Phase 5 Step 4: Road / Traffic Data Integration (TomTom)

This document specifies the technical architecture, verified API endpoints, data models, canonical normalization, idempotency, retry/rate-limiting policies, and security boundaries for integrating **TomTom** road and traffic intelligence into RiskWise 2.0.

---

## 1. Executive Summary & Architecture Context

Phase 5 Step 4 introduces TomTom as the primary road and traffic provider for RiskWise 2.0 supply-chain transport intelligence. It strictly abides by the foundational contracts established in:
- **Phase 5 Step 1 (`base.py`, `boundaries.py`, `config.py`, `service.py`)**: Provider abstraction, boundary buffering, credential resolution, bounded retry, rate limiting, and deterministic idempotency deduplication.
- **Phase 5 Step 2 (`canonical.py`, `normalizers.py`)**: The provider-agnostic `CanonicalExternalEvent` taxonomy, quality assessment (`VALID`, `PARTIAL`, `INVALID`), and `ShipmentEventBridge`.
- **Phase 5 Step 3 (`openweather.py`)**: Established provider adapter conventions and non-destructive health checking.

### Architectural Invariant
TomTom-specific JSON response structures are **strictly confined** to the provider adapter and `RawEvent` storage boundaries. Downstream risk scoring engines, routing optimizations, and control tower displays interact exclusively with strongly typed `CanonicalExternalEvent` models.

```
TomTom Traffic APIs (Flow Segment Data v4 / Incident Details v5)
         ↓
TomTomAdapter (api/app/integrations/providers/tomtom.py)
         ↓
RawEvent (Stored in RawEventStorage with sanitized raw_payload)
         ↓
TomTomNormalizer (NormalizationPipeline)
         ↓
CanonicalExternalEvent (Validated, strongly typed, quality-scored)
         ↓
Optional ShipmentEventBridge / Downstream Subsystems
```

---

## 2. Verified TomTom API Endpoints & Capabilities

### Verified Provider Endpoints

| Service | Official TomTom Endpoint | HTTP Method | Version | Verification Source |
|---|---|---|---|---|
| **Traffic Flow Segment Data** | `https://api.tomtom.com/traffic/services/4/flowSegmentData/{style}/{zoom}/{format}` | `GET` | v4 | TomTom Developer Portal Traffic Flow API |
| **Traffic Incident Details** | `https://api.tomtom.com/traffic/services/5/incidentDetails` | `GET` | v5 | TomTom Developer Portal Traffic Incident API |

### 1. Traffic Flow Segment Data (v4)
Retrieves real-time speed and travel time information for the road segment closest to specified coordinates.
- **Default Path Variables**: `style=absolute`, `zoom=10`, `format=json`.
- **Query Parameters**:
  - `point`: Required. Latitude,longitude (e.g. `52.3731,4.8922`).
  - `unit`: Optional. Unit of speed (`KMPH` [default] or `MPH`).
  - `key`: Required. TomTom Developer API Key.
- **Verified Response Structure**:
  ```json
  {
    "flowSegmentData": {
      "frc": "FRC0",
      "currentSpeed": 85,
      "freeFlowSpeed": 110,
      "currentTravelTime": 142,
      "freeFlowTravelTime": 110,
      "confidence": 0.95,
      "roadClosure": false,
      "coordinates": {
        "coordinate": [
          { "latitude": 52.3731, "longitude": 4.8922 },
          { "latitude": 52.3735, "longitude": 4.8928 }
        ]
      }
    }
  }
  ```

### 2. Traffic Incident Details (v5)
Retrieves detailed information regarding active incidents within an area defined by a bounding box or by specific IDs.
- **Query Parameters**:
  - `key`: Required. TomTom Developer API Key.
  - `bbox`: Required for area queries. Bounding box coordinates in `minLon,minLat,maxLon,maxLat` order.
  - `ids`: Optional. Comma-separated list of incident IDs.
  - `language`: Optional. Output language code (default `en-GB`).
- **Verified Response Structure**:
  ```json
  {
    "incidents": [
      {
        "type": "Feature",
        "id": "tt_inc_001",
        "geometry": {
          "type": "Point",
          "coordinates": [4.8922, 52.3731]
        },
        "properties": {
          "id": "tt_inc_001",
          "iconCategory": 1,
          "magnitudeOfDelay": 2,
          "delay": 720,
          "length": 1200,
          "startTime": "2026-09-08T08:00:00Z",
          "endTime": "2026-09-08T10:00:00Z",
          "from": "Junction 3",
          "to": "Junction 4",
          "roadNumbers": ["A10"],
          "roadName": "Ring A10",
          "events": [
            {
              "code": 101,
              "description": "accident involving multiple vehicles",
              "iconCategory": 1
            }
          ]
        }
      }
    ]
  }
  ```

---

## 3. Road / Traffic Capabilities & Normalization

### Supported Traffic Flow Metrics
- **Current Speed (`currentSpeed`)**: Observed speed in km/h.
- **Free-Flow Speed (`freeFlowSpeed`)**: Expected speed in km/h under uncongested conditions.
- **Current Travel Time (`currentTravelTime`)**: Observed seconds to traverse segment.
- **Free-Flow Travel Time (`freeFlowTravelTime`)**: Free-flow seconds to traverse segment.
- **Congestion Ratio**: Calculated as `currentSpeed / freeFlowSpeed`.
- **Functional Road Class (`frc`)**: Road category indicator (e.g. `FRC0` Motorway/Freeway, `FRC1` Major Road).
- **Road Closure (`roadClosure`)**: Boolean flag indicating total segment blockage.
- **Confidence (`confidence`)**: Quality score between 0.0 and 1.0.

### Supported Traffic Incident Metrics
- **Incident ID (`id`)**: Stable provider identifier.
- **Incident Category (`iconCategory`)**:
  - `1`: Accident
  - `6`: Jam / Congestion
  - `7`: Lane closed
  - `8`: Road closed
  - `9`: Road works
  - `14`: Hazard
- **Magnitude of Delay (`magnitudeOfDelay`)**:
  - `0`: Unknown
  - `1`: Minor
  - `2`: Moderate
  - `3`: Major
  - `4`: Indefinite / Blocked
- **Delay (`delay`)**: Duration in seconds $\to$ converted to `delay_minutes`.
- **Temporal Bounds**: `startTime` and `endTime` normalized to timezone-aware UTC.
- **Location Geometry**: GeoJSON `coordinates` `[lon, lat]` normalized to `EventLocation(latitude, longitude)`.

---

## 4. Canonical Event Taxonomy Alignment

RiskWise strictly preserves the established `CanonicalEventType` taxonomy without modifying database enums or creating synthetic types:

| Provider Data Signal | Canonical Event Type | Justification / Rules |
|---|---|---|
| **Road Closure** (`roadClosure=True` or `iconCategory=8`) | `CanonicalEventType.ROAD_CLOSURE` | Road physically impassable; severity `CRITICAL` or `HIGH`. |
| **Severe Congestion / Traffic Jam** (`iconCategory=6` or `congestion_ratio < 0.5`) | `CanonicalEventType.TRAFFIC_CONGESTION` | Severe speed degradation; severity `MEDIUM` or `HIGH`. |
| **Accidents, Construction, Hazards** (`iconCategory` 1, 7, 9, 14) | `CanonicalEventType.ROAD_INCIDENT` | Road disruption event; severity `LOW`, `MEDIUM`, or `HIGH` based on `magnitudeOfDelay`. |
| **Normal Traffic Flow** (`congestion_ratio >= 0.85` or close to free flow) | `CanonicalEventType.CUSTOM` (`event_classification="TRAFFIC_FLOW"`) | Ambient traffic flow; severity `INFO` or `LOW`. **Never becomes critical risk.** |

### Operational Risk Prevention
Normal traffic conditions are classified at `EventSeverity.INFO` or `LOW` and **never** trigger false-positive critical alarms. Severe classifications (`HIGH` / `CRITICAL`) are reserved strictly for road closures, `magnitudeOfDelay == 4`, or delays $\ge 60\text{ minutes}$.

---

## 5. Location & Route Input Handling

1. **Point Coordinates (Flow)**:
   - Inputs: `latitude`, `longitude` (WGS84).
   - Validated via `CoordinateValidator.validate(lat, lon)` **before** issuing the HTTP request.
   - Out-of-bounds coordinates raise `ProviderValidationError` immediately.
2. **Bounding Box (Incidents)**:
   - Input: Sequence of 4 floats `(minLon, minLat, maxLon, maxLat)`.
   - Validates that latitudes are in $[-90, 90]$, longitudes in $[-180, 180]$, and `minLat <= maxLat`.

---

## 6. Deterministic Idempotency Strategy

- **Incidents**: Keyed on the stable TomTom incident identifier:
  $$\text{Fingerprint} = \text{SHA-256}(\text{"org:"} + \text{org\_id} + \text{":tomtom:event\_id:"} + \text{incident\_id})$$
- **Flow Observations**: Keyed on spatial precision (coordinates rounded to 4 decimals $\sim 11\text{m}$), observation epoch, and Functional Road Class (`frc`):
  $$\text{Payload} = \{\text{lat}: \text{round}(\text{lat}, 4),\, \text{lon}: \text{round}(\text{lon}, 4),\, \text{ts}: \text{str}(\text{ts}),\, \text{frc}: \text{frc}\}$$
  $$\text{Fingerprint} = \text{SHA-256}(\text{"org:"} + \text{org\_id} + \text{":tomtom:ts:"} + \text{ts} + \text{":payload:"} + \text{canonical\_json}(\text{Payload}))$$
- Duplicate observations within deduplication TTL are identified and skipped per tenant scope.

---

## 7. Error Handling, Retries & Rate Limiting

- **HTTP 401/403**: Raises non-retriable `ProviderAuthenticationError`.
- **HTTP 429**: Raises retriable `ProviderRateLimitError`, parsing `Retry-After` response header.
- **HTTP 500, 502, 503, 504**: Raises retriable `ProviderResponseError` executing bounded exponential backoff with jitter via `RetryPolicy`.
- **Timeouts / Connection drops**: Raises retriable `ProviderTimeoutError` / `ProviderConnectionError`.
- **HTTP 400**: Raises non-retriable `ProviderValidationError`.

---

## 8. Provider Health Check Specification

Implemented in `TomTomAdapter.health_check()`:
- Probes non-destructive reference coordinates (Amsterdam `52.3731, 4.8922`).
- Reports:
  - `HEALTHY`: HTTP 200 with valid `flowSegmentData`.
  - `UNCONFIGURED`: API key missing from secret, config, and environment.
  - `UNHEALTHY`: HTTP 401/403, 5xx, or network timeout.
  - `DEGRADED`: HTTP 429 quota exhaustion.
- Credentials are never exposed in health status diagnostics.

---

## 9. Testing & Validation Summary

Verified by 40 focused unit tests in `api/tests/test_tomtom_integration.py` using `httpx.MockTransport` with zero live network calls:
1. Adapter initialization & metadata
2. Provider capability inspection
3. Configuration loading
4. Missing API key handling
5. Custom configuration overrides
6. Traffic flow segment data fetch
7. Traffic incident details fetch
8. Coordinate validation
9. Invalid latitude rejection
10. Invalid longitude rejection
11. UTC timestamp normalization
12. Traffic speed mapping (km/h)
13. Free-flow speed mapping (km/h)
14. Congestion ratio and delay mapping
15. Road segment category (`frc`)
16. Incident ID mapping
17. Incident type mapping (`ROAD_INCIDENT`, `TRAFFIC_CONGESTION`, `ROAD_CLOSURE`)
18. Incident severity mapping
19. Incident location mapping
20. Incident description mapping
21. Incident time mapping
22. Road closure mapping
23. Missing optional fields robustness
24. Malformed provider response handling
25. Authentication failure (HTTP 401/403)
26. Rate limiting (HTTP 429 with `Retry-After`)
27. Transient 5xx failure handling
28. Bounded retry behavior
29. `Retry-After` delay handling
30. Deterministic idempotency fingerprinting
31. Duplicate observation deduplication
32. Canonical event generation
33. Raw payload preservation in `RawEvent`
34. Secret redaction from payloads and URLs
35. Provider health check (HEALTHY, UNCONFIGURED, UNHEALTHY, DEGRADED)
36. Scheduler integration (`ScheduledIngestionJob`)
37. Observability metadata tracking
38. Multi-tenant `org_id` isolation
39. Normal traffic non-inflation (never becomes critical risk)
40. Severe incident severity mapping (`CRITICAL`)

---

## 10. Known Provider Limitations & Unsupported Capabilities

1. **Point Coordinates for Flow vs Bounding Box for Incidents**: TomTom Flow API requires point coordinates, whereas TomTom Incident API requires a bounding box (`minLon,minLat,maxLon,maxLat`).
2. **Speed Calculation Latency**: Real-time traffic speeds reflect upstream aggregation of vehicle probe data updated every 1–3 minutes.
3. **Out-of-Scope Capabilities**: Intermediate flow tiles, vector map tiles, and routing recalculation are deferred to downstream routing engines and are not part of Step 4 ingestion.
