# RiskWise 2.0

> **Enterprise Autonomous Supply Chain Risk Intelligence, Multi-Agent Orchestration, Digital Twin Simulation & Governed Operational Action Platform**
> 
> *A high-resilience enterprise platform integrating real-time multimodal telemetry, deterministic composite risk scoring, hybrid RAG, multi-agent LangGraph orchestration with AWS Bedrock (Claude 3.5 Sonnet & Titan), GBDT delay regression, deterministic graph digital twin synthesis, Monte Carlo disruption simulation, Google OR-Tools multi-constraint optimization, cryptographic human-in-the-loop governance, governed operational execution adapters, and authoritative post-action outcome verification.*

---

[![Status: Phase 18 Complete](https://img.shields.io/badge/Roadmap-Phase%2018%20Complete%20(18%2F21)-emerald?style=flat-square&logo=git)](docs/phase18-verification-agent.md)
[![Tests: 4,506 Passing](https://img.shields.io/badge/Tests-4%2C506%20Passed%20%7C%200%20Failed%20%7C%200%20Skipped-success?style=flat-square&logo=pytest)](api/tests)
[![Code Coverage: 100%](https://img.shields.io/badge/Coverage-100%25%20Completed%20Phases-blue?style=flat-square)](api/tests)
[![Python: 3.12 | 3.13](https://img.shields.io/badge/Python-3.12%20%7C%203.13-blue?style=flat-square&logo=python)](api/pyproject.toml)
[![FastAPI: 0.115+](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=flat-square&logo=fastapi)](api/requirements.txt)
[![PostgreSQL: 16 RDS](https://img.shields.io/badge/PostgreSQL-16%20RDS%20(34%20Tables)-336791?style=flat-square&logo=postgresql)](docs/database-schema-inventory.md)
[![SQLAlchemy: 2.0](https://img.shields.io/badge/ORM-SQLAlchemy%202.0-red?style=flat-square)](api/app/models)
[![Multi-Agent: LangGraph](https://img.shields.io/badge/Multi--Agent-LangGraph%200.2%2B-purple?style=flat-square)](api/app/agents)
[![LLM: Claude 3.5 Sonnet](https://img.shields.io/badge/Reasoning-Claude%203.5%20Sonnet%20(Bedrock)-D97706?style=flat-square)](docs/phase10-bedrock-claude.md)
[![Optimization: OR-Tools](https://img.shields.io/badge/Solver-Google%20OR--Tools%20MILP-4285F4?style=flat-square&logo=google)](docs/phase14-optimization.md)
[![ML: LightGBM GBDT](https://img.shields.io/badge/ML-LightGBM%20GBDT%20Regression-brightgreen?style=flat-square)](docs/phase11-ml.md)
[![Web: Next.js 14](https://img.shields.io/badge/Frontend-Next.js%2014%20App%20Router-black?style=flat-square&logo=next.js)](web/)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary%20Enterprise-red?style=flat-square)](LICENSE)

---

## Table of Contents

1. [Executive Summary & Platform Value Proposition](#executive-summary--platform-value-proposition)
2. [Complete End-to-End WOW Operational Flow](#complete-end-to-end-wow-operational-flow)
   - [End-to-End Visual Architecture (Mermaid)](#end-to-end-visual-architecture-mermaid)
   - [Real-World Incident Scenario Walkthrough](#real-world-incident-scenario-walkthrough)
3. [Master Roadmap & Implementation Status (Phases 1–21)](#master-roadmap--implementation-status-phases-121)
4. [Authoritative Repository Layout](#authoritative-repository-layout)
5. [The 10 Core System Invariants & Safety Discipline](#the-10-core-system-invariants--safety-discipline)
6. [Detailed Technical Deep-Dive of All 18 Completed Subsystems](#detailed-technical-deep-dive-of-all-18-completed-subsystems)
   - [Phase 01: Core Foundation & Framework Architecture](#phase-01-core-foundation--framework-architecture)
   - [Phase 02: Database Schema & Relational Integrity](#phase-02-database-schema--relational-integrity)
   - [Phase 03: Google Authentication & Enterprise RBAC](#phase-03-google-authentication--enterprise-rbac)
   - [Phase 04: Core Domain APIs & Clean Architecture](#phase-04-core-domain-apis--clean-architecture)
   - [Phase 05: External Telemetry Ingestion Connectors](#phase-05-external-telemetry-ingestion-connectors)
   - [Phase 06: Event Normalization & Entity Resolution](#phase-06-event-normalization--entity-resolution)
   - [Phase 07: Deterministic Multi-Factor Risk Engine](#phase-07-deterministic-multi-factor-risk-engine)
   - [Phase 08: Hybrid RAG Knowledge Engine & Vector Search](#phase-08-hybrid-rag-knowledge-engine--vector-search)
   - [Phase 09: LangGraph Multi-Agent Orchestration](#phase-09-langgraph-multi-agent-orchestration)
   - [Phase 10: AWS Bedrock & Claude 3.5 Sonnet Integration](#phase-10-aws-bedrock--claude-35-sonnet-integration)
   - [Phase 11: Machine Learning Shipment Delay Regression](#phase-11-machine-learning-shipment-delay-regression)
   - [Phase 12: Digital Twin Supply Chain Graph Engine](#phase-12-digital-twin-supply-chain-graph-engine)
   - [Phase 13: Disruption Simulation & Cascade Engine](#phase-13-disruption-simulation--cascade-engine)
   - [Phase 14: Mathematical Optimization Subsystem](#phase-14-mathematical-optimization-subsystem)
   - [Phase 15: Mitigation Decision Agent & Claude Synthesis](#phase-15-mitigation-decision-agent--claude-synthesis)
   - [Phase 16: Human Governance & Approval Subsystem](#phase-16-human-governance--approval-subsystem)
   - [Phase 17: Operational Action Agent & Execution Adapters](#phase-17-operational-action-agent--execution-adapters)
   - [Phase 18: Operational Verification Agent & Outcome Evidence](#phase-18-operational-verification-agent--outcome-evidence)
7. [Authoritative 34-Table Database Inventory](#authoritative-34-table-database-inventory)
8. [REST API Architecture & Comprehensive Endpoint Catalog](#rest-api-architecture--comprehensive-endpoint-catalog)
9. [Multi-Agent LangGraph State Machine Architecture](#multi-agent-langgraph-state-machine-architecture)
10. [Supported Operational Actions & Verification Matrix](#supported-operational-actions--verification-matrix)
11. [Post-Action Verification Agent (Phase 18) Deep-Dive](#post-action-verification-agent-phase-18-deep-dive)
12. [Verification & Automated Test Suite Metrics](#verification--automated-test-suite-metrics)
13. [Local Development, Setup & Configuration Guide](#local-development-setup--configuration-guide)
14. [Complete Documentation Index](#complete-documentation-index)

---

## Executive Summary & Platform Value Proposition

Modern global supply chains operate under extreme volatility. Geopolitical conflicts in strategic transit corridors (Suez Canal, Bab-el-Mandeb, Strait of Malacca), severe weather anomalies, port labor disputes, carrier insolvencies, and supplier disruptions routinely cascade across multi-tier networks, causing catastrophic factory shutdowns, unmet customer SLAs, and billions in unanticipated logistics costs.

Traditional Supply Chain Management (SCM) platforms are passive and siloed:
- **Lagging Visibility**: They surface disruptions days after they occur via static reporting dashboards.
- **Disconnected Decision-Making**: Disruption analysis, impact modeling, and reroute planning are manual, ad-hoc spreadsheet exercises.
- **Uncontrolled Automation**: Unregulated bot automations risk executing dangerous real-world mutations without auditability or human accountability.
- **Blind Execution**: Systems assume dispatching an order guarantees success, lacking closed-loop operational verification.

**RiskWise 2.0** solves this paradigm through an autonomous, governed, and closed-loop multi-agent supply chain resilience platform:
1. **Continuous Real-Time Ingestion**: Monitors maritime AIS, aviation ADS-B, road telemetry, weather forecasts, rail schedules, and global OSINT news.
2. **Deterministic Risk & ML Forecasting**: Evaluates multi-factor risk scores and predicts consignment delays using calibrated gradient-boosted decision trees.
3. **Digital Twin Simulation**: Synthesizes a deterministic network topology graph using RFC 4122 UUIDv5 identities and models shock propagation via Monte Carlo cascades.
4. **Mathematical Optimization**: Formulates and solves mixed-integer linear programming (MILP) models with Google OR-Tools to identify Pareto-optimal mitigation strategies balancing cost, delay, and carbon.
5. **Domain-Grounded Reasoning**: Leverages Anthropic Claude 3.5 Sonnet on AWS Bedrock to synthesize transparent, executive-grade operational justifications grounded in company standard operating procedures.
6. **Cryptographic Human Governance**: Enforces a strict human approval perimeter with SHA-256 state fingerprinting, role-gated sign-offs, and tamper prevention.
7. **Governed Operational Execution**: Dispatches validated mitigation actions through dedicated operational adapters with strict idempotency guarantees and allowlists.
8. **Authoritative Post-Action Verification**: Gathers post-action evidence across an authoritative source hierarchy (`REAL > ESTIMATED > SIMULATED`), deterministically verifying whether the real-world operational outcome matched business intent without permitting autonomous loops.

---

## Complete End-to-End WOW Operational Flow

### End-to-End Visual Architecture (Mermaid)

```mermaid
flowchart TD
    subgraph S1["1. INGESTION & NORMALIZATION"]
        EXT["External Telemetry Feeds<br/>(AISStream, OpenSky, TomTom, Weather, Tavily, Rail, Karrio)"]
        NORM["Normalization & Entity Resolution Engine<br/>(Phase 5 & Phase 6: Canonical Event Model, IMO/MMSI/ICAO Matcher)"]
        EXT --> NORM
    end

    subgraph S2["2. MULTI-AGENT INTELLIGENCE & SCORING"]
        RES["OSINT Research Agent<br/>(Phase 9 & 10: Tavily News Search & Hybrid RAG Retrieval)"]
        RISK["Deterministic Risk Engine<br/>(Phase 7: Geopolitical, Climate, Transit, Financial Scoring)"]
        ML["Predictive Machine Learning<br/>(Phase 11: LightGBM GBDT Delay Regression)"]
        NORM --> RES
        NORM --> RISK
        NORM --> ML
    end

    subgraph S3["3. DIGITAL TWIN & SIMULATION"]
        TWIN["Digital Twin Graph Synthesis<br/>(Phase 12: RFC 4122 UUIDv5 Topology, BFS Pathfinding)"]
        SIM["Disruption Simulation Engine<br/>(Phase 13: Monte Carlo Cascade Stress-Testing)"]
        OPT["Mathematical Optimization<br/>(Phase 14: Google OR-Tools Multi-Constraint MILP Solver)"]
        RISK --> TWIN
        ML --> TWIN
        TWIN --> SIM
        SIM --> OPT
    end

    subgraph S4["4. DECISION & HUMAN GOVERNANCE"]
        DEC["Decision Agent<br/>(Phase 15: Ranked Mitigation Candidates & Trade-Off Matrix)"]
        CLAUDE["Claude 3.5 Sonnet Synthesis<br/>(Domain-Grounded Justification & Trade-Off Explanation)"]
        APPR["Human Approval Subsystem<br/>(Phase 16: Cryptographic Perimeter, Role-Gated Sign-Off)"]
        OPT --> DEC
        DEC --> CLAUDE
        CLAUDE --> APPR
    end

    subgraph S5["5. ACTION EXECUTION & VERIFICATION"]
        ACT["Action Agent Execution<br/>(Phase 17: Allowlist, Idempotency Caching, Operational Adapters)"]
        AUDIT["Immutable Audit Trail<br/>(audit_logs, recommendation = EXECUTED)"]
        VERIF["Verification Agent<br/>(Phase 18: Authoritative Post-Action Verification)"]
        OUTCOME["Final Operational Outcome<br/>(REAL > ESTIMATED > SIMULATED, Deterministic Policy)"]
        APPR -- "APPROVED" --> ACT
        ACT --> AUDIT
        ACT --> VERIF
        VERIF --> OUTCOME
    end

    style S1 fill:#f8fafc,stroke:#cbd5e1,stroke-width:2px
    style S2 fill:#f0fdf4,stroke:#86efac,stroke-width:2px
    style S3 fill:#eff6ff,stroke:#93c5fd,stroke-width:2px
    style S4 fill:#fdf4ff,stroke:#f0abfc,stroke-width:2px
    style S5 fill:#fffbeb,stroke:#fde68a,stroke-width:2px
```

### Real-World Incident Scenario Walkthrough

To understand the platform's power, consider a Category 4 Typhoon (*Muifa*) approaching the East China Sea, threatening Ningbo-Zhoushan Port:

1. **Ingestion & Resolution (Phases 5 & 6)**:
   - Open-Meteo transmits gale-force wind alerts (>45 knots) and 6-meter wave height forecasts for coastal Zhejiang.
   - AISStream transmits real-time GPS coordinates and speed of container vessel *MSC Oscar* (IMO: 9703291), decelerating 40 nautical miles southeast of Ningbo.
   - The normalization engine correlates telemetry with `shipment_id = "shp_oscar_001"` carrying critical lithium battery cells bound for a Munich automotive factory.
2. **Multi-Factor Risk & ML Delay Prediction (Phases 7, 8, 10, 11)**:
   - Phase 7 Risk Engine computes a composite score of `88.5 / 100` (`CRITICAL`), driven by climate risk (`95.0`) and transit congestion (`82.0`).
   - Phase 8 RAG retrieves internal maritime operating guidelines specifying minimum safe operating margins.
   - Phase 11 LightGBM Regression predicts an expected port dwell delay of `96.4 hours` if the vessel continues on its baseline trajectory.
3. **Digital Twin & Disruption Cascade Simulation (Phases 12 & 13)**:
   - Phase 12 Digital Twin resolves the supply chain topology: `Ningbo Port -> Ocean Corridor -> Rotterdam -> Rail Corridor -> Munich Factory`.
   - Phase 13 Monte Carlo Simulation models 500 perturbations, uncovering that a 96-hour delay exhausts the Munich factory's safety inventory buffer, forcing an assembly line halt after 36 hours with an estimated financial loss of `$2.8M`.
4. **Optimization & Ranked Decision Candidates (Phases 14 & 15)**:
   - Phase 14 Google OR-Tools MILP solver evaluates alternate transit corridors, carrier availability, and port congestion indices.
   - Solver identifies an optimal bypass: Reroute *MSC Oscar* to discharge containers at **Port of Busan (South Korea)**, followed by expedited air freight for critical components to Munich.
   - Phase 15 Decision Agent ranks Candidate #1 (`SHIPMENT_REROUTE` to Busan + `EXPEDITE_SHIPMENT` for critical sub-lots) with an overall utility score of `0.92`, saving 78 hours of transit time at an incremental cost of `$45,000`.
   - Claude 3.5 Sonnet formats an executive-ready operational mitigation brief.
5. **Human Approval Perimeter (Phase 16)**:
   - The recommendation triggers a mandatory human approval perimeter requiring `RiskManager` authorization.
   - The payload is locked with a SHA-256 state fingerprint `a8f9...4c21`.
   - An authorized Risk Manager inspects the trade-off matrix on the platform and issues an `APPROVED` decision with cryptographic signature.
6. **Governed Operational Execution (Phase 17)**:
   - Phase 17 Action Agent receives the approved command, validates against the strict operational allowlist, verifies role RBAC, and enforces idempotency via SHA-256 command hashing.
   - `ShipmentRerouteExecutor` executes the reroute adapter, updating operational consignment records, reassigning target waypoint coordinates to Busan, and emitting carrier EDI change orders.
   - Recommendation status transitions to `EXECUTED` in `recommendations`, and an immutable entry is logged in `audit_logs`.
7. **Authoritative Post-Action Verification (Phase 18)**:
   - Phase 18 Verification Agent initiates post-action outcome verification.
   - Collects incoming authoritative telemetry from physical AIS transponders (`REAL` precedence).
   - Confirms vessel trajectory altered to 035° heading toward Busan, speed stabilized at 18.2 knots, and carrier booking confirmed.
   - Verification policy evaluates outcome as `VERIFIED` with zero conflicting evidence.
   - The workflow cleanly halts at `selected_route = "termination"`, guaranteeing zero autonomous infinite loops.

---

## Master Roadmap & Implementation Status (Phases 1–21)

| Phase | Subsystem | Technical Scope & Architectural Capabilities | Status | Automated Test Suite |
| :---: | :--- | :--- | :---: | :---: |
| **01** | **Foundation Architecture** | Monorepo layout, Pydantic V2 settings, async context, structured JSON logging, error taxonomy | **COMPLETE** | 100% |
| **02** | **Database & Models** | 34 SQLAlchemy 2.0 ORM models, 26 PostgreSQL enums, foreign keys, Alembic migrations, tenant isolation | **COMPLETE** | 100% (32 tests) |
| **03** | **Google Authentication** | OAuth2 code-grant flow, secure HTTP-only cookies, JWT verification, 5-role RBAC security matrix | **COMPLETE** | 100% |
| **04** | **Core Domain APIs** | Clean Architecture repositories, Unit of Work, 67 REST endpoints across 103 operations | **COMPLETE** | 100% (48 tests) |
| **05** | **External Ingestion** | 7 telemetry connectors: AISStream, OpenSky, TomTom, Weather, Tavily, Rail, Karrio | **COMPLETE** | 100% |
| **06** | **Normalization Engine** | Canonical event transformations, entity resolution engine, IMO/MMSI/ICAO correlation | **COMPLETE** | 100% |
| **07** | **Risk Engine** | Multi-factor deterministic risk scoring (Geopolitical, Climate, Transit, Financial), threshold alerts | **COMPLETE** | 100% (515 tests) |
| **08** | **Hybrid RAG** | Document chunking, AWS Bedrock Titan text embeddings (1536d), pgvector cosine + BM25 keyword search | **COMPLETE** | 100% (221 tests) |
| **09** | **LangGraph Orchestration** | 6 core agent nodes, immutable state contracts, deterministic routing edges, loop prevention | **COMPLETE** | 100% (1,284 tests) |
| **10** | **Bedrock + Claude** | Claude 3.5 Sonnet reasoning, structured output validation, security scrubbing, prompt engineering | **COMPLETE** | 100% (942 tests) |
| **11** | **Predictive ML** | Feature engineering pipeline, LightGBM GBDT shipment delay regression, model registry & rollback | **COMPLETE** | 100% (161 tests) |
| **12** | **Digital Twin** | Graph synthesis, RFC 4122 UUIDv5 identities, 6 node types, 4 edge types, bounded BFS pathfinding | **COMPLETE** | 100% (161 tests) |
| **13** | **Simulation Engine** | Multi-scenario perturbation, Monte Carlo temporal propagation, cascade financial loss metrics | **COMPLETE** | 100% (56 tests) |
| **14** | **Optimization Solver** | Google OR-Tools MILP solver, capacity/lead-time/budget constraints, multi-objective Pareto frontier | **COMPLETE** | 100% (36 tests) |
| **15** | **Decision Agent** | Multi-criteria mitigation evaluation, ranked candidate generation, Claude domain synthesis | **COMPLETE** | 100% (57 tests) |
| **16** | **Human Approval** | Mandatory sign-off perimeter, cryptographic SHA-256 fingerprinting, tamper prevention | **COMPLETE** | 100% (29 tests) |
| **17** | **Action Agent** | Governed execution, strict allowlist, idempotency caching, operational adapters (Reroute, Hold, etc.) | **COMPLETE** | 100% (69 tests) |
| **18** | **Verification Agent** | Post-action operational outcome verification, precedence hierarchy (REAL > ESTIMATED > SIMULATED), deterministic idempotency, fail-closed policy | **COMPLETE** | 100% (36 tests) |
| *19* | *Control Tower UI* | Real-time global dashboard, digital twin canvas, approval center, live telemetry layers | *ROADMAP* | — |
| *20* | *Evaluation Harness* | Continuous multi-agent benchmark, hallucination detection, regression evaluation | *ROADMAP* | — |
| *21* | *Production Hardening* | AWS VPC peering, AWS KMS envelope encryption, rate limiting, enterprise HA clustering | *ROADMAP* | — |

---

## Authoritative Repository Layout

RiskWise 2.0 maintains a strictly partitioned, modular monorepo structure:

```
riskwise/
├── .agents/                                   # Antigravity agent skills, plugins, and custom tooling
├── .env.example                               # Comprehensive environment configuration template
├── .gitignore                                 # Git ignore patterns for Python, Node, caches, and storage
├── AGENTS.md                                  # Agent development guidelines and framework rules
├── CLAUDE.md                                  # Claude code assistant workspace rules and commands
├── README.md                                  # Authoritative Master Project Documentation
├── credentials.json                           # Google OAuth2 client secrets template
│
├── api/                                       # Authoritative Backend API Service (FastAPI, Python 3.12 / 3.13)
│   ├── alembic/                               # Alembic database migration environment and version scripts
│   │   ├── env.py                             # Alembic migration runner binding target metadata
│   │   ├── script.py.mako                     # Migration script template
│   │   └── versions/                          # Schema revision files
│   ├── pyproject.toml                         # Project metadata, dependencies, and pytest configuration
│   ├── requirements.txt                       # Frozen runtime Python package dependencies
│   │
│   ├── app/                                   # Core Backend Application Package
│   │   ├── main.py                            # FastAPI entrypoint, middleware, CORS, security headers, routers
│   │   │
│   │   ├── agents/                            # Multi-Agent LangGraph Subsystem (Phases 9, 10, 15, 16, 17, 18)
│   │   │   ├── contracts.py                   # Frozen Pydantic agent state & transition schemas (AgentGraphState)
│   │   │   ├── edges.py                       # Deterministic and conditional routing edges between agent nodes
│   │   │   ├── graph.py                       # Compiled LangGraph workflow state machine
│   │   │   ├── nodes.py                       # Node wrapper functions with state transition validations
│   │   │   ├── observability.py               # Structured telemetry, timing, and agent logging
│   │   │   ├── recovery.py                    # Fallback, retry, and node-level recovery policies
│   │   │   ├── security.py                    # Agent action RBAC scopes and authorization guards
│   │   │   ├── validator.py                   # State boundary and contract invariant validator
│   │   │   │
│   │   │   ├── verification/                  # Phase 18: Operational Verification Agent
│   │   │   │   ├── agent.py                   # Core VerificationAgent orchestrator
│   │   │   │   ├── contract.py                # VerificationCommand, VerificationResultPayload, enums, fingerprinting
│   │   │   │   ├── errors.py                  # Strongly-typed verification domain error hierarchy
│   │   │   │   ├── evidence.py                # Read-only authoritative evidence collection & temporal filtering
│   │   │   │   ├── node.py                    # LangGraph node execution function (AgentStage.VERIFICATION)
│   │   │   │   ├── persistence.py             # Transactional persistence & idempotency manager
│   │   │   │   ├── policy.py                  # 16-step deterministic outcome evaluation policy
│   │   │   │   └── verifiers.py               # Specialized domain verifiers for all 6 action types
│   │   │   │
│   │   │   ├── action/                        # Phase 17: Operational Action Agent & Adapters
│   │   │   │   ├── agent.py                   # Core ActionAgent orchestrator
│   │   │   │   ├── contract.py                # ActionCommand, ActionResult, enums & fingerprinting
│   │   │   │   ├── errors.py                  # Strongly-typed action domain error hierarchy
│   │   │   │   ├── executors.py               # Operational domain executors (Reroute, Reallocate, Expedite, etc.)
│   │   │   │   ├── node.py                    # LangGraph node execution function (AgentStage.ACTION)
│   │   │   │   ├── persistence.py             # Transactional persistence & recommendation status update
│   │   │   │   └── policy.py                  # Safety allowlist, role checks & approval binding
│   │   │   │
│   │   │   ├── approval/                      # Phase 16: Human Approval Governance Agent
│   │   │   ├── decision/                      # Phase 15: Mitigation Decision Agent
│   │   │   ├── prediction/                    # Delay Forecasting Agent (Phases 9 & 11)
│   │   │   ├── research/                      # OSINT Intelligence & News Research Agent (Phases 9 & 10)
│   │   │   ├── risk/                          # Real-Time Composite Risk Evaluation Agent (Phase 9)
│   │   │   └── scenario/                      # What-If Disruption Scenario Agent (Phase 9)
│   │   │
│   │   ├── api/                               # REST API Layer (67 Endpoints across 103 Operations)
│   │   │   ├── deps.py                        # Dependencies (DB session, current user, tenant & RBAC guards)
│   │   │   └── v1/
│   │   │       ├── router.py                  # Consolidated v1 APIRouter registering 22 domain controllers
│   │   │       └── endpoints/                 # Domain REST controllers
│   │   │           ├── actions.py             # POST /actions/{id}/execute, GET /actions, GET /actions/{id}
│   │   │           ├── approvals.py           # POST /approvals, GET /approvals/{id}
│   │   │           ├── audit_logs.py          # GET /audit-logs
│   │   │           ├── auth.py                # Google OAuth2 login, callback, session verification, logout
│   │   │           ├── carriers.py            # Logistics carrier profiles and reliability ratings
│   │   │           ├── factories.py           # Manufacturing plants and operational throughput
│   │   │           ├── health.py              # Liveness, readiness, and database connectivity probes
│   │   │           ├── incidents.py           # Disruption event reporting, tracking, and resolution
│   │   │           ├── inventory.py           # Real-time stock levels and safety buffer metrics
│   │   │           ├── inventory_movements.py # Stock transfer history and inbound/outbound adjustments
│   │   │           ├── notifications.py       # Multi-channel alert dispatch and delivery
│   │   │           ├── ports.py               # Maritime container terminals and dwell times
│   │   │           ├── products.py            # SKU catalog, bills of materials, and criticality
│   │   │           ├── recommendations.py     # Mitigation options and recommendation review
│   │   │           ├── risk_assessments.py    # Multi-factor risk evaluations and scores
│   │   │           ├── risk_factors.py        # Granular geopolitical, climate, transit risk drivers
│   │   │           ├── risks.py               # Active operational risks and exposure tracking
│   │   │           ├── routes.py              # Multi-modal transport corridors and lanes
│   │   │           ├── shipment_events.py     # Waypoint milestones and tracking history
│   │   │           ├── shipments.py           # Consignment lifecycle, ETA calculation, and delays
│   │   │           ├── supplier_sites.py      # Vendor manufacturing facilities and geographic coordinates
│   │   │           ├── suppliers.py           # Tier-1/2/3 vendor organizational profiles
│   │   │           ├── verification_results.py# POST /verification-results/verify, GET /verification-results
│   │   │           └── warehouses.py          # Regional distribution centers and hubs
│   │   │
│   │   ├── core/                              # Cross-Cutting Infrastructure
│   │   │   ├── config.py                      # Pydantic V2 BaseSettings loaded from .env
│   │   │   ├── errors.py                      # Global exception handlers and error envelopes
│   │   │   └── logging.py                     # Structured JSON logging configuration
│   │   │
│   │   ├── db/                                # Database Connectivity & Session Lifecycle
│   │   │   ├── base.py                        # DeclarativeBase model registry
│   │   │   └── session.py                     # SQLAlchemy session factory and connection verification
│   │   │
│   │   ├── digital_twin/                      # Phase 12: Digital Twin Graph Subsystem
│   │   │   ├── builder.py                     # Graph synthesis from relational DB models
│   │   │   ├── contracts.py                   # TwinNode, TwinEdge, GraphSnapshot schemas
│   │   │   ├── pathfinding.py                 # Bounded BFS and alternate route pathfinders
│   │   │   └── query.py                       # Topological query engine and bottleneck identification
│   │   │
│   │   ├── simulation/                        # Phase 13: Disruption Simulation Engine
│   │   │   ├── engine.py                      # Monte Carlo perturbation propagation engine
│   │   │   ├── scenarios.py                   # Port closure, carrier insolvency, weather shock generators
│   │   │   └── contracts.py                   # SimulationConfig, CascadeResult schemas
│   │   │
│   │   ├── optimization/                      # Phase 14: Mathematical Optimization Subsystem
│   │   │   ├── solver.py                      # Google OR-Tools MILP solver engine
│   │   │   ├── constraints.py                 # Capacity, lead-time, budget, inventory balance models
│   │   │   └── contracts.py                   # OptimizationProblem, OptimizationSolution schemas
│   │   │
│   │   ├── integrations/                      # Phase 5: External Ingestion Connectors (7 Providers)
│   │   │   ├── aisstream.py                   # Live maritime vessel AIS WebSocket connector
│   │   │   ├── opensky.py                     # ADS-B aviation flight tracking REST connector
│   │   │   ├── tomtom.py                      # Road traffic congestion and routing connector
│   │   │   ├── openweather.py                 # Marine and terrestrial weather forecast connector
│   │   │   ├── tavily.py                      # OSINT global news and intelligence search connector
│   │   │   ├── rail.py                        # Rail corridor delay and schedule tracking connector
│   │   │   └── karrio.py                      # Multi-carrier logistics EDI & shipping label connector
│   │   │
│   │   ├── normalization/                     # Phase 6: Telemetry Normalization & Entity Correlation
│   │   │   ├── canonical.py                   # CanonicalEvent model and standard payloads
│   │   │   ├── entity_resolution.py           # IMO, MMSI, ICAO, UN/LOCODE matching algorithms
│   │   │   └── deduplication.py               # Sliding-window SHA-256 telemetry deduplicator
│   │   │
│   │   ├── risk_engine/                       # Phase 7: Deterministic Multi-Factor Risk Engine
│   │   │   ├── engine.py                      # Composite risk scoring orchestrator
│   │   │   ├── factors.py                     # Geopolitical, climate, transit, financial evaluators
│   │   │   └── alerts.py                      # Risk threshold evaluation and escalation triggers
│   │   │
│   │   ├── rag/                               # Phase 8: Hybrid RAG Knowledge Engine & Vector Search
│   │   │   ├── chunking.py                    # Semantic document chunking with metadata preservation
│   │   │   ├── embeddings.py                  # AWS Bedrock Titan text embeddings client (1536d)
│   │   │   ├── vector_store.py                # PostgreSQL pgvector similarity search repository
│   │   │   ├── hybrid_search.py               # Reciprocal Rank Fusion (RRF) of vector + BM25 search
│   │   │   └── context_assembler.py           # Grounded context assembly with source citations
│   │   │
│   │   ├── llm/                               # Phase 10: AWS Bedrock & Claude 3.5 Sonnet Integration
│   │   │   ├── client.py                      # AWS Bedrock Anthropic Claude client
│   │   │   ├── prompts.py                     # Domain-grounded prompt templates
│   │   │   ├── schemas.py                     # Pydantic structured output validation schemas
│   │   │   └── security.py                    # Prompt injection detection and PII scrubbing
│   │   │
│   │   ├── ml/                                # Phase 11: Machine Learning Shipment Delay Regression
│   │   │   ├── features.py                    # Feature engineering pipeline (distances, weather, historical)
│   │   │   ├── dataset.py                     # Training dataset generator and split validation
│   │   │   ├── model.py                       # LightGBM GBDT regression estimator wrapper
│   │   │   └── registry.py                    # Local artifact registry, versioning & fallback manager
│   │   │
│   │   ├── models/                            # SQLAlchemy 2.0 ORM Models (Strictly 34 Tables)
│   │   │   ├── organization.py                # Multi-tenant organization model
│   │   │   ├── user.py                        # User account and role assignment model
│   │   │   ├── supplier.py                    # Supplier and tier classification model
│   │   │   ├── supplier_site.py               # Vendor manufacturing site model
│   │   │   ├── factory.py                     # Internal assembly plant model
│   │   │   ├── warehouse.py                   # Regional distribution center model
│   │   │   ├── port.py                        # Maritime terminal, airport, and inland port model
│   │   │   ├── route.py                       # Multi-modal transit corridor model
│   │   │   ├── carrier.py                     # Freight carrier and reliability rating model
│   │   │   ├── product.py                     # SKU catalog and criticality model
│   │   │   ├── bill_of_materials.py           # Multi-level product component dependencies
│   │   │   ├── inventory_item.py              # Facility stock level and safety buffer model
│   │   │   ├── inventory_movement.py          # Inbound/outbound stock transfer ledger
│   │   │   ├── shipment.py                    # Consignment lifecycle, ETA, and delay tracking model
│   │   │   ├── shipment_event.py              # Telemetry tracking milestone event model
│   │   │   ├── risk.py                        # Identified operational risk exposure model
│   │   │   ├── risk_factor.py                 # Granular risk driver assessment model
│   │   │   ├── risk_assessment.py             # Time-stamped composite risk evaluation model
│   │   │   ├── incident.py                    # Disruption incident lifecycle model
│   │   │   ├── incident_update.py             # Incident milestone progress update model
│   │   │   ├── twin_node.py                   # Digital twin graph node snapshot model
│   │   │   ├── twin_edge.py                   # Digital twin graph edge relationship model
│   │   │   ├── simulation.py                  # Disruption simulation scenario configuration model
│   │   │   ├── simulation_result.py           # Simulation outcome, cascade, and financial loss model
│   │   │   ├── optimization_run.py            # Mathematical solver configuration and run model
│   │   │   ├── recommendation.py              # Mitigation recommendation option model
│   │   │   ├── approval.py                    # Cryptographic human sign-off audit model
│   │   │   ├── action.py                      # Operational execution command and adapter log model
│   │   │   ├── verification_result.py         # Authoritative post-action outcome verification model
│   │   │   ├── audit_log.py                   # Immutable security and compliance audit log model
│   │   │   ├── notification.py                # User alert dispatch and delivery record model
│   │   │   ├── agent_run.py                   # LangGraph multi-agent execution session model
│   │   │   ├── document.py                    # RAG document metadata and ingest status model
│   │   │   └── document_chunk.py              # RAG chunk content and vector embedding model
│   │   │
│   │   ├── repositories/                      # Clean Architecture Data Access Repositories
│   │   │   ├── base.py                        # Generic CRUD repository with tenant fencing
│   │   │   └── uow.py                         # Unit of Work transactional manager
│   │   │
│   │   └── schemas/                           # Pydantic V2 Request & Response Data Transfer Objects
│   │
│   └── tests/                                 # Comprehensive Backend Test Suite (4,506 Passing Tests)
│
├── web/                                       # Frontend Web Application (Next.js 14, React, Tailwind CSS)
│   ├── app/                                   # Next.js App Router layout and pages
│   ├── components/                            # Reusable UI component library
│   ├── lib/                                   # API client, auth utilities, and state hooks
│   └── package.json                           # Frontend package dependencies and scripts
│
└── docs/                                      # Full Architecture & Technical Specification Index
    ├── RiskWise_2.0_Technical_Project_Spec.md # Master Technical Project Architecture Specification
    ├── database-schema-inventory.md           # Authoritative 34-table relational database inventory
    ├── authentication-architecture.md         # Google OAuth2, multi-tenancy & RBAC governance
    ├── phase5-canonical-event-model.md        # Telemetry ingestion connectors specification
    ├── phase6-normalization-architecture.md   # Event normalization and entity resolution
    ├── phase7-risk-engine-architecture.md     # Deterministic multi-factor risk scoring
    ├── phase8-rag-architecture-contracts.md   # Hybrid RAG and vector storage architecture
    ├── phase9-langgraph-agent-state-contract.md # LangGraph multi-agent state contracts
    ├── phase10-bedrock-claude.md              # AWS Bedrock Claude 3.5 Sonnet integration
    ├── phase11-ml.md                          # Predictive machine learning delay estimator
    ├── phase12-digital-twin.md                # Digital Twin graph synthesis and query engine
    ├── phase13-simulation.md                  # Disruption simulation and scenario engine
    ├── phase14-optimization.md                # OR-Tools mathematical optimization solver
    ├── phase15-decision-agent.md              # Mitigation decision agent and option ranking
    ├── phase16-human-approval.md              # Human governance and approval subsystem
    ├── phase17-action-agent.md                # Operational action agent and execution adapters
    └── phase18-verification-agent.md          # Post-action verification agent and outcome evidence
```

---

## The 10 Core System Invariants & Safety Discipline

To guarantee enterprise compliance, deterministic outcomes, and prevent catastrophic automated actions, RiskWise 2.0 strictly enforces ten architectural invariants:

1. **Singular Source of Truth Authority**: Operational database tables (`suppliers`, `shipments`, `inventory`, `ports`, `factories`) are the singular source of truth. External telemetry, digital twin graphs, and simulation outputs are derivative projections.
2. **Zero Schema Drift Guarantee**: Exactly **34 database tables** and **26 enum domains** are maintained across all roadmap phases with zero uncoordinated migrations or schema modifications.
3. **Strict Multi-Tenant Isolation**: Every database query, API route, Digital Twin snapshot, simulation run, agent execution, and operational action is strictly scoped by `organization_id`. Tenant boundaries are verified in SQL queries, ORM layers, and API dependencies.
4. **Mandatory Human Approval Perimeter**: No operational action can execute without an authentic, unexpired `ApprovalResult` in `APPROVED` status signed by an authorized human role (`RiskManager` or `Admin`).
5. **Phase Boundary Separation**:
   - **Phase 15 (Decision Agent)**: Evaluates what action should happen.
   - **Phase 16 (Human Approval)**: Determines whether the action is permitted to execute.
   - **Phase 17 (Action Agent)**: Dispatches the approved action to the operational adapter.
   - **Phase 18 (Verification Agent)**: Strictly answers *"Did the approved action actually produce the intended operational outcome?"*
6. **Action Dispatch != Outcome Verification**: Successful action submission or adapter acknowledgement proves execution dispatch, but only authoritative post-action operational evidence can prove business outcome verification.
7. **Strict Source Precedence**: `REAL > ESTIMATED > SIMULATED`. Simulated telemetry or synthetic twin states can NEVER prove that a real-world action succeeded.
8. **Deterministic Verification Governance**: No probabilistic model, neural network, or large language model determines whether an action succeeded or failed. Verification policies are 100% deterministic code. Claude 3.5 Sonnet remains explanation-only.
9. **Fail-Closed Execution & No Autonomous Loops**: If verification fails or evidence is conflicting, the pipeline cleanly halts at Stage `VERIFICATION -> TERMINATION`. The graph never automatically re-runs optimization or dispatches new actions autonomously.
10. **SSRF, RCE & Parameter Neutralization**: Zero user-supplied URLs are accepted. Zero dynamic code execution (`eval()`, `exec()`) is permitted. All identifiers are validated through strict UUIDv4, UUIDv5, or alphanumeric schemas.

---

## Detailed Technical Deep-Dive of All 18 Completed Subsystems

### Phase 01: Core Foundation & Framework Architecture
- **Purpose**: Establishes the enterprise monorepo foundation, environment configuration, structured logging, and centralized error envelopes.
- **Key Features**:
  - Pydantic V2 `BaseSettings` supporting strict type parsing from `.env` files.
  - Asynchronous application context management with graceful startup and shutdown hooks.
  - High-performance structured JSON logging with correlation IDs (`request_id`, `trace_id`).
  - Standardized JSON:API error envelopes preventing stack trace leakage.

### Phase 02: Database Schema & Relational Integrity
- **Purpose**: Defines the authoritative relational foundation for the entire enterprise supply chain data model.
- **Key Features**:
  - Exactly 34 SQLAlchemy 2.0 ORM declarative models.
  - 26 PostgreSQL domain enums ensuring strict value domain integrity.
  - Foreign key constraints, cascade controls, and composite indexing on `(organization_id, id)`.
  - Alembic database migration management configured for AWS RDS PostgreSQL 16.

### Phase 03: Google Authentication & Enterprise RBAC
- **Purpose**: Governs identity, multi-tenant boundaries, and role-based access control.
- **Key Features**:
  - Secure Google OAuth2 code exchange flow.
  - Tamper-proof HTTP-only, SameSite cookies carrying signed JWT session tokens.
  - 5-role enterprise RBAC matrix: `Admin`, `RiskManager`, `OpsManager`, `Analyst`, `Viewer`.
  - Automated tenant context injection enforcing cross-tenant query prevention.

### Phase 04: Core Domain APIs & Clean Architecture
- **Purpose**: Provides high-throughput REST CRUD services across all core business entities.
- **Key Features**:
  - Clean Architecture pattern: Repositories -> Unit of Work -> Services -> Routers.
  - 67 REST endpoints across 103 operations and 22 controllers.
  - Full OpenAPI 3.1 specification auto-generation with interactive Swagger UI.

### Phase 05: External Telemetry Ingestion Connectors
- **Purpose**: Ingests real-world global telemetry across maritime, aviation, road, rail, weather, and news channels.
- **Key Features**:
  - **AISStream Connector**: Ingests real-time maritime AIS transponder messages (MMSI, coordinates, SOG, COG).
  - **OpenSky Connector**: Polls ADS-B flight tracking data for air freight consignments.
  - **TomTom Connector**: Captures highway congestion indices, road incidents, and transit delays.
  - **Open-Meteo Connector**: Ingests marine weather forecasts, gale warnings, and tropical storm trajectories.
  - **Tavily Connector**: Executes targeted OSINT news searches for geopolitical and labor disruptions.
  - **Rail Connector**: Ingests intermodal rail corridor throughput and terminal delays.
  - **Karrio Connector**: Connects multi-carrier logistics APIs for status milestones and tracking updates.

### Phase 06: Event Normalization & Entity Resolution
- **Purpose**: Translates heterogeneous telemetry streams into a canonical, deduplicated event format linked to operational entities.
- **Key Features**:
  - Canonical Event Model schema unifying timestamp, coordinate, source, and payload attributes.
  - High-accuracy entity resolution matching IMO/MMSI to `shipments`, ICAO to air freight, and UN/LOCODE to `ports`.
  - Sliding-window SHA-256 telemetry deduplication rejecting redundant or out-of-order frames.

### Phase 07: Deterministic Multi-Factor Risk Engine
- **Purpose**: Computes objective, reproducible risk scores across supply chain assets and transit lanes.
- **Key Features**:
  - 4 independent risk dimensions: **Geopolitical**, **Climate & Natural Hazards**, **Transit Congestion**, **Financial & Supplier Health**.
  - Calibrated deterministic weighting: `RiskScore = w_geo*S_geo + w_cli*S_cli + w_tra*S_tra + w_fin*S_fin`.
  - Dynamic threshold alerting generating automated incident candidates when risk exceeds tolerance bounds.

### Phase 08: Hybrid RAG Knowledge Engine & Vector Search
- **Purpose**: Enhances reasoning with contextual enterprise knowledge, SOPs, and carrier contracts.
- **Key Features**:
  - Document chunking with semantic overlap and metadata preservation.
  - AWS Bedrock Titan text embeddings (`amazon.titan-embed-text-v1`) generating 1536-dimensional vectors.
  - Hybrid retrieval combining PostgreSQL `pgvector` cosine similarity with BM25 full-text search via Reciprocal Rank Fusion (RRF).
  - Context assembly ensuring every extracted fact includes source document and section citations.

### Phase 09: LangGraph Multi-Agent Orchestration
- **Purpose**: Orchestrates specialized autonomous agents in a reliable, cyclic state machine.
- **Key Features**:
  - Immutable `AgentGraphState` contract with strict field ownership rules.
  - 6 core agent nodes: **Detection**, **Research**, **Risk Evaluation**, **Prediction**, **Scenario Analysis**, **Optimization**.
  - Deterministic routing edges with cycle counters and maximum iteration halts.

### Phase 10: AWS Bedrock & Claude 3.5 Sonnet Integration
- **Purpose**: Supplies domain-grounded generative reasoning and structured synthesis.
- **Key Features**:
  - Direct integration with Anthropic Claude 3.5 Sonnet on AWS Bedrock.
  - Pydantic structured output validation with retry schemas.
  - Prompt sanitization stripping prompt-injection attempts and PII.
  - Deterministic fallbacks ensuring business continuity when LLM endpoints are unreachable.

### Phase 11: Machine Learning Shipment Delay Regression
- **Purpose**: Forecasts quantitative consignment arrival delays using supervised machine learning.
- **Key Features**:
  - Feature engineering pipeline computing distance, carrier reliability, congestion, and weather indices.
  - LightGBM Gradient-Boosted Decision Tree (GBDT) regression models trained on historical shipping logs.
  - Model registry managing semantic model versioning, artifacts, and graceful fallback heuristics.

### Phase 12: Digital Twin Supply Chain Graph Engine
- **Purpose**: Synthesizes a unified topological graph of the entire supply chain network.
- **Key Features**:
  - RFC 4122 UUIDv5 deterministic node and edge identity generation.
  - 6 node types (`SUPPLIER`, `SUPPLIER_SITE`, `FACTORY`, `WAREHOUSE`, `PORT`, `CUSTOMER`).
  - 4 edge types (`FLOW`, `DEPENDENCY`, `TRANSPORT`, `CONTRACT`).
  - Bounded breadth-first search (BFS) pathfinding detecting single points of failure and bottlenecks.

### Phase 13: Disruption Simulation & Cascade Engine
- **Purpose**: Quantifies systemic operational shock propagation across the supply chain network.
- **Key Features**:
  - Monte Carlo simulation engine executing hundreds of perturbation iterations.
  - Cascade modeling across inventory buffer depletion, production stoppage, and revenue exposure.
  - Scenario definitions for port strikes, canal blockages, supplier insolvency, and extreme storms.

### Phase 14: Mathematical Optimization Subsystem
- **Purpose**: Solves multi-objective resource reallocation problems with mathematical precision.
- **Key Features**:
  - Google OR-Tools mixed-integer linear programming (MILP) solver.
  - Multi-constraint modeling: factory throughput limits, carrier vessel capacities, expedited shipping budgets.
  - Multi-objective Pareto frontier generation balancing transit time, operational cost, and CO2 emissions.

### Phase 15: Mitigation Decision Agent & Claude Synthesis
- **Purpose**: Evaluates optimization candidates and prepares executive-ready mitigation proposals.
- **Key Features**:
  - Multi-criteria decision analysis (MCDA) scoring mitigation options.
  - Claude 3.5 Sonnet domain-grounded synthesis explaining operational trade-offs and rationale.
  - Recommendation creation in `recommendations` table with status `PENDING`.

### Phase 16: Human Governance & Approval Subsystem
- **Purpose**: Enforces mandatory human-in-the-loop governance before any operational mutation occurs.
- **Key Features**:
  - Cryptographic SHA-256 state fingerprinting binding the exact recommendation payload.
  - Role-gated approval permissions (`RiskManager`, `Admin`).
  - Tamper detection: rejects approvals if underlying operational state or recommendation was modified.
  - Approval expiration window enforcing fresh review for stale recommendations.

### Phase 17: Operational Action Agent & Execution Adapters
- **Purpose**: Executes approved mitigation actions through governed operational adapters.
- **Key Features**:
  - Strict operational allowlist: `SHIPMENT_REROUTE`, `CARRIER_REALLOCATION`, `FACILITY_REALLOCATION`, `EXPEDITE_SHIPMENT`, `HOLD_SHIPMENT`, `MONITOR`.
  - SHA-256 command hashing enforcing strict execution idempotency (replays return cached result).
  - Transactional state updates transitioning recommendation to `EXECUTED`.
  - Immutable audit logging recording actor, timestamps, and adapter response codes in `audit_logs`.

### Phase 18: Operational Verification Agent & Outcome Evidence
- **Purpose**: Gathers authoritative post-action evidence to verify whether real-world business intent succeeded.
- **Key Features**:
  - Strict evidence source precedence hierarchy: `REAL > ESTIMATED > SIMULATED`.
  - 16-step deterministic policy evaluation pipeline.
  - 9 verification statuses: `VERIFIED`, `PARTIALLY_VERIFIED`, `FAILED`, `PENDING`, `INSUFFICIENT_EVIDENCE`, `NOT_APPLICABLE`, `EXPIRED`, `CONFLICT`, `ERROR`.
  - Fail-closed terminal execution: halts at `TERMINATION`, strictly prohibiting autonomous retry loops.

---

## Authoritative 34-Table Database Inventory

The RiskWise 2.0 relational database maintains exactly 34 models organized into 10 cohesive business domains:

| # | Domain | Table Name | Primary Key | Foreign Keys & Relationships | Operational Purpose |
| :---: | :--- | :--- | :---: | :--- | :--- |
| 1 | **Tenancy** | `organizations` | `id` (VARCHAR) | Root entity | Multi-tenant root organization entity, plans, settings |
| 2 | **Tenancy** | `users` | `id` (VARCHAR) | `organizations.id` | User accounts, roles (`Admin`, `RiskManager`, etc.), auth |
| 3 | **Network** | `suppliers` | `id` (VARCHAR) | `organizations.id` | Tier-1/2/3 vendor profiles, criticality, health rating |
| 4 | **Network** | `supplier_sites` | `id` (VARCHAR) | `organizations.id`, `suppliers.id` | Physical manufacturing facilities and geographic coordinates |
| 5 | **Network** | `factories` | `id` (VARCHAR) | `organizations.id` | Internal manufacturing plants, lines, capacity, status |
| 6 | **Network** | `warehouses` | `id` (VARCHAR) | `organizations.id` | Regional distribution centers, storage capacity |
| 7 | **Network** | `ports` | `id` (VARCHAR) | `organizations.id` | Sea terminals, airports, inland ports, dwell time |
| 8 | **Network** | `routes` | `id` (VARCHAR) | `organizations.id`, `ports.id` | Transport corridors, transit modes, distance, typical lead-time |
| 9 | **Network** | `carriers` | `id` (VARCHAR) | `organizations.id` | Logistics carriers, contract terms, reliability ratings |
| 10 | **Catalog** | `products` | `id` (VARCHAR) | `organizations.id` | Finished goods and critical sub-assemblies SKU catalog |
| 11 | **Catalog** | `bills_of_materials` | `id` (VARCHAR) | `organizations.id`, `products.id` | Multi-level product part dependencies and component ratios |
| 12 | **Inventory** | `inventory_items` | `id` (VARCHAR) | `organizations.id`, `products.id` | Real-time facility stock levels, safety buffers, reorder points |
| 13 | **Inventory** | `inventory_movements` | `id` (VARCHAR) | `organizations.id`, `inventory_items.id` | Stock transfer history and inbound/outbound adjustments |
| 14 | **Logistics** | `shipments` | `id` (VARCHAR) | `organizations.id`, `carriers.id`, `routes.id` | Consignment lifecycle, origin/dest, ETA, delay status |
| 15 | **Logistics** | `shipment_events` | `id` (VARCHAR) | `organizations.id`, `shipments.id` | Telemetry tracking milestone events and coordinates |
| 16 | **Risk** | `risks` | `id` (VARCHAR) | `organizations.id` | Identified operational risk exposures, severities, trends |
| 17 | **Risk** | `risk_factors` | `id` (VARCHAR) | `organizations.id`, `risks.id` | Granular risk drivers (geopolitical, weather, transit) |
| 18 | **Risk** | `risk_assessments` | `id` (VARCHAR) | `organizations.id`, `risks.id` | Time-stamped composite risk evaluations and scores |
| 19 | **Incident** | `incidents` | `id` (VARCHAR) | `organizations.id`, `risks.id` | Disruption incident tracking and resolution lifecycles |
| 20 | **Incident** | `incident_updates` | `id` (VARCHAR) | `organizations.id`, `incidents.id` | Chronological incident progress updates and logs |
| 21 | **Twin** | `twin_nodes` | `id` (VARCHAR) | `organizations.id` | Digital Twin graph node snapshots and RFC 4122 UUIDv5 IDs |
| 22 | **Twin** | `twin_edges` | `id` (VARCHAR) | `organizations.id`, `twin_nodes.id` | Digital Twin graph edge dependencies and flows |
| 23 | **Simulation**| `simulations` | `id` (VARCHAR) | `organizations.id` | Disruption simulation scenario parameters and mode |
| 24 | **Simulation**| `simulation_results` | `id` (VARCHAR) | `organizations.id`, `simulations.id` | Cascade impact metrics, delay days, financial loss values |
| 25 | **Solver** | `optimization_runs` | `id` (VARCHAR) | `organizations.id`, `simulations.id` | OR-Tools MILP solver configuration, constraints, and status |
| 26 | **Decision** | `recommendations` | `id` (VARCHAR) | `organizations.id`, `optimization_runs.id` | Ranked mitigation candidate options and trade-off scores |
| 27 | **Governance**| `approvals` | `id` (VARCHAR) | `organizations.id`, `recommendations.id`, `users.id` | Cryptographic human sign-off audit records and decisions |
| 28 | **Action** | `actions` | `id` (VARCHAR) | `organizations.id`, `approvals.id` | Governed operational execution command records and adapter logs |
| 29 | **Verify** | `verification_results` | `id` (VARCHAR) | `organizations.id`, `actions.id` | Authoritative post-action outcome verification results |
| 30 | **Audit** | `audit_logs` | `id` (VARCHAR) | `organizations.id`, `users.id` | Immutable security, compliance, and operational audit trail |
| 31 | **Alerts** | `notifications` | `id` (VARCHAR) | `organizations.id`, `users.id` | User alert notifications, severities, read status |
| 32 | **Agents** | `agent_runs` | `id` (VARCHAR) | `organizations.id` | Multi-agent LangGraph workflow execution records and state |
| 33 | **RAG** | `documents` | `id` (VARCHAR) | `organizations.id` | Ingested enterprise documents, SOPs, and policies |
| 34 | **RAG** | `document_chunks` | `id` (VARCHAR) | `organizations.id`, `documents.id` | Text chunks and 1536-dimensional Titan vector embeddings |

---

## REST API Architecture & Comprehensive Endpoint Catalog

The RiskWise 2.0 backend exposes 67 REST endpoints across 103 operations and 22 controllers registered under `/api/v1`:

```
/api/v1/
├── /health                          # Infrastructure liveness & readiness probes
├── /auth                            # Google OAuth2, JWT session cookies, logout
├── /suppliers                       # Supplier organizational profiles & criticality tiers
├── /supplier-sites                 # Supplier manufacturing sites & geographic locations
├── /factories                       # Internal manufacturing plants, capacity, & status
├── /warehouses                      # Regional distribution centers & stock capacities
├── /ports                           # Maritime container ports, airports, & dwell times
├── /carriers                        # Logistics carriers & reliability performance ratings
├── /products                        # SKU master catalog, bills of materials, & criticality
├── /routes                          # Multimodal corridors, transport modes, & lead times
├── /shipments                       # Consignment lifecycles, ETAs, delays, & routes
├── /shipment-events                 # Waypoint tracking milestones & GPS telemetry
├── /inventory                       # Real-time stock levels, buffers, & reorder thresholds
├── /inventory-movements             # Stock transfer movements & inbound/outbound adjustments
├── /risks                           # Operational risk exposures & composite risk trends
├── /risk-factors                    # Detailed risk drivers (geopolitical, weather, transit)
├── /risk-assessments                # Composite risk assessments & threshold evaluations
├── /incidents                       # Disruption incidents, investigation, & resolution
├── /recommendations                 # Ranked mitigation candidate options & Claude rationales
├── /approvals                       # Human approval sign-off perimeter & cryptographic checks
├── /actions                         # Governed operational action execution adapters
├── /verification-results            # Authoritative post-action outcome verification
├── /audit-logs                      # Immutable regulatory compliance & security audit logs
└── /notifications                   # Multi-channel notification delivery & alert feeds
```

### Key Endpoint Catalog by Subsystem

| Controller | HTTP | Endpoint Path | Operational Purpose | RBAC Scope |
| :--- | :---: | :--- | :--- | :---: |
| **Auth** | `POST` | `/api/v1/auth/google/login` | Initiates Google OAuth2 code exchange flow | Public |
| **Auth** | `GET` | `/api/v1/auth/session` | Validates session cookie and returns user context | Authenticated |
| **Auth** | `POST` | `/api/v1/auth/logout` | Clears HTTP-only session cookies and revokes token | Authenticated |
| **Shipments** | `GET` | `/api/v1/shipments` | Lists consignments with filtering by origin/carrier/status | `Viewer+` |
| **Shipments** | `POST` | `/api/v1/shipments` | Registers a new consignment tracking record | `OpsManager+` |
| **Shipments** | `GET` | `/api/v1/shipments/{id}` | Retrieves full consignment details, route, and milestone log | `Viewer+` |
| **Risks** | `GET` | `/api/v1/risks` | Queries active risk exposures and composite scores | `Viewer+` |
| **Risks** | `POST` | `/api/v1/risks` | Creates a new identified operational risk entity | `Analyst+` |
| **Incidents** | `GET` | `/api/v1/incidents` | Lists active disruption incidents and severity rankings | `Viewer+` |
| **Recommendations**| `GET` | `/api/v1/recommendations`| Lists ranked mitigation options generated by Decision Agent | `Viewer+` |
| **Approvals** | `POST` | `/api/v1/approvals` | Submits human approval decision with SHA-256 fingerprint | `RiskManager`, `Admin` |
| **Approvals** | `GET` | `/api/v1/approvals/{id}`| Retrieves cryptographic sign-off audit details | `Viewer+` |
| **Actions** | `POST` | `/api/v1/actions/{id}/execute` | Dispatches approved action to governed execution adapter | `OpsManager+` |
| **Actions** | `GET` | `/api/v1/actions/{id}` | Retrieves action execution status and adapter response code | `Viewer+` |
| **Verification** | `POST` | `/api/v1/verification-results/verify` | Executes authoritative post-action outcome verification | `RiskManager`, `Admin` |
| **Verification** | `GET` | `/api/v1/verification-results` | Queries historical verification results and evidence records | `Viewer+` |
| **Audit Logs** | `GET` | `/api/v1/audit-logs` | Queries immutable compliance and security audit records | `Admin`, `RiskManager` |
| **Health** | `GET` | `/health` | Root infrastructure liveness check | Public |
| **Health** | `GET` | `/health/db` | Database connectivity readiness probe (`SELECT 1`) | Public |

---

## Multi-Agent LangGraph State Machine Architecture

The RiskWise multi-agent intelligence layer is built on **LangGraph**, providing a cyclic, stateful, and deterministic orchestration machine:

### State Machine Transition Topology

```mermaid
stateDiagram-v2
    [*] --> DetectionNode: External Telemetry Signal
    DetectionNode --> ResearchNode: Disruption Threshold Breached
    ResearchNode --> RiskNode: Correlated Context & News Extracted
    RiskNode --> PredictionNode: Composite Risk Evaluated
    PredictionNode --> ScenarioNode: Delays Quantified
    ScenarioNode --> OptimizerNode: Network Shocks Modeled
    OptimizerNode --> DecisionNode: Optimal Candidates Solved
    DecisionNode --> HumanApprovalPerimeter: Mitigation Candidates Ranked
    
    state HumanApprovalPerimeter {
        [*] --> PendingReview
        PendingReview --> Approved: RiskManager Sign-Off
        PendingReview --> Rejected: RiskManager Rejection
    }
    
    Rejected --> [*]: Workflow Terminated
    Approved --> ActionNode: Governed Dispatch
    ActionNode --> VerificationNode: Adapter Dispatched
    VerificationNode --> [*]: Outcome Verified / Terminated
```

### Authoritative Field Ownership Contract

To prevent state corruption or uncoordinated field mutations in the LangGraph shared state (`AgentGraphState`), fields are strictly partitioned by authoritative owner:

| Agent Node | Permitted State Fields Written | Read-Only State Dependencies |
| :--- | :--- | :--- |
| **Detection** | `detected_events`, `active_incidents`, `current_stage` | `raw_telemetry` |
| **Research** | `research_findings`, `osint_context`, `rag_citations` | `active_incidents` |
| **Risk Evaluation** | `composite_risk_scores`, `dimension_breakdown` | `detected_events`, `research_findings` |
| **Prediction** | `predicted_delay_hours`, `ml_confidence_interval` | `composite_risk_scores`, `active_incidents` |
| **Scenario** | `simulation_scenario_id`, `cascade_metrics` | `predicted_delay_hours`, `digital_twin_id` |
| **Optimizer** | `optimization_run_id`, `pareto_candidates` | `cascade_metrics`, `constraints` |
| **Decision** | `decision_recommendations`, `claude_justification` | `pareto_candidates`, `rag_citations` |
| **Human Approval** | `approval_id`, `approval_status`, `fingerprint` | `decision_recommendations` |
| **Action** | `action_id`, `action_status`, `idempotency_key` | `approval_status`, `decision_recommendations` |
| **Verification** | `verification_id`, `verification_status`, `verification_result` | `action_id`, `action_status`, `authoritative_evidence` |

---

## Supported Operational Actions & Verification Matrix

The platform supports 6 governed operational action types. Each action type pairs a governed Phase 17 execution adapter with an authoritative Phase 18 outcome verification policy:

| Action Type | Target Entity | Phase 17 Execution Adapter | Operational Parameters | Phase 18 Verification Criteria & Authoritative Evidence |
| :--- | :---: | :--- | :--- | :--- |
| `SHIPMENT_REROUTE` | `shipment` | `ShipmentRerouteExecutor` | `target_route_id`, `target_port_id`, `corridor_code` | Verifies `Shipment.route_id` matches approved corridor or physical AIS GPS transponder confirms revised waypoint trajectory (`REAL` evidence). |
| `CARRIER_REALLOCATION` | `carrier` | `CarrierReallocationExecutor` | `target_carrier_id`, `booking_reference` | Verifies `Shipment.carrier_id` reassigned in database and carrier EDI confirms booking acceptance (`CARRIER_ACCEPTED`). |
| `FACILITY_REALLOCATION`| `facility` | `FacilityReallocationExecutor` | `source_facility_id`, `target_facility_id`, `units` | Verifies production or storage allocation load successfully rebalanced in `factories` or `warehouses`. |
| `EXPEDITE_SHIPMENT` | `shipment` | `ShipmentExpediteExecutor` | `transit_mode` (`AIR`), `airway_bill` | Verifies consignment transport mode updated to `AIR` and air freight airway bill booking milestone issued (`AIR_FREIGHT_BOOKED`). |
| `HOLD_SHIPMENT` | `shipment` | `ShipmentHoldExecutor` | `hold_reason_code`, `quarantine_location` | Verifies `Shipment.status` transitioned to `HELD` without contradictory release or dispatch milestone. |
| `MONITOR` | `incident` | `MonitorExecutor` | `monitoring_interval`, `metrics` | Passive continuous observation; verified as `NOT_APPLICABLE` (does not mutate operational state). |

---

## Post-Action Verification Agent (Phase 18) Deep-Dive

### Evidence Source Precedence Hierarchy

The Verification Agent enforces an inviolable evidence hierarchy:

```
REAL  >  ESTIMATED  >  SIMULATED
```

- **REAL**: Physical AIS transponder GPS telemetry, confirmed carrier EDI milestones, authoritative operational DB state changes.
- **ESTIMATED**: Machine learning delay predictions, mathematical ETA estimations.
- **SIMULATED**: Digital twin synthetic perturbations, what-if Monte Carlo simulations. *Can NEVER prove real-world success.*

### The 9 Verification Statuses

1. `VERIFIED`: The intended operational outcome was observed and proven by authoritative `REAL` evidence.
2. `PARTIALLY_VERIFIED`: Expected outcome observed, but evidence source is `ESTIMATED` or secondary operational sync is in flight.
3. `FAILED`: Authoritative evidence explicitly proves the intended outcome did not occur (e.g. carrier rejected booking, route unchanged).
4. `PENDING`: Action dispatched within allowable observation window; awaiting arrival of post-action telemetry.
5. `INSUFFICIENT_EVIDENCE`: No authoritative evidence exists, or only `SIMULATED` evidence was provided.
6. `NOT_APPLICABLE`: Passive operations (e.g., `MONITOR`) that do not alter operational state.
7. `EXPIRED`: Verification evaluated after the configured observation window without telemetry arrival.
8. `CONFLICT`: Contradictory authoritative evidence detected (e.g., reroute confirmed alongside carrier failure).
9. `ERROR`: Unhandled runtime or infrastructure exception encountered during verification evaluation.

### Deterministic 16-Step Verification Policy Pipeline

```mermaid
flowchart TD
    S1[1. Input Validation] --> S2[2. Action Entity Lookup]
    S2 --> S3[3. Execution State Check]
    S3 --> S4[4. Tenant Isolation Validation]
    S4 --> S5[5. Approval Binding Check]
    S5 --> S6[6. Action Type Compatibility]
    S6 --> S7[7. Target Entity Resolution]
    S7 --> S8[8. Passive Monitor Check]
    S8 --> S9[9. Authoritative Evidence Collection]
    S9 --> S10[10. Precedence Filtering]
    S10 --> S11[11. Temporal Window Validation]
    S11 --> S12[12. Conflict Detection]
    S12 --> S13[13. Specialized Verifier Execution]
    S13 --> S14[14. Payload Construction]
    S14 --> S15[15. Idempotent Persistence]
    S15 --> S16[16. Audit Log Emission]
```

---

## Verification & Automated Test Suite Metrics

RiskWise 2.0 maintains a 100% passing automated test suite with **4,506 automated backend tests** running across all completed roadmap phases:

```
================================================================================
Backend Test Suite Results: 4,506 passed, 0 failed, 0 skipped, 0 errors (100%)
================================================================================
```

### Complete Test Inventory by Subsystem

| Phase | Test Suite Module | Test Focus & Scope | Passing Tests |
| :---: | :--- | :--- | :---: |
| **18** | `api/tests/test_phase18_*.py` | Verification Agent, verifiers, evidence precedence, security, LangGraph node | **36** |
| **17** | `api/tests/test_phase17_*.py` | Action Agent, executors, allowlist, idempotency, approval binding, security | **69** |
| **16** | `api/tests/test_phase16_*.py` | Human Approval perimeter, SHA-256 fingerprinting, RBAC guards, tamper detection | **29** |
| **15** | `api/tests/test_phase15_*.py` | Mitigation Decision Agent, trade-off matrix, Claude domain synthesis | **57** |
| **14** | `api/tests/test_phase14_*.py` | Google OR-Tools MILP solver, multi-objective Pareto frontier, constraints | **36** |
| **13** | `api/tests/test_phase13_*.py` | Disruption Simulation Engine, Monte Carlo cascade modeling, financial metrics | **56** |
| **12** | `api/tests/test_phase12_*.py` | Digital Twin graph synthesis, UUIDv5 identities, bounded BFS pathfinding | **161** |
| **11** | `api/tests/test_phase11_*.py` | Machine Learning feature pipeline, LightGBM GBDT delay regression, registry | **161** |
| **10** | `api/tests/test_phase10_*.py` | AWS Bedrock & Claude 3.5 Sonnet reasoning, structured schemas, safety scrubbing | **942** |
| **09** | `api/tests/test_phase9_*.py` | LangGraph multi-agent orchestration, state machine contracts, routing edges | **1,284** |
| **08** | `api/tests/test_phase8_*.py` | Hybrid RAG, Titan embeddings, pgvector cosine search, BM25 Reciprocal Rank Fusion | **221** |
| **07** | `api/tests/test_phase7_*.py` | Deterministic multi-factor risk scoring engine, evidence assessment, alerts | **515** |
| **04** | `api/tests/test_phase4_*.py` | Core domain REST APIs, Clean Architecture repositories, Unit of Work | **48** |
| **05–06**| `api/tests/test_phase5_*.py`, `test_phase6_*.py` | Ingestion connectors, canonical event normalization, entity resolution | **120** |
| **02–03**| `api/tests/test_database_validation.py`, `test_auth_*.py` | Database schema validation, Google OAuth2, JWT sessions, RBAC security | **771** |
| **Total**| **Complete Backend Test Suite** | **All 18 Completed Roadmap Subsystems** | **4,506** |

### Running the Test Suite

```bash
cd api

# Run the complete test suite:
pytest -q

# Run Phase 18: Verification Agent tests (36 tests):
pytest tests/test_phase18_*.py -v

# Run Phase 17: Operational Action Agent tests (69 tests):
pytest tests/test_phase17_*.py -v

# Run Phase 16: Human Governance tests (29 tests):
pytest tests/test_phase16_*.py -v

# Run Phase 15: Mitigation Decision Agent tests (57 tests):
pytest tests/test_phase15_*.py -v

# Run Phase 14: Mathematical Optimization tests (36 tests):
pytest tests/test_phase14_*.py -v

# Run Phase 12: Digital Twin Graph tests (161 tests):
pytest tests/test_phase12_*.py -v

# Run Phase 09: Multi-Agent LangGraph Orchestration tests (1,284 tests):
pytest tests/test_phase9_*.py -q
```

---

## Local Development, Setup & Configuration Guide

### 1. Prerequisites
- **Python**: `3.12` or `3.13` (Virtual environment recommended)
- **Node.js**: `v20.x` or later (LTS)
- **npm**: `v10.x` or later
- **PostgreSQL**: `v15` or later with `pgvector` and `pgcrypto` extensions (or SQLite for local test suite execution)
- **Git**

### 2. Environment Configuration
Copy the environment template and configure your credentials:
```bash
cp .env.example .env
```

Key environment configuration variables:
```dotenv
# Application Settings
PROJECT_NAME="RiskWise API"
VERSION="2.0.0"
ENVIRONMENT="development"
DEBUG=true

# Database (PostgreSQL 16)
DB_HOST="localhost"
DB_PORT="5432"
DB_USER="riskwise_admin"
DB_PASSWORD="your_secure_password"
DB_NAME="riskwise"

# Google OAuth2 Authentication
GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET="your-google-client-secret"
JWT_SECRET_KEY="your-random-32-byte-secret-key"

# AWS Bedrock & Claude 3.5 Sonnet
AWS_REGION="us-east-1"
AWS_ACCESS_KEY_ID="your-aws-access-key"
AWS_SECRET_ACCESS_KEY="your-aws-secret-key"
BEDROCK_CLAUDE_MODEL_ID="anthropic.claude-3-5-sonnet-20241022-v2:0"
BEDROCK_EMBEDDING_MODEL_ID="amazon.titan-embed-text-v1"

# Telemetry Integrations
AISSTREAM_API_KEY="your-aisstream-key"
OPENSKY_USERNAME="your-opensky-username"
OPENSKY_PASSWORD="your-opensky-password"
TOMTOM_API_KEY="your-tomtom-key"
TAVILY_API_KEY="your-tavily-key"
```

### 3. Backend Development (`api`)
```bash
cd api

# Activate virtual environment:
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies:
pip install -r requirements.txt

# Run database migrations:
alembic upgrade head

# Start FastAPI development server:
uvicorn app.main:app --reload --port 8000
```

#### API Health Probes & Documentation:
- **Liveness Probe**: [http://localhost:8000/health](http://localhost:8000/health)
- **Readiness Probe**: [http://localhost:8000/ready](http://localhost:8000/ready)
- **Database Connectivity Probe**: [http://localhost:8000/health/db](http://localhost:8000/health/db)
- **Interactive Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Interactive ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI 3.1 JSON Specification**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

### 4. Frontend Development (`web`)
```bash
cd web

# Install dependencies:
npm install

# Start Next.js development server:
npm run dev
```
The Next.js web application is accessible at [http://localhost:3000](http://localhost:3000).

---

## Complete Documentation Index

Exhaustive technical documentation and architecture specifications are available in [`docs/`](docs/):

- [`docs/RiskWise_2.0_Technical_Project_Spec.md`](docs/RiskWise_2.0_Technical_Project_Spec.md) — Master technical architecture and system specification
- [`docs/database-schema-inventory.md`](docs/database-schema-inventory.md) — Complete 34-table relational database inventory and enum types
- [`docs/authentication-architecture.md`](docs/authentication-architecture.md) — Google OAuth2, multi-tenancy & enterprise RBAC governance
- [`docs/phase5-canonical-event-model.md`](docs/phase5-canonical-event-model.md) — Telemetry ingestion connectors specification
- [`docs/phase6-normalization-architecture.md`](docs/phase6-normalization-architecture.md) — Telemetry normalization & entity resolution engine
- [`docs/phase7-risk-engine-architecture.md`](docs/phase7-risk-engine-architecture.md) — Deterministic multi-factor risk scoring engine
- [`docs/phase8-rag-architecture-contracts.md`](docs/phase8-rag-architecture-contracts.md) — Hybrid RAG and vector storage architecture
- [`docs/phase9-langgraph-agent-state-contract.md`](docs/phase9-langgraph-agent-state-contract.md) — LangGraph multi-agent state machine contracts
- [`docs/phase10-bedrock-claude.md`](docs/phase10-bedrock-claude.md) — AWS Bedrock & Claude 3.5 Sonnet integration
- [`docs/phase11-ml.md`](docs/phase11-ml.md) — Predictive machine learning delay forecasting
- [`docs/phase12-digital-twin.md`](docs/phase12-digital-twin.md) — Digital Twin graph synthesis and query engine
- [`docs/phase13-simulation.md`](docs/phase13-simulation.md) — Disruption simulation & cascade engine
- [`docs/phase14-optimization.md`](docs/phase14-optimization.md) — Google OR-Tools mathematical optimization solver
- [`docs/phase15-decision-agent.md`](docs/phase15-decision-agent.md) — Mitigation decision agent and candidate ranking
- [`docs/phase16-human-approval.md`](docs/phase16-human-approval.md) — Human governance and approval subsystem
- [`docs/phase17-action-agent.md`](docs/phase17-action-agent.md) — Operational action agent and execution adapters
- [`docs/phase18-verification-agent.md`](docs/phase18-verification-agent.md) — Post-action verification agent and outcome evidence

---

## Enterprise License & Operational Notice

RiskWise 2.0 is proprietary and confidential enterprise software. All rights reserved.  
The Verification Agent enforces conservative, fail-closed operational outcome verification across all completed roadmap phases and does not permit autonomous remediation loops.
