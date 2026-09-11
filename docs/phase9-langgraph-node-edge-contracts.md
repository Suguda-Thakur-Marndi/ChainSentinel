# Phase 9 Step 3: LangGraph Node & Edge Contracts

## 1. Objective
Phase 9 Step 3 establishes the strongly typed contracts and governance boundaries governing LangGraph nodes and edges in RiskWise 2.0. The architecture makes it structurally impossible for future agents to arbitrarily mutate state, traverse unregistered paths, perform unauthorized actions, or bypass human governance gates. Every transition is explicit, validated, tenant-safe, stage-aware, observable, and bounded.

## 2. Node Contract
LangGraph nodes in RiskWise are governed by `AgentNodeContract` (aliased to `NodeContract` from Step 1). Every node must be formally instantiated as an immutable contract declaring its identity, stage, description, input requirements, output fields, allowed state mutations, evidence criteria, authorization constraints, side-effect classifications, and execution bounds (timeouts and retries).

```python
class AgentNodeContract(BaseModel):
    node_id: str
    name: str
    description: str
    stage: AgentStage
    is_terminal: bool = False
    required_inputs: List[str] = Field(default_factory=list)
    output_fields: List[str] = Field(default_factory=list)
    allowed_state_fields: List[str] = Field(default_factory=list)
    requires_evidence: bool = False
    minimum_evidence: int = 0
    required_evidence_types: List[str] = Field(default_factory=list)
    required_references: List[str] = Field(default_factory=list)
    required_roles: List[str] = Field(default_factory=list)
    required_permissions: List[str] = Field(default_factory=list)
    side_effect_type: ToolSideEffectType = ToolSideEffectType.READ_ONLY
    is_side_effecting: bool = False
    retryable: bool = True
    max_retries: int = 3
    timeout_seconds: float = 60.0
```

## 3. Node Metadata
Nodes declare explicit metadata that informs runtime execution wrappers, graph validators, and observability pipelines:
- `node_id`: Unique, deterministic, kebab_case/snake_case allowlisted identifier.
- `stage`: Architectural stage within the multi-agent orchestration pipeline.
- `side_effect_type` & `is_side_effecting`: Strict demarcation between non-destructive analysis and state-mutating actions.
- `retryable` & `max_retries`: Explicit retry parameters for transient execution errors.
- `timeout_seconds`: Bound on node execution duration to prevent infinite hangs.
- `is_terminal`: Declares whether the node directly finalizes graph execution.

## 4. Node Ownership
Every node declares which state fields it is authorized to mutate via `allowed_state_fields` and `output_fields`. The state update engine (`validate_state_update` and `apply_state_update` from Step 2) strictly prevents unauthorized field overwrites by verifying the writer's stage against `AUTHORITATIVE_FIELD_OWNERS`. State update attempts for fields outside the node's authoritative domain raise `AgentStateOwnershipViolationError`.

## 5. Input Requirements
A node declares prerequisite state keys via `required_inputs` and `required_references`. The execution wrapper (`NodeExecutionWrapper`) checks the presence and non-emptiness of required fields before invoking the node handler. Missing requirements raise `AgentMissingInputError` without executing any node logic.

## 6. Output Requirements
Output updates produced by a node handler are validated through Step 2's `apply_state_update`:
1. The update dictionary is scanned for prohibited keys (e.g. passwords, bearer tokens, API keys, and chain-of-thought).
2. Identity fields (`run_id`, `actor_id`, `request_id`, etc.) are verified immutable.
3. Authoritative field ownership rules are strictly enforced.
4. Total serialized payload size is bounded to 500 KB to prevent unbounded state bloat.

## 7. Edge Contract
Graph edges are defined by `AgentEdgeContract`:
```python
class AgentEdgeContract(BaseModel):
    edge_id: str
    from_node: str
    to_node: str
    edge_type: EdgeType = EdgeType.NORMAL
    reason_code: Union[RoutingReasonCode, str] = RoutingReasonCode.INITIAL_ROUTE
    condition_code: Optional[ConditionCode] = None
    required_roles: List[str] = Field(default_factory=list)
    required_permissions: List[str] = Field(default_factory=list)
    is_terminal: bool = False
    description: Optional[str] = None
```

## 8. Edge Types
Edges are classified into 6 strongly typed variants (`EdgeType`):
- `NORMAL`: Deterministic direct edge between sequential stages.
- `CONDITIONAL`: Dynamic branch evaluated by `ConditionEvaluator` based on explicit `ConditionCode`.
- `RETRY`: Explicit self-loop or recovery transition bounded by `max_retries`.
- `FAILURE`: Explicit transition to error handling or termination on unrecoverable error.
- `TERMINATION`: Final transition from a terminal node to `END`.
- `APPROVAL_GATE`: Human governance gate blocking entry into side-effecting operations.

## 9. Transition Validation
The graph enforces strict topological order via `StageTransitionValidator` using `ALLOWED_STAGE_TRANSITIONS`:
- `INITIALIZATION` -> `RESEARCH`, `RISK_ASSESSMENT`, `APPROVAL`, `TERMINATION`
- `RESEARCH` -> `RISK_ASSESSMENT`, `TERMINATION`
- `RISK_ASSESSMENT` -> `PREDICTION`, `SCENARIO_ANALYSIS`, `DECISION`, `TERMINATION`
- `PREDICTION` -> `SCENARIO_ANALYSIS`, `DECISION`, `TERMINATION`
- `SCENARIO_ANALYSIS` -> `DECISION`, `TERMINATION`
- `DECISION` -> `APPROVAL`, `TERMINATION`
- `APPROVAL` -> `ACTION`, `TERMINATION`
- `ACTION` -> `VERIFICATION`, `TERMINATION`
- `VERIFICATION` -> `TERMINATION`
- `TERMINATION` -> (No outgoing transitions)

Any out-of-order, backward, or illegal jump raises `AgentStageTransitionError`.

## 10. Conditional Routing
Conditional edge routing is governed by `ConditionEvaluator`, which maps registered `ConditionCode` enums to deterministic state predicates. 
- Arbitrary Python expressions, lambdas, strings, or `eval()` calls are strictly forbidden and fail-closed with `AgentValidationError`.
- Supported condition codes:
  - `ALWAYS`: Unconditional transition.
  - `HAS_ERRORS`: Errors present or lifecycle status is FAILED.
  - `NO_ERRORS`: Error-free execution.
  - `IS_RETRYABLE`: State indicates a retryable transient failure.
  - `NEEDS_APPROVAL`: Human governance flag is active.
  - `APPROVAL_APPROVED`: Human reviewer authorized the action.
  - `APPROVAL_REJECTED`: Human reviewer rejected the action.
  - `EVIDENCE_SATISFIED`: Evidence references satisfy minimum threshold.
  - `MAX_STEPS_REACHED`: Graph step budget exhausted.

## 11. Retry Semantics
Retries are explicitly modeled transitions:
- A node must have `retryable=True` and `max_retries > 0` in its contract.
- Transient errors increment `retry_count` in `AgentErrorState`.
- If `retry_count >= max_retries`, the retry edge is denied and routing transitions to `FAILURE`.
- Tenant violations, authorization failures, and schema corruptions are categorized as `NON_RETRYABLE` and never retried.

## 12. Failure Handling
Unrecoverable errors immediately transition to `termination` via explicit `FAILURE` edges:
- Error details (`category`, `message`, `error_code`, `correlation_id`) are preserved in `errors` list.
- Graph status transitions to `AgentLifecycleStatus.FAILED`.
- The failure reason is persisted in `termination_reason`.

## 13. Termination Behavior
Termination is explicit and reaches `END`:
- Handled by `termination_node` which sets `current_stage = TERMINATION` and `current_node = "termination"`.
- Determines lifecycle status: `COMPLETED`, `FAILED`, `BLOCKED`, `MAX_STEPS_REACHED`, `NO_ACTION_REQUIRED`, or `WAITING_FOR_APPROVAL`.
- An explicit edge connects `termination` -> `END` (`edge_type=EdgeType.TERMINATION`, `is_terminal=True`).

## 14. Approval Gate
Side-effecting nodes must be preceded by an `APPROVAL_GATE` edge or originate from an `AgentStage.APPROVAL` node:
- When `requires_human_approval=True`, the graph transitions into `approval_boundary_node`.
- Status is set to `WAITING_FOR_APPROVAL`, halting autonomous execution.
- No side-effecting operations execute without human authorization.

## 15. Side-Effect Boundary
Nodes are classified as either `READ_ONLY` or `SIDE_EFFECTING`. In Step 3, side-effecting nodes cannot execute without approval governance flags present in `AgentExecutionContext`. Direct transitions into side-effecting nodes from non-approval stages without an `APPROVAL_GATE` edge are rejected by `GraphValidator`.

## 16. Authorization
Nodes and edges declare required roles (`required_roles`) and permissions (`required_permissions`):
- `NodeExecutionWrapper` compares required permissions against `context.roles` and `context.permissions`.
- Superadmins (`context.is_admin=True`) bypass role checks.
- Unauthorized callers fail-closed with `AgentUnauthorizedNodeError`.
- State updates cannot alter authorization context or escalate roles.

## 17. Evidence Requirements
Nodes declare evidence prerequisites (`requires_evidence`, `minimum_evidence`, `required_evidence_types`):
- Handled via references to Phase 8 RAG evidence bundles (`evidence_references`).
- Nodes cannot invent raw evidence or synthesize fabricated findings.
- Foreign tenant evidence references fail-closed.

## 18. Tenant Isolation
Tenant isolation is enforced on every node execution and state update:
- `context.organization_id == state["organization_id"]`.
- References in `evidence_references`, `risk_assessment`, and `approval_reference` are scanned for foreign tenant prefixes.
- Any mismatch raises `AgentTenantIsolationError`.

## 19. Observability
Every node execution wrapped by `NodeExecutionWrapper` generates structured `NodeExecutionTelemetry`:
- Emits `run_id`, `organization_id`, `actor_id`, `node_name`, `stage`, `duration_ms`, `status`, `request_id`, `correlation_id`, `trace_id`, and `step_count`.
- Automatic redaction of credentials, bearer tokens, and sensitive keys via `sanitize_sensitive_data`.
- Chain-of-thought and private model reasoning are strictly excluded via `screen_untrusted_input`.

## 20. Graph Validation
The `GraphValidator` statically verifies graph topology before compilation:
1. `_validate_node_endpoints()`: All source and destination nodes exist in `NodeRegistry`.
2. `_validate_approval_gates_and_side_effects()`: All side-effecting nodes are guarded by `APPROVAL_GATE`.
3. `_validate_cycles_are_bounded()`: All self-loops and cycles are explicit `RETRY` edges targeting retryable nodes.
4. `_validate_stage_transitions()`: All edges adhere to `ALLOWED_STAGE_TRANSITIONS`.
5. `_validate_terminal_reachability()`: All registered operational nodes are reachable from the start node, and every reachable node can reach `END`.

## 21. LangGraph Compatibility
`AgentGraphBuilder` compiles deterministic StateGraphs using real LangGraph primitives (`langgraph.graph.StateGraph` and `langgraph.checkpoint.memory.MemorySaver`).
- Nodes are wrapped as pure state-dict functions.
- Conditional branches map to LangGraph conditional edges.
- Tested and verified on installed LangGraph with in-memory checkpointer.

## 22. Tests
A focused suite of 104 tests in `api/tests/test_phase9_langgraph_node_edge_contracts.py` validates:
- Node contracts, registration, allowlists, and role requirements (Tests 1–25).
- Edge contracts, types, registration, and duplicate rejection (Tests 26–37).
- Stage transitions and topological enforcement (Tests 28–36).
- Deterministic condition evaluation and eval() rejection (Tests 38–45).
- Retry policies and bounded retry loops (Tests 46–52).
- Failure routing and error preservation (Tests 53–57).
- Termination statuses and explicit END transitions (Tests 58–66).
- Approval gate and side-effect boundary enforcement (Tests 67–73).
- Tenant isolation and cross-tenant reference rejection (Tests 74–77).
- Node authorization, role escalation, and credential scrubbing (Tests 78–82).
- Observability telemetry and secret redaction (Tests 83–88).
- Graph validation for reachability, cycles, and dangling endpoints (Tests 89–96).
- Real LangGraph compilation and execution flows (Tests 97–104).

## 23. Security
- Fail-closed tenant isolation.
- Anti-eval condition evaluator prevents code injection.
- Redaction of bearer tokens (`[REDACTED_BEARER_TOKEN]`) and API keys.
- Exclusion of chain-of-thought reasoning from agent state.
- State size capping at 500 KB prevents memory exhaustion.

## 24. Explicit Non-Goals
- No implementation of business agents (Research, Risk, Prediction, Scenario, Decision, Action, Verification).
- No LLM / Claude / Bedrock API calls or prompt synthesis.
- No ML models, simulation engines, or OR-Tools solvers.
- No external side effects or real tool executions.
- No human approval database persistence, UI, or workflows.
- No database migrations (34 PostgreSQL tables remain unchanged).
- No new public API endpoints (OpenAPI contract remains 60 paths, 96 operations, 104 schemas).
