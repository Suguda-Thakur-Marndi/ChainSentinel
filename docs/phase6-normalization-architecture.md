# Phase 6 — Normalization Architecture & Data Contract

## 1. Architectural Boundary & Context

RiskWise 2.0 strictly enforces decoupling between heterogeneous external ingestion and internal risk intelligence:

```
External Data Sources (APIs, WebSockets, GTFS-RT Protobuf, Webhooks)
        ↓
Phase 5: Provider Ingestion & Canonicalization (OpenWeather, TomTom, AIS, OpenSky, Rail, Karrio, Tavily)
        ↓
CanonicalExternalEvent (Phase 5 Provider-Independent Model)
        ↓
PHASE 6: SEMANTIC NORMALIZATION (This Architecture)
        ├── Domain Handlers & Registry (Weather, Road, Ocean, Air, Rail, Logistics, Intelligence, General)
        ├── Unit Normalizer (km, km/h, minutes, °C, kg, m³, currency, WGS84)
        ├── Status Normalizer (DELAYED, CANCELLED, ACTIVE, DISRUPTED, RESOLVED, UNKNOWN)
        ├── Temporal & Coordinate Normalization (UTC enforcement, WGS84 bounds)
        ├── Semantic Fingerprinting & Corroboration (SHA-256 fingerprint, source precedence)
        └── Batch Isolation & Quality Assessment (VALID, PARTIAL, INVALID)
        ↓
NormalizedRiskSignal (Domain-Neutral Normalized Representation)
        ↓
Phase 7: Risk Engine (Scoring, Graph Traversal, Compound Risk Analysis)
        ↓
Future Phases: RAG / Autonomous Agents / Digital Twin / Simulation
```

### Strict Boundary Invariant
- **Phase 5 Responsibilities**: Rate limiting, retry backoff, circuit breaking, raw event persistence, canonical schema translation, coordinate bounds checking, idempotency deduplication, and raw provider logging.
- **Phase 6 Responsibilities**: Converts `CanonicalExternalEvent` into a standardized, unit-normalized, status-mapped, multi-source corroborated `NormalizedRiskSignal`.
- **Strict Boundary Defense**: Phase 6 **never** directly ingests raw provider payloads (e.g. raw JSON dictionaries). If a raw payload is supplied to `NormalizationPipeline.normalize_event`, it is immediately rejected as `NormalizationStatus.INVALID`.
- **Phase 7 Boundary**: Phase 6 is **not** the Risk Engine; it does not calculate risk scores, traverse supply chain graphs, compute Bayesian probabilities, or dispatch automated mitigations.

---

## 2. NormalizedRiskSignal Contract Specification

The `NormalizedRiskSignal` represents the unified internal contract for supply-chain disruptions, delays, hazards, and telemetry.

### Typed Internal Contract Structure

| Category | Field Name | Type | Semantics / Constraints |
|---|---|---|---|
| **Identity & Tenancy** | `signal_id` | `str` (UUIDv4) | Unique internal signal identifier |
| | `organization_id` | `Optional[str]` | Multi-tenant tenant boundary identifier (preserved from canonical `org_id`) |
| **Classification** | `domain` | `SignalDomain` | `WEATHER`, `ROAD`, `OCEAN`, `AIR`, `RAIL`, `LOGISTICS`, `INTELLIGENCE`, `GENERAL` |
| | `signal_type` | `SignalType` | `DELAY`, `DISRUPTION`, `CONGESTION`, `HAZARD`, `STATUS_UPDATE`, `ANOMALY`, `INCIDENT`, `CUSTOM` |
| | `event_type` | `str` | Underlying canonical event type (e.g. `ROAD_CLOSURE`, `VESSEL_LOCATION`) |
| | `status` | `SignalStatus` | Normalized semantic status (`NORMAL`, `ACTIVE`, `WARNING`, `DISRUPTED`, `DELAYED`, `CANCELLED`, `RESOLVED`, `COMPLETED`, `UNKNOWN`) |
| | `severity` | `EventSeverity` | Operational severity (`INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) |
| | `confidence` | `float` ($[0.0, 1.0]$) | Probabilistic certainty of the signal's accuracy |
| | `quality` | `EventQuality` | Structural data quality (`VALID`, `PARTIAL`, `INVALID`) |
| **Timing (UTC)** | `event_time` | `datetime` | Time the real-world condition occurred |
| | `observed_at` | `Optional[datetime]` | Time the sensor/provider captured the condition |
| | `received_at` | `datetime` | Time RiskWise ingested the event |
| | `effective_from` | `Optional[datetime]` | Validity window start timestamp |
| | `effective_to` | `Optional[datetime]` | Validity window expiration timestamp |
| **Spatial** | `latitude` | `Optional[float]` | Decimal degrees WGS84 ($-90.0 \le \text{lat} \le 90.0$) |
| | `longitude` | `Optional[float]` | Decimal degrees WGS84 ($-180.0 \le \text{lon} \le 180.0$) |
| | `location_name` | `Optional[str]` | Human-readable location or place name |
| | `country_code` | `Optional[str]` | ISO 3166-1 alpha-2 or alpha-3 code |
| | `region` | `Optional[str]` | Administrative division / region / state |
| | `precision_meters`| `Optional[float]` | Geolocation accuracy radius in meters |
| **Entities** | `entities` | `SignalEntityReferences` | Associated graph references (shipment, supplier, port, route, carrier, vehicle, vessel, flight, etc.) |
| **Provenance** | `source` | `str` | Primary external source or provider name |
| | `source_type` | `EventSourceType` | `REAL`, `ESTIMATED`, `SIMULATED` |
| | `provider` | `str` | Name of the ingestion provider |
| | `canonical_event_id`| `str` | Upstream Phase 5 `CanonicalExternalEvent.event_id` |
| | `raw_event_id` | `Optional[str]` | Reference to original raw payload ID |
| | `provider_event_id` | `Optional[str]` | External provider's proprietary transaction/event ID |
| | `source_reference` | `Optional[str]` | Web URL or document citation |
| | `supporting_sources`| `List[CorroboratingEvidence]` | Corroborating sources from cross-provider corroboration |
| **Distributed Tracing** | `correlation_id` | `Optional[str]` | Distributed correlation identifier |
| | `trace_id` | `Optional[str]` | Distributed trace identifier |
| | `ingestion_run_id`| `Optional[str]` | Batch or scheduled job execution ID |
| **Measurements** | `measurements` | `OperationalValues` | Normalized engineering units (`delay_minutes`, `speed_kmh`, `distance_km`, `temperature_celsius`, `weight_kg`, `volume_m3`, `monetary_amount`, `currency_code`, `disruption_level`) |
| **Metadata** | `normalized_attributes` | `Dict[str, Any]` | Domain-specific structured attributes |
| | `canonical_attributes` | `Dict[str, Any]` | Preserved original canonical values for lineage |
| | `fingerprint` | `str` | Deterministic SHA-256 semantic fingerprint |

---

## 3. Field Semantics & Design Boundaries

Each category in `NormalizedRiskSignal` enforces strict semantic contracts:
- **Identity**: Signals receive a deterministic or UUIDv4 `signal_id`. Multi-tenant isolation is enforced via `organization_id`.
- **Classification**: Categorizes signals into standard domains (`WEATHER`, `ROAD`, `OCEAN`, `AIR`, `RAIL`, `LOGISTICS`, `INTELLIGENCE`, `GENERAL`) and functional signal types (`DELAY`, `DISRUPTION`, `CONGESTION`, `HAZARD`, `STATUS_UPDATE`, `ANOMALY`, `INCIDENT`, `CUSTOM`).
- **Measurements**: Operational telemetry is extracted from domain-specific attributes into typed `OperationalValues` using canonical units.
- **Attributes**: Unconverted or domain-specific data is preserved in `normalized_attributes`, while raw values (e.g. raw status string) are captured in `canonical_attributes["raw_status"]`.

---

## 4. Temporal Semantics

All timestamps in Phase 6 are strictly timezone-aware UTC (`datetime.timezone.utc`). If naive timestamps are received, they are converted to UTC.

The four distinct time dimensions:
1. **`event_time`**: The physical instant when the incident occurred or the sensor measurement was taken.
2. **`observed_at`**: The instant when the external monitoring provider or scraper observed the data.
3. **`received_at`**: The exact timestamp when RiskWise received and registered the canonical event.
4. **`effective_from` & `effective_to`**: The temporal validity window (e.g. for forecasted severe weather alerts or planned road closures).

---

## 5. Deterministic Unit Normalization Policy

To prevent ambiguous units downstream, telemetry is mapped to canonical engineering units:

| Measurement | Canonical Unit | Supported Conversions |
|---|---|---|
| **Distance** | Kilometers (`km`) | Meters ($m / 1000$), Miles ($mi \times 1.609344$), Nautical Miles ($nm \times 1.852$), Feet ($ft \times 0.0003048$) |
| **Speed** | Kilometers per hour (`km/h`) | Knots ($knots \times 1.852$), Meters/sec ($mps \times 3.6$), Miles/hour ($mph \times 1.609344$) |
| **Duration / Delay** | Minutes (`minutes`) | Seconds ($s / 60$), Hours ($hr \times 60$), Days ($d \times 1440$) |
| **Temperature** | Celsius (`°C`) | Kelvin ($K - 273.15$), Fahrenheit ($(°F - 32) \times 5/9$) |
| **Weight** | Kilograms (`kg`) | Pounds ($lbs \times 0.45359237$), Grams ($g / 1000$), Metric tons ($t \times 1000$) |
| **Volume** | Cubic Meters (`m³`) | Liters ($l / 1000$), US Gallons ($gal \times 0.00378541$), Cubic Feet ($cuft \times 0.0283168$) |
| **Currency** | ISO 4217 Currency Code | Standardized to 3-letter uppercase code (USD, EUR, GBP, JPY, CNY) |
| **Coordinates** | Decimal Degrees (WGS84) | Latitude ($-90.0 \le \text{lat} \le 90.0$), Longitude ($-180.0 \le \text{lon} \le 180.0$) rounded to 6 decimal places |

### Strict Unknown-Unit & Unknown-FX Policy
- **No Guessing / No Fabrication**: RiskWise **never** fabricates or guesses conversion factors when the unit is unspecified or unrecognized.
- **Preservation**: The original numeric value is preserved as-is, `is_converted` is set to `False`, `target_unit` is set to `"unknown"`, and a descriptive `conversion_note` is attached.
- **Currency Conversion**: RiskWise preserves original currency and amounts without synthetic FX conversion. Foreign exchange translation requires an authoritative financial rate oracle in downstream layers.

---

## 6. Status Normalization Policy

Disparate provider vocabularies are mapped to canonical `SignalStatus`:

- **`DELAYED`**: `"delayed"`, `"late"`, `"behind schedule"`, `"running late"`, `"estimated delay"`, `"delay"`, `"postponed"`
- **`CANCELLED`**: `"cancelled"`, `"canceled"`, `"void"`, `"service cancelled"`, `"abandoned"`, `"aborted"`
- **`ACTIVE`**: `"on_time"`, `"on schedule"`, `"active"`, `"in_transit"`, `"moving"`, `"operational"`, `"normal"`, `"en_route"`, `"underway"`
- **`DISRUPTED`**: `"incident"`, `"accident"`, `"congestion"`, `"hazard"`, `"alert"`, `"warning"`, `"severe"`, `"closed"`, `"blocked"`, `"strike"`
- **`RESOLVED`**: `"delivered"`, `"completed"`, `"arrived"`, `"resolved"`, `"cleared"`, `"docked"`, `"landed"`
- **`UNKNOWN`**: Any unmapped status string that does not match recognized synonyms.

The original raw status string is always preserved in `canonical_attributes["raw_status"]`.

---

## 7. Severity, Confidence, and Quality Distinction

Phase 6 strictly maintains three independent orthogonal dimensions:

1. **`severity` (`EventSeverity`)**: How severe the event is in the physical world (`INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
2. **`confidence` (`float`)**: How confident RiskWise is in the truth/accuracy of the report ($0.0$ to $1.0$).
3. **`quality` (`EventQuality`)**: The structural completeness of the data payload (`VALID`, `PARTIAL`, `INVALID`).

These three values are **never** collapsed into a single composite score at the normalization stage.

---

## 8. Provenance Lineage Model

Every normalized signal remains fully traceable back through the complete ingestion hierarchy:

$$\text{NormalizedRiskSignal} \longrightarrow \text{CanonicalExternalEvent} \longrightarrow \text{RawEvent} \longrightarrow \text{External Provider}$$

Preserved lineage attributes:
- `provider`: External provider name (e.g. TomTom, OpenWeather, AISStream)
- `source`: Primary external source
- `source_type`: Origin nature (`REAL`, `ESTIMATED`, `SIMULATED`)
- `canonical_event_id`: ID of the upstream Phase 5 canonical event
- `raw_event_id`: ID of the persisted raw provider payload
- `provider_event_id`: External provider's proprietary ID
- `source_reference`: Web URL or document citation
- `supporting_sources`: Full list of corroborating sources with their own URLs and IDs

---

## 9. Entity Correlation & Unresolved Identifiers

`SignalEntityReferences` maintains references to internal supply chain entities:
- `shipment_id`: Correlated shipment identifier
- `supplier_id`: Correlated supplier identifier
- `supplier_site_id`, `factory_id`, `warehouse_id`, `port_id`, `route_id`, `carrier_id`
- Transit asset identifiers: `vehicle_id`, `vessel_mmsi`, `aircraft_icao24`, `flight_number`, `trip_id`
- **Unresolved Identifiers**: Any custom identifiers from external sources (e.g. `trip_id`, `icao24`, `mmsi`, `callsign`) are preserved in `unresolved_identifiers` for future graph resolution without fabricating false entity links.
- **`correlation_status`**: Evaluates to `RESOLVED` (primary entity linked), `PARTIAL` (port/route/transit asset known), or `NONE` (unlinked signal).

---

## 10. Cross-Provider Deduplication & Fingerprinting Strategy

Disruptions often generate signals across multiple independent providers (e.g. TomTom road incident + Tavily news report).

### Semantic Fingerprint
Each signal computes a deterministic SHA-256 fingerprint:
$$\text{fingerprint} = \text{SHA-256}(\text{domain} \parallel \text{signal\_type} \parallel \text{event\_type} \parallel \text{lat\_bucket} \parallel \text{lon\_bucket} \parallel \text{hour\_bucket} \parallel \text{primary\_entity})$$

### Deduplication vs Corroboration Rules
When two incoming signals produce identical semantic fingerprints:
1. **Exact Duplicate**: If source, canonical event ID, and provider event ID are identical, the duplicate is safely dropped.
2. **Multi-Source Corroborating Evidence**: If the sources or canonical IDs differ:
   - Primary signal retains highest-precedence data.
   - Secondary signal is appended to `supporting_sources` as a `CorroboratingEvidence` item.
   - **Zero Provenance Loss**: All source URLs, provider IDs, and timestamps remain completely preserved.

---

## 11. Source Precedence Hierarchy

When corroborating conflicting data for the same semantic incident:
$$\mathbf{REAL} \ (3) > \mathbf{ESTIMATED} \ (2) > \mathbf{SIMULATED} \ (1)$$

- If an incoming signal has strictly higher precedence than an existing signal, it is promoted to primary and the existing signal is demoted to a supporting source.
- Never replace real observational data with simulated or synthetic data merely because the simulation timestamp is newer.

---

## 12. Lifecycle Status: VALID, PARTIAL, and INVALID Behavior

`NormalizationPipeline.normalize_event` returns a typed `NormalizationResult` with `NormalizationStatus`:

1. **`VALID`**:
   - The canonical event has `EventQuality.VALID`.
   - The signal has at least one resolved primary supply-chain entity reference (`entities.has_any_entity == True`).
   - All coordinates are within valid WGS84 bounds.
   - Ready for active downstream risk scoring.

2. **`PARTIAL`**:
   - The canonical event has `EventQuality.PARTIAL` OR the signal is unlinked to a primary supply-chain entity.
   - The signal is structurally valid, coordinates are preserved, and it is stored as an unlinked risk observation.
   - A `PARTIAL` signal never silently becomes `VALID` without explicit entity resolution.

3. **`INVALID`**:
   - The input is not a `CanonicalExternalEvent` (e.g. raw dictionary).
   - The event has `EventQuality.INVALID`.
   - Coordinates exceed geographic bounding limits (latitude outside $[-90, +90]$ or longitude outside $[-180, +180]$).
   - An `INVALID` signal is rejected and recorded in `rejected_signals` with structured error messages. It **never** enters downstream risk processing.

---

## 13. Normalization Pipeline & Domain Handlers

The pipeline is completely provider-agnostic and organized by domain handlers:

```
CanonicalExternalEvent
        ↓
1. Type & Quality Check (Reject raw payloads or INVALID quality)
        ↓
2. Coordinate Bounds Defense (lat [-90, +90], lon [-180, +180])
        ↓
3. Domain Registry Resolution (Resolve handler by domain / event_type)
        ↓
4. Domain Normalization Handler (Weather, Road, Ocean, Air, Rail, Logistics, Intelligence, General)
        ├── Unit Normalizer
        ├── Status Normalizer
        ├── Spatial Context Extraction
        └── Entity Reference Extraction
        ↓
5. Quality & Status Assessment (VALID vs PARTIAL)
        ↓
6. Semantic Fingerprinting (Deterministic SHA-256)
        ↓
NormalizationResult (status, signal, errors, warnings, duration_ms)
```

### Phase 5 to Phase 6 Canonical Domain Normalization Matrix
The Phase 5 canonical external event taxonomy establishes 9 distinct domain categories. Phase 6 routes and normalizes 100% of these 9 canonical domains through registered domain normalization handlers:

| # | Phase 5 Canonical Domain Category | Phase 5 Canonical Event Types | Phase 6 Normalization Handler | Phase 6 Signal Domain | Operational Normalization Focus |
|---|---|---|---|---|---|
| 1 | **Transport** | `SHIPMENT_STATUS`, `SHIPMENT_DELAY`, `ETA_CHANGE`, `LOCATION_UPDATE` | `LogisticsTrackingNormalizationHandler` | `LOGISTICS` | Milestone status, transit delays, tracking checkpoints |
| 2 | **Port / Maritime Hub** | `PORT_CONGESTION`, `PORT_CLOSURE`, `PORT_DELAY` | `OceanAISNormalizationHandler` *(aliased as `PortNormalizationHandler` / `MaritimePortNormalizationHandler`)* | `OCEAN` | Port delay duration, berth congestion, operational disruption level, UN/LOCODE & port identifier preservation |
| 3 | **Road & Traffic** | `ROAD_INCIDENT`, `TRAFFIC_CONGESTION`, `ROAD_CLOSURE` | `RoadTrafficNormalizationHandler` | `ROAD` | Delay minutes, jam factor, speed reduction, route closure |
| 4 | **Weather & Climate** | `SEVERE_WEATHER_ALERT`, `TEMPERATURE_EXTREME`, `PRECIPITATION_EVENT` | `WeatherNormalizationHandler` | `WEATHER` | Temperature in °C, wind speed in km/h, precipitation in mm |
| 5 | **Ocean / AIS** | `VESSEL_LOCATION`, `VESSEL_DELAY`, `MARITIME_INCIDENT` | `OceanAISNormalizationHandler` | `OCEAN` | Vessel speed (knots → km/h), heading, maritime disruption |
| 6 | **Air Freight** | `FLIGHT_DELAY`, `AIRSPACE_RESTRICTION`, `AIRPORT_CONGESTION` | `AirFreightNormalizationHandler` | `AIR` | Flight delay minutes, ground speed, airport congestion level |
| 7 | **Rail** | `RAIL_DELAY`, `DERAILMENT`, `TRACK_MAINTENANCE` | `RailTransitNormalizationHandler` | `RAIL` | Train delay minutes, track speed, rail disruption level |
| 8 | **Logistics / Parcel** | `CARRIER_EXCEPTION`, `CUSTOMS_HOLD`, `PACKAGE_HANDOFF` | `LogisticsTrackingNormalizationHandler` | `LOGISTICS` | Customs hold disruption, package weight (kg), volume (m³) |
| 9 | **Global Intelligence / Research** | `GEOPOLITICAL_RISK`, `LABOR_STRIKE`, `TRADE_RESTRICTION`, `SECURITY_INCIDENT` | `IntelligenceNewsNormalizationHandler` | `INTELLIGENCE` | Sentiment score, strike disruption level, trade restriction impact |

### Domain Handlers in Registry
- `WeatherNormalizationHandler`: Meteorological alerts, cyclones, floods, storms, extreme temperatures (`SignalDomain.WEATHER`).
- `RoadTrafficNormalizationHandler`: Highway incidents, traffic congestion, road closures (`SignalDomain.ROAD`).
- `OceanAISNormalizationHandler` *(also available as `PortNormalizationHandler` / `MaritimePortNormalizationHandler`)*: Vessel tracking, maritime incidents, port congestion, port delays, terminal closures, UN/LOCODE resolution (`SignalDomain.OCEAN`).
- `AirFreightNormalizationHandler`: Flight delays, airspace restrictions, airport congestion (`SignalDomain.AIR`).
- `RailTransitNormalizationHandler`: Train delays, derailments, track maintenance, rail bottlenecks (`SignalDomain.RAIL`).
- `LogisticsTrackingNormalizationHandler`: Multi-modal transport status, carrier exceptions, customs holds, parcel handoffs (`SignalDomain.LOGISTICS`).
- `IntelligenceNewsNormalizationHandler`: Unstructured news, geopolitical alerts, labor strikes, trade policy shifts (`SignalDomain.INTELLIGENCE`).
- `GeneralNormalizationHandler`: Fallback handler for arbitrary custom signals (`SignalDomain.GENERAL`).


---

## 14. Future Extension Points

This architecture establishes the semantic foundation for subsequent phases:
- **Phase 7 Risk Engine**: Ingests `NormalizedRiskSignal` objects to evaluate supply chain exposure, calculate Bayesian impact probabilities, and execute graph traversal.
- **Asset Graph Resolver**: Resolves `unresolved_identifiers` (e.g. `trip_id`, `mmsi`, `icao24`) into canonical shipment or facility nodes.
- **FX Oracle Integration**: Authoritative foreign exchange rate service for converting `monetary_amount` across currency pairs.
- **Digital Twin & Simulation**: Feeds normalized signals into simulated disruption scenarios.

> [!NOTE]
> Phase 6 Step 1 is strictly an internal normalization architecture and data contract layer. It contains NO database schema modifications, NO public REST API endpoint alterations, and NO frontend changes.
