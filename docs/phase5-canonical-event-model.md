# RiskWise 2.0 — Phase 5 Step 2
# Canonical External Event Model & Normalization Boundary

**Status**: Production Foundation Complete & Verified  
**Scope**: Canonical Event Model & Normalization Boundary (Phase 5 Step 2)  
**PostgreSQL Schema**: Zero Migrations, Zero DDL, 34 Models / 26 Enums Unchanged  
**Test Suite**: 332 tests collected, 331 passed, 1 skipped (RDS live network), 0 failed  
**OpenAPI Contract**: 60 paths, 96 operations, 104 schemas (Unchanged)  

---

## 1. Canonical Event Schema

RiskWise ingests signals across heterogeneous provider formats (weather radar, TomTom traffic, AISStream maritime NMEA/JSON, flight trackers, carrier webhooks, and intelligence feeds). To prevent coupling downstream risk engines, simulations, and decision agents to provider schemas, Step 2 implements `CanonicalExternalEvent`:

- **Location**: [`apps/api/app/integrations/canonical.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/apps/api/app/integrations/canonical.py)
- **Primary Schema Structure**:

```python
class CanonicalExternalEvent(BaseModel):
    # 1. Identity
    event_id: str                      # Globally unique canonical UUID
    provider: str                      # Normalized provider key (e.g. 'tomtom', 'openweather')
    source_event_id: Optional[str]     # Provider-native identifier (if emitted)
    event_type: Union[CanonicalEventType, str] # Classified domain event

    # 2. Timing (All normalized to timezone-aware UTC)
    event_timestamp: datetime          # Real-world event time
    observed_at: Optional[datetime]    # Telemetry sensor observation time
    received_at: datetime              # RiskWise ingestion arrival time

    # 3. Location
    location: Optional[EventLocation]  # WGS84 coordinates and naming context

    # 4. Entity Correlation
    correlation: EntityCorrelation     # Bound shipment, carrier, port, route, or unresolved

    # 5. Operational Impact & Telemetry
    status: Optional[str]              # Provider status (e.g. 'IN_TRANSIT', 'CLOSED', 'ACTIVE')
    severity: EventSeverity            # Event operational severity (INFO -> CRITICAL)
    delay_minutes: Optional[float]     # Operational transit delay if applicable
    eta: Optional[datetime]            # Updated estimated time of arrival

    # 6. Source Semantics & Confidence
    source_type: EventSourceType       # REAL, SIMULATED, or ESTIMATED
    source_url: Optional[str]          # Source reference link or bulletin URL
    confidence: Optional[float]        # Normalized confidence score (0.0 to 1.0)
    raw_event_id: Optional[str]        # Pointer to underlying RawEvent for replay

    # 7. Payload & Metadata
    normalized_attributes: Dict[str, Any] # Sanitized key-value domain attributes
    provider_metadata: Dict[str, Any]     # Provider telemetry metadata

    # 8. Traceability & Multi-Tenancy
    ingestion_run_id: Optional[str]    # Ingestion cycle UUID
    correlation_id: Optional[str]      # Distributed tracing correlation UUID
    payload_fingerprint: Optional[str] # SHA-256 deduplication fingerprint
    org_id: Optional[str]              # Tenant ID (None for public/global signals)

    # 9. Quality Assessment
    quality: EventQuality              # VALID, PARTIAL, or INVALID
    validation_errors: List[str]       # Diagnostic error strings
```

---

## 2. Event Taxonomy

RiskWise organizes external supply-chain signals into a unified, provider-independent taxonomy via `CanonicalEventType`:

| Category | Canonical Event Types | Domain Scope |
| :--- | :--- | :--- |
| **Transport** | `SHIPMENT_STATUS`, `SHIPMENT_DELAY`, `ETA_CHANGE`, `LOCATION_UPDATE` | Waypoint milestones, carrier delay notices, transit pings |
| **Port / Maritime Hub** | `PORT_CONGESTION`, `PORT_CLOSURE`, `PORT_DELAY` | Berth wait times, port terminal lockdowns, strike actions |
| **Road & Traffic** | `ROAD_INCIDENT`, `ROAD_CLOSURE`, `TRAFFIC_CONGESTION` | Highway closures, pileups, toll bottlenecks, corridor jams |
| **Weather & Climate** | `WEATHER_ALERT`, `STORM`, `FLOOD`, `CYCLONE`, `EXTREME_WEATHER` | Typhoon paths, blizzards, flash floods, extreme heatwaves |
| **Ocean / AIS** | `VESSEL_LOCATION`, `VESSEL_DELAY`, `MARITIME_INCIDENT` | AIS transponder pings, dead reckoning, canal blockages |
| **Air Freight** | `FLIGHT_DELAY`, `FLIGHT_CANCELLATION`, `AIRPORT_DISRUPTION` | Air cargo groundings, tarmac delays, airspace closures |
| **Rail** | `TRAIN_DELAY`, `RAIL_DISRUPTION` | Freight train derailments, track maintenance blocks |
| **Logistics / Parcel** | `PARCEL_STATUS`, `DELIVERY_DELAY` | Last-mile hub scans, failed delivery attempts |
| **Global Intelligence** | `NEWS_EVENT`, `GEOPOLITICAL_EVENT` | Sanctions announcements, trade disputes, civil unrest |
| **Extensible Fallback** | `CUSTOM` | Domain-specific telemetry and proprietary sensor pings |

The taxonomy is extensible: unexpected or vendor-specific string identifiers are parsed into custom types without failing model validation.

---

## 3. Source Semantics

The model preserves the origin classification of signals via `EventSourceType`:

- `REAL`: Empirical real-world telemetry directly observed by hardware or reported by authorized human operators (e.g. GPS sensor pings, port authority notices).
- `SIMULATED`: Synthetic events generated during what-if scenario analyses, digital twin runs, or automated drills.
- `ESTIMATED`: Algorithmically inferred values produced by intermediate models (e.g. carrier transit interpolations or weather forecast projections).

Future AI decision agents and risk engines inspect this flag to ensure simulation data is never conflated with real physical disruptions.

---

## 4. Severity vs. Risk Distinction

RiskWise strictly distinguishes **Event Severity** from **Composite Risk Score**:

- **Event Severity (`EventSeverity`)**: Describes the objective magnitude of the external physical occurrence as reported by the provider (`INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
  - *Example*: A Category 5 Cyclone in the South China Sea has `severity = CRITICAL`.
- **Risk Score**: The evaluated potential financial, operational, or customer impact of an event on a specific tenant's supply network.
  - *Example*: If an organization has zero shipments, suppliers, or routes transiting through the cyclone zone, the resulting network risk score is `0.0 (NEGLIGIBLE)`.
  - Conversely, if 40% of high-value semiconductor shipments are stranded in the path, the evaluated risk is `HIGH`.

Normalization computes event severity only. Composite risk scoring is strictly deferred to the downstream Risk Engine.

---

## 5. Confidence Representation

Confidence is represented as a normalized floating point score bounded between `0.0` and `1.0`:

- `confidence: Optional[float] = Field(None, ge=0.0, le=1.0)`
- Values reflect provider accuracy estimates, transponder signal clarity, or reporting reliability.
- Inferences with lower confidence (e.g. unverified social news) are ingested with lower confidence scores without discarding the signal.

---

## 6. Location Model

Spatial data is encapsulated in `EventLocation`:

- **Coordinates**: `latitude: Optional[float]` ($\in [-90.0, +90.0]$) and `longitude: Optional[float]` ($\in [-180.0, +180.0]$).
- **Contextual Labels**: `location_name: Optional[str]`, `country_code: Optional[str]` (ISO-3166 alpha-3), and `region: Optional[str]`.
- **Precision**: `precision_meters: Optional[float]` reflecting GPS HDOP or spatial bounding box radius.
- **Non-Geographic Support**: Events without intrinsic coordinates (e.g. national tariff announcements or global market news) legitimately set `location = None`.

---

## 7. Entity Correlation: Known vs. Unresolved

External events often arrive before their association with internal RiskWise entities can be resolved. The model supports both states natively:

- **Entity Correlation Container (`EntityCorrelation`)**:
  - `shipment_id`: Bound shipment primary key.
  - `carrier_id`: Bound carrier primary key.
  - `port_id`: Bound port primary key.
  - `route_id`: Bound route primary key.
  - `supplier_id`: Bound supplier primary key.
  - `facility_id`: Bound factory or warehouse primary key.
  - `custom_identifiers`: Dynamic vendor identifiers (e.g. `{"mmsi": "563000111", "flight_icao": "SIA318"}`).
- **Operational States**:
  - **Known Correlation**: At least one primary entity ID is populated (`is_correlated == True`).
  - **Unresolved Correlation**: Event arrives with vendor metadata only (`is_correlated == False`). The normalization pipeline retains the event without fabricating relations. Subsequent background correlation engines associate it with shipments and routes.

---

## 8. Normalizer Interface

Decoupled normalizer abstraction defined in [`apps/api/app/integrations/normalizers.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/apps/api/app/integrations/normalizers.py):

```python
class BaseEventNormalizer(ABC):
    @abstractmethod
    def can_normalize(self, raw_event: RawEvent) -> bool:
        """Check if normalizer handles the given provider/event."""
        pass

    @abstractmethod
    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        """Transform raw provider envelope into canonical event."""
        pass
```

Implementations isolate vendor-specific data wrangling from the rest of the application.

---

## 9. Normalization Pipeline

The pipeline implements the sequential processing flow:

```
RawEvent
   ↓
1. Sanitize Raw Payload (Credential Redaction)
   ↓
2. Match Normalizer (Registry Priority / Fallback)
   ↓
3. Execute Provider Transformation
   ↓
4. Validate & Normalize Timestamps to UTC
   ↓
5. Validate Spatial Bounds (WGS84)
   ↓
6. Bind Traceability (raw_event_id, fingerprint, run_id, org_id)
   ↓
7. Evaluate Quality State (VALID, PARTIAL, INVALID)
   ↓
CanonicalExternalEvent
```

---

## 10. Timestamp Handling

- All timestamps (`event_timestamp`, `observed_at`, `received_at`, `eta`) are strictly normalized to **timezone-aware UTC**.
- `TimestampNormalizer.parse_to_utc()` safely handles:
  - ISO-8601 strings (e.g. `2026-09-07T14:30:00Z` or `2026-09-07T19:30:00+05:00`).
  - UNIX epoch timestamps in seconds (`1788777000.0`) and milliseconds (`1788777000000`).
  - Python `datetime` objects (converting naive timestamps to UTC).
- Unparseable, empty, or malformed timestamps are rejected with explicit `ValueError` exceptions and tagged as `INVALID` quality.

---

## 11. Idempotency Integration

The normalization layer integrates directly with the Step 1 `IdempotencyEngine`:

- `payload_fingerprint`: Preserves the 256-bit SHA-256 fingerprint computed during raw ingestion.
- Deduplicated events in Step 1 (`SKIPPED_DUPLICATE`) are filtered out prior to normalization, preventing redundant compute overhead.
- Fingerprints preserve tenant isolation by scoping hashes with `org:{org_id}` for private streams.

---

## 12. Raw vs. Canonical Separation

RiskWise enforces absolute separation between raw and canonical representations:

1. **`RawEvent`**: Holds un-normalized provider payloads for audit, compliance, and algorithmic replay. Stored at the raw boundary without lossy transformations.
2. **`CanonicalExternalEvent`**: Strongly typed, sanitized, and normalized for consumption by internal services.
3. Raw payloads are **never overwritten** by normalized structures.

---

## 13. Source Traceability

Every canonical event carries end-to-end lineage:

- `provider`: Identifying integration adapter.
- `source_event_id`: External upstream transaction/alert ID.
- `raw_event_id`: Direct foreign pointer to the raw storage record.
- `ingestion_run_id`: Execution batch identifier.
- `correlation_id`: Distributed trace token linking API requests.
- `payload_fingerprint`: Deterministic hash of source content.

---

## 14. Event Quality States

Validation outcomes are categorized under `EventQuality`:

| Quality State | Criteria | Handling |
| :--- | :--- | :--- |
| `VALID` | All mandatory identity fields, valid UTC timestamps, valid coordinates, and entity correlations are present. | Immediately forwarded to operational event pipelines. |
| `PARTIAL` | Identity and timestamps are valid, but coordinates or entity correlations are unresolved. | Stored and retained for subsequent background correlation jobs. |
| `INVALID` | Malformed timestamps, coordinates exceeding WGS84 limits, or missing provider identity. | Flagged with `validation_errors`, quarantined, and excluded from risk scoring. |

---

## 15. Persistence Boundary & Database Gap Analysis

### Current Schema State
- The PostgreSQL schema contains **no generic `external_events` table** (as confirmed by the Phase 2 database audit, which established that external events map to `incidents` and `risks` once materialized).
- The existing `shipment_events` table contains a non-nullable foreign key `shipment_id: Mapped[str] = mapped_column(String(64), ForeignKey("shipments.id"), nullable=False)`.

### Persistence Strategy
1. **Application-Layer Storage**: Canonical events are managed via [`CanonicalEventStorage`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/apps/api/app/integrations/boundaries.py#L93-L122) and [`InMemoryCanonicalEventStorage`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/apps/api/app/integrations/boundaries.py#L125-L177).
2. **Correlated Bridge**: [`ShipmentEventBridge`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/apps/api/app/integrations/boundaries.py#L180-L224) converts canonical events into database `ShipmentEvent` records **if and only if** `shipment_id` is correlated.
3. **Uncorrelated Event Buffer**: Uncorrelated events (e.g. ambient weather, AIS pings) remain staged in canonical storage for correlation resolution without forcing invalid relational inserts.
4. **Zero Migrations**: This design maintains **zero DDL, zero migrations, and zero schema drift**.

---

## 16. Security & Credential Protection

- **No Secrets in Canonical Models**: Normalization strictly invokes [`SecretResolver.sanitize_payload()`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/apps/api/app/integrations/config.py#L97-L110) across raw payloads, normalized attributes, and provider metadata.
- **Redaction Rules**: Any key matching `api_key`, `token`, `secret`, `password`, `auth`, or `credential` is recursively replaced with `[REDACTED]`.
- **Multi-Tenant Isolation**: Events belonging to specific organizations are tagged with `org_id`. Ingestion logs do not print raw authorization headers.

---

## 17. Testing Strategy & Validation

Comprehensive test suite in [`apps/api/tests/test_canonical_external_events.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/apps/api/tests/test_canonical_external_events.py):

- **Test Count**: 27 unit tests (100% pass rate in 1.23s).
- **Validation Matrix**:
  1. `test_01`: Canonical event instantiation
  2. `test_02`: Required field validation
  3. `test_03`: Timestamp normalization to UTC
  4. `test_04`: Malformed timestamp rejection
  5. `test_05`: Timezone offset conversion
  6. `test_06`: Latitude range validation (-90 to +90)
  7. `test_07`: Longitude range validation (-180 to +180)
  8. `test_08`: Optional location handling
  9. `test_09`: Event taxonomy validation
  10. `test_10`: Unknown / extensible event types
  11. `test_11`: Source type handling (`REAL`, `SIMULATED`, `ESTIMATED`)
  12. `test_12`: Severity handling (`INFO` through `CRITICAL`)
  13. `test_13`: Confidence scoring (0.0 to 1.0)
  14. `test_14`: Known entity correlation
  15. `test_15`: Unresolved correlation preservation
  16. `test_16`: Provider/source traceability
  17. `test_17`: Payload fingerprint preservation
  18. `test_18`: Idempotency engine integration
  19. `test_19`: Raw vs canonical data separation
  20. `test_20`: `VALID` quality state evaluation
  21. `test_21`: `PARTIAL` quality state evaluation
  22. `test_22`: `INVALID` quality state evaluation
  23. `test_23`: Normalizer interface abstraction
  24. `test_24`: Fake provider normalization (weather, AIS, traffic)
  25. `test_25`: Sensitive payload sanitization
  26. `test_26`: Full JSON serialization round-trip
  27. `test_27`: Regression compatibility & `ShipmentEventBridge`

---

## 18. Future Provider Integration Roadmap

With the canonical event model and normalizer pipeline complete, concrete providers in subsequent Phase 5 steps will implement:

1. **Provider Adapter** (`BaseProviderAdapter.fetch`): Retrieves raw JSON/payload.
2. **Provider Normalizer** (`BaseEventNormalizer.normalize`): Maps vendor payload to `CanonicalExternalEvent`.
3. **Downstream Correlation**: Associates canonical events with shipments, routes, and risk assessments.
