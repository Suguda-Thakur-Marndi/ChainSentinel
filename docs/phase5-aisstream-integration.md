# RiskWise 2.0 — Phase 5 Step 5: AISStream Ocean / AIS Integration

## 1. Executive Summary & Architecture Overview

Phase 5 Step 5 integrates real-time maritime AIS (Automatic Identification System) vessel-position and static voyage intelligence into the RiskWise 2.0 platform using **AISStream** (`wss://stream.aisstream.io/v0/stream`).

This integration strictly enforces the provider-agnostic ingestion architecture established in Phase 5 Step 1 (Ingestion Foundation) and Step 2 (Canonical External Event Model):

```text
AISStream (WebSocket)
    │
    ▼
AISStreamAdapter (apps/api/app/integrations/providers/aisstream.py)
    │
    ▼
RawEvent (Envelope with Raw Payload & Deterministic SHA-256 Fingerprint)
    │
    ▼
AISStreamNormalizer
    │
    ▼
CanonicalExternalEvent (VESSEL_LOCATION, MARITIME_INCIDENT, CUSTOM)
    │
    ▼
Optional ShipmentEventBridge (ShipmentEvent persistence only when valid shipment_id correlation exists)
```

No provider-specific WebSocket structures, frame protocols, or field names leak into downstream RiskWise components (e.g. Risk Engine, Digital Twin, or Control Tower).

---

## 2. Verified AISStream Specifications & Protocols

Before implementation, official AISStream documentation was thoroughly verified.

### 2.1 Verified WebSocket Endpoint
- **URL**: `wss://stream.aisstream.io/v0/stream`
- **Protocol**: Bi-directional persistent WebSocket over TLS (`wss://`).
- **Connection Handshake**: Standard HTTP/1.1 Upgrade to WebSocket.
- **Compression**: Per-message deflate supported.

### 2.2 Verified Authentication Mechanism
- AISStream does **not** authenticate via HTTP Authorization headers or URL query parameters.
- Authentication occurs via a JSON subscription frame sent immediately after the WebSocket handshake completes (within 3 seconds of connection establishment).
- The field `APIKey` is mandatory in the subscription JSON envelope.

### 2.3 Verified Subscription Message Schema
```json
{
  "APIKey": "<YOUR_API_KEY>",
  "BoundingBoxes": [
    [
      [<minLatitude>, <minLongitude>],
      [<maxLatitude>, <maxLongitude>]
    ]
  ],
  "FiltersShipMMSI": ["244710000", "211281610"],
  "FilterMessageTypes": ["PositionReport", "ShipStaticData"]
}
```

- **`BoundingBoxes`** (Required): Array of bounding boxes. Each bounding box is defined by a pair of `[latitude, longitude]` coordinate arrays.
- **`FiltersShipMMSI`** (Optional): Array of vessel MMSI strings (up to 200 MMSIs).
- **`FilterMessageTypes`** (Optional): Array of message type strings to filter server-side (e.g. `"PositionReport"`, `"ShipStaticData"`).

### 2.4 Verified Inbound Message Envelope
Every message received over the stream is structured into a 3-part JSON envelope:
```json
{
  "MessageType": "PositionReport",
  "MetaData": {
    "MMSI": 244710000,
    "ShipName": "ROTTERDAM STAR",
    "latitude": 51.9244,
    "longitude": 4.4777,
    "time_utc": "2026-09-08 00:15:30.000000 +0000 UTC"
  },
  "Message": {
    "PositionReport": {
      "Cog": 182.5,
      "Sog": 12.8,
      "TrueHeading": 180,
      "NavigationalStatus": 0,
      "Latitude": 51.9244,
      "Longitude": 4.4777,
      "Timestamp": 30,
      "UserID": 244710000,
      "RateOfTurn": 0
    }
  }
}
```

For static metadata (`MessageType = "ShipStaticData"`):
```json
{
  "MessageType": "ShipStaticData",
  "MetaData": {
    "MMSI": 244710000,
    "ShipName": "ROTTERDAM STAR",
    "latitude": 51.9244,
    "longitude": 4.4777,
    "time_utc": "2026-09-08 00:15:30.000000 +0000 UTC"
  },
  "Message": {
    "ShipStaticData": {
      "ImoNumber": 9321483,
      "CallSign": "PD3841",
      "Name": "ROTTERDAM STAR",
      "Type": 70,
      "Destination": "ANTWERP",
      "Dimension": {"A": 120, "B": 280, "C": 20, "D": 22},
      "Draught": 14.5,
      "Eta": {"Month": 9, "Day": 10, "Hour": 18, "Minute": 0}
    }
  }
}
```

---

## 3. Dedicated Provider Adapter (`AISStreamAdapter`)

Located at: `apps/api/app/integrations/providers/aisstream.py`.

Subclasses `BaseProviderAdapter` and implements:
- **`provider_name`**: `"aisstream"`
- **`provider_type`**: `ProviderType.OCEAN_AIS`
- **`capabilities`**:
  - `supports_streaming = True`
  - `supports_polling = False`
  - `supports_webhook = False`
  - `supports_batch = True`
  - `supports_health_check = True`
  - `supported_entities = ["location", "vessel", "shipment", "carrier", "port"]`
  - `supported_modalities = ["ocean", "ais", "vessel_tracking", "maritime"]`

### 3.1 WebSocket Transport Abstraction
To ensure testability and prevent external dependency coupling, transport is encapsulated behind `AISWebSocketTransport`:
- `connect(url: str, timeout: float = 10.0)`
- `send(message: str)`
- `receive(timeout: Optional[float] = None) -> str`
- `close()`
- `is_connected: bool`

`MockAISWebSocketTransport` allows testing 100% of the adapter lifecycle, frames, and error edge cases with **zero live network calls**.

### 3.2 Subscription Model (`AISStreamSubscription`)
Validates geographic coordinates and bounding box structures before sending:
- All latitude coordinates validated against `[-90.0, 90.0]`.
- All longitude coordinates validated against `[-180.0, 180.0]`.
- Rejects bounding boxes with invalid coordinate pairs or inverted counts.
- Restricts MMSI filter arrays to a maximum of 200 entries (AISStream limit).

---

## 4. Normalization Matrix & Canonical Event Mapping

`AISStreamNormalizer` maps raw AISStream messages into `CanonicalExternalEvent` without schema alterations:

| AISStream Field | Canonical Mapping | Type / Format | Notes |
| :--- | :--- | :--- | :--- |
| `MessageType == "PositionReport"` | `CanonicalEventType.VESSEL_LOCATION` or `MARITIME_INCIDENT` | `CanonicalEventType` | Based on `NavigationalStatus` |
| `NavigationalStatus == 0, 1, 5, 8` | `VESSEL_LOCATION`, `severity=INFO` | `EventSeverity.INFO` | Normal underway, at anchor, moored |
| `NavigationalStatus == 6` (Aground) | `MARITIME_INCIDENT`, `severity=CRITICAL` | `EventSeverity.CRITICAL` | Operational emergency |
| `NavigationalStatus == 14` (AIS-SART) | `MARITIME_INCIDENT`, `severity=CRITICAL` | `EventSeverity.CRITICAL` | Active distress beacon |
| `NavigationalStatus == 2` (Not under command) | `MARITIME_INCIDENT`, `severity=HIGH` | `EventSeverity.HIGH` | Vessel loss of steering/engine |
| `NavigationalStatus == 3, 4` (Restricted) | `VESSEL_LOCATION`, `severity=MEDIUM` / `LOW` | `EventSeverity.MEDIUM` | Constrained navigation |
| `MessageType == "ShipStaticData"` | `CanonicalEventType.CUSTOM` (`"VESSEL_STATIC_DATA"`) | `CanonicalEventType` | Static metadata & voyage plans |
| `MetaData.MMSI` / `UserID` | `EntityCorrelation.custom_identifiers["mmsi"]` | `str` | Maritime Mobile Service Identity |
| `ShipStaticData.ImoNumber` | `EntityCorrelation.custom_identifiers["imo"]` | `str` | IMO vessel number |
| `ShipStaticData.CallSign` | `EntityCorrelation.custom_identifiers["call_sign"]` | `str` | Radio call sign |
| `MetaData.ShipName` | `EntityCorrelation.custom_identifiers["vessel_name"]` | `str` | Vessel vessel name |
| `MetaData.time_utc` | `CanonicalExternalEvent.event_timestamp` | UTC `datetime` | Normalized from Go-format timestamp |
| `MetaData.latitude`, `longitude` | `CanonicalExternalEvent.location` | `EventLocation` | Validated WGS84 coordinates |
| `PositionReport.Sog` | `normalized_attributes["speed_over_ground_knots"]` | `float` | Knots |
| `PositionReport.Cog` | `normalized_attributes["course_over_ground"]` | `float` | Degrees (0–360) |
| `PositionReport.TrueHeading` | `normalized_attributes["heading_degrees"]` | `int` | Degrees (0–359) |
| `PositionReport.RateOfTurn` | `normalized_attributes["rate_of_turn"]` | `int` | Rotational velocity |

Normal vessel transit positions are **never** artificially elevated to risk status (`EventSeverity.INFO`).

---

## 5. Entity Correlation & ShipmentEventBridge Behavior

- **Vessel Identifiers**: Extracted into `EntityCorrelation.custom_identifiers` (`{"mmsi": ..., "imo": ..., "call_sign": ..., "vessel_name": ...}`).
- **Uncorrelated Observations**: If an AIS vessel observation cannot be matched with certainty to an active RiskWise shipment, `correlation.shipment_id` remains `None`, `quality` is marked `PARTIAL` or `VALID` (observation quality), and `ShipmentEventBridge.can_persist_to_shipment_event()` returns `False`.
- **Correlated Observations**: When downstream engines correlate a vessel observation to a shipment (e.g. `shipment_id = "SHP-2026-001"`), `ShipmentEventBridge.can_persist_to_shipment_event()` evaluates to `True`, and `to_shipment_event_dict()` produces the exact dictionary required for `ShipmentEvent` creation with `mode="OCEAN"`.

No false or fabricated shipment correlations are created.

---

## 6. Deterministic Idempotency & Consecutive Deduplication

Because AISStream message frames lack a globally unique ID across transmissions, `AISStreamAdapter` generates a deterministic SHA-256 fingerprint:

```text
Fingerprint Input:
org:{org_id}:aisstream:{MessageType}:mmsi:{mmsi}:ts:{time_utc}:pos:{lat_4dec},{lon_4dec}
```

- **Duplicate Resilience**: Re-transmissions of the exact same message frame produce identical SHA-256 hashes and are deduplicated by `IdempotencyEngine`.
- **Consecutive Position Preservation**: Legitimate consecutive vessel reports (which advance in timestamp or geographic coordinates) produce distinct fingerprints and are **never** erroneously dropped.

---

## 7. Reconnect, Retry & Health Checks

- **Error Classification**:
  - `ProviderAuthenticationError`: Non-retryable. Aborts immediately upon missing key or invalid credentials without endless loops.
  - `ProviderConnectionError` / `ProviderTimeoutError`: Retryable via `RetryPolicy` with exponential backoff and jitter.
  - `ProviderRateLimitError`: Raised on upstream rate limits.
  - `ProviderValidationError`: Raised on malformed frames or missing envelope fields.
- **Provider Health Checks**:
  - `HEALTHY`: API key present and non-destructive probe frame dispatched successfully.
  - `UNCONFIGURED`: API key missing or unresolvable.
  - `DEGRADED`: WebSocket transport timed out during handshake or probe.
  - `UNHEALTHY`: Authentication rejected by upstream or socket disconnected.
  - All credentials and API keys are strictly redacted from `ProviderHealthResult.details`.

---

## 8. Database & API Scope Integrity

- **Database**: Zero PostgreSQL migrations, zero DDL statements, zero schema alterations, zero enum additions.
- **API / Frontend**: Zero public AIS WebSocket endpoints created, no frontend UI modifications, and no public routes added. Provider logic is entirely isolated to the integration layer.
