# Phase 9 Step 1 — LangGraph Agent Graph Architecture & Contracts

## 1. Phase 9 Step 1 Objective

The objective of **Phase 9 Step 1** is to establish the foundational architecture, execution lifecycle, and strongly typed contracts for the LangGraph multi-agent orchestration subsystem in RiskWise 2.0. 

This step serves as the secure, deterministic, and tenant-isolated scaffolding for future agent nodes (Research, Risk, Prediction, Scenario, Decision, Verification), while strictly avoiding the implementation of premature business logic, probabilistic LLM text generation, or autonomous external actions.

---

## 2. LangGraph Version

- **Exact Version Installed**: `langgraph==1.2.11`
- **Core Companion Dependencies**:
  - `langchain-core==1.6.2`
  - `langgraph-checkpoint==4.2.0`
  - `langgraph-prebuilt==1.1.0`
  - `langgraph-sdk==0.4.4`
- **Python Compatibility**: Python `3.13.14` and Pydantic `2.13.5` (fully verified without version conflicts).

---

## 3. Dependency Changes

- Added `langgraph>=1.2.0` to `apps/api/requirements.txt` under a dedicated `# Phase 9: LangGraph Agent Graph Architecture & Orchestration` comment.
- Zero unrelated AI packages added. No OpenAI, Anthropic, or Bedrock dependencies introduced.

---

## 4. Graph Architecture

The graph architecture follows a deterministic flow from `START` to `END`:

```
                 START (__start__)
                         │
                         ▼
             [ initialization_node ]
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
[ placeholder_node ]  [ approval_boundary ]  │
        │                │                │
        └────────────────┼────────────────┘
                         ▼
             [  termination_node  ]
                         │
                         ▼
                  END (__end__)
```

- **Graph Builder**: `AgentGraphBuilder` initializes a `StateGraph(state_schema=AgentGraphStateDict)`.
- **Node Linking**: `START` unconditionally routes to `initialization`.
- **Conditional Routing**: Conditional routing edge routes dynamically to allowlisted nodes or `termination`.
- **Exit Edge**: `termination` unconditionally connects to `END`.

---

## 5. State Contract

The state contract is defined in `apps/api/app/agents/contracts.py`:

- **`AgentGraphState` (Pydantic Model)**:
  - **Operational Identity**: `run_id`, `organization_id`, `actor_id`, `request_id`, `correlation_id`, `trace_id`.
  - **Lifecycle**: `current_stage` (`AgentStage`), `status` (`AgentLifecycleStatus`), `objective` (str), `input_references` (dict).
  - **Subsystem Reference Bindings**: `evidence_bundle` (`Optional[RAGEvidenceReference]`), `risk_assessment` (`Optional[RiskAssessmentReference]`).
  - **Structured Findings & Routing**: `findings` (dict), `selected_route` (Optional[str]), `requires_human_approval` (bool), `termination_reason` (Optional[str]).
  - **Reliability & Telemetry**: `step_count` (int), `retry_count` (int), `errors` (list of dicts), `warnings` (list of str), `started_at`, `completed_at`, `metadata` (dict).
- **`AgentGraphStateDict` (TypedDict)**:
  - Mirror schema providing native compatibility with LangGraph's internal graph runtime and reducers.
- **Strict Prohibition of Chain-of-Thought & Secrets**:
  - Validated by `validate_no_forbidden_keys`.
  - Explicitly rejects keys matching `chain_of_thought`, `private_reasoning`, `hidden_reasoning`, `internal_monologue`, `password`, `secret`, `token`, `api_key`, `credentials`, `authorization`.

---

## 6. Execution Context

Defined as `AgentExecutionContext`:
- Encapsulates execution invariants: `organization_id`, `actor_id`, `request_id`, `correlation_id`, `trace_id`, `role`, `feature_flags`, `max_steps` (default: 25), `max_retries` (default: 3), `timeout_seconds` (default: 120.0).
- **Tenant Immutability**: Configured with `frozen=True` and `extra="forbid"`. Nodes cannot alter the tenant identity of the execution context.

---

## 7. Node Contract

Defined as `NodeContract`:
- `node_id`: Unique identifier (e.g., `"initialization"`, `"termination"`).
- `name`: Human-readable title.
- `description`: Architectural responsibility.
- `stage`: Associated `AgentStage`.
- `is_side_effecting`: Boolean flag distinguishing read-only operations from side effects.
- `input_keys`: Expected state fields.
- `output_keys`: Modified state fields.

---

## 8. Node Registry

Defined as `NodeRegistry` in `apps/api/app/agents/registry.py`:
- **Explicit Allowlist**: Only node IDs registered in `PERMISSIBLE_NODE_IDS` (`initialization`, `termination`, `approval_boundary`, `research_placeholder`, `risk_placeholder`, `prediction_placeholder`, `scenario_placeholder`, `decision_placeholder`, `action_placeholder`, `verification_placeholder`) can be registered.
- **Duplicate Prevention**: Rejects duplicate registrations with `AgentValidationError`.
- **Arbitrary Code Execution Shield**: Rejects non-allowlisted node names with `AgentUnauthorizedNodeError` and requires handlers to be callable functions.

---

## 9. Routing Contract

Defined as `RouteEvaluator` in `apps/api/app/agents/routing.py`:
- Returns structured `RouteDecision` containing `next_node`, `reason_code`, `confidence`, `evidence_references`, and `termination_flag`.
- **Fail-Closed Rule**: If an unauthorized, unknown, or unregistered node is selected in `selected_route`, an `AgentInvalidRouteError` is raised immediately.
- **Circuit Breaker**: Automatically routes to `termination` if `step_count >= max_steps`, if unhandled errors exist, or if `requires_human_approval` is active.

---

## 10. Termination Contract

Explicit lifecycle states defined in `AgentLifecycleStatus`:
- `COMPLETED`: Run finished successfully.
- `FAILED`: Terminated due to unrecoverable or unhandled error.
- `BLOCKED`: Terminated by security, tenancy, or regulatory policy.
- `WAITING_FOR_APPROVAL`: Paused at approval boundary pending human review.
- `NO_ACTION_REQUIRED`: Evaluation indicated no operational action is necessary.
- `MAX_STEPS_REACHED`: Terminated by the step-limit circuit breaker to prevent infinite loops.

---

## 11. Error / Recovery Contract

Defined in `apps/api/app/agents/errors.py`:
- **Classification**: `ErrorClassification.RETRYABLE` vs `ErrorClassification.NON_RETRYABLE`.
- **Security & Tenancy Fail-Closed**:
  - `AgentTenantIsolationError`: NON_RETRYABLE.
  - `AgentValidationError`: NON_RETRYABLE.
  - `AgentUnauthorizedNodeError`: NON_RETRYABLE.
  - `AgentInvalidRouteError`: NON_RETRYABLE.
  - `AgentEvidenceIntegrityError`: NON_RETRYABLE.
  - `AgentApprovalBoundaryViolationError`: NON_RETRYABLE.
- **Transient Failures**:
  - `AgentTimeoutError`: RETRYABLE.
  - `AgentDependencyFailureError`: Selectable via `retryable` parameter.

---

## 12. RAG Evidence Boundary

- Future agents must strictly consume Phase 8 `RAGEvidenceBundle` packages.
- Bound in state via `RAGEvidenceReference`:
  - `bundle_id`, `organization_id`, `bundle_fingerprint`, `total_evidence_units`, `grounding_status`.
- **Prohibitions**: Direct consumption of raw provider payloads, arbitrary document dictionaries, raw database rows, or ungrounded chunk text is rejected.

---

## 13. Risk Engine Boundary

- Phase 7 Risk Engine remains authoritative for all deterministic risk scoring, risk factors, levels, and recommendation evaluations.
- Bound in state via `RiskAssessmentReference`:
  - `assessment_id`, `organization_id`, `assessment_fingerprint`, `risk_score`, `risk_level`, `factor_count`.
- LangGraph does not calculate, overwrite, or replace deterministic risk calculations.

---

## 14. Tool Boundary

Defined as `ToolDefinition` in `apps/api/app/agents/contracts.py`:
- `tool_name`, `description`, `input_schema`, `output_schema`, `side_effect_type` (`READ_ONLY` vs `SIDE_EFFECTING`), `allowed_stages`, `tenant_scoped`, `requires_audit`.
- Arbitrary user-supplied tool names or execution of arbitrary code are prohibited.

---

## 15. Human Approval Boundary

- State flag: `requires_human_approval: bool = True`.
- Architectural node: `approval_boundary_node` halts execution, transitions status to `WAITING_FOR_APPROVAL`, and prevents side-effecting operations from running autonomously.
- Model invariant validator raises `AgentApprovalBoundaryViolationError` if any run with `requires_human_approval=True` attempts to finalize as `COMPLETED`.

---

## 16. Tenant Isolation

- Enforced by `validate_tenant_isolation` in `apps/api/app/agents/security.py`.
- Invariant:
  $$\text{Authenticated Org} == \text{Context Org} == \text{State Org} == \text{Evidence Bundle Org} == \text{Risk Assessment Org}$$
- Any mismatch raises `AgentTenantIsolationError` and fails closed immediately.

---

## 17. Observability

- Centralized in `AgentObservability` (`apps/api/app/agents/observability.py`).
- Emits structured telemetry records (`NodeExecutionTelemetry`): `run_id`, `organization_id`, `actor_id`, `request_id`, `correlation_id`, `trace_id`, `node_name`, `duration_ms`, `status`, `error_code`, `step_count`.
- Automatic recursive credential and secret scrubbing on all logged payloads.
- Strictly never logs chain-of-thought, internal monologues, or authorization headers.

---

## 18. Checkpointing Decision

- Evaluated LangGraph 1.2.11 checkpointing architecture.
- For Step 1, pure execution contracts use `MemorySaver` in-memory checkpointing.
- **Database Schema Decision**: No new agent database tables created. The existing `agent_runs`, `agent_tasks`, and `agent_tool_calls` tables (from the 34 platform tables) will serve as the persistence sink in later phases, maintaining zero schema drift.

---

## 19. Database Impact

- **PostgreSQL Tables**: Exactly 34 tables.
- **Migrations Added**: 0.
- **Schema Drift**: 0.

---

## 20. API Impact

- **Public API Endpoints Added**: 0.
- **OpenAPI Surface**: Preserved at 60 paths / 96 operations / 104 schemas.

---

## 21. Testing

- Dedicated Step 1 test suite: `apps/api/tests/test_phase9_langgraph_architecture_contracts.py`.
- **Total Tests**: 64 focused unit tests (exceeding the 50+ target).
- **Coverage**: Groups A through L fully covered (State contracts, Execution context, Node registry, Graph construction, Routing, Termination, Errors, Evidence boundary, Tool boundary, Approval boundary, Observability, Architectural constraints).
- **Pass Rate**: 100% (64 / 64 passed in 0.90s).

---

## 22. Security

- Untrusted input screening: heuristic prompt injection scanning using `PROMPT_INJECTION_PATTERNS`.
- Credential scrubbing: recursive redaction using `SENSITIVE_KEY_PATTERN`.
- Fail-closed security architecture for routing, node execution, and tenancy.

---

## 23. Explicit Non-Goals & Phase Boundaries

The following capabilities were **strictly omitted** in accordance with Step 1 boundaries:
- ❌ No Research Agent business logic
- ❌ No Risk Agent business logic
- ❌ No Prediction Agent
- ❌ No Scenario Agent
- ❌ No Decision Agent
- ❌ No Action Agent
- ❌ No Verification Agent
- ❌ No Claude / Bedrock / OpenAI LLM generation calls
- ❌ No autonomous tool execution
- ❌ No carrier communication or shipment rerouting
- ❌ No inventory mutation
- ❌ No OR-Tools optimization
- ❌ No Digital Twin simulation
