# Phase 16 — Human Approval Subsystem Documentation

## 1. Purpose & Pipeline Topology

The **RiskWise 2.0 Human Approval Subsystem (Phase 16)** enforces an uncompromising governance boundary between automated analytical synthesis (Phase 15 Decision Agent) and real-world operational execution (Phase 17 Action Agent).

```
Detection
   ↓
Research Agent (Phase 8 RAG Grounding)
   ↓
Risk Engine (Phase 7 Deterministic Scoring)
   ↓
Prediction / ML (Phase 11 Transit Delays)
   ↓
Digital Twin (Phase 12 Network Model)
   ↓
Simulation (Phase 13 Monte Carlo)
   ↓
Optimization (Phase 14 Google OR-Tools)
   ↓
Decision Agent (Phase 15 Synthesis Policy)
   ↓
┌─────────────────────────────────────────────────────────────┐
│                      PHASE 16                               │
│                   HUMAN APPROVAL                            │
│                                                             │
│       Dossier Review  ──→  Explicit Approve / Reject        │
│                                                             │
│  - Zero autonomous sign-off                                 │
│  - Multi-tenant boundary isolation                          │
│  - Row-level lock concurrency & idempotency                 │
│  - SHA-256 tamper-evident fingerprinting                    │
│  - Transactional audit log persistence                      │
└─────────────────────────────────────────────────────────────┘
   ↓ (If Approved)
Phase 17 Action Agent (Real-World Operational Dispatch)
```

### Strict Operational Invariants

> [!IMPORTANT]
> **ZERO AUTONOMOUS APPROVAL INVARIANT**
> - The system MUST NEVER auto-approve operational decisions.
> - Under no circumstances does the Decision Agent, Claude, Bedrock, or any automated node have authority to set `status = APPROVED` or `side_effect_allowed = True`.
> - Operational sign-off strictly requires an authenticated human user possessing `RiskManager` or `Admin` privileges.

> [!CAUTION]
> **IMMUTABILITY & FINALITY INVARIANT**
> - Once an approval item has been finalized as `APPROVED` or `REJECTED`, it is permanently immutable.
> - Any subsequent attempt to re-decide, re-approve, or alter a finalized decision yields an immediate `409 Conflict` (`ApprovalAlreadyFinalizedError`).

> [!NOTE]
> **ZERO SCHEMA MIGRATIONS (34 TABLES PRESERVED)**
> - Phase 16 introduces 0 new database tables and 0 Alembic migrations.
> - All governance records reuse the existing `recommendations`, `approvals`, `audit_logs`, and `users` tables.

---

## 2. Architecture & Data Flow

The Human Approval subsystem operates across two complementary modalities:
1. **LangGraph State Graph Execution (`human_approval_node`)**:
   - Evaluates whether an incoming operational proposal requires human sign-off.
   - If pending sign-off, halts graph progression, sets `status = WAITING_FOR_APPROVAL`, flags `requires_human_approval = True`, and routes to graph termination.
   - When resumed with explicit human sign-off (`ApprovalDecisionInput`), records the decision, generates the audit fingerprint, and flags `side_effect_allowed = True` (or `False` if rejected).
2. **Synchronous REST API Layer (`/api/v1/approvals`)**:
   - Provides supply chain operators and risk executives with interactive endpoints to query pending queues, inspect comprehensive audit dossiers, and execute cryptographic sign-offs.

```
       [ Upstream Pipeline ]
                │
                ▼
        [ Decision Agent ]
                │ (DecisionResult: requires_human_approval=True)
                ▼
      [ human_approval_node ] ──(No Human Input)──► State: WAITING_FOR_APPROVAL
                │                                    Halts for Human Review
                │
                ▼ (Dossier Inspection)
     [ GET /api/v1/approvals/{id}/dossier ]
                │
                ▼ (Human Executive Decision: RiskManager / Admin)
     [ POST /api/v1/approvals/{id}/decide ]
                │
                ▼
     [ ApprovalRepository.record_human_decision ]
      ├─ Row-level lock (`with_for_update`)
      ├─ Verify tenant isolation & authorization
      ├─ Update `recommendations` & insert `approvals`
      ├─ SHA-256 fingerprint generation
      └─ Write structured event to `audit_logs`
                │
                ▼ (Resume State Graph / Trigger Action Stage)
      [ side_effect_allowed = True ] ──► Phase 17 Action Agent
```

---

## 3. Contracts & Domain Models

All Phase 16 domain contracts are defined in [`api/app/agents/approval/contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/approval/contract.py) with Pydantic V2 (`extra="forbid"`, `validate_assignment=True`):

### Core Enums
- `ApprovalStatus`: `PENDING`, `APPROVED`, `REJECTED`, `EXPIRED`, `CANCELLED`
- `ApprovalDecision`: `APPROVE`, `REJECT`

### Domain Objects
- **`ApprovalActor`**:
  - `actor_id`: String identifier of the human operator.
  - `organization_id`: Tenant scope of the actor.
  - `role`: Role string (`RiskManager`, `Admin`).
- **`ApprovalRequest`**:
  - Encapsulates `organization_id`, `decision_id`, `candidate_id`, `recommendation_id`, `required_role`, `evidence_references`, and `constraints`.
  - Enforces cross-tenant validation ensuring candidate and decision IDs match the requester organization.
- **`ApprovalDecisionInput`**:
  - Carries the explicit human action: `decision`, `actor`, `comments`, and `decided_at`.
- **`ApprovalResult`**:
  - Emitted by `HumanApprovalAgent`.
  - Contains deterministic `approval_id`, `status`, `fingerprint` (SHA-256), `requires_human_approval`, and `side_effect_allowed`.
- **`ApprovalDossier`**:
  - Comprehensive inspection view combining decision attributes, optimization solver stats, upstream risk context, and approval status.
- **`HumanDecisionRequest`**:
  - Request body schema for `/api/v1/approvals/{id}/decide`:
    - `decision`: `APPROVE` or `REJECT`
    - `comments`: Optional operational sign-off rationale (1–2000 chars).

---

## 4. REST API Reference

The REST API is implemented in [`api/app/api/v1/endpoints/approvals.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/approvals.py):

| Method | Endpoint | Authorized Roles | Description |
|---|---|---|---|
| `GET` | `/api/v1/approvals/pending` | Any authenticated tenant user | Returns paginated list of items awaiting review. |
| `GET` | `/api/v1/approvals/{id}/dossier` | Any authenticated tenant user | Retrieves comprehensive evidence dossier for human inspection. |
| `POST` | `/api/v1/approvals/{id}/decide` | `RiskManager`, `Admin` | Submits official human decision (`APPROVE` or `REJECT`). |
| `POST` | `/api/v1/approvals/{id}/approve` | `RiskManager`, `Admin` | Convenience endpoint to approve directly with optional comment. |
| `POST` | `/api/v1/approvals/{id}/reject` | `RiskManager`, `Admin` | Convenience endpoint to reject directly with optional comment. |

### Error Codes
- `401 Unauthorized`: Missing or invalid authentication token.
- `403 Forbidden`: User role is not permitted to sign off on decisions (e.g., `Viewer`, `Analyst`).
- `404 Not Found`: Approval or decision record does not exist within the requester's tenant.
- `409 Conflict`: Attempting to decide on an already finalized (`APPROVED` or `REJECTED`) decision.

---

## 5. Security & RBAC Matrix

Phase 16 enforces strict multi-tenant boundary checks and role-based permissions:

```
┌─────────────────┬─────────────────┬─────────────────┬─────────────────┐
│ Role            │ List / Dossier  │ Review          │ Sign-Off        │
│                 │ (Read-Only)     │ (Inspection)    │ (Approve/Reject)│
├─────────────────┼─────────────────┼─────────────────┼─────────────────┤
│ Viewer          │       ✓         │       ✓         │        ✗        │
│ LogisticsCoord  │       ✓         │       ✓         │        ✗        │
│ Analyst         │       ✓         │       ✓         │        ✗        │
│ RiskManager     │       ✓         │       ✓         │        ✓        │
│ Admin           │       ✓         │       ✓         │        ✓        │
└─────────────────┴─────────────────┴─────────────────┴─────────────────┘
```

### Multi-Tenant Isolation
All database queries in `ApprovalRepository` filter strictly by `organization_id = auth_context.organization_id`. Attempts by Tenant A to inspect, list, or approve recommendations owned by Tenant B return `404 Not Found` (shielding existence information).

### Anti-Tamper SHA-256 Fingerprinting
Every recorded decision generates a deterministic cryptographic fingerprint over:
- Organization ID
- Decision ID
- Candidate ID
- Approval Status (`APPROVED` / `REJECTED`)
- Approver User ID
- Timestamp
- Decision Comments

Any unauthorized modification of the row or history record renders the fingerprint invalid.

---

## 6. Verification & Test Coverage

Phase 16 is backed by 4 dedicated test suites (29 tests) and regression verified against all preceding phases (180+ tests passing 100%):

1. **`tests/test_phase16_contracts.py`** (7 tests):
   - Validates all Pydantic V2 models, strictness (`extra="forbid"`), tenant match checks, deterministic UUIDv5 generation, and SHA-256 fingerprinting.
2. **`tests/test_phase16_security_rbac.py`** (6 tests):
   - Enforces Zero Autonomous Approval invariant.
   - Validates role rejection (`Viewer`, `Analyst` forbidden; `RiskManager`, `Admin` allowed).
   - Validates multi-tenant isolation, immutability on finalized decisions, and audit log generation.
3. **`tests/test_phase16_persistence_api.py`** (8 tests):
   - Table count invariant (exactly 34 tables, 0 schema changes).
   - Endpoint testing for `/pending`, `/dossier`, `/decide`, `/approve`, `/reject`.
   - Cross-tenant rejection (`404`) and RBAC rejection (`403`).
4. **`tests/test_phase16_integration.py`** (5 tests):
   - Decision Agent → Human Approval handoff in LangGraph.
   - Pending evaluation halts execution with `requires_human_approval = True`.
   - Explicit sign-off resumes and sets `side_effect_allowed = True`.
   - Authoritative field ownership verification via `validate_state_update`.
