# RiskWise 2.0 — Phase 9 Step 9: Human Approval Boundary

## 1. Objective
The Human Approval boundary establishes a safe, explicit, auditable, and human-governed operational checkpoint immediately downstream of the Decision Agent (`AgentStage.DECISION`) and upstream of pipeline termination or future execution.

Its primary architectural mission is to enforce the core invariant:
$$\text{Decision Proposed} \neq \text{Decision Approved} \neq \text{Action Executed}$$

The system must **NEVER** autonomously approve an operational decision. Only an explicit, authenticated, and authorized human action can transition a decision candidate from `PENDING` to `APPROVED` or `REJECTED`.

---

## 2. Human-in-the-Loop Architecture
The pipeline topology integrates the approval boundary as follows:
```
START
  ↓
INITIALIZATION
  ↓
RESEARCH
  ↓
RISK_ASSESSMENT
  ↓
PREDICTION
  ↓
SCENARIO
  ↓
DECISION
  ↓
HUMAN_APPROVAL (human_approval node)
  ↓
TERMINATION (Waiting for human review or completing approval record)
  ↓
END
```

The node contract is registered as:
- **Node ID**: `human_approval`
- **Stage**: `AgentStage.APPROVAL`
- **Side Effect Type**: `ToolSideEffectType.HUMAN_GOVERNED` (`is_side_effecting=False`)
- **Input Keys**: `decision_result`, `decision_id`, `decision_reference`, `organization_id`
- **Output Keys**: `approval_id`, `approval_reference`, `approval_result`, `approval_status`, `requires_human_approval`, `side_effect_allowed`, `findings`, `structured_findings`, `warnings`

---

## 3. Approval Lifecycle
The approval lifecycle strictly preserves zero autonomous approval and rejects illegal bypass transitions:
1. **PENDING (`WAITING_FOR_APPROVAL`)**:
   - Upstream decision produces candidate recommendations.
   - `human_approval` node receives state without an explicit human decision.
   - Generates deterministic `approval_id` via UUIDv5.
   - Records pending state: `requires_human_approval=True`, `side_effect_allowed=False`.
   - Halts pipeline execution gracefully at `TERMINATION`.
2. **APPROVED**:
   - An authorized human (`RiskManager` or `Admin`) submits an explicit `APPROVE` decision with valid actor context.
   - Graph resumes or evaluates input: validates tenant, actor RBAC, and candidate identity.
   - Sets `status=APPROVED`, `requires_human_approval=False`, `side_effect_allowed=True`.
   - Commits DB transaction (`approvals` + `audit_logs`) and logs immutable audit trail.
3. **REJECTED**:
   - An authorized human submits an explicit `REJECT` decision.
   - Sets `status=REJECTED`, `requires_human_approval=False`, `side_effect_allowed=False`.
   - Graph terminates safely without invoking any operational execution.
4. **EXPIRED**:
   - If an `expiration_timestamp` was specified and current UTC exceeds the deadline, the request transitions to `EXPIRED`.
   - Any subsequent approval attempts fail closed with `ApprovalExpiredError`.

---

## 4. ApprovalRequest
Strongly typed Pydantic V2 model with `ConfigDict(extra="forbid", validate_assignment=True)`:
- `approval_id`: Optional[str] (generated deterministically if omitted)
- `organization_id`: str (min_length=1, max_length=64)
- `decision_id`: str (min_length=1, max_length=64)
- `decision_reference`: Optional[Dict[str, Any]] (tenant-validated and sanitized)
- `candidate_id`: str (min_length=1, max_length=64)
- `recommendation_id`: Optional[str] (link to existing `recommendations` table)
- `requester_id`: Optional[str] (actor initiating or triggering the decision run)
- `required_role`: str (defaults to `"RiskManager"`)
- `expiration_timestamp`: Optional[datetime] (UTC deadline)
- `evidence_references`: List[str] (upstream lineage references)
- `constraints`: List[Dict[str, Any]] (policy constraints)
- `correlation_id`: Optional[str]
- `trace_id`: Optional[str]

---

## 5. ApprovalDecision
Explicit enum for human governance actions:
- `ApprovalDecision.APPROVE = "APPROVE"`
- `ApprovalDecision.REJECT = "REJECT"`
- `ApprovalDecision.EXPIRE = "EXPIRE"` (system lifecycle state)

*Prohibited*: `AUTO_APPROVE`, `SYSTEM_APPROVE`, `LLM_APPROVE` are strictly forbidden and non-representable.

---

## 6. ApprovalResult
Strongly typed output contract (`ConfigDict(extra="forbid", validate_assignment=True)`):
- `approval_id`: str
- `organization_id`: str
- `decision_id`: str
- `candidate_id`: str
- `recommendation_id`: Optional[str]
- `status`: str (`PENDING`, `APPROVED`, `REJECTED`, `EXPIRED`)
- `actor_id`: Optional[str] (mandatory when `APPROVED` or `REJECTED`)
- `actor_role`: Optional[str]
- `decided_at`: Optional[datetime] (mandatory when `APPROVED` or `REJECTED`)
- `reason`: Optional[str]
- `comments`: Optional[str] (validated business commentary)
- `evidence_references`: List[str]
- `audit_reference`: Optional[str] (reference to `audit_logs.id`)
- `provenance`: Dict[str, Any] (credential-scrubbed lineage)
- `requires_human_approval`: bool
- `side_effect_allowed`: bool (`True` only when `APPROVED`)
- `fingerprint`: Optional[str] (SHA-256 canonical digest)

---

## 7. Actor Identity
Every approval decision requires full human actor attribution:
- `ApprovalActor`:
  - `actor_id`: str
  - `organization_id`: str
  - `role`: str
  - `email`: Optional[str]
  - `correlation_id`: Optional[str]
  - `request_id`: Optional[str]

Anonymous, unauthenticated, or heuristic approvals fail closed immediately.

---

## 8. Authorization
Enforces strict Role-Based Access Control (RBAC):
- Permitted approver roles: `RiskManager`, `Admin`, or an explicit `required_role` matching the actor.
- Unauthorized roles (e.g., `Viewer`, `Analyst`, `Operator`, `Guest`, arbitrary strings) raise `ApprovalAuthorizationError` (non-retryable).
- Forged actor IDs or role escalation attempts fail closed.

---

## 9. Tenant Isolation
Every boundary transition verifies cross-tenant alignment:
$$\text{ExecutionContext.org} == \text{GraphState.org} == \text{ApprovalRequest.org} == \text{Decision.org} == \text{Actor.org}$$
Any tenant mismatch raises `ApprovalTenantIsolationError` immediately. Cross-tenant reads, approvals, queries, or candidate updates fail closed.

---

## 10. Decision Immutability
The Human Approval node is strictly a governance evaluation layer:
- **Never modifies**:
  - Decision scores
  - Candidate rankings or lists
  - Decision rationales
  - Risk assessment factors or scores
  - Prediction forecasts or intervals
  - Scenario simulation inputs or outputs
  - Evidence bundles or citations

---

## 11. Approval Immutability
Once an approval decision is finalized (`APPROVED` or `REJECTED`), it becomes permanently immutable:
- Re-deciding an approval with conflicting decisions (`APPROVE` then `REJECT`) raises `ApprovalAlreadyFinalizedError`.
- Mutating approver identity or decision candidate raises `ApprovalAlreadyFinalizedError`.
- Idempotent replays (identical decision by authorized actor) return the existing finalized record safely.

---

## 12. Explicit Human Event
Approval requires an explicit decision event:
- Viewing a recommendation is NOT approval.
- API GET requests do NOT approve.
- High prediction confidence, zero risk score, or automated rule triggers DO NOT approve.
- The pipeline remains in `PENDING` / `WAITING_FOR_APPROVAL` until an explicit human payload is supplied.

---

## 13. Approval Service
`HumanApprovalService` (`apps/api/app/agents/approval/service.py`) encapsulates all domain logic:
- `create_pending_approval(request, uow)`
- `approve(approval_id, actor, request, comments, uow)`
- `reject(approval_id, actor, request, comments, uow)`
- `get_status(approval_id, organization_id)`
- `record_human_decision(approval_id, decision_input, request, uow)`

All operations are thread-safe, tenant-validated, auditable, and idempotent.

---

## 14. Database Transaction
Reuses existing PostgreSQL tables with zero schema migration:
- Updates `recommendations.status` (`APPROVED` / `REJECTED`) when matching record exists.
- Inserts record into `approvals` table (`recommendation_id`, `decided_by_user_id`, `decision`, `comments`, `decided_at`).
- Inserts audit record into `audit_logs` table via `AuditService.log_event`.
- Mutations execute atomically within `UnitOfWork` transaction boundary. Any failure rolls back completely and raises `ApprovalPersistenceError`.

---

## 15. Idempotency
- Replaying the identical approval action (`APPROVE` approval `X` followed by `APPROVE` approval `X`) returns the existing `ApprovalResult` without creating duplicate database entries or corrupting state.
- Conflicting actions (`APPROVE` followed by `REJECT`) fail closed with `ApprovalAlreadyFinalizedError`.

---

## 16. Audit Trail
Every approval action produces a tamper-evident audit record:
- Resource Type: `"Approval"`
- Action: `AGENT_APPROVAL_APPROVE` or `AGENT_APPROVAL_REJECT`
- Actor Type: `"USER"`
- Stored Fields: `approval_id`, `decision_id`, `candidate_id`, `recommendation_id`, `decision`, `comments`, `fingerprint`
- Context: `correlation_id`, `request_id`, `trace_id`
- All secrets, tokens, API keys, and chain-of-thought are strictly scrubbed prior to persistence.

---

## 17. Expiration
- Supports `expiration_timestamp` in `ApprovalRequest`.
- When evaluated after expiration, status transitions to `EXPIRED`.
- Attempting to approve an expired request raises `ApprovalExpiredError`.

---

## 18. LangGraph Interruption / Resume
Compatible with LangGraph Human-in-the-Loop workflows:
- Pipeline executes from `START` through `DECISION` to `human_approval`.
- Without human input, `human_approval` halts at `AgentLifecycleStatus.WAITING_FOR_APPROVAL` with `selected_route="termination"`.
- When resumed with checkpoint state and `human_approval_decision` input, `human_approval` evaluates and transitions to `APPROVED` or `REJECTED`.

---

## 19. State Ownership
Strict field ownership registered under `AgentStage.APPROVAL`:
- Authoritative Fields:
  - `approval_id`
  - `approval_reference`
  - `approval_result`
  - `approval_status`
  - `requires_human_approval`
  - `side_effect_allowed`
- Nodes in other stages (e.g. `DECISION`, `RISK_ASSESSMENT`) attempting to write approval fields are rejected by `validate_state_update()` with `AgentStateOwnershipViolationError`.
- Approval node cannot mutate upstream stage fields (`decision_result`, `scenario_result`, `prediction_result`, `risk_assessment`, `evidence_bundle`).

---

## 20. Security
- Full credential and token scrubbing via `validate_no_sensitive_values()` on comments, actor identity, and provenance.
- Prohibits passwords, bearer tokens, API keys, private reasoning, and chain-of-thought.
- Enforces strict tenant separation with zero cross-tenant access.

---

## 21. Error Handling
Dedicated, strongly typed exception hierarchy:
- `ApprovalAgentError` (base class)
- `InvalidApprovalRequestError`
- `ApprovalTenantIsolationError`
- `ApprovalAuthorizationError`
- `ApprovalNotFoundError`
- `InvalidApprovalTransitionError`
- `ApprovalAlreadyFinalizedError`
- `ApprovalCandidateMismatchError`
- `ApprovalDecisionRequiredError`
- `ApprovalExpiredError`
- `ApprovalPersistenceError`
- `ApprovalStateOwnershipViolationError`

Security, authorization, and tenant errors are strictly `NON_RETRYABLE`.

---

## 22. Observability
Emits structured `NodeExecutionTelemetry` via `AgentObservability`:
- Metrics: `run_id`, `organization_id`, `actor_id`, `request_id`, `correlation_id`, `trace_id`, `node_name="human_approval"`, `stage=AgentStage.APPROVAL`, `duration_ms`, `status` (`SUCCESS` / `FAILED`), `error_code`, `step_count`, `metadata` (`approval_id`, `candidate_id`).
- Emitted reliably inside `finally` blocks with credentials sanitized.

---

## 23. Action Boundary
Even upon successful `APPROVE`:
- Step 9 **NEVER** executes operational actions.
- `side_effect_allowed=True` signals readiness for a future Action Agent, but Step 9 terminates safely without mutation.
- No shipment rerouting, no inventory updates, no supplier/carrier communication.

---

## 24. Rejection Behavior
Upon explicit human `REJECT`:
- `status=REJECTED`
- `side_effect_allowed=False`
- `selected_route="termination"`
- Execution terminates cleanly. The system does not automatically retry or substitute alternative candidates.

---

## 25. Database Impact
- **Tables Created**: 0 (zero schema drift).
- **Existing Tables Reused**: `approvals`, `audit_logs`, `recommendations`, `users`, `organizations`.
- **Total Tables in Base.metadata.tables**: Exactly 34.

---

## 26. OpenAPI Impact
- **Paths**: Exactly 60 (zero change).
- **Operations**: Exactly 96 (zero change).
- **Schemas**: Exactly 104 (zero change).

---

## 27. Tests
A comprehensive test suite in `apps/api/tests/test_phase9_approval_agent.py` contains 133 focused tests:
- Contracts Validation: 15 tests
- Lifecycle Transitions: 12 tests
- Mandatory No Auto-Approval: 8 tests
- Actor & RBAC Authority: 10 tests
- Multi-Tenant Boundary Isolation: 8 tests
- Decision Immutability: 9 tests
- Finalized Approval Immutability: 5 tests
- Explicit Approval Event: 4 tests
- Security Scrubbing: 8 tests
- Observability & Telemetry: 8 tests
- Deterministic Identity: 6 tests
- Graph Topology: 8 tests
- Graph Resume Flow: 6 tests
- Explicit No-Side-Effect Safety: 5 tests
- Error Taxonomy: 5 tests
- Database Transactional Persistence: 7 tests
- Additional Edge Cases: 9 tests
- **Result**: 133 / 133 PASSED (100%).

---

## 28. Non-Goals
The following are strictly out of scope for Phase 9 Step 9:
- Action Agent operational execution
- Carrier and supplier communication
- Shipment rerouting or inventory alteration
- Verification Agent execution
- LLM or automated approval heuristics
- Multi-approver quorum workflows

---

## 29. Future Action Agent Boundary
The Human Approval boundary serves as the authoritative gateway to the upcoming Phase 9 Step 10 Action Agent. Only runs that exit `human_approval` with `status="APPROVED"` and `side_effect_allowed=True` are eligible for operational dispatch.
