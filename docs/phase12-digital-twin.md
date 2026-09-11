# RiskWise 2.0 — Phase 12 Digital Twin Architectural Specification

## 1. Digital Twin Purpose

The RiskWise Digital Twin represents the current authoritative operational supply-chain network as a deterministic, tenant-isolated, queryable graph. It connects disparate physical and organizational entities—suppliers, manufacturing sites, factories, distribution warehouses, ports, carriers, shipping corridors, consignments, and product inventories—into a coherent, validated topology.

The Digital Twin is **not** a simulation engine, **not** an optimization solver, and **not** an automated decision-maker. It is a strictly derived representation of current ground truth designed to be queried safely by downstream services and agents.

```
AUTHORITATIVE DATABASE / OPERATIONAL STATE
                  ↓
           DIGITAL TWIN BUILDER
                  ↓
          VALIDATED TWIN GRAPH
                  ↓
         TWIN NODES + TWIN EDGES
                  ↓
       Digital Twin Query Layer
                  ↓
      Future Simulation / Optimization (Phases 13 & 14)
```

---

## 2. Source-of-Truth Model

1. **Source Database Authority**: The PostgreSQL relational database remains the sole authoritative source of truth for all operational entities (`suppliers`, `supplier_sites`, `factories`, `warehouses`, `ports`, `carriers`, `routes`, `shipments`, `products`, `inventory`, `incidents`).
2. **Derived Invariant**: The Digital Twin is strictly derived from database state. It never writes back operational metrics (e.g. changing warehouse capacity or modifying carrier status) to authoritative tables.
3. **Freshness Invariant**: When source records are updated in PostgreSQL, subsequent twin builds immediately reflect those changes without stale data retention.

---

## 3. Node Model

Twin nodes represent physical facilities, organizational entities, transit hubs, and items within the network.

- **Contract**: `TwinNodeContract` (Pydantic v2, `extra="forbid"`, `frozen=True`).
- **Supported Types (`TwinNodeType`)**:
  - `SUPPLIER`: Tiered vendor organizations profile.
  - `SUPPLIER_SITE`: Specific manufacturing or extraction facility operated by a supplier.
  - `FACTORY`: Manufacturing plant or assembly facility.
  - `WAREHOUSE`: Storage, distribution, or cross-docking facility.
  - `PORT`: Sea, air, or inland transit terminal (shared reference data).
  - `CARRIER`: Logistics service provider.
  - `ROUTE`: Corridor connecting network facilities.
  - `SHIPMENT`: Consignment in transit.
  - `PRODUCT`: Catalog item SKU.
  - `CUSTOMER`: Downstream delivery destination.
  - `CUSTOM`: Extensible domain entity.
- **Node Attributes**:
  - `node_id`: Deterministic UUIDv5 identifier.
  - `organization_id`: Multi-tenant boundary key.
  - `node_type`: Strongly typed `TwinNodeType`.
  - `source_entity_type`: Source table / model name.
  - `source_entity_id`: Primary key in source table.
  - `label`: Human-readable entity label.
  - `latitude` / `longitude`: Validated geographic coordinates ([-90, 90], [-180, 180]).
  - `health_score`: Normalized operational metric in [0, 100].
  - `status`: Current lifecycle state (`OPERATIONAL`, `ACTIVE`, `IN_TRANSIT`, etc.).
  - `properties`: Arbitrary metadata dictionary preserving capacity, occupancy, tier, SKU, etc.
  - `source_timestamp`: Entity creation timestamp.
  - `fingerprint`: 64-character SHA-256 hex digest.

---

## 4. Edge Model

Twin edges represent directed operational relationships, flow dependencies, transport corridors, and inventory allocations.

- **Contract**: `TwinEdgeContract` (Pydantic v2, `extra="forbid"`, `frozen=True`).
- **Supported Types (`TwinEdgeType`)**:
  - `FLOW`: Material or consignment flow between entities (`Shipment -> Product`).
  - `TRANSPORT`: Physical transit corridor between facilities (`Origin -> Destination`).
  - `DEPENDENCY`: Upstream-downstream relationship.
  - `LOCATED_AT`: Inventory stock mapping (`Facility -> Product`).
  - `OPERATES`: Operational management link.
  - `CONNECTS`: Lane linkage (`Origin -> Route`, `Route -> Destination`, `Shipment -> Route`).
  - `CARRIES`: Haulage relationship (`Carrier -> Shipment`).
  - `SUPPLIES`: Supplier production link (`Supplier -> SupplierSite`).
- **Edge Attributes**:
  - `edge_id`: Deterministic UUIDv5 identifier.
  - `organization_id`: Tenant key.
  - `from_node_id`: Origin node UUIDv5.
  - `to_node_id`: Destination node UUIDv5.
  - `edge_type`: Strongly typed `TwinEdgeType`.
  - `status`: Edge operational status.
  - `flow_capacity`: Non-negative throughput capacity limit.
  - `current_flow`: Non-negative active volume or stock quantity.
  - `risk_score`: Realized corridor risk in [0, 100].
  - `properties`: Operational parameters (mode, distance, lead time).
  - `source_reference`: Traceable database source link.
  - `fingerprint`: 64-character SHA-256 hex digest.

---

## 5. Deterministic Identity Strategy

Twin node and edge identifiers do not use random UUID4 generation. Instead, they use deterministic RFC 4122 Version 5 UUIDs derived from a constant namespace (`TWIN_NAMESPACE = uuid.UUID("a7e1f4b8-3d2c-4f9e-8b1a-5c6d7e8f9a0b")`).

- **Node Identity**:
  $$\text{Node UUID} = \text{UUIDv5}\left(\text{TWIN\_NAMESPACE}, \text{"riskwise:node:"} + \text{org} + \text{":"} + \text{type} + \text{":"} + \text{id}\right)$$
- **Edge Identity**:
  $$\text{Edge UUID} = \text{UUIDv5}\left(\text{TWIN\_NAMESPACE}, \text{"riskwise:edge:"} + \text{org} + \text{":"} + \text{from} + \text{":"} + \text{to} + \text{":"} + \text{type} + \text{":"} + \text{rel\_id}\right)$$

This ensures:
1. Same database state rebuilt twice produces identical node and edge UUIDs.
2. Cross-tenant entities have distinct UUIDs even if source IDs collide.
3. Multiple parallel edges between the same endpoints are disambiguated by `rel_id`.

---

## 6. Provenance & Auditability

Every node and edge maintains explicit provenance:
- Nodes record `source_entity_type` (e.g. `FACTORY`), `source_entity_id` (e.g. `fac_100`), and `source_timestamp`.
- Edges record `source_reference` (e.g. `routes:rt_001`, `supplier_sites:site_01`).
- When serialized into the database, provenance is recorded in `properties_json` (`_source_entity_type`, `_source_reference`, `_fingerprint`) and reconstructed on load.

---

## 7. Snapshots & Immutability

A `DigitalTwinSnapshot` represents an immutable, frozen point-in-time capture of the supply chain network:
- `twin_id`: Identifier for the twin (default: `twin-<organization_id>`).
- `organization_id`: Tenant identifier.
- `version`: Monotonic or semantic version (e.g. `"1"`).
- `node_count` & `edge_count`: Validated entity counts.
- `nodes`: Dictionary mapping `node_id -> TwinNodeContract`.
- `edges`: Dictionary mapping `edge_id -> TwinEdgeContract`.
- `source_fingerprint`: Cryptographic aggregate digest of all source records.
- `twin_fingerprint`: Cryptographic aggregate digest of the resulting graph.
- `generated_at`: UTC timestamp of generation.
- `status`: Semantic freshness flag (`CURRENT`, `SNAPSHOT`, `STALE`).

The snapshot is declared with `frozen=True` in Pydantic v2; any attempt to mutate a published snapshot in place raises a validation error.

---

## 8. Cryptographic Fingerprinting

Deterministic SHA-256 fingerprints ensure tamper detection and change tracking:
1. **Node Fingerprint**: Canonical JSON serialization (keys sorted, whitespace stripped) of node identity and attributes.
2. **Edge Fingerprint**: Canonical JSON serialization of edge identity, endpoints, capacity, flow, and properties.
3. **Source Fingerprint**: SHA-256 hash of sorted source entity digests.
4. **Twin Fingerprint**: SHA-256 hash of the header, sorted node fingerprints, and sorted edge fingerprints.

---

## 9. Digital Twin Builder

The `DigitalTwinBuilder` executes a deterministic pipeline:
1. **Tenant Filtering**: Filters operational records by `organization_id`.
2. **Node Synthesis**: Maps suppliers, sites, factories, warehouses, ports, carriers, routes, shipments, and products into `TwinNodeContract` objects.
3. **Edge Synthesis**: Constructs valid relationships supported by foreign keys and domain associations:
   - `Supplier -> SupplierSite` via `supplier_sites.supplier_id`
   - `Facility -> Route -> Facility` via `routes.origin_facility_id` & `routes.destination_facility_id`
   - `Carrier -> Shipment` via `shipments.carrier_id`
   - `Shipment -> Route` via `shipments.route_id`
   - `Shipment -> Product` via `shipments.product_id`
   - `Facility -> Product` via `inventory.facility_id` & `inventory.product_id`
4. **Incident Context**: Enriches node properties with active disruption summaries from `incidents.affected_assets` without fabricating graph edges.
5. **Graph Validation**: Runs full graph integrity validation.
6. **Snapshot Packaging**: Packages immutable `DigitalTwinSnapshot`.

---

## 10. Graph Validation Engine

`TwinGraphValidator` enforces structural and multi-tenant invariants:
- **Endpoint Existence**: Every edge's `from_node_id` and `to_node_id` must exist in the node set.
- **Tenant Integrity**: All nodes and edges in a graph must belong to the specified `organization_id`.
- **Attribute Ranges**:
  - Latitude in $[-90.0, 90.0]$; Longitude in $[-180.0, 180.0]$
  - Health score in $[0.0, 100.0]$; Risk score in $[0.0, 100.0]$
  - Capacities and flows $\ge 0.0$
- **Fingerprint Verification**: Recomputed SHA-256 digests must match contract fingerprints.
- **Typed Exceptions**: Raises `TwinTenantIsolationError`, `TwinReferenceError`, `TwinFingerprintError`, or `TwinValidationError`.

---

## 11. Transactional Database Persistence

Persistence reuses the existing `twin_nodes` and `twin_edges` tables without schema migrations:
- **Atomic Transaction**: Deletes existing tenant edges, deletes existing tenant nodes, inserts new nodes, inserts new edges, and commits.
- **Rollback Guarantee**: Any validation failure, foreign key conflict, or database error causes an immediate rollback, leaving prior state intact.
- **Zero Migrations**: New attributes (e.g. fingerprints, status, source entity types) are persisted inside `properties_json`.

---

## 12. Query Service

The `DigitalTwinQueryService` provides a read-only, in-memory query interface over an immutable snapshot:
- `get_snapshot()`: Returns the underlying snapshot.
- `get_node(node_id)`: Retrieves a specific node with tenant enforcement.
- `get_outbound_edges(node_id)`: Fetches originating edges.
- `get_inbound_edges(node_id)`: Fetches terminating edges.
- `get_neighbors(node_id, direction, node_type, edge_type)`: Fetches adjacent nodes with optional filtering.
- `get_subgraph(root_node_id, max_depth, max_nodes, max_edges, direction)`: Bounded BFS subgraph extraction.
- `find_path(source_node_id, target_node_id, max_depth)`: Deterministic BFS reachability discovery.

---

## 13. Graph Traversal & Reachability

Graph traversal is implemented using bounded Breadth-First Search (BFS):
- Pure reachability traversal without cost functions, heuristics, or optimization.
- Does **not** calculate shortest-cost paths or optimal supply allocations.
- Bounded by hard upper limits to prevent resource exhaustion.

---

## 14. Cycle Handling

Supply networks frequently contain physical cycles (e.g., circular replenishment routes, returnable container flows, multi-leg transit lanes). The Digital Twin supports cycles without assuming a DAG:
- Traversal maintains a `visited_node_ids: Set[str]` set.
- A cycle like $A \to B \to C \to A$ is traversed without infinite loops or stack overflow.

---

## 15. Multi-Tenant Isolation

Multi-tenant isolation is enforced at every layer:
1. **Source Query Layer**: All queries to operational tables include `.filter(Model.org_id == organization_id)`.
2. **Builder Layer**: Any entity with an mismatched `org_id` is excluded.
3. **Validator Layer**: Asserts that every node and edge matches the expected tenant.
4. **Persistence Layer**: Reads and writes are scoped strictly to `org_id`.
5. **Query Layer**: Cross-tenant node lookups are rejected with `TwinTenantIsolationError` or `TwinQueryError`.

---

## 16. Temporal Semantics

The twin captures a snapshot at `generated_at`:
- Distinguishes current operational status (e.g., `IN_TRANSIT`, `OPERATIONAL`) from entity creation dates.
- Historical events (e.g., milestone telemetry in `shipment_events`) do not overwrite current operational shipment state.
- Stale snapshots can be marked with `status="STALE"`.

---

## 17. Security & Resource Bounding

- **Depth Bound**: `max_depth` is hard-clamped to a maximum of 10 (`MAX_ALLOWED_DEPTH = 10`).
- **Node Bound**: `max_nodes` is hard-clamped to 500 (`MAX_ALLOWED_NODES = 500`).
- **Edge Bound**: `max_edges` is hard-clamped to 1000 (`MAX_ALLOWED_EDGES = 1000`).
- **Secret Redaction**: Audit log payloads scrub sensitive keys (`api_key`, `token`, `password`, `secret`).
- **Read-Only**: The query service contains no mutating methods.

---

## 18. Observability & Telemetry

`TwinObservability` tracks graph lifecycle metrics and audit events:
- Events:
  - `DIGITAL_TWIN_BUILD_STARTED`
  - `DIGITAL_TWIN_BUILD_VALIDATED`
  - `DIGITAL_TWIN_BUILD_SUCCEEDED`
  - `DIGITAL_TWIN_BUILD_FAILED`
  - `DIGITAL_TWIN_QUERY`
- Telemetry captures build duration, validation duration, query duration, node count, edge count, fingerprints, and correlation IDs.

---

## 19. Performance

- In-memory dictionary indexing of outbound and inbound edges yields $O(1)$ adjacency lookups.
- Single-transaction database writes minimize connection overhead.
- Fingerprints are calculated during graph synthesis using canonical single-pass JSON hashing.
- Full suite of 150 focused tests executes in under 24 seconds on SQLite in-memory databases.

---

## 20. Known Limitations

- Real-time streaming synchronization (e.g., EventBridge / Kafka CDC) is not implemented in this phase. Snapshots represent transactional rebuilds.
- Geocoding is not performed automatically; entities without latitude and longitude remain non-spatial nodes.

---

## 21. Boundary with Phase 13 — Simulation

- **Phase 12 Scope**: Static, authoritative operational topology and current state representation only.
- **Phase 13 Exclusions**: Monte Carlo simulation, stochastic event generation, disruption injection, what-if demand variations, and inventory depletion simulations are **strictly excluded** from Phase 12.

---

## 22. Boundary with Phase 14 — Optimization

- **Phase 12 Scope**: Graph reachability discovery and structural relationship queries only.
- **Phase 14 Exclusions**: Mathematical optimization solvers (OR-Tools, PuLP, linear programming), minimum-cost network flow, optimal carrier selection, and route optimization are **strictly excluded** from Phase 12.
