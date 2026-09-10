# Phase 9 — Step 8: Decision Flow Integration

## 1. Objective
Establish the strongly-typed Decision orchestration boundary following the Scenario Agent in the LangGraph pipeline:
```
START → INITIALIZATION → RESEARCH → RISK_ASSESSMENT → PREDICTION → SCENARIO → DECISION → TERMINATION → END
```
The Decision Agent transforms validated upstream Scenario, Risk, and Prediction context into a deterministic, structured, auditable **Decision Candidate** (`DecisionResult`). It defines an uncrossable architectural boundary before Human Approval and Operational Action.

---

## 2. Decision Agent Role
The Decision Agent operates as an orchestration boundary that:
1. Consumes authoritative upstream state from `AgentGraphState`.
2. Validates decision inputs and enforces multi-tenant boundary isolation.
3. Evaluates deterministic, versioned decision rules without external solvers or LLM heuristics.
4. Identifies candidate operational responses without executing them.
5. Preserves end-to-end evidence references, upstream IDs, and audit provenance.
6. Produces a structured `DecisionResult` with transparent, auditable rationales.
7. Exposes operational limitations and missing upstream dependencies.
8. Enforces strict state ownership (writing only Decision-owned fields).
9. Halts autonomous execution prior to the Human Approval Gate (`status=REQUIRES_APPROVAL`, `requires_human_approval=True`).
10. Remains strictly read-only (`SideEffectType.READ_ONLY`).

---

## 3. Risk / Prediction / Scenario / Decision Distinction
To preserve architectural integrity, RiskWise 2.0 maintains strict conceptual separation across stages:

| Stage | Core Question | Primary Output | Boundary Constraint |
|---|---|---|---|
| **Risk** | *How risky is the situation?* | `RiskAssessment` (score, level, factors) | Does not forecast outcomes or suggest responses. |
| **Prediction** | *What is expected to happen?* | `PredictionResult` (predicted delay, confidence) | Does not evaluate alternative scenarios or suggest actions. |
| **Scenario** | *What could happen under defined conditions?* | `ScenarioResult` (simulated parameters, delta) | Does not decide which candidate response is preferable. |
| **Decision** | *Which candidate response is preferable under evidence?* | `DecisionResult` (candidates, ranking, rationales) | **Does not execute actions; does not approve candidates.** |
| **Approval (Future)** | *Has an authorized human approved the candidate?* | `ApprovalRecord` (approved/rejected, audit log) | Human-in-the-loop governance gate. |
| **Action (Future)** | *Execute the approved operational response.* | `ActionExecution` (mutation, carrier dispatch) | Operational mutation execution. |
| **Verification (Future)** | *Did the executed action achieve intended outcome?* | `VerificationResult` (variance, metrics) | Closed-loop outcome validation. |

**Invariants**:
- Decision $\neq$ Approval
- Decision $\neq$ Action
- Decision $\neq$ Optimization
- Decision $\neq$ Simulation

---

## 4. DecisionRequest
The `DecisionRequest` model is a strongly-typed Pydantic V2 contract (`extra="forbid"`) encapsulating input references:
- `decision_id`: Optional caller override or auto-generated deterministic UUIDv5.
- `organization_id`: Required tenant identifier for isolation verification.
- `decision_type`: Enum `DecisionType` (e.g. `OPERATIONAL_REVIEW`, `REROUTE_EVALUATION`, `INVENTORY_BUFFERING`, `SUPPLIER_CONTINGENCY`, `EXPEDITE_TRANSIT`).
- `target_reference`: Target shipment, route, facility, or scenario reference.
- Upstream references: `scenario_id`, `scenario_reference`, `scenario_result`, `scenario_definition`, `risk_assessment_id`, `risk_assessment_reference`, `prediction_id`, `prediction_reference`, `prediction_result`.
- `recommendation_references`: List of Phase 7 recommendation references.
- `evidence_references`: Preserved evidence IDs from all upstream nodes.
- `constraints`: List of explicit `DecisionConstraint` models.
- Contextual tracking: `correlation_id`, `trace_id`.

Arbitrary decision payloads or bypass flags are strictly forbidden.

---

## 5. DecisionCandidate
A structured, non-executed response candidate:
- `candidate_id`: Deterministic UUIDv5 based on `(decision_id, action_type, ordinal)`.
- `action_type`: Descriptive response category (e.g. `ESCALATE_FOR_HUMAN_REVIEW`, `PREPARE_ALTERNATIVE_ROUTING`, `INVESTIGATE_DELAY_FACTORS`, `MONITOR_CONDITIONS`).
- `title`: Human-readable summary.
- `description`: Detailed action description based on validated evidence.
- `priority`: Priority classification (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`).
- `status`: Candidate status (`PROPOSED`, `ACCEPTED_FOR_REVIEW`, `DEFERRED`, `REJECTED`).
- `requires_human_approval`: Strictly `True` for operational review candidates.
- `parameters`: Key-value parameters passed to downstream approval/action.
- `prerequisites`: Required conditions prior to action execution.
- `constraints`: Explicit operational/authority boundaries.
- `expected_effect`: Expected outcome context derived from scenario/prediction.
- `evidence_references`: Evidence IDs supporting this specific candidate.
- `provenance`: Audit trail linking to rule ID, node, and timestamp.

A candidate is **never** an executed action.

---

## 6. DecisionResult
The primary output contract emitted by the Decision Agent:
- `decision_id`: Deterministic UUIDv5 identifier.
- `organization_id`: Tenant ID.
- `decision_type`: `DecisionType`.
- `status`: `DecisionStatus` (`READY`, `REQUIRES_APPROVAL`, `INSUFFICIENT_EVIDENCE`, `BLOCKED`, `INVALID`).
- `candidates`: List of ranked `DecisionCandidate` objects.
- `preferred_candidate`: Highest-ranked candidate selected by deterministic rules.
- `rationales`: List of `DecisionRationale` explaining the evaluation.
- `constraints`: Preserved and evaluated `DecisionConstraint` items.
- `requires_human_approval`: Set to `True` whenever candidates require human sign-off.
- `upstream_references`: Traceability dictionary to Scenario, Risk, and Prediction IDs.
- `evidence_references`: Unified list of evidence IDs.
- `limitations`: List of `AgentLimitation` records.
- `provenance`: Execution metadata (node, rule version, timestamp).
- `fingerprint`: Deterministic SHA-256 canonical hash.
- `rule_version`: `DecisionRuleEngine` version string (`v1.0.0-deterministic`).

---

## 7. Decision Rationale
Every candidate evaluation produces structured, auditable `DecisionRationale` records:
- `basis_type`: Enum `DecisionBasis` (`RISK_ASSESSMENT`, `PREDICTION`, `SCENARIO`, `RECOMMENDATION`, `CONSTRAINT`, `EVIDENCE`).
- `source_reference`: Identifier of the upstream source entity.
- `rule_id`: Identifier of the deterministic rule evaluated.
- `finding_ids`: Structured finding IDs justifying the selection.
- `evidence_references`: Supporting evidence identifiers.
- `explanation_code`: Machine-readable explanation code (e.g. `CRITICAL_DELAY_ESCALATION`, `HIGH_DELAY_ALTERNATIVE_PREPARATION`, `MODERATE_DELAY_INVESTIGATION`, `LOW_RISK_CONTINUED_MONITORING`).
- `provenance`: Execution timestamp and validator metadata.

LLM-generated natural language reasoning, hidden fields, and chain-of-thought payloads are prohibited.

---

## 8. Deterministic Decision Rules
Rule evaluation is executed by `DecisionRuleEngine` (version `v1.0.0-deterministic`). The engine uses explicit, hardcoded, deterministic rules:
1. `rule_critical_delay_escalate`:
   - **Condition**: Scenario simulated delay $\ge 720$ min (12h) OR Risk Level is `CRITICAL`.
   - **Candidate**: `ESCALATE_FOR_HUMAN_REVIEW` (Priority: `CRITICAL`).
2. `rule_high_delay_prepare_alternative`:
   - **Condition**: Scenario simulated delay between $240$ min (4h) and $720$ min OR Risk Level is `HIGH`.
   - **Candidate**: `PREPARE_ALTERNATIVE_ROUTING` (Priority: `HIGH`).
3. `rule_moderate_delay_investigate`:
   - **Condition**: Scenario simulated delay between $60$ min (1h) and $240$ min OR Risk Level is `MEDIUM`.
   - **Candidate**: `INVESTIGATE_DELAY_FACTORS` (Priority: `MEDIUM`).
4. `rule_low_risk_monitor`:
   - **Condition**: Scenario simulated delay $< 60$ min AND Risk Level is `LOW` or `MINIMAL`.
   - **Candidate**: `MONITOR_CONDITIONS` (Priority: `LOW`).
5. `rule_phase7_recommendation`:
   - **Condition**: Authoritative Phase 7 recommendations present in upstream state.
   - **Candidate**: Formulates candidate referencing the recommendation ID, action type, and required approval flags.

No `eval()`, `exec()`, or runtime dynamic expressions are used.

---

## 9. Candidate Selection & Ranking
Candidates are deterministically ordered using ordinal priority ranking:
$$\text{Priority Rank: } \text{CRITICAL (4)} > \text{HIGH (3)} > \text{MEDIUM (2)} > \text{LOW (1)} > \text{INFO (0)}$$
Ties are broken deterministically by alphabetical order of `action_type` followed by `candidate_id`. The candidate with the highest rank is assigned as `preferred_candidate`.

Terminology strictly uses:
- *Candidate*
- *Preferred Candidate*
- *Deterministic Recommendation*
- *Rule-Ranked Candidate*

The words *optimal*, *globally optimal*, or *mathematically optimal* are forbidden.

---

## 10. Scenario Integration
`ScenarioResult` is the primary upstream operational input:
- Validates `scenario.organization_id == decision.organization_id`.
- Extracts scenario type, parameters, constraints, fingerprint, and evidence references.
- Extracts simulated impact metrics (e.g. `simulated_delay_minutes`, `cost_impact_usd`).
- Preserves the scenario reference immutably in `upstream_references["scenario_id"]` and `upstream_references["scenario_fingerprint"]`.
- Never mutates the upstream scenario.

---

## 11. Prediction Integration
`PredictionResult` provides quantitative forecast context:
- Validates `prediction.organization_id == decision.organization_id`.
- Extracts `prediction_id`, `predicted_value`, target, model metadata, and evidence references.
- Preserves prediction uncertainty and status.
- If prediction is unavailable (`status=NOT_AVAILABLE` or `None`), formulates candidates based on scenario and risk, emitting an `AgentLimitation` (`LimitationCategory.PREDICTION_MODEL_UNAVAILABLE`).
- Never invents or converts prediction confidence into decision probabilities.

---

## 12. Risk Integration
`RiskAssessment` remains the authoritative risk evaluation:
- Consumes `risk_level`, `risk_score`, and evidence references.
- Validates `risk.organization_id == decision.organization_id`.
- Does NOT recalculate risk scores, alter factor weights, or modify risk findings.
- Does NOT convert risk scores into probabilities.

---

## 13. Recommendation Integration
Integrates with Phase 7 recommendation infrastructure:
- Inspects upstream `recommendation_references` or `recommendations`.
- Preserves original `recommendation_id`, description, and approval requirements.
- Never auto-approves or executes recommendations.

---

## 14. Constraints
Decision candidates must respect validated operational and authority constraints:
- `HUMAN_APPROVAL_AUTHORITY`: Mandates that operational review candidates require human sign-off.
- `EVIDENCE_SUFFICIENCY`: Verifies that required upstream references exist.
- Scenario constraints: Ingests and preserves constraints defined in `ScenarioDefinition`.
- Authority constraints: Prevents autonomous operational actions.

---

## 15. State Ownership
`AgentGraphState` enforces strict authoritative field ownership:
- Stage `AgentStage.DECISION` owns:
  - `decision_id`
  - `decision_reference`
  - `decision_result`
- Validated via `validate_state_update()` and `apply_state_update()`.
- The Decision Agent **cannot** write to:
  - Research fields (`evidence_bundle`, `rag_context`)
  - Risk fields (`risk_assessment_id`, `risk_score`)
  - Prediction fields (`prediction_id`, `predicted_value`)
  - Scenario fields (`scenario_id`, `scenario_result`)
  - Approval fields (`approval_id`, `requires_human_approval` at top-level state)
  - Action fields (`actions`, `action_executions`)
  - Verification fields (`verification_results`)
  - Identity fields (`session_id`, `organization_id`, `actor_id`)

---

## 16. Tenant Isolation
Strict tenant isolation is validated across all upstream entities:
$$\text{ExecutionContext.organization\_id} == \text{GraphState.organization\_id} == \text{DecisionRequest.organization\_id} == \text{Scenario.organization\_id} == \text{Prediction.organization\_id} == \text{Risk.organization\_id}$$
Any tenant mismatch immediately raises `DecisionTenantIsolationError` and fails closed.

---

## 17. Security
The Decision Agent enforces enterprise security protocols:
- `validate_no_credentials()` checks all candidate parameters, descriptions, and provenance metadata.
- Rejects patterns matching `api_key`, `bearer`, `private_key`, `token`, `password`, `secret`, `credentials`.
- Strips and rejects chain-of-thought or internal reasoning leakage.
- Sanitizes all log outputs and telemetry events.

---

## 18. Deterministic Identity & Fingerprinting
- **Decision ID**: Generated via UUIDv5 using namespace `UUID("a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d")` and canonical seed string:
  $$\text{seed} = \text{org\_id} \mid \text{scenario\_id} \mid \text{risk\_id} \mid \text{prediction\_id} \mid \text{rule\_version}$$
  No volatile timestamps or request IDs are included.
- **Fingerprint**: Canonical SHA-256 digest over normalized JSON payload:
  $$\text{fingerprint} = \text{SHA-256}(\text{org\_id}, \text{scenario\_id}, \text{target\_ref}, \text{candidates}, \text{constraints}, \text{evidence\_refs}, \text{rule\_version})$$
  Identical inputs always generate identical fingerprints.

---

## 19. Error Handling Taxonomy
Typed error hierarchy rooted in `DecisionAgentError`:
- `InvalidDecisionRequestError`: Malformed or missing mandatory request fields (non-retryable).
- `DecisionTenantIsolationError`: Cross-tenant boundary violation (non-retryable).
- `MissingScenarioError`: Mandatory upstream scenario missing (non-retryable).
- `InvalidScenarioReferenceError`: Scenario reference malformed or unverifiable (non-retryable).
- `InvalidDecisionCandidateError`: Candidate model validation failure (non-retryable).
- `InsufficientEvidenceError`: Evidence prerequisites unfulfilled (non-retryable).
- `UnsupportedDecisionTypeError`: Unknown decision type requested (non-retryable).
- `DecisionGenerationError`: Internal rule evaluation failure.
- `DecisionAuthorizationError`: Authority boundary violation.

All deterministic errors are classified as `RetryabilityCategory.NON_RETRYABLE`.

---

## 20. Observability & Telemetry
In `decision_node`, execution telemetry is emitted in a `finally` block via `AgentObservability.emit_node_telemetry`:
- `node_name`: `"decision_agent"`
- `stage`: `AgentStage.DECISION`
- `status`: `"SUCCESS"` or `"FAILED"`
- `duration_ms`: Execution duration in milliseconds
- `metadata`: Contains `decision_id`, `candidate_count`, `rule_version`, `status`, and sanitized parameters.
- Redaction: Sensitive keys are scrubbed before emission.

---

## 21. LangGraph Integration & Node Registration
Registered node in `apps/api/app/agents/node_contracts.py` and `apps/api/app/agents/nodes.py`:
- `node_id`: `"decision_agent"`
- `stage`: `AgentStage.DECISION`
- `side_effect_type`: `SideEffectType.READ_ONLY`
- `requires_evidence`: `True`
- `timeout_ms`: `10000`
- `max_retries`: `0`
- Contract: `DECISION_NODE_CONTRACT`

Allowed transitions:
- Upstream: `SCENARIO → DECISION`
- Downstream: `DECISION → APPROVAL_GATE` (route: `"approval_boundary"`) or `DECISION → TERMINATION` (route: `"termination"`).
- Backward transitions (e.g. `DECISION → SCENARIO`, `DECISION → RESEARCH`) are strictly illegal.

---

## 22. Human Approval Boundary
The Decision Agent stops immediately before human approval:
- Decision candidates that specify operational changes set `requires_human_approval = True`.
- `result.status` is set to `DecisionStatus.REQUIRES_APPROVAL`.
- `update_payload["selected_route"] = "approval_boundary"`.
- The Decision Agent never creates an `ApprovalRecord`, never marks approval as approved, and never bypasses approval gates.

---

## 23. Action Boundary
The Decision Agent has zero operational side effects:
- No carrier API dispatch.
- No shipment route mutation.
- No warehouse inventory reallocation.
- No supplier contract modification.
- No notification or alerting command dispatch.
- Purely read-only evaluation.

---

## 24. Database Impact
- **Tables**: Strictly **34 tables** (no new tables created).
- **Existing Tables**: `recommendations`, `approvals`, `actions`, `optimization_runs`, `scenarios`, `risk_assessments` remain completely unchanged.
- Output persistence remains in `AgentGraphState`.

---

## 25. OpenAPI Impact
- **Paths**: Strictly **60 paths**.
- **Operations**: Strictly **96 operations**.
- **Schemas**: Strictly **104 schemas**.
- No public API endpoints were added or modified.

---

## 26. Tests
A dedicated test suite `apps/api/tests/test_phase9_decision_agent.py` contains **151 unit and integration tests** covering:
- Contracts and Pydantic validation (Group 1)
- Candidates formulation and parameters (Group 2)
- Structured rationales and auditability (Group 3)
- Risk assessment integration and immutability (Group 4)
- Prediction result integration (Group 5)
- Scenario result integration (Group 6)
- Recommendation integration (Group 7)
- Deterministic rules and priority ranking (Group 8)
- State ownership and unauthorized field rejection (Group 9)
- Tenant boundary isolation and cross-tenant rejection (Group 10)
- Security sanitization and credential rejection (Group 11)
- Human approval boundary preservation (Group 12)
- Read-only contract and zero operational side-effects (Group 13)
- Observability and telemetry emission (Group 14)
- Deterministic identity and fingerprinting (Group 15)
- Graph topology and edge transition rules (Group 16)
- Error taxonomy and retryability (Group 17)
- Deterministic end-to-end pipeline fixture (Group 18)
- Explicit no-side-effect safety (Group 19)

---

## 27. Non-Goals
The following were explicitly excluded from Phase 9 Step 8:
- Human approval execution or approval record creation.
- Operational action execution or mutation commands.
- OR-Tools, mathematical optimization solvers, or linear programming.
- Simulation or digital twin execution.
- LLM decision generation or Claude/Bedrock prompts.
- Public Decision REST API endpoints.
- Database migrations or schema alterations.

---

## 28. Future Optimization Boundary
When Phase 10 introduces mathematical optimization:
- Optimization will ingest `DecisionCandidate` options and `DecisionConstraint` models as candidate targets.
- Mathematical programming (e.g. MIP/LP via OR-Tools) will determine optimal network flows or vehicle routings.
- The Decision Agent will continue to serve as the evidence-grounded candidate formulation boundary preceding optimization.
