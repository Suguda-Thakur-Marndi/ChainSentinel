# RiskWise 2.0 — Comprehensive Testing & Quality Assurance Guide

## 1. Testing Philosophy & Hierarchy

RiskWise 2.0 employs a strict defense-in-depth testing architecture designed for mission-critical supply chain operations. Reliability is enforced through five discrete testing layers:

```
        ▲
       / \         Layer 5: Continuous Evaluation & Golden Datasets (Phase 20)
      /   \        Layer 4: Automated Browser E2E & Visual Verification (Playwright)
     /     \       Layer 3: End-to-End Service & Multi-Agent Integration Tests
    /       \      Layer 2: REST API Contract & Cryptographic State Tests
   /         \     Layer 1: Deterministic Domain Unit & Mathematical Solver Tests
  ─────────────
```

---

## 2. Backend Test Architecture (`api/tests`)

The backend test suite contains **124 test files** totaling **4,532 tests** passing with 0 failures:

| Test Domain | Target Subsystems | Key Test Suites | Coverage Areas |
| :--- | :--- | :--- | :--- |
| **Foundation & DB** | Phase 01–04 | `test_models.py`, `test_crud.py`, `test_database_validation.py`, `test_service_repository_foundations.py` | Schema constraints, cascade rules, multi-tenant isolation, repository abstractions |
| **Authentication & RBAC**| Phase 03 | `test_auth_config.py`, `test_auth_final_validation.py`, `test_sessions_and_auth.py` | Google OAuth PKCE, JWT tokens, session lifecycle, role permission matrices |
| **Telemetry Ingestion** | Phase 05–06 | `test_aisstream_*.py`, `test_opensky_*.py`, `test_openweather_*.py`, `test_rail_*.py`, `test_tomtom_*.py`, `test_tavily_*.py`, `test_karrio_*.py`, `test_canonical_*.py` | Raw feed parsing, deduplication, GeoJSON spatial validation, event normalization |
| **Risk Scoring & Alerts**| Phase 07 | `test_phase7_baseline_scoring.py`, `test_phase7_risk_engine_contracts.py`, `test_phase7_risk_alerts_escalation.py` | Deterministic composite math, threshold breaches, notification dispatch |
| **Hybrid RAG** | Phase 08 | `test_phase8_rag_*.py` (6 files) | Document chunking, vector embedding storage, cosine similarity, grounding |
| **LangGraph Multi-Agent**| Phase 09 | `test_phase9_*.py` (11 files) | Agent state machine, node transitions, research, risk, scenario, prediction agents |
| **Gemini LLM Provider** | Phase 10 | `test_gemini_provider.py`, `test_phase10_*.py` | Google GenAI SDK integration, JSON schema enforcement, token telemetry, error backoff |
| **Machine Learning** | Phase 11 | `test_phase11_ml_*.py` (11 files) | GBDT regression, feature leakage prevention, drift detection, model registry |
| **Digital Twin** | Phase 12 | `test_phase12_twin_*.py` (9 files) | RFC 4122 UUIDv5 IDs, network graph topology, shortest-path calculation |
| **Simulation** | Phase 13 | `test_phase13_*.py` (6 files) | Monte Carlo cascade iterations, stochastic disruption spread, P10/P50/P90 variance |
| **Optimization** | Phase 14 | `test_phase14_*.py` (7 files) | Google OR-Tools MILP solver, Pareto frontier trade-offs, constraint satisfaction |
| **Decision & Governance**| Phase 15–16 | `test_phase15_*.py`, `test_phase16_*.py` | Mitigation synthesis, SHA-256 fingerprinting, dual-control human approval |
| **Action & Verification**| Phase 17–18 | `test_phase17_*.py`, `test_phase18_*.py` | Carrier reroute execution, idempotency, ground-truth physical verification (`REAL > ESTIMATED > SIMULATED`) |
| **Quality Evaluation** | Phase 20 | `test_phase20_*.py` (7 files) | Golden dataset validation, agent decision accuracy, hallucination index, latency |
| **Production Hardening**| Phase 21 | `test_phase21_production_hardening.py` | High availability, rate limiting, encryption, connection pool resilience |

### Executing Backend Tests

```bash
cd api

# Run the complete test suite
python -m pytest tests/ -v --tb=short

# Run specific domain suites
python -m pytest tests/test_auth_*.py -v
python -m pytest tests/test_phase14_*.py -v   # Optimization
python -m pytest tests/test_phase20_*.py -v   # Golden Evaluation
```

---

## 3. Frontend Test Architecture (`web/tests`)

The frontend test suite validates component rendering, API client behavior, authentication flows, and state management using the Node.js test runner with TypeScript execution:

- `web/tests/auth-integration.test.ts`: Validates Google OAuth redirect generation, callback session parsing, and RBAC route protection.
- `web/tests/frontend-backend-integration.test.ts`: Verifies real API client interaction against FastAPI endpoints, ensuring contract synchronization.
- `web/tests/phase19-control-tower.test.ts`: Validates Control Tower dashboard metrics, telemetry radar feeds, and data table filtering.

### Executing Frontend Tests

```bash
cd web

# Run all frontend tests
npm test

# Run type checking
npx tsc --noEmit

# Run ESLint quality checks
npm run lint

# Validate production build (App Router compilation across all 36 routes)
npm run build
```

---

## 4. Automated Page-by-Page Browser Audit Harness

RiskWise 2.0 includes an automated headless Chromium audit harness that validates every route in `web/app`:

- **Scope**: 36 discoverable routes and 107 interactive features.
- **Responsive Inspection**: Validates rendering on Desktop (1920x1080), Tablet (768x1024), and Mobile (375x812).
- **Diagnostics**: Monitors browser console for runtime warnings/errors, inspects network requests, and verifies API status codes.

---

## 5. Non-Negotiable Test Invariants

1. **Zero Test Degradation**: Tests must never be deleted, skipped, or loosened merely to make a build pass.
2. **Deterministic Assertions**: Tests must use fixed random seeds and mock external networks to guarantee 100% reproducible results.
3. **No Flaky Tests**: Any test with timing dependencies must use deterministic condition polling rather than arbitrary sleep delays.
