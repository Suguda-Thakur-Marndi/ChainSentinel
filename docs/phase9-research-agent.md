# Phase 9 Step 4: Research Agent

## Overview

The Research Agent is the **first operational node** in the RiskWise 2.0 LangGraph multi-agent pipeline. It is a **deterministic, read-only, non-LLM evidence analyst** that transforms a `RAGEvidenceBundle` (retrieved in Phase 8) into structured `ResearchFinding` objects for downstream agents.

> **Boundary**: The Research Agent is **evidence-only**. It does not compute risk scores, issue recommendations, invoke ML models, or take any external actions.

---

## Module Layout

```
api/app/agents/research/
+-- __init__.py        # Public surface: research_node, RESEARCH_NODE_CONTRACT, ResearchAgent
+-- contract.py        # ResearchRequest, ResearchResult, ResearchFinding, ResearchNodeOutput
+-- evidence.py        # EvidenceValidator (tenant isolation + quarantine)
+-- analysis.py        # ResearchAnalysisEngine (deterministic findings + conflicts)
+-- agent.py           # ResearchAgent orchestrator
+-- node.py            # LangGraph node function + RESEARCH_NODE_CONTRACT registration
+-- errors.py          # ResearchAgentError, InvalidResearchRequestError, EvidenceBoundaryError
```

---

## Architecture

```
AgentGraphState
     ¦
     ?
research_node()           ? LangGraph node function (node.py)
     ¦
     +-? EvidenceValidator (evidence.py)
     ¦       +- Tenant isolation check
     ¦       +- Prompt-injection quarantine
     ¦       +- Adversarial pattern scan
     ¦
     +-? ResearchAnalysisEngine (analysis.py)
     ¦       +- Deterministic finding generation
     ¦       +- Conflict detection
     ¦       +- Fingerprint / reproducibility hash
     ¦
     +-? ResearchAgent.execute() (agent.py)
     ¦       +- Validates request + bundle ownership
     ¦       +- Runs validator ? engine
     ¦       +- Returns ResearchResult
     ¦
     +-? validate_state_update()   ? write-boundary enforcement
```

---

## Security Properties

### Tenant Isolation
- Every evidence item's `organization_id` is checked against the request tenant
- Cross-tenant items are **rejected** and produce a `TENANT_BOUNDARY_VIOLATION` limitation
- `organization_id` in state is a write-protected field — the node cannot overwrite it

### Prompt-Injection Quarantine
Evidence is scanned for adversarial patterns from two sources:
1. `PROMPT_INJECTION_PATTERNS` (Phase 8, `rag/contracts.py`) — base patterns
2. `RESEARCH_PROMPT_INJECTION_PATTERNS` (Phase 9, `research/evidence.py`) — extended patterns

Quarantined items are excluded from findings and tagged with an `UNSAFE_SOURCE` limitation.

### Chain-of-Thought Prohibition
`AgentConflict.description`, `AgentLimitation.description`, and `ResearchResult.summary`
all run through `validate_no_reasoning_content()` — a Pydantic field validator that rejects
strings containing CoT markers (`chain_of_thought`, `<thinking>`, `reasoning`, etc.).

### State Write Boundaries
`validate_state_update()` enforces that the research node cannot write to fields owned by
other stages (risk scores, recommendations, approval status, identity fields).

---

## Determinism Guarantees

1. **Fingerprint**: `SHA-256(sorted(evidence_ids) | objective.lower().strip() | bundle_id)`
2. **Finding IDs**: `SHA-256(finding_title + organization_id + objective)`
3. **Research ID**: `SHA-256(organization_id + objective.lower().strip() + bundle_id)`

---

## Telemetry

Every execution (success **or** failure) emits a `NodeExecutionTelemetry` record via
`AgentObservability.emit_node_telemetry()` in a `finally` block, capturing run_id,
duration_ms, status (SUCCESS/FAILED), and error_code on failure.

---

## Tests

**106 tests** in `api/tests/test_phase9_research_agent.py`

- Full regression: **2030 passed, 1 skipped, 0 failed**

---

## Hard Constraints

- No LLM calls, no ML models, no external APIs
- No risk score computation, no recommendations, no autonomous actions
- No database mutations, no schema migrations, no public API changes
- Read-only, deterministic, tenant-isolated, zero-side-effect
