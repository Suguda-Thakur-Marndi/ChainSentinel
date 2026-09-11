# RiskWise 2.0 — Phase 5 Step 7: Rail Data Integration

## 1. Executive Summary & Selected Provider

For Phase 5 Step 7, RiskWise 2.0 integrates official real-time rail intelligence using the **Transport for NSW (TfNSW) Open Data GTFS-Realtime v2** feeds.

| Attribute | Specification |
|---|---|
| **Provider** | Transport for NSW (TfNSW) Open Data |
| **Official Documentation** | [Transport for NSW Open Data Hub - Public Transport Realtime APIs](https://opendata.transport.nsw.gov.au/dataset/public-transport-realtime-gtfs) |
| **API Version** | GTFS-Realtime Version 2.0 |
| **Format** | Google Protocol Buffers (`application/x-google-protobuf`) |
| **Protobuf Bindings** | `gtfs-realtime-bindings==2.2.0`, `protobuf==7.36.1` |
| **Transport** | HTTPS GET |
| **Authentication** | Header API Key (`Authorization: apikey <TFNSW_API_KEY>`) / Support for unauthenticated feeds |
| **Geographic Coverage** | New South Wales & Greater Sydney Metropolitan Area, Australia |
| **Primary Rail Networks** | Sydney Trains (urban/suburban rail), NSW TrainLink (intercity/regional passenger rail) |

---

## 2. Official Endpoints & Verification

The following live endpoints were verified against the Transport for NSW Open Data Hub:

- **Base Endpoint**: `https://api.transport.nsw.gov.au/v2/gtfs`
- **Trip Updates (Sydney Trains)**: `https://api.transport.nsw.gov.au/v2/gtfs/realtime/sydneytrains`
- **Trip Updates (NSW TrainLink)**: `https://api.transport.nsw.gov.au/v2/gtfs/realtime/nswtrains`
- **Vehicle Positions (Sydney Trains)**: `https://api.transport.nsw.gov.au/v2/gtfs/vehiclepos/sydneytrains`
- **Vehicle Positions (NSW TrainLink)**: `https://api.transport.nsw.gov.au/v2/gtfs/vehiclepos/nswtrains`
- **Service Alerts (Sydney Trains)**: `https://api.transport.nsw.gov.au/v2/gtfs/alerts/sydneytrains`
- **Service Alerts (NSW TrainLink)**: `https://api.transport.nsw.gov.au/v2/gtfs/alerts/nswtrains`

### Selection Rationale
1. **Regional Alignment**: RiskWise infrastructure and pilot logistics operations are situated in Australia.
2. **Official Public Authority**: TfNSW is the statutory government transport authority for New South Wales, providing authoritative, SLA-backed transit data.
3. **True Binary Protocol Buffer Delivery**: Unlike aggregated JSON mirrors, TfNSW serves standard GTFS-Realtime 2.0 protobuf payloads directly via HTTPS.
4. **Comprehensive Rail Entities**: Exposes all three GTFS-Realtime entity categories: Trip Updates, Vehicle Positions, and Service Alerts.
5. **Deterministic Licensing & Access**: Open Data licence (Creative Commons Attribution 4.0 International) with complimentary developer access tiers.

---

## 3. Strict Freight vs. Passenger Rail Limitation

> [!WARNING]
> **CRITICAL SUPPLY CHAIN ARCHITECTURAL CONSTRAINT**:
> Publicly accessible GTFS-Realtime feeds across Australia (and globally) represent **passenger public transportation networks**, not commercial freight cargo movements.
>
> In RiskWise 2.0:
> - Passenger rail data is used exclusively for **rail corridor disruption, network congestion, route delay, and infrastructure status signals**.
> - Passenger train positions and schedules **MUST NEVER** be used to infer cargo shipment location, container status, or freight delivery ETAs.
> - Train vehicle IDs (`V_9001`) and trip descriptors (`TRIP_101`) are **NEVER** mapped to `shipment_id`.
> - Every normalized rail event embeds an explicit disclaimer:
>   `"passenger_rail_notice": "Observation represents regional/passenger rail network infrastructure; not a commercial freight shipment."`
> - Commercial freight tracking (e.g. Pacific National, Aurizon, SCT Logistics) will integrate under dedicated enterprise carrier APIs in future phases.

---

## 4. Architectural Architecture & Pipeline Flow

The rail integration strictly adheres to the established RiskWise ingestion architecture without schema leakage:

```
TfNSW GTFS-Realtime Endpoints (HTTPS Protobuf)
                    │
                    ▼
          RailAdapter (Polling)
    ├── Rate Limiter (Token Bucket)
    ├── Bounded Exponential Retry (5xx, 429)
    ├── Header Authorization (apikey)
    └── Google Protobuf Deserializer (FeedMessage)
                    │
                    ▼
               RawEvent
    ├── provider_name: "rail"
    ├── provider_type: ProviderType.RAIL
    ├── provider_event_id: "rail:{operator}:{entity_id}:{timestamp}"
    ├── raw_payload: (JSON-serializable GTFS-RT dictionary)
    ├── fingerprint: SHA-256(entity_type + entity_id + route + trip + vehicle + pos/delay)
    └── org_id: Tenant isolation scope
                    │
                    ▼
         InMemoryRawEventStorage
                    │
                    ▼
             RailNormalizer
    ├── CoordinateValidator (lat: [-90, 90], lon: [-180, 180])
    ├── TimestampNormalizer (epoch / ISO -> UTC)
    ├── Conservative Delay Classifier (300s, 900s, 1800s thresholds)
    ├── Alert Effect & Cause Evaluator
    └── Strict EntityCorrelation (shipment_id=None by default)
                    │
                    ▼
         CanonicalExternalEvent
    ├── event_type: LOCATION_UPDATE / TRAIN_DELAY / RAIL_DISRUPTION / CUSTOM
    ├── severity: INFO / LOW / MEDIUM / HIGH / CRITICAL
    ├── quality: VALID / PARTIAL
    ├── source_type: REAL
    └── normalized_attributes: (mode="RAIL", passenger disclaimer, delay, stops)
                    │
                    ▼
      InMemoryCanonicalEventStorage
                    │
                    ▼ (Only if explicit shipment_id is correlated)
          ShipmentEventBridge
```

---

## 5. GTFS-Realtime Entity Parsing & Normalization

### 5.1 Feed Header
- GTFS-Realtime Version: `2.0`
- Header Timestamp: Extracted as UTC epoch and recorded in `raw_event.source_timestamp` and `source_metadata["header_timestamp"]`.

### 5.2 Trip Updates (`gtfs_realtime_pb2.TripUpdate`)
Trip updates communicate dynamic schedule deviations and stop-time adjustments.

- **Trip Descriptor**: `trip_id`, `route_id`, `start_time`, `start_date`, `schedule_relationship`.
- **Stop-Time Updates**: Sequence of stops with `stop_id`, `stop_sequence`, `arrival.delay`, `departure.delay`.
- **Delay Normalization**:
  The primary delay (in seconds) is extracted from the latest stop update or the root `delay` field.

| Delay / Condition | Canonical Event Type | Canonical Severity | Canonical Status |
|---|---|---|---|
| `schedule_relationship == CANCELED` | `RAIL_DISRUPTION` | `CRITICAL` | `CANCELED` |
| `delay >= 1800s` (>= 30 mins) | `RAIL_DISRUPTION` | `CRITICAL` | `MAJOR_DELAY` |
| `delay >= 900s` (>= 15 mins) | `TRAIN_DELAY` | `HIGH` | `DELAYED` |
| `delay >= 300s` (>= 5 mins) | `TRAIN_DELAY` | `MEDIUM` | `MODERATE_DELAY` |
| `delay > 60s` (> 1 min) | `TRAIN_DELAY` | `LOW` | `MINOR_DELAY` |
| `delay <= 60s` | `TRAIN_DELAY` | `INFO` | `ON_TIME` |

### 5.3 Vehicle Positions (`gtfs_realtime_pb2.VehiclePosition`)
Vehicle positions track real-time physical train coordinates.

- **Fields Extracted**:
  - `latitude`, `longitude` (validated via `CoordinateValidator`)
  - `bearing` (degrees clockwise)
  - `speed` (converted to m/s)
  - `current_status` (`INCOMING_AT`, `STOPPED_AT`, `IN_TRANSIT_TO`)
  - `current_stop_sequence`, `stop_id`
  - `vehicle.id`, `vehicle.label`
- **Canonical Mapping**:
  - `event_type`: `CanonicalEventType.LOCATION_UPDATE`
  - `severity`: `EventSeverity.INFO`
  - `location`: `EventLocation(latitude, longitude, location_name="Train {id} (Route {route})", country_code="AU")`
  - `quality`: `EventQuality.VALID` if coordinates pass validation; `EventQuality.PARTIAL` if invalid or missing.

### 5.4 Service Alerts (`gtfs_realtime_pb2.Alert`)
Service alerts communicate unplanned disruptions, infrastructure incidents, trackwork, and maintenance.

- **Fields Extracted**:
  - `cause`: Cause enum name (`TECHNICAL_PROBLEM`, `STRIKE`, `WEATHER`, `MAINTENANCE`, etc.)
  - `effect`: Effect enum name (`NO_SERVICE`, `REDUCED_SERVICE`, `SIGNIFICANT_DELAYS`, `DETOUR`, `STOP_MOVED`, etc.)
  - `header_text`: Multilingual translation text (primary English translation)
  - `description_text`: Detailed description
  - `active_period`: `start` and `end` timestamps
  - `informed_entity`: Affected `route_id` and `stop_id` items
- **Canonical Mapping**:

| Alert Effect | Canonical Event Type | Canonical Severity |
|---|---|---|
| `NO_SERVICE` | `RAIL_DISRUPTION` | `CRITICAL` |
| `SIGNIFICANT_DELAYS` | `TRAIN_DELAY` | `HIGH` |
| `REDUCED_SERVICE` | `RAIL_DISRUPTION` | `MEDIUM` |
| `MODIFIED_SERVICE` / `DETOUR` | `RAIL_DISRUPTION` | `MEDIUM` |
| `STOP_MOVED` | `RAIL_DISRUPTION` | `LOW` |
| `ADDITIONAL_SERVICE` | `CUSTOM` | `INFO` |
| All other / unclassified effects | `RAIL_DISRUPTION` | `INFO` |

---

## 6. Entity Correlation & Strict Isolation

To prevent false correlation between passenger rolling stock and commercial cargo:

```python
correlation = EntityCorrelation(
    route_id=route_id,           # e.g., "T1", "BMT", "CCN"
    shipment_id=None,            # Strictly None unless externally injected
    carrier_id=None,             # Strictly None unless externally injected
    custom_identifiers={
        "operator": "sydneytrains",
        "entity_type": "TripUpdate",
        "trip_id": "TRIP_101",
        "route_id": "T1",
        "vehicle_id": "V_9001",
        "stop_id": "STATION_CENTRAL",
    },
)
```

`ShipmentEventBridge.can_persist_to_shipment_event(event)` evaluates to `False` for all default rail events. It evaluates to `True` only when a verified, explicit correlation exists.

---

## 7. Deterministic Idempotency Fingerprinting

To deduplicate identical feed polling responses while preserving legitimate movement and delay progressions:

```python
raw_key = (
    f"{org_prefix}rail:{entity_type}:{entity_id}:{trip_id}:"
    f"{route_id}:{vehicle_id}:ts:{ts}:{pos_or_metric_key}"
)
fingerprint = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
```

- **VehiclePosition**: Includes 4-decimal rounded coordinates (`lat: -33.8688, lon: 151.2093`) and stop status. Consecutive positions 10 seconds apart produce distinct fingerprints.
- **TripUpdate**: Includes delay in seconds, schedule relationship, and stop ID. Changing delay or cancellation status produces distinct fingerprints.
- **Alert**: Includes cause and effect names.

---

## 8. Diagnostic Health Check System

`RailAdapter.health_check()` provides non-destructive connectivity and payload validation by probing the `alerts` feed:

| Status Code / State | Health Status | Diagnostic Message / Details |
|---|---|---|
| Missing API key (when required) | `UNCONFIGURED` | "Rail provider unconfigured: missing TfNSW API key." |
| HTTP 200 + Valid Protobuf | `HEALTHY` | Probe succeeded, protobuf verified, entity count reported. |
| HTTP 200 + Malformed Protobuf | `UNHEALTHY` | HTTP 200 returned but binary payload failed protobuf deserialization. |
| HTTP 401 / 403 | `UNHEALTHY` | Authorization rejected. Verify TfNSW API key. |
| HTTP 429 | `DEGRADED` | Rate limit or quota exceeded. |
| HTTP 5xx | `UNHEALTHY` | Upstream TfNSW service error. |
| Connection Timeout | `DEGRADED` | Probe timeout. |
| Network / DNS Failure | `UNHEALTHY` | Connection failure. |

---

## 9. Security & Secret Redaction

- **Zero Credential Hardcoding**: TfNSW API keys are retrieved dynamically via `SecretResolver` from `TFNSW_API_KEY` or `RAIL_API_KEY`.
- **Payload & Header Sanitization**: `SecretResolver.sanitize_payload()` scrubs any credential keys before logging or persistence.
- **HTTP Header Masking**: `Authorization: apikey [REDACTED]` is enforced in all outbound telemetry.

---

## 10. Verification & Test Suite Summary

A comprehensive, self-contained unit test suite was implemented in `api/tests/test_rail_integration.py`.

- **Total Rail Unit Tests**: **59 passed, 0 failed, 0 skipped**
- **Cumulative Phase 5 Steps 1–7 Tests**: **287 passed, 0 failed**
- **Test Categories**:
  - Adapter lifecycle, capabilities, configuration, and operator routing (tests 1–9)
  - Protobuf deserialization for TripUpdate, VehiclePosition, Alert, empty feeds, and invalid wire formats (tests 10–17)
  - Delay threshold calculations, schedule cancellations, and conservative disruption mapping (tests 18–21)
  - Coordinate validation, bounding checks, and partial quality degradation (tests 22–25)
  - Entity identifier preservation and missing optional fields (tests 26–28)
  - Alert cause and effect taxonomy mappings (tests 29–33)
  - Deterministic idempotency, consecutive position preservation, and duplicate suppression (tests 34–36)
  - Strict passenger rail isolation and ShipmentEventBridge constraints (tests 37–39)
  - Source metadata, passenger disclaimer, and raw-canonical separation (tests 40–42)
  - Resilient network retries (5xx), HTTP 429 + Retry-After, auth failures, timeouts, and connection errors (tests 43–47)
  - Multi-state health check diagnostics (tests 48–54)
  - Secret redaction, registry discovery, scheduler helper, and tenant isolation (tests 55–58)
  - End-to-end multi-tier pipeline integration (test 59)
