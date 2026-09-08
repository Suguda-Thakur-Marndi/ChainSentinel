# RiskWise 2.0 — Phase 5 Step 8: Tracking / Logistics Integration (Karrio)

## 1. Executive Summary & Verified Provider Strategy

For Phase 5 Step 8, RiskWise 2.0 integrates multi-carrier package, freight, and parcel tracking intelligence using **Karrio**, an open-source, self-hosted logistics tracking and shipping platform.

| Attribute | Specification |
|---|---|
| **Provider** | Karrio Open-Source Shipping Platform (`karrioapi/karrio`) |
| **Official Documentation** | [Karrio Official Documentation](https://karrio.io/docs) / [Karrio Carrier Integration Guide](https://github.com/karrioapi/karrio/blob/main/CARRIER_INTEGRATION_GUIDE.md) |
| **Supported Architecture** | Self-hosted Karrio Server (Docker containerized) & Karrio Cloud |
| **Transport Protocol** | REST JSON over HTTP/HTTPS |
| **Default Endpoint** | `http://localhost:5002` (configurable via `KARRIO_BASE_URL` or `ProviderConfig.base_url`) |
| **Authentication** | Token Header (`Authorization: Token <KARRIO_API_KEY>` or `Bearer <KARRIO_API_KEY>`) |
| **Modality Support** | Parcel, Courier, Less-Than-Truckload (LTL), Container, Intermodal Tracking |
| **Supported Carriers** | 100+ native carrier integrations (FedEx, UPS, DHL, Australia Post, Aramex, Maersk, etc.) |

---

## 2. Verified Karrio API & Endpoint Specifications

Verified directly against the official `karrioapi/karrio` repository and API specifications:

### Verified Endpoints
1. **Single Package Tracker Query**:
   - `GET /v1/trackers/{carrier_name}/{tracking_number}`
   - Retrieves real-time tracking details and chronological milestones for a specific carrier and tracking number.
2. **List / Filter Trackers**:
   - `GET /v1/trackers`
   - Supports filtering by `carrier_name`, `tracking_number`, `status`, and pagination via `limit` and `offset`.
3. **Create Tracker**:
   - `POST /v1/trackers`
   - Registers a new package tracker: `{"tracking_number": "...", "carrier_name": "..."}`.
4. **Webhook Notifications**:
   - `POST /webhooks/karrio`
   - Receives push updates (`tracker_updated`, `tracker_created`) with optional HMAC-SHA256 signature verification.

---

## 3. Architectural Boundary & Data Flow

The tracking integration strictly isolates provider-specific structures from the core database and canonical taxonomy:

```
Carrier / Karrio Engine (REST API / Webhooks)
                    │
                    ▼
          KarrioAdapter (Polling & Fetch)
    ├── Token-bucket Rate Limiter
    ├── Bounded Exponential Retry (5xx, 429)
    ├── Token Header Authorization
    └── KarrioTracker Deserialization
                    │
                    ▼
               RawEvent
    ├── provider_name: "karrio"
    ├── provider_type: ProviderType.LOGISTICS_TRACKING
    ├── provider_event_id: "karrio:{carrier}:{tracking}:{idx}:{ts}"
    ├── raw_payload: (JSON-serializable tracker event milestone)
    ├── fingerprint: SHA-256(carrier + tracking + code + status + ts + loc)
    └── org_id: Tenant isolation scope
                    │
                    ▼
         InMemoryRawEventStorage
                    │
                    ▼
            KarrioNormalizer
    ├── CoordinateValidator (lat: [-90, 90], lon: [-180, 180])
    ├── TimestampNormalizer (ISO 8601 / epoch / date+time -> UTC)
    ├── Status & Incident Reason Mapping
    ├── ETA & Delay Minutes Computation
    └── Strict EntityCorrelation (shipment_id=None unless explicit)
                    │
                    ▼
         CanonicalExternalEvent
    ├── event_type: SHIPMENT_STATUS / SHIPMENT_DELAY / CUSTOM
    ├── severity: INFO / LOW / MEDIUM / HIGH / CRITICAL
    ├── quality: VALID / PARTIAL
    ├── source_type: REAL
    └── normalized_attributes: (mode="PARCEL", carrier, tracking_number, status)
                    │
                    ▼
      InMemoryCanonicalEventStorage
                    │
                    ▼ (Only when explicit shipment_id is correlated)
          ShipmentEventBridge
                    │
                    ▼
              ShipmentEvent
```

---

## 4. Status Taxonomy & Exception Normalization

### 4.1 Status Mapping Matrix
Karrio normalizes diverse carrier codes into standard tracking statuses. RiskWise translates these into canonical event models:

| Karrio Status | Canonical Event Type | Canonical Severity | Canonical Status | Description |
|---|---|---|---|---|
| `delivered`, `completed` | `SHIPMENT_STATUS` | `INFO` | `DELIVERED` | Consignment successfully delivered to destination/recipient. |
| `in_transit`, `transit` | `SHIPMENT_STATUS` | `INFO` | `IN_TRANSIT` | Consignment moving through transport network / intermediate hubs. |
| `out_for_delivery` | `SHIPMENT_STATUS` | `LOW` | `OUT_FOR_DELIVERY` | Package loaded on local delivery vehicle for final delivery. |
| `picked_up`, `collected` | `SHIPMENT_STATUS` | `INFO` | `PICKED_UP` | Shipment collected from shipper or received at carrier facility. |
| `ready_for_pickup` | `SHIPMENT_STATUS` | `INFO` | `READY_FOR_PICKUP` | Consignment awaiting customer collection at locker, depot, or PUDO. |
| `pending`, `created`, `label_created` | `SHIPMENT_STATUS` | `INFO` | `PENDING` | Shipping label generated; awaiting physical parcel receipt. |
| `delivery_delayed`, `delayed` | `SHIPMENT_DELAY` | `MEDIUM` / `HIGH` | `DELAYED` | Operational, routing, or weather delay reported by carrier. |
| `delivery_failed`, `failed` | `SHIPMENT_STATUS` | `HIGH` | `DELIVERY_FAILED` | Attempted delivery was unsuccessful (recipient unavailable, closed). |
| `on_hold`, `exception` | `SHIPMENT_DELAY` | `HIGH` | `ON_HOLD` | Shipment held due to customs, address issues, or regulatory holds. |
| `cancelled`, `canceled` | `SHIPMENT_STATUS` | `CRITICAL` | `CANCELLED` | Shipment voided, cancelled, or permanently aborted. |
| Unrecognized / unknown | `CUSTOM` | `INFO` | `UNKNOWN` | Unrecognized carrier milestone mapped to extensible custom event. |

### 4.2 Incident Reason Overrides
Karrio exposes standardized incident reasons under `KarrioIncidentReason`. When present, they override default severity:

- **`carrier_damaged_parcel`**, **`carrier_parcel_lost`**: `CRITICAL` severity (`INCIDENT_CARRIER_DAMAGED_PARCEL`, `INCIDENT_CARRIER_PARCEL_LOST`).
- **`customs_delay`**, **`weather_delay`**, **`carrier_sorting_error`**, **`carrier_vehicle_issue`**: `HIGH` severity with `CanonicalEventType.SHIPMENT_DELAY`.
- **`consignee_refused`**, **`consignee_business_closed`**, **`consignee_not_available`**: `MEDIUM` severity (`EXCEPTION_CONSIGNEE_REFUSED`).

---

## 5. Location Handling & Coordinate Validation

1. **Coordinates Present**:
   - If `latitude` and `longitude` are supplied (common in last-mile courier tracking):
   - Validated against WGS84 bounds `[-90, 90]` and `[-180, 180]` via `CoordinateValidator.validate()`.
   - Populates `EventLocation(latitude, longitude, location_name)`.
   - If coordinates violate geographic bounds, sets `location = None`, appends validation error, and marks event as `EventQuality.PARTIAL`.
2. **Text Location Only**:
   - If only text location is supplied (e.g., `"MEMPHIS, TN, US"`):
   - Populates `EventLocation(location_name=location_str)`.
   - Coordinates remain `None` (zero fabrication or unverified geocoding).

---

## 6. ETA & Delay Calculation

- **Estimated Delivery Date (`estimated_delivery`)**:
  - Normalized to UTC datetime using `TimestampNormalizer.parse_to_utc()`.
  - Populates `canonical_event.eta`.
- **Delay Minutes Computation**:
  - If a baseline scheduled delivery time (`scheduled_eta`) is available in request parameters or tracker metadata:
    $$\text{delay\_minutes} = \frac{\text{estimated\_delivery} - \text{scheduled\_eta}}{60}$$
  - Only positive delays are computed; missing baselines do not manufacture fabricated delays.

---

## 7. Strict Shipment Correlation & Bridge Constraints

To ensure zero false correlation between carrier tracking numbers and internal RiskWise shipments:

```python
correlation = EntityCorrelation(
    shipment_id=resolved_shipment_id,  # None unless explicitly provided
    carrier_id=carrier_id or carrier_name,
    custom_identifiers={
        "provider": "karrio",
        "tracking_number": tracking_number,
        "carrier_name": carrier_name,
        "carrier_id": carrier_id,
    },
)
```

- **Explicit Correlation Sources**:
  1. `shipment_id` supplied directly to `KarrioAdapter.fetch(..., shipment_id="SHP-001")`
  2. `shipment_id` stored in Karrio tracker metadata (`tracker.metadata["shipment_id"]`)
  3. Pre-mapped tracking number lookup table
- **False Correlation Prevention**:
  - Tracking numbers and carrier IDs are **never** used as implicit `shipment_id` values.
  - If unmapped, `shipment_id` is strictly `None`.
- **`ShipmentEventBridge`**:
  - Evaluates `can_persist_to_shipment_event(event)`.
  - Returns `False` when `shipment_id` is `None` (cannot persist to `ShipmentEvent` database table).
  - Returns `True` when explicit correlation exists, generating a dictionary matching all columns of `ShipmentEvent`.

---

## 8. Idempotency & Chronological Milestone Preservation

To prevent redundant processing of polled tracking data without collapsing distinct historical events:

```python
raw_key = (
    f"{org_prefix}karrio:{carrier}:{tracking}:{code}:{status}:"
    f"{date_val}:{time_val}:{ts_val}:{event_idx}:{lat_str},{lon_str}:{loc_str}:{desc_str}"
)
fingerprint = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
```

- Individual tracking events along a package's journey (e.g. "Picked Up" at 08:15 vs "Departed Facility" at 14:30) have distinct timestamps, status codes, and event indices, producing unique fingerprints.
- Repeated polling queries with identical milestones are suppressed by `IdempotencyEngine`.

---

## 9. Webhook Receiver & HMAC Signature Verification

In addition to scheduled polling, Karrio provides push-based webhook delivery (`tracker_updated`):

- **`KarrioWebhookReceiver`**: Inherits `WebhookReceiver`.
- **HMAC-SHA256 Verification**: Computes HMAC-SHA256 digest over raw request body using tenant webhook secret and compares via constant-time `hmac.compare_digest()`.
- **Payload Parsing**: Unwraps Karrio envelope `{"event": "tracker_updated", "data": {...}}` and validates JSON integrity.

---

## 10. Health Check System

`KarrioAdapter.health_check()` probes the Karrio server (`GET /v1/trackers?limit=1`):

| Health Status | Trigger Condition | Diagnostic Outcome |
|---|---|---|
| `UNCONFIGURED` | API key required but missing from config / environment | Provider unconfigured; missing `KARRIO_API_KEY`. |
| `HEALTHY` | HTTP 200 returned with valid tracker JSON list / dict | Probe succeeded, connectivity and schema verified. |
| `UNHEALTHY` | HTTP 200 returned but body is malformed / non-JSON | Invalid response body. |
| `UNHEALTHY` | HTTP 401 / 403 authorization rejection | Invalid API key or expired token. |
| `DEGRADED` | HTTP 429 rate limit exceeded | Quota or rate limit exceeded. |
| `UNHEALTHY` | HTTP 5xx server error | Upstream Karrio service outage. |
| `DEGRADED` | Network timeout (> 5.0s) | Request timeout contacting Karrio. |

---

## 11. Security & Redaction

- **Zero Credential Storage**: API keys are resolved at runtime via `SecretResolver` from `KARRIO_API_KEY`.
- **Payload Sanitization**: `SecretResolver.sanitize_payload()` scrubs `karrio_api_key`, `api_key`, and `token` fields from logs and persistence envelopes.
- **Untrusted Input Defense**: Tracking descriptions, carrier notes, and custom fields are treated as untrusted text without dynamic script evaluation.

---

## 12. Verification & Test Suite Summary

Implemented in `apps/api/tests/test_karrio_integration.py`:

- **Total Dedicated Tests**: **65 passed, 0 failed**
- **Cumulative Phase 5 Tests (Steps 1–8)**: **352 passed, 0 failed**
- **Test Categories**:
  - Adapter initialization, configuration, and URL resolution (tests 1–7)
  - Successful tracking and multi-event extraction (tests 8–11)
  - Complete status mapping taxonomy (tests 12–22)
  - Incident reason classification and severity rules (tests 23–25)
  - Timestamp parsing, epoch conversions, and malformed fallbacks (tests 26–29)
  - Estimated delivery date (ETA) and delay computation (tests 30–32)
  - Location and coordinate validation (tests 33–35)
  - Explicit shipment correlation and false correlation prevention (tests 36–39)
  - `ShipmentEventBridge` compliance (test 40)
  - Batch tracking queries (test 41)
  - Idempotency fingerprinting and sequential milestone preservation (tests 42–44)
  - Network retries (5xx), HTTP 429 + `Retry-After`, auth errors (401/403), 404s, timeouts (tests 45–51)
  - Diagnostic health checks across 6 states (tests 52–57)
  - Secret redaction, registry integration, and polling job helper (tests 58–60)
  - Webhook signature verification and payload parsing (tests 61–63)
  - Tenant isolation and full multi-tier pipeline integration (tests 64–65)
