# Phase 6 Step 3 — Entity Normalization & Cross-Source Correlation Architecture

## 1. Architectural Overview & Processing Lifecycle

RiskWise 2.0 strictly enforces decoupling between external canonical signal ingestion and internal risk intelligence. Entity normalization and cross-source correlation execute downstream of canonicalization:

```
External Data Sources (APIs, AIS, Webhooks, Feeds)
        ↓
Phase 5: Canonicalization (CanonicalExternalEvent)
        ↓
Phase 6 Step 1 & 2: Semantic Normalization (NormalizedRiskSignal)
        ├── Unit Normalizer (km, km/h, minutes, °C, kg, m³, currency, WGS84)
        ├── Status Normalizer (DELAYED, CANCELLED, ACTIVE, DISRUPTED, RESOLVED, UNKNOWN)
        └── Domain Handlers & Registry (Weather, Road, Ocean/Port, Air, Rail, Logistics, Intelligence)
        ↓
Phase 6 Step 3: Entity & Cross-Source Normalization (This Layer)
        ├── Identifier Normalizer (Namespace-aware, deterministic cleanup & validation)
        ├── Entity Normalizer (Conservative tenant-scoped resolution & conflict detection)
        └── Cross-Source Correlator (Deterministic SHA-256 fingerprinting & corroboration)
        ↓
Corroborated NormalizedRiskSignal
        ↓
Future Phase 7 Risk Engine
```

### Strict Architectural Invariant
- **Post-Canonicalization Rule**: Entity normalization **never** directly consumes raw provider envelopes (`RawEvent`). It strictly processes strongly typed `NormalizedRiskSignal` representations derived from `CanonicalExternalEvent`.
- **False Correlation Prevention**: RiskWise aggressively guards against false correlations. Geographic proximity alone, timestamps alone, or company name similarities **never** establish an entity association without explicit verified evidence.

---

## 2. Entity Reference Architecture

Every entity association within a `NormalizedRiskSignal` is captured via the strongly typed, namespace-aware `EntityReference` model:

```python
class EntityReference(BaseModel):
    entity_type: EntityType
    internal_id: Optional[str] = None
    external_id: Optional[str] = None
    identifier_namespace: Optional[str] = None
    identifier_type: Optional[str] = None
    correlation_confidence: CorrelationConfidence = CorrelationConfidence.UNRESOLVED
    correlation_method: CorrelationMethod = CorrelationMethod.UNRESOLVED
    evidence: Optional[Dict[str, Any]] = None
    raw_identifier: Optional[str] = None
    is_conflict: bool = False
    conflict_details: Optional[str] = None
```

### Supported Entity Types
The layer supports only the 12 domain entities defined in the RiskWise 2.0 data model:
1. `SHIPMENT`: Consignment cargo in transit.
2. `SUPPLIER`: Tier-1, tier-2, or tier-3 vendor organization.
3. `SUPPLIER_SITE`: Specific manufacturing/storage plant operated by a supplier.
4. `FACTORY`: Internal manufacturing or production facility.
5. `WAREHOUSE`: Storage, cross-dock, or distribution hub.
6. `PORT`: Maritime container seaport or transshipment terminal.
7. `ROUTE`: Predefined shipping corridor between network nodes.
8. `CARRIER`: Freight forwarder or logistics service provider.
9. `VESSEL`: Commercial container ship, tanker, or bulk carrier.
10. `AIRCRAFT`: Air cargo freighter or passenger transport.
11. `VEHICLE`: Ground fleet truck or tractor-trailer unit.
12. `TRACKING_OBJECT`: Intermodal container or pallet telemetry device.

---

## 3. Identifier Normalization & Namespace Isolation

External identifiers are heterogeneous and require deterministic sanitization without arbitrary character loss:

| Identifier Type | Namespace | Normalization Rules | Validation |
|---|---|---|---|
| **IMO** | `MARITIME` | Strip optional case-insensitive `IMO` prefix, remove spaces/hyphens | Exactly 7 digits |
| **MMSI** | `MARITIME` | Trim whitespace, remove hyphens | Exactly 9 digits |
| **ICAO24** | `AVIATION` | Lowercase hexadecimal representation, trim whitespace | Exactly 6 hex characters (`[0-9a-f]{6}`) |
| **Callsign** | `AVIATION` / `MARITIME` | Uppercase alphanumeric representation, trim whitespace | Alphanumeric (`2-10` characters) |
| **UN/LOCODE** | `PORT` | Uppercase, remove internal spaces/hyphens | 5 chars (2-letter country + 3-char location) |
| **Tracking Number** | Carrier Namespace (`FEDEX`, `UPS`, `DHL`) | Trim whitespace, preserve case & special characters | Non-empty string |
| **Generic** | Domain Namespace | Trim whitespace, preserve raw identifier verbatim | Non-empty string |

### Qualified Identifier Keys
Every identifier is qualified by its namespace and type:
$$\text{qualified\_key} = \text{NAMESPACE} : \text{IDENTIFIER\_TYPE} : \text{NORMALIZED\_VALUE}$$
Example: `PROVIDER_A:TRACKING:12345` $\neq$ `PROVIDER_B:TRACKING:12345`, and `MARITIME:IMO:1234567` $\neq$ `MARITIME:MMSI:1234567`.

---

## 4. Domain-Specific Correlation Policies

### 4.1 Shipment Correlation
- **Allowed Evidence**:
  1. Exact internal `shipment_id` within tenant scope (`CorrelationConfidence.EXACT`).
  2. Verified tracking number + carrier namespace mapping (`CorrelationConfidence.VERIFIED`).
  3. Explicit provider mapping.
- **Prohibited**: Name similarity, proximity alone, timestamp proximity alone, or fuzzy guessing.
- **Fallback**: External tracking numbers are preserved in `unresolved_identifiers["tracking_number"]` with `CorrelationConfidence.UNRESOLVED`.

### 4.2 Supplier Correlation
- **Allowed Evidence**: Exact internal `supplier_id` or registered `supplier_code` under tenant scope.
- **Strict Prohibition**: Company name similarity ("ABC Manufacturing" $\neq$ "ABC Manufacturing Ltd"). Unverified company names are preserved in `unresolved_identifiers["supplier_name"]`.

### 4.3 Supplier Site vs Factory vs Supplier
- **Strict Boundary**: A Supplier is a business entity; a Supplier Site is a facility operated by a supplier; a Factory is an internal manufacturing plant.
- RiskWise never collapses these three distinct entities into a generic "facility" bucket.

### 4.4 Warehouse Correlation
- **Allowed Evidence**: Internal `warehouse_id` or registered `warehouse_code` under tenant scope.
- **Strict Prohibition**: Geographic proximity alone never associates a signal with a warehouse.

### 4.5 Port Correlation (Single Authoritative Path)
- Follows the single authoritative maritime hub route established in Step 1:
  1. Internal `port_id`.
  2. Verified `UN/LOCODE` mapping (e.g. `USLAX` $\rightarrow$ Port of Los Angeles).
  3. Verified provider mapping (`port_code`).
- Nearby coordinates never auto-snap to a port without an explicit port identifier.

### 4.6 Vessel Correlation & Identity Hierarchy
- **Hierarchy Order**: $\text{IMO} > \text{MMSI} > \text{Callsign} > \text{Vessel Name}$.
- **Conflict Handling**: If both IMO and MMSI are present and resolve to conflicting vessels, RiskWise flags `is_conflict=True`, sets `correlation_confidence=UNRESOLVED`, marks `correlation_status=AMBIGUOUS`, and records the conflict explanation.

### 4.7 Aircraft Correlation & Callsign Dynamics
- Permanent identity is governed by `ICAO24`. Callsigns are transient and non-permanent.
- If a reported callsign conflicts with a registered aircraft's permanent callsign, both are preserved, conflict is flagged, and confidence is marked `UNRESOLVED`.

### 4.8 Carrier Correlation
- Carrier codes are namespace-dependent (`carrier_code` under Karrio $\neq$ `carrier_code` under custom EDI). Resolved only through verified mappings.

---

## 5. Cross-Source Event Correlation & Deduplication

When multiple external feeds report on the same physical incident (e.g. TomTom road closure and Tavily news article):

### 5.1 Deterministic Correlation Key
The engine computes a SHA-256 fingerprint incorporating multi-tenant isolation:
$$\text{key} = \text{SHA-256}(\text{org\_id} \parallel \text{domain} \parallel \text{signal\_type} \parallel \text{event\_type} \parallel \text{entity\_key} \parallel \text{lat\_bucket} \parallel \text{lon\_bucket} \parallel \text{hour\_bucket} \parallel \text{incident\_ref})$$
- `org_id`: Guarantees events in Organization A never merge with events in Organization B.
- `lat_bucket` / `lon_bucket`: Rounded to 2 decimal places ($\approx 1.1\text{ km}$).
- `hour_bucket`: UTC hour bucket (`YYYY-MM-DD-HH`).

### 5.2 Duplicate vs Corroborating Source
- **Exact Duplicate**: Same provider, same source, and identical canonical/provider event ID. Safely dropped; does **not** inflate evidence count.
- **Corroborating Source**: Independent provider/source reporting supporting evidence for the same physical event. Merged into `supporting_sources` with complete provenance.

### 5.3 Source Precedence Hierarchy
$$\mathbf{REAL}\ (3) > \mathbf{ESTIMATED}\ (2) > \mathbf{SIMULATED}\ (1)$$
- Higher-precedence source becomes the primary signal; lower-precedence source is preserved as supporting evidence.
- Zero provenance loss: No observation is deleted.

### 5.4 Conflict Handling
- If Source A reports `ACTIVE` and Source B reports `RESOLVED`, both observations are retained in `supporting_sources` and logged in `canonical_attributes["status_conflicts"]`.

---

## 6. Multi-Tenant Isolation & Performance

1. **Strict Organization Scoping**: All internal entity queries require `org_id`. Lookups across tenant boundaries are strictly rejected.
2. **$O(1)$ In-Memory Indexing**: Correlation uses dictionary bucket hashing by correlation key, completely avoiding $O(N^2)$ global comparisons.
3. **Database Unchanged**: No PostgreSQL schema changes, tables, columns, or indexes were added. Future database persistence for entity resolution indices can be layered via Redis or PostgreSQL GIN indexes without impacting Step 3.
