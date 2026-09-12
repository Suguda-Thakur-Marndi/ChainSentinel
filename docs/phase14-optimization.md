# Phase 14: Optimization Subsystem — Architectural & Operational Specification

## 1. Executive Summary & Objective

The **RiskWise Optimization Subsystem** provides a deterministic, mathematically rigorous prescriptive solver layer built on top of **Google OR-Tools** and strictly bounded by the authoritative data from **Phase 12 Digital Twin** and **Phase 13 Simulation**.

- **Phase 12 (Digital Twin):**
  > *"What does my supply chain look like right now?"*
- **Phase 13 (Simulation Engine):**
  > *"What happens if something changes?"*
- **Phase 14 (Optimization Subsystem):**
  > *"Given the current or simulated state, constraints, and explicit objective, what feasible or optimal mathematical solutions exist?"*
- **Phase 15 (Decision Agent — Strictly Out of Scope):**
  > *"What decision should be proposed?"*
- **Phase 16 (Human Approval — Strictly Out of Scope):**
  > *"Who approves it?"*
- **Phase 17 (Action Agent — Strictly Out of Scope):**
  > *"Execute the approved action."*

### Explicit Phase Boundary:
> **"Optimization generates mathematical candidate/feasible/optimal solutions. It does not make the final business decision."**

---

## 2. Architecture & Components

```
api/app/optimization/
├── __init__.py          # Public API exports
├── config.py            # Hard resource bounds, timeouts, engine constants
├── contracts.py         # Strongly typed Pydantic V2 contracts & schemas
├── errors.py            # Optimization exception hierarchy
├── fingerprints.py      # Canonical SHA-256 deterministic fingerprinting
├── validators.py        # Strict tenant, bounds, and non-fabrication validation
├── variables.py         # Explicit mathematical decision variable builders
├── constraints.py       # Hard (assignment, capacity, availability) & soft constraints
├── objectives.py        # Explicit linear objective formulations (Delay, Cost, Risk)
├── model.py             # OptimizationProblem assembly & canonicalization
├── solver.py            # Google OR-Tools wrapper with strict status mapping & timeout
├── result.py            # OptimizationResult assembly & comparative metric calculation
├── persistence.py       # Transactional, idempotent persistence in optimization_runs
├── service.py           # Central orchestration layer
└── integration.py       # Read-only adapters for Digital Twin, Simulation, Risk, ML
```

---

## 3. Mathematical Formulation & Supported Domains

### Supported Domains:
1. **`SHIPMENT_REROUTE`**: Joint assignment of delayed or disrupted consignments across available network corridors.
2. **`ROUTE_SELECTION`**: Optimal corridor selection under capacity and risk constraints.
3. **`CARRIER_ALLOCATION`**: Freight volume assignment across approved carriers.
4. **`FACILITY_ALLOCATION`**: Throughput and storage load distribution across warehouses and supplier sites.

### Decision Variables:
Explicit binary assignment variables:
$$x_{s,r} \in \{0, 1\}$$
where $x_{s,r} = 1$ if shipment $s$ is routed through candidate alternative $r$, and $0$ otherwise.

### Hard Constraints:
- **Assignment**: Each consignment must be assigned to exactly one candidate alternative:
  $$\sum_{r \in R_s} x_{s,r} = 1 \quad \forall s \in S$$
- **Availability**: Any route or facility marked unavailable (via operational status or Phase 13 simulation disruption) is forced to 0:
  $$x_{s,r} = 0 \quad \forall r \in R_{\text{unavailable}}$$
- **Capacity**: Cumulative allocated volume cannot exceed authoritative corridor or facility capacity:
  $$\sum_{s \in S} \text{load}_s \cdot x_{s,r} \le \text{Capacity}_r \quad \forall r \in R$$

### Objectives:
- **`MINIMIZE_DELAY`**: $\min \sum_{s,r} \text{transit\_time}_{s,r} \cdot x_{s,r}$
- **`MINIMIZE_COST`**: $\min \sum_{s,r} \text{cost}_{s,r} \cdot x_{s,r}$ (strictly requires authoritative cost data)
- **`MINIMIZE_RISK`**: $\min \sum_{s,r} \text{risk}_{s,r} \cdot x_{s,r}$ (derived from Phase 7 Risk Engine / Twin edge risk)
- **`MINIMIZE_ROUTE_DEVIATION`**: Minimizes diversion from authoritative baseline routes.

---

## 4. Google OR-Tools Integration & Solver Status Mapping

Google OR-Tools (`pywraplp.Solver`) provides mathematical execution. Solver outcomes are mapped strictly without ambiguity:

- **`OPTIMAL`**: Solver proved mathematical optimality.
- **`FEASIBLE`**: Feasible solution satisfies all constraints, but optimality was not proven within limits.
- **`INFEASIBLE`**: Conflicting or impossible constraints; no mathematical solution exists.
- **`UNBOUNDED`**: Mathematical model is unbounded.
- **`TIME_LIMIT`**: Configured execution time limit was reached.
- **`NOT_AVAILABLE`**: Solver backend, library, or required authoritative data is unavailable.
- **`FAILED`**: Unexpected solver exception.

> **Invariant**: Never label `FEASIBLE` or `TIME_LIMIT` as `OPTIMAL`.

---

## 5. Strict Non-Fabrication Guarantees

The optimizer strictly enforces that missing operational data is never fabricated:
1. **Zero Fabricated Costs**: If an optimization request specifies `MINIMIZE_COST` and any candidate lacks authoritative cost, the optimizer returns `OptimizationDataMissingError` / `NOT_AVAILABLE`. Never uses synthetic numbers (e.g. `1`, `100`, `999999`).
2. **Zero Fabricated Capacities**: Never assumes infinite or zero capacity unless explicitly recorded in authoritative operational records.
3. **Zero Fabricated Demand**: Consignment demand is strictly drawn from operational `Shipment` entities.
4. **Zero Fabricated Transit Times**: Transit times must be non-negative and derived from authoritative route lead times or Digital Twin edge properties.
5. **Zero Fabricated Topology**: Candidate corridors must exist in the Phase 12 Digital Twin graph. Non-existent connections are never hallucinated.

---

## 6. Safety, Determinism, & Immutability

1. **Strict Multi-Tenant Isolation**: Enforced across request context, Digital Twin snapshots, scenarios, simulations, and database persistence. Cross-tenant access fails closed with HTTP 403 / `OptimizationTenantIsolationError`.
2. **Deterministic Cryptographic Fingerprints**: SHA-256 canonical JSON serialization (with sorted keys and no non-deterministic timestamps) ensures identical requests yield identical fingerprints and deterministic UUIDv5 run IDs.
3. **Idempotency**: Repeated requests against equivalent state update existing run records in `optimization_runs` without creating duplicate rows or integrity errors.
4. **Zero Operational DB Mutation**: Source-of-truth operational tables (`suppliers`, `warehouses`, `factories`, `ports`, `carriers`, `routes`, `shipments`, `inventory`) remain 100% read-only.
5. **No Code Execution**: User input is strictly deserialized into strongly typed Pydantic V2 contracts; `eval()` and `exec()` are completely forbidden.

---

## 7. Database & API Parity

- **Database Model**: Reuses existing `optimization_runs` table (`app.models.simulation.OptimizationRun`).
- **Migrations**: **0 migrations, 0 schema changes**.
- **Table Count**: Strictly **34 database tables**.
- **REST Endpoints**:
  - `POST /api/v1/optimization-runs`: Trigger optimization run
  - `GET /api/v1/optimization-runs`: List historical runs for tenant
  - `GET /api/v1/optimization-runs/{id}`: Retrieve optimization run outcome
- **OpenAPI Invariant**: Base API specification retains strictly **60 paths, 96 operations, 104 schemas**.
