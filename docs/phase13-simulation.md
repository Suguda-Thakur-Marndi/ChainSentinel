# Phase 13: Simulation Engine — Architectural & Operational Specification

## 1. Executive Summary & Objective

The **RiskWise Simulation Engine** provides a deterministic, queryable, and strictly isolated **What-If simulation platform** built on top of the authoritative **Phase 12 Digital Twin**.

- **Phase 12 (Digital Twin):**
  > *"What does my supply chain look like right now?"*
- **Phase 13 (Simulation Engine):**
  > *"What happens if something changes?"*
- **Phase 14 (Optimization & Autonomous Actions — Strictly Out of Scope):**
  > *"What is the best response?"*

The Simulation Engine evaluates hypothetical disruptions, delays, capacity shifts, and demand changes against an immutable snapshot of the operational supply chain graph. It determines downstream flow severances, arrival delays, capacity bottlenecks, and inventory exposure.

---

## 2. Strict Phase Boundary & Non-Goals

### Out of Scope for Phase 13:
- **Zero Optimization:** No OR-Tools, linear programming solvers, or mathematical optimization.
- **Zero Autonomous Execution:** No automatic rerouting, purchase order creation, carrier rescheduling, or production mitigation.
- **Zero Source Mutation:** Real operational entities (`suppliers`, `factories`, `warehouses`, `shipments`, `routes`, `inventories`) are never modified.
- **No LLM Topology Inference:** Claude and LLMs are never used to decide graph propagation or invent physical supply chain links.
- **No Control Tower UI:** Control Tower visualization belongs to Phase 19.

---

## 3. Architecture & Components

```
apps/api/app/simulation/
├── __init__.py          # Public API exports
├── contracts.py         # Strongly-typed Pydantic contracts & schemas
├── errors.py            # Simulation-specific typed exception hierarchy
├── fingerprints.py      # Canonical SHA-256 deterministic fingerprinting
├── validation.py        # Strict tenant, entity, parameter & bound validation
├── scenario.py          # Scenario definition & hypothetical change models
├── state.py             # Isolated in-memory simulation state cloned from Digital Twin
├── propagation.py       # Deterministic, bounded graph effect propagation engine
├── effects.py           # Simulation effect classification & tracking
├── metrics.py           # Baseline vs. simulated metric calculations & delta comparisons
├── engine.py            # Headless, API-independent simulation execution engine
├── repository.py        # Safe tenant-scoped persistence against scenarios & simulations
├── service.py           # Orchestration layer coordinating engine, repo, ML & Risk
└── observability.py     # Structured logging, timing, and metrics audit trail
```

---

## 4. Scenario & Change Model

A scenario is an immutable definition of one or more hypothetical disruptions applied to an authoritative Digital Twin snapshot.

### Supported Change Types:
1. `NODE_UNAVAILABLE`: Outage of a port, factory, or facility (e.g. 72h port closure).
2. `EDGE_UNAVAILABLE`: Severance of a transport corridor or route.
3. `DELAY`: Transit or processing delay (hours/minutes) applied to shipments, ports, or corridors.
4. `CAPACITY_REDUCTION`: Percentage or unit reduction in facility throughput/storage.
5. `CAPACITY_INCREASE`: Temporary capacity expansion.
6. `TRANSIT_TIME_INCREASE`: Route travel duration elongation.
7. `DEMAND_CHANGE`: Shifts in downstream inventory draw (where authoritative demand exists).
8. `INVENTORY_CHANGE`: Stock adjustments at specific facilities.

All changes are strictly tagged with:
```json
"source_type": "SIMULATED"
```

---

## 5. In-Memory State Isolation

Simulation operates on a deep clone of the Digital Twin state:
1. `DigitalTwinSnapshot` is fetched read-only.
2. `SimulationState` clones nodes into `SimulatedNodeState` and edges into `SimulatedEdgeState`.
3. Hypothetical changes mutate only in-memory attributes (`is_available`, `effective_delay_minutes`, `capacity`, `simulated_tags`).
4. Authoritative tables in PostgreSQL remain 100% untouched.

---

## 6. Deterministic Propagation Engine

The propagation engine executes a bounded breadth-first search (BFS) along relationship edges:
- **Resource Bounds:**
  - `max_depth` (default: 5, hard maximum: 10)
  - `max_nodes` (default: 200, hard maximum: 1,000)
  - `max_edges` (default: 500, hard maximum: 2,000)
  - `max_effects` (default: 100, hard maximum: 500)
- **Cycle Prevention:** Visited tracking prevents infinite loops across cyclical network topologies (e.g. factory-warehouse feedback loops).
- **Explainable Rules:**
  - **Rule A (Supply Severance):** Outages sever dependent incoming and outgoing flows.
  - **Rule B (Delay Cascade):** Delays propagate downstream through corridors to downstream arrival times.
  - **Rule C (Inventory Exposure):** Upstream flow cuts flag downstream warehouses with replenishment stockout exposure risks.

---

## 7. Metrics & Comparative Analysis

The engine computes standardized comparative metrics:
- `total_delay_minutes` (Baseline, Simulated, Delta)
- `affected_nodes_count`
- `affected_edges_count`
- `affected_shipments_count`
- `total_capacity_units`
- `inventory_exposure_units`
- `overall_risk_score`

If underlying authoritative data is missing for a metric, it is explicitly flagged as `availability = "NOT_AVAILABLE"` rather than fabricating arbitrary constants.

---

## 8. Deterministic Fingerprints & Cryptographic Identity

- **UUIDv5 Identifiers:**
  - Scenarios: `uuid5(SCENARIO_NAMESPACE, f"{org_id}:{name}:{snapshot_fp}")`
  - Simulations: `uuid5(SIMULATION_NAMESPACE, f"{scenario_id}:{snapshot_fp}:{config_hash}")`
  - Changes: `uuid5(CHANGE_NAMESPACE, f"{scenario_id}:{target}:{type}:{magnitude}")`
- **SHA-256 Fingerprints:**
  - Canonical JSON serialization with sorted keys.
  - Identical inputs produce identical scenario and simulation fingerprints.

---

## 9. Multi-Tenant Isolation & Security

- Repository and Service layers enforce strict organization scoping on all queries and mutations.
- Cross-tenant scenario creation, retrieval, simulation execution, or comparison attempts raise `SimulationTenantIsolationError` and return `HTTP 403 Forbidden`.
- Traversal depth and node counts are bounded to prevent resource exhaustion attacks.

---

## 10. Persistence & Schema Integrity

- Reuses existing PostgreSQL tables: `scenarios` and `simulations` (`apps/api/app/models/simulation.py`).
- Zero Alembic migrations required.
- Idempotent and transactional operations.

---

## 11. Phase Boundary Confirmation

- **Phase 13:** What-if simulation engine implemented.
- **Phase 14:** Optimization / OR-Tools / Prescriptive Actions is **NOT** implemented.
