# Phase 9 Step 10 — Observability & Recovery for the LangGraph Agent Pipeline

## 1. Executive Summary

Phase 9 Step 10 establishes production-grade observability, execution tracing, failure classification, bounded retries, deterministic state recovery, and governance checkpointing for the RiskWise 2.0 multi-agent LangGraph pipeline (`START → INIT → RESEARCH → RISK → PREDICTION → SCENARIO → DECISION → APPROVAL → TERMINATION → END`).

All graph runs are strictly deterministic, tenant-isolated, auditable, and fail-closed against security or state corruption events. Zero database schema migrations or enum mutations were introduced, preserving exactly 34 database tables and existing OpenAPI schemas.

---

## 2. Architecture & Execution Lifecycle

```
[START]
   ↓
[INIT] (Initializes graph state, records input_state_hash, checks tenant boundary)
   ↓
[RESEARCH AGENT] (Bounded RAG evidence retrieval, read-only)
   ↓
[RISK AGENT] (Multi-factor risk scoring, read-only)
   ↓
[PREDICTION AGENT] (Quantitative impact forecasts, read-only)
   ↓
[SCENARIO AGENT] (Deterministic operational scenarios, read-only)
   ↓
[DECISION AGENT] (Rule-based candidate generation, immutable recommendation)
   ↓
[HUMAN APPROVAL GATEWAY]
   ├── [Pending / Review] ──→ WAITING_FOR_APPROVAL (Suspends execution, saves checkpoint)
   ├── [Approved] ──────────→ RESUME (Restores state integrity, executes governed nodes)
   └── [Rejected] ──────────→ TERMINATE (Safe shutdown, logs reason to audit ledger)
   ↓
[TERMINATION NODE] (Final state hash validation, metrics export, audit event)
   ↓
[END]
```

Every execution stage is wrapped by `NodeExecutionWrapper`, which acts as an execution boundary enforcing:
- Tenant boundary verification (`validate_tenant_isolation`)
- Role-based authorization & permission verification
- Mandatory input presence & minimum evidence counts
- Execution step limit enforcement (`step_count < max_steps`)
- State integrity hash calculation (`input_state_hash` and `output_state_hash`)
- Timeout handling (`timeout_seconds`)
- Bounded retry loop for retryable errors with exponential backoff and jitter
- Structured telemetry emission (`NodeExecutionTelemetry` and `AgentRunTelemetry`)
- Audit log emission via `AuditService`

---

## 3. Telemetry Model

The telemetry architecture provides strongly typed Pydantic models:

### 3.1 `AgentRunTelemetry`
Captures end-to-end and node-level telemetry without persisting secrets:
- `organization_id`: Tenant UUID
- `agent_run_id`: Run identifier
- `execution_id`: Execution run identifier (defaults to `agent_run_id`)
- `request_id`: Originating HTTP request ID
- `correlation_id`: Distributed transaction correlation ID
- `trace_id`: Distributed trace ID
- `parent_span_id`: Optional parent span identifier
- `node_id`: Executed node ID
- `stage`: Pipeline stage name
- `attempt`: Execution attempt number (1-indexed)
- `status`: Execution outcome (`SUCCESS`, `FAILED`, `RECOVERABLE_FAILURE`, `COMPLETED`, `WAITING_FOR_APPROVAL`)
- `started_at` / `completed_at`: UTC ISO-8601 timestamps
- `duration_ms`: Execution latency in milliseconds
- `retry_count`: Total retries attempted
- `error_code` / `error_category`: Diagnostic codes on failure
- `selected_route`: Next node selected by routing rules
- `state_version`: State schema version (`1.0.0`)
- `input_state_hash`: SHA-256 digest of input state
- `output_state_hash`: SHA-256 digest of resulting state
- `metadata`: Sanitized contextual key-values

### 3.2 `AgentToolCallTelemetry`
Captures tool invocations for future integrations:
- `tool_call_id`, `agent_run_id`, `node_id`, `tool_name`, `attempt`
- `safe_input_fingerprint`, `safe_output_fingerprint`
- `status`, `duration_ms`, `error_code`, `metadata`

### 3.3 `AgentMetricsCollector`
Thread-safe in-memory metrics aggregator tracking:
- Total graph executions, successes, and failures
- Per-node average latencies in milliseconds
- Node retries count (`node_retries`)
- Node timeouts count (`node_timeouts`)
- Recovery evaluations (`recovery_count`)
- Governance approval pauses (`approval_waits`) and resumes (`approval_resume_count`)
- Routing failures and step-limit violations (`routing_failures`)
- Security and tenant isolation violations (`security_failures`)

---

## 4. Trace Propagation

Trace identifiers propagate immutably through every node, lifecycle phase, and checkpoint:
- `request_id`
- `correlation_id`
- `trace_id`
- `agent_run_id`
- `execution_id`
- `organization_id`

### Propagation Invariants:
1. Every node execution is attributable to `(organization_id, agent_run_id, node_id, attempt)`.
2. Nodes are strictly prohibited from generating disconnected trace IDs when valid execution context exists.
3. Trace ID mismatch between `AgentExecutionContext` and `AgentGraphState` immediately triggers `AgentTenantIsolationError` and increments `security_failures`.

---

## 5. Error Taxonomy & Classification

Errors are classified into 15 deterministic categories via `AgentErrorCategory`:

| Error Category | Retryable | Description | Handling Action |
|---|---|---|---|
| `VALIDATION_ERROR` | **No** | State payload or schema validation failure | Fail closed |
| `SECURITY_ERROR` | **No** | Secret leakage, tampering, forbidden key access | Fail closed immediately |
| `TENANT_ISOLATION_ERROR` | **No** | Cross-tenant access or missing organization_id | Fail closed immediately |
| `AUTHORIZATION_ERROR` | **No** | Caller missing required role or permission | Fail closed |
| `CONTRACT_ERROR` | **No** | Violation of graph topology or node contract | Fail closed |
| `DEPENDENCY_ERROR` | **Yes** | Remote database, retriever, or network blip | Retry up to `max_retries` |
| `TIMEOUT_ERROR` | **Yes** | Node execution deadline exceeded | Retry if budget remains |
| `TRANSIENT_ERROR` | **Yes** | Socket error, connection reset, temporary conflict | Retry with exponential backoff |
| `RATE_LIMIT_ERROR` | **Yes** | Capacity or rate threshold hit | Retry with backoff |
| `STATE_ERROR` | **No** | State hash mismatch or corrupted payload | Fail closed |
| `ROUTING_ERROR` | **No** | Unregistered route or step limit exceeded | Fail closed |
| `APPROVAL_ERROR` | **No** | Governance violation or duplicate approval | Fail closed |
| `PERSISTENCE_ERROR` | **Yes** | Database lock contention or transient conflict | Retry up to `max_retries` |
| `INTERNAL_ERROR` | **No** | Unhandled system exception or bug | Fail closed |
| `UNKNOWN_ERROR` | **No** | Unrecognized exception type | Fail closed |

### Rule: Security and Tenant Violations Never Retry
Under no circumstances may `SECURITY_ERROR`, `TENANT_ISOLATION_ERROR`, `AUTHORIZATION_ERROR`, `CONTRACT_ERROR`, `VALIDATION_ERROR`, or `STATE_ERROR` be retried automatically.

---

## 6. Retry & Timeout Policies

### 6.1 RetryPolicy
- **Exponential Backoff**: `delay = min(max_delay, base_delay * 2^(attempt - 1))`
- **Jitter**: Bounded random jitter `(0.5 + 0.5 * rand)` to prevent thundering herd.
- **Budget Bound**: Strict termination at `context.max_retries` (default 3, range 0–10). Zero infinite retry loops.

### 6.2 Timeout Handling
- Enforced at node execution level via `NodeExecutionWrapper`.
- Evaluates deadline against `timeout_seconds`.
- If timeout fires: raises `AgentTimeoutError`, records `global_metrics_collector.node_timeouts`, and evaluates retry eligibility.

---

## 7. State Integrity & Checkpointing

### 7.1 Deterministic State Hashing
- `compute_state_hash(state)` generates a canonical SHA-256 digest over all state dictionary keys and values.
- Excludes transient ephemeral fields (`started_at`, `completed_at`, `last_error`, `errors`).
- Guarantees identical state hashes for semantically identical states regardless of dictionary insertion order.

### 7.2 CheckpointManager
- Captures immutable checkpoint snapshots at state transitions.
- Stores canonical SHA-256 state hashes.
- On resumption: validates restored state against expected hash. If tampered or altered, raises `AgentStateError` and fails closed.
- Validates restored tenant against expected tenant ID; raises `AgentTenantIsolationError` on mismatch.

---

## 8. Human Approval Integration

When the pipeline reaches `DECISION → APPROVAL`:
1. Pipeline enters `WAITING_FOR_APPROVAL` lifecycle status.
2. Side-effect execution is strictly prohibited (`side_effect_allowed = False`).
3. Retries cannot bypass human approval.
4. On human decision:
   - **APPROVED**: State restored from checkpoint, `approval_status = APPROVED`, `side_effect_allowed = True`.
   - **REJECTED**: State transitions to `COMPLETED` with `termination_reason = HUMAN_APPROVAL_REJECTED`.
   - **UNAUTHORIZED / INVALID**: Fail closed immediately with `AgentApprovalError`.

---

## 9. Audit Event Integration

Significant lifecycle events are emitted to the immutable audit ledger via `AuditService.log_event`:
- `GRAPH_STARTED`: Emitted at beginning of graph execution.
- `GRAPH_SUCCEEDED`: Emitted on successful run completion.
- `GRAPH_TERMINATED`: Emitted on clean pipeline termination.
- `GRAPH_FAILED`: Emitted on unrecoverable failure.

All audit entries include tenant ID, actor ID, request ID, state hashes, and strictly scrub passwords, tokens, API keys, and authorization headers.

---

## 10. Failure Response Contract (`AgentFailureResult`)

Public-safe structured failure response preserving diagnostics without leaking stack traces or internal secrets:
- `execution_id`: UUID
- `agent_run_id`: Run UUID
- `node_id`: Failing node identifier
- `stage`: Pipeline stage
- `status`: `FAILED`
- `error_code`: Machine-readable error code (e.g. `AGENT_TIMEOUT_ERROR`)
- `error_category`: Taxonomy category (e.g. `TIMEOUT_ERROR`)
- `retryable`: Boolean flag
- `recovery_action`: Recommended recovery action (`RETRY`, `RESUME`, `FAIL`, `ESCALATE`, `WAIT_FOR_HUMAN`)
- `trace_id`: Distributed trace identifier
- `message`: Sanitized public message suitable for client display
- `occurred_at`: UTC timestamp

---

## 11. Testing & Verification

The Step 10 test suite (`apps/api/tests/test_phase9_step10_observability_recovery.py`) contains **137 focused automated tests** covering sections A through P:
- **A. Trace Propagation** (Tests 1–10)
- **B. Node Telemetry** (Tests 11–20)
- **C. Error Classification** (Tests 21–35)
- **D. Retry Policy & Bounded Retries** (Tests 36–45)
- **E. Timeout Handling** (Tests 46–53)
- **F. Recovery Policy** (Tests 54–63)
- **G. State Integrity & Hashing** (Tests 64–73)
- **H. Routing Safety & Loop/Crash Protection** (Tests 74–81)
- **I. Human Approval Integration** (Tests 82–91)
- **J. Audit Event Integration** (Tests 92–99)
- **K. Secret Redaction & Sanitization** (Tests 100–107)
- **L. Tenant Isolation** (Tests 108–115)
- **M. Idempotent Retry** (Tests 116–121)
- **N. Concurrent & Replayed Execution** (Tests 122–126)
- **O. Failure Response Contract** (Tests 127–132)
- **P. Tool Telemetry & Metrics Integration** (Tests 133–137)

---

## 12. Known Limitations & Non-Goals

1. **No External Side Effects**: Operational carriers, suppliers, and shipments are not mutated in Phase 9.
2. **No LLM / ML Generation**: No Claude, Bedrock, simulation engines, or optimization solvers are introduced in this step.
3. **In-Memory & SQLite Checkpointer**: Checkpoint persistence uses LangGraph MemorySaver and CheckpointManager for deterministic in-memory execution; distributed Redis/PostgreSQL checkpointers are reserved for operational deployment.
