# RiskWise 2.0 — Technical Project Specification
### AI-Powered Supply Chain Risk Intelligence & Decision Platform

**Companion document:** `RiskWise_2.0_UI_UX_Design_System.md` (design tokens, components, screen specs). Build the frontend against that document's colors, typography, and component definitions — this document defines everything behind the screens: architecture, stack, data, APIs, and business logic.

This document is written as a build brief for an agentic engineering tool. It defines what to build, in what shape, with what stack, and to what standard — not a step-by-step tutorial. Where a decision is genuinely open (e.g. "Postgres vs. a dedicated graph DB for the twin"), that's called out explicitly rather than silently picked, so the build can start from an informed default and be revisited.

---

## 1. Project overview

**Product:** RiskWise 2.0 is a multi-tenant enterprise SaaS control center for supply-chain risk. It ingests network and shipment data, detects and scores risk in near real time, runs a multi-agent AI investigation pipeline over emerging incidents, simulates "what-if" scenarios against a digital twin of the supply chain, recommends and optimizes mitigations, and routes high-impact actions through human approval before execution — with a full audit trail.

**Primary users:** supply-chain analysts (day-to-day monitoring, triage), risk managers (investigation, approval), operations managers (shipment/supplier action), executives (dashboards, reports).

**Core product pillars → system requirements:**
| Pillar | What the system must do |
|---|---|
| Real-time visibility | Ingest and serve live shipment/supplier/facility state at low latency |
| AI risk detection | Continuously score risk from structured + unstructured signals |
| Multi-agent investigation | Orchestrate a traceable, evidence-based agent pipeline per incident |
| Prediction | Forecast disruption likelihood, delay, and financial exposure with confidence |
| Simulation | Run deterministic and stochastic what-if scenarios against a network model |
| Optimization | Recommend and rank mitigations against a multi-objective cost function |
| Human approval | Gate high-impact actions behind an auditable approval workflow |
| Auditability | Record every AI and human action with who/what/when/why/evidence |

---

## 2. Success criteria & non-functional targets

- P95 API response time < 300ms for read endpoints, < 1.5s for write/action endpoints.
- Live map/shipment position updates delivered to the client within 5s of ingestion (WebSocket push, not polling).
- Agent pipeline (Detection → Verification) completes a standard incident investigation in < 90s end-to-end for the automated stages; human approval steps are excluded from this budget.
- 99.9% uptime SLA for the core API and web app; degraded-provider states (§12) must never surface as a silent failure to the user.
- Every AI-generated number in the product is traceable to a source, timestamp, model/version, and confidence value in the API response — the frontend cannot render one without the backend supplying it (this is enforced by API contract, not just UI convention).
- Multi-tenant data isolation: no query path can return another organization's data, enforced at the database row level (see §10.3).

---

## 3. System architecture

RiskWise is a **polyglot service architecture**, not a single monolith and not a maximal microservices split — the split follows a real seam: deterministic business logic (CRUD, workflow, auth) vs. AI orchestration (agents, LLM calls, tool use). Splitting there lets each half scale, deploy, and be tested independently without the overhead of a dozen tiny services.

```
                              ┌─────────────────────┐
                              │   Web App (Next.js)  │
                              │  UI per design system │
                              └──────────┬───────────┘
                                         │ REST + WebSocket
                              ┌──────────▼───────────┐
                              │   API Gateway / BFF    │  (NestJS)
                              │  auth, rate limit,     │
                              │  request shaping        │
                              └──────┬───────────┬─────┘
                    ┌────────────────┘           └────────────────┐
        ┌───────────▼───────────┐                     ┌───────────▼────────────┐
        │   Core Platform API    │                     │  AI Orchestration Svc   │
        │   (NestJS / TypeScript) │◄───event bus──────►│   (FastAPI / Python)     │
        │ suppliers, shipments,   │   (Kafka/Redis      │ agent pipeline, LLM,     │
        │ risks, approvals, audit │    Streams)          │ prediction, optimization │
        └───────────┬─────────────┘                     └───────────┬────────────┘
                    │                                              │
        ┌───────────▼─────────────┐                    ┌───────────▼────────────┐
        │  PostgreSQL (+ TimescaleDB)│                  │ Vector store (pgvector)  │
        │  primary relational store  │                  │ agent knowledge / RAG     │
        └────────────────────────────┘                  └──────────────────────────┘
                    │
        ┌───────────▼─────────────┐        ┌─────────────────────────┐
        │  Redis (cache + pub/sub)  │        │  Object storage (S3)      │
        └────────────────────────────┘        │  reports, exports, docs   │
                                               └─────────────────────────┘

External data ingestion (weather, vessel/port tracking, news/geopolitical feeds, ERP
connectors) lands via a dedicated Ingestion Service that normalizes and writes into
Postgres/Kafka — see §12.
```

**Why this split:**
- The **Core Platform API** owns everything that must be strongly consistent and auditable: entities, relationships, approvals, RBAC, audit log. TypeScript/NestJS gives strict typing across a large domain model and a mature ecosystem for RBAC, validation, and OpenAPI generation.
- The **AI Orchestration Service** owns everything that talks to LLMs, runs the agent pipeline, does prediction/simulation/optimization math. Python is the right tool here for its ML/optimization ecosystem (LangGraph, NumPy/SciPy, OR-Tools, Prophet) — forcing this into TypeScript would mean reinventing or thinly wrapping Python libraries.
- The two communicate over an **event bus** (not synchronous chained REST calls) so a long-running agent pipeline doesn't block a request thread, and so the Core API can react to agent output (write a Recommendation, notify a user) the same way it reacts to any other domain event.

---

## 4. Tech stack

### 4.1 Frontend
| Layer | Choice | Why |
|---|---|---|
| Framework | Next.js 14 (App Router), TypeScript | SSR for fast first paint on data-heavy dashboards, file-based routing matches the sidebar's screen list 1:1 |
| Styling | Tailwind CSS, tokens mapped from the design system's CSS variables | Utility classes keep the hairline/flat-surface discipline enforceable in code review |
| Component primitives | Radix UI (unstyled, accessible) wrapped in RiskWise's own styled component library | Radix gives correct keyboard/focus/ARIA behavior for free; RiskWise skins it per §4 of the design system rather than adopting a pre-styled kit whose defaults fight the brief |
| Server state | TanStack Query (React Query) | Caching, background refetch, and the "data freshness" timestamp requirement map directly onto its `dataUpdatedAt` |
| Client/UI state | Zustand | Lightweight, avoids Redux boilerplate for shell state (sidebar collapse, active filters, selected map layer) |
| Map | Mapbox GL JS (or MapLibre GL for a fully open-source path) + deck.gl for the route/hotspot overlay layers | deck.gl handles thousands of shipment points/routes at 60fps, which Recharts/D3 alone cannot |
| Network graph (Digital Twin) | React Flow | Purpose-built for interactive node/edge graphs with custom node renderers — matches the twin's diamond/square/hexagon node shapes |
| Charts | Recharts for standard line/bar/area; a thin D3 layer only for the risk matrix and Sankey/flow views | Recharts covers 90% of the chart needs declaratively; D3 is reserved for the two chart types Recharts can't express cleanly |
| Real-time | Native WebSocket client via a typed thin wrapper (or Socket.io-client if the gateway uses Socket.io) | Matches the WebSocket gateway in §11 |
| Forms | React Hook Form + Zod | Schema validation shared in spirit with the backend's Zod/class-validator DTOs |
| Testing | Vitest + React Testing Library, Playwright for E2E | Standard, fast, CI-friendly |

### 4.2 Core Platform API
| Layer | Choice | Why |
|---|---|---|
| Framework | NestJS (TypeScript, Node 20 LTS) | Structured module system matches the domain's natural boundaries (suppliers, shipments, risk, approvals...); built-in DI, guards, interceptors cover auth/audit cleanly |
| ORM | Prisma | Type-safe schema-to-client generation, good migration story, works well with Postgres row-level security |
| Validation | class-validator / class-transformer (or Zod via nestjs-zod) | Request DTO validation at the edge, before anything touches business logic |
| API style | REST, OpenAPI 3.1 spec auto-generated (nestjs/swagger) | REST is the right fit here — the domain is resource-oriented (suppliers, shipments, risks) rather than needing GraphQL's flexible querying; OpenAPI spec becomes the frontend's typed client source |
| Auth | OAuth2/OIDC via Auth0 (or self-hosted Keycloak for on-prem/enterprise deployments), JWT access tokens, refresh rotation | Enterprise buyers expect SSO/SAML; Auth0/Keycloak both support it without building it from scratch |
| Background jobs | BullMQ (Redis-backed) | Report generation, scheduled ingestion triggers, digest notifications |
| Realtime gateway | NestJS WebSocket Gateway (Socket.io adapter) | Push risk/shipment/notification updates to connected clients |

### 4.3 AI Orchestration Service
| Layer | Choice | Why |
|---|---|---|
| Framework | FastAPI (Python 3.12) | Async-first, fast, typed via Pydantic — matches the need for many concurrent agent runs |
| Agent orchestration | LangGraph (or a hand-rolled state-machine orchestrator if LangGraph's abstractions don't fit the exact 10-stage pipeline in §9.2) | Gives explicit, inspectable state transitions between agent stages — critical since the product's trust story depends on being able to show *why* the pipeline reached a conclusion |
| LLM provider | Anthropic Claude API (Claude Sonnet for standard investigation reasoning, Claude Opus for high-stakes/complex multi-hop research) | Structured tool use and long-context research synthesis fit the Research/Decision agent roles |
| Retrieval / knowledge base | pgvector (Postgres extension) for embeddings, keeping vector data in the same operational database rather than standing up a separate vector DB — revisit for a dedicated store (Pinecone/Weaviate) only if embedding volume outgrows Postgres | Simpler ops for v1; avoids a second database to keep consistent with the primary store |
| Forecasting (Prediction agent) | Prophet or a gradient-boosted model (LightGBM) over historical shipment/incident time series, versioned via MLflow | Prophet is a reasonable default for delay/ETA forecasting with seasonality; LightGBM for feature-rich disruption-probability models |
| Optimization (Optimization agent) | Google OR-Tools (CP-SAT or linear solver) for the mitigation-ranking multi-objective problem | Purpose-built constraint/optimization solver rather than hand-rolled heuristics |
| Simulation engine | Custom discrete-event / Monte Carlo simulator over the network graph model, built on NumPy/SciPy | Scenario simulation needs stochastic runs (capacity reduction, delay distributions) that a simple deterministic calculation can't represent honestly |
| Task queue | Celery or native async workers consuming from Kafka/Redis Streams | Long-running agent pipelines and simulation runs shouldn't block the request/response cycle |

### 4.4 Data layer
| Store | Purpose |
|---|---|
| **PostgreSQL 16** (primary OLTP) | Suppliers, facilities, shipments, risks, incidents, recommendations, approvals, users, orgs, audit log — the system of record |
| **TimescaleDB** (Postgres extension) | Time-series tables: shipment position history, risk-score history, KPI history for sparklines/trends |
| **pgvector** (Postgres extension) | Embeddings for the Research agent's knowledge base / RAG over evidence documents |
| **Redis** | Session cache, WebSocket pub/sub fan-out, BullMQ/Celery queue backing, rate-limit counters |
| **S3-compatible object storage** | Generated reports (PDF/XLSX), uploaded documents, exported audit bundles |
| **Kafka (or Redis Streams for a lighter v1)** | Event bus between Core API and AI Orchestration Service; ingestion pipeline event stream |

**Open decision — Digital Twin graph storage:** the network graph (supplier → factory → port → route → warehouse → customer) can be modeled as relational tables with adjacency (simplest, fits Postgres, sufficient for the twin's actual query patterns: "show me this node's neighbors," "find paths affected by this port") or as a dedicated graph database (Neo4j) if multi-hop dependency queries become a bottleneck. **Default: relational adjacency in Postgres for v1** — introduce Neo4j only if profiling shows multi-hop traversal queries are actually slow, not preemptively.

### 4.5 Infrastructure & DevOps
| Layer | Choice |
|---|---|
| Cloud | AWS (primary target; architecture stays portable — no proprietary services with no OSS equivalent) |
| Compute | ECS Fargate for the Core API and AI Orchestration Service (simpler ops than EKS for a v1 team size); revisit EKS/Kubernetes if the org needs multi-cluster or complex autoscaling policies later |
| Database hosting | Amazon RDS for PostgreSQL (Multi-AZ), ElastiCache for Redis |
| Event streaming | Amazon MSK (managed Kafka) or Redis Streams on ElastiCache for a lighter v1 |
| Object storage | S3 |
| CDN | CloudFront in front of the Next.js static assets |
| IaC | Terraform, one module per bounded context (network, data, compute, observability) |
| CI/CD | GitHub Actions: lint → typecheck → unit test → build → integration test → deploy to staging → manual promote to prod |
| Containers | Docker, multi-stage builds, distroless final images |
| Secrets | AWS Secrets Manager, injected at deploy time — never committed, never logged |

### 4.6 Observability & security tooling
| Concern | Choice |
|---|---|
| Tracing/metrics | OpenTelemetry SDK in both services, exported to a Grafana/Tempo/Prometheus stack (or AWS X-Ray/CloudWatch if staying fully AWS-native) |
| Logs | Structured JSON logs, shipped to CloudWatch Logs or Loki |
| Error tracking | Sentry (frontend + both backend services) |
| Uptime/alerting | Grafana Alerting or CloudWatch Alarms → PagerDuty/Slack |
| Dependency/vuln scanning | Dependabot + Snyk (or GitHub's native code scanning) in CI |
| WAF | AWS WAF in front of the ALB/CloudFront |

---

## 5. Repository structure

Monorepo (Turborepo or Nx) so the frontend's generated API client always tracks the backend's OpenAPI spec in the same commit.

```
riskwise/
├── apps/
│   ├── web/                     # Next.js frontend
│   ├── api/                     # NestJS Core Platform API
│   └── ai-orchestrator/         # FastAPI AI Orchestration Service
├── packages/
│   ├── design-tokens/           # colors, type scale, spacing — source of truth, consumed by web/ Tailwind config
│   ├── ui/                      # shared React component library (MetricCard, RiskBadge, DataTable, ...)
│   ├── api-client/               # generated TypeScript client from the OpenAPI spec
│   └── types/                    # shared TS types for domain entities (mirrors Prisma schema)
├── infra/
│   ├── terraform/
│   └── docker/
├── docs/
│   ├── RiskWise_2.0_UI_UX_Design_System.md
│   ├── RiskWise_2.0_Technical_Project_Spec.md   (this file)
│   └── adr/                      # architecture decision records for the "open decisions" called out in this doc
└── .github/workflows/
```

---

## 6. Data model

Core entities and their key fields. This is the contract both services and the frontend build against — treat field names as fixed unless a documented reason changes them.

### 6.1 Tenancy & identity
```
Organization      { id, name, plan, created_at, settings_json }
User              { id, org_id, email, name, role, sso_provider, last_active_at }
Role              { id, name, permissions[] }         # Admin, RiskManager, Analyst, OpsManager, Executive, Viewer
```

### 6.2 Network entities
```
Supplier          { id, org_id, name, country, criticality, reliability_score,
                    financial_exposure, lead_time_days, alt_supplier_ids[], current_risk_id }
Facility          { id, org_id, type[factory|warehouse|port], name, lat, lng, capacity, utilization }
Product           { id, org_id, sku, name, category }
Route             { id, org_id, origin_facility_id, destination_facility_id, mode[vessel|air|road|rail],
                    lead_time_days, capacity, current_utilization }
Shipment          { id, org_id, route_id, product_id, carrier, status, origin, destination,
                    current_lat, current_lng, eta, eta_confidence, delay_days, risk_id, data_provenance[real|estimated|simulated] }
```

### 6.3 Risk & investigation
```
Risk              { id, org_id, title, type, severity, location, probability, impact,
                    risk_score, confidence, trend, detected_at, updated_at, source }
Incident          { id, org_id, risk_id, title, status, severity, detected_at, resolved_at,
                    source, location, affected_asset_ids[] }
Evidence          { id, incident_id|risk_id, source_name, source_url, excerpt, timestamp, confidence }
AgentRun          { id, incident_id, workflow, trigger, status, started_at, completed_at, confidence, outcome }
AgentStep         { id, agent_run_id, agent_name[Research|Risk|Prediction|Scenario|Decision],
                    status, duration_ms, tools_used[], evidence_ids[], findings_json, confidence }
Prediction        { id, risk_id, model_name, model_version, forecast_json, confidence, generated_at }
```

### 6.4 Simulation & optimization
```
Scenario          { id, org_id, name, event_description, variables_json, created_by, created_at }
SimulationRun     { id, scenario_id, status, baseline_json, result_json, started_at, completed_at }
OptimizationRun   { id, org_id, objective, candidate_actions_json, recommended_plan_json, created_at }
```

### 6.5 Decisions & audit
```
Recommendation    { id, org_id, title, rationale, evidence_ids[], expected_benefit_json,
                    estimated_cost, confidence, status[pending|approved|rejected|modified|auto_applied] }
Approval          { id, recommendation_id, requested_by_agent_run_id, decided_by_user_id,
                    decision, decided_at, comment }
AuditLog          { id, org_id, actor_type[user|agent], actor_id, action, resource_type,
                    resource_id, status, request_id, timestamp, before_json, after_json }
Notification      { id, org_id, user_id, category, severity, summary, related_resource, read_at, created_at }
```

**Row-level security:** every table carrying `org_id` has a Postgres RLS policy scoping all reads/writes to the requesting session's org — enforced at the database layer, not just in application code, so a bug in one API route can't leak cross-tenant data.

---

## 7. API specification

REST, versioned under `/api/v1`. Auth via `Authorization: Bearer <JWT>`. All list endpoints support `?page`, `?pageSize`, `?sort`, and domain-specific filters. All timestamps are ISO 8601 UTC.

### 7.1 Endpoint groups

| Domain | Base path | Key endpoints |
|---|---|---|
| Auth | `/auth` | `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me` |
| Organizations | `/orgs` | `GET/PATCH /orgs/:id`, `GET /orgs/:id/members` |
| Suppliers | `/suppliers` | `GET /suppliers`, `GET /suppliers/:id`, `GET /suppliers/:id/dependency-graph`, `GET /suppliers/:id/risk-history` |
| Facilities | `/facilities` | `GET /facilities`, `GET /facilities/:id` |
| Shipments | `/shipments` | `GET /shipments`, `GET /shipments/:id`, `GET /shipments/:id/timeline`, `GET /shipments/:id/prediction` |
| Routes | `/routes` | `GET /routes`, `GET /routes/:id` |
| Risks | `/risks` | `GET /risks`, `GET /risks/:id`, `GET /risks/:id/evidence`, `GET /risks/:id/matrix-position` |
| Incidents | `/incidents` | `GET /incidents`, `GET /incidents/:id`, `GET /incidents/:id/agent-runs`, `GET /incidents/:id/timeline` |
| Predictions | `/predictions` | `GET /predictions?risk_id=` |
| Scenarios | `/scenarios` | `POST /scenarios`, `GET /scenarios`, `GET /scenarios/:id`, `POST /scenarios/:id/run` |
| Simulation runs | `/simulation-runs` | `GET /simulation-runs/:id`, `GET /simulation-runs/:id/compare?baseline=` |
| Optimization | `/optimization-runs` | `POST /optimization-runs`, `GET /optimization-runs/:id` |
| Recommendations | `/recommendations` | `GET /recommendations`, `POST /recommendations/:id/approve`, `POST /recommendations/:id/reject`, `POST /recommendations/:id/modify` |
| Approvals | `/approvals` | `GET /approvals` (queue), `GET /approvals/history` |
| Agent runs | `/agent-runs` | `GET /agent-runs`, `GET /agent-runs/:id/steps` |
| Audit | `/audit-logs` | `GET /audit-logs` (filterable by user/agent/action/resource/date/severity) |
| Notifications | `/notifications` | `GET /notifications`, `PATCH /notifications/:id/read` |
| Reports | `/reports` | `POST /reports/generate`, `GET /reports/:id`, `GET /reports/:id/export` |
| Search | `/search` | `GET /search?q=` (cross-entity, grouped by type) |
| Integrations | `/integrations` | `GET /integrations`, `PATCH /integrations/:id`, `POST /integrations/:id/test` |

### 7.2 Response contract for AI-derived data

Every field that originates from an agent, model, or prediction must be returned inside an envelope that carries its provenance — this is enforced in the API layer via a shared DTO, not left to each endpoint to remember:

```json
{
  "value": 78,
  "unit": "risk_score_0_100",
  "source": "Prediction Agent v2.3",
  "generated_at": "2026-09-06T14:32:00Z",
  "confidence": 0.78,
  "data_provenance": "estimated"
}
```

The frontend's shared `ui` package (§5) includes a single `<AiValue>` component that consumes exactly this shape, so the "never show an unexplained AI number" rule (design system §6) is structurally guaranteed rather than a convention teams can forget.

### 7.3 WebSocket channels

Gateway at `/ws`, authenticated on connect via the same JWT.

| Channel | Payload | Used by |
|---|---|---|
| `risk.updated` | Risk delta (id, new score, severity change) | Dashboard KPIs, Risk Center list |
| `shipment.position` | Shipment id, lat/lng, eta delta | Map, Shipment Control Center |
| `agent_run.status` | Agent run id, stage, status | Incident Investigation, Agent Operations |
| `notification.created` | Notification object | Notification Center, top-bar bell |
| `approval.queue_changed` | Approval id, action | Approval Center |

---

## 8. AI multi-agent architecture

### 8.1 Pipeline stages (matches the design system's Agent Operations screen exactly)

```
Detection → Research → Risk → Prediction → Scenario → Optimization → Decision → Approval → Action → Verification
```

| Stage | Responsibility | Inputs | Outputs |
|---|---|---|---|
| Detection | Continuously score incoming signals (shipment delay, port congestion feed, weather alert, news event) against threshold rules and a lightweight anomaly model; opens an `Incident` when a signal crosses threshold | Ingested events (§12) | `Incident` (status: detected) |
| Research | Gathers evidence: internal data (affected shipments/suppliers) + external sources (news, port authority statements) via tool calls; synthesizes into structured findings, never raw scraped text | Incident, knowledge base (pgvector RAG), external APIs | `Evidence[]`, structured findings |
| Risk | Computes/updates the composite risk score from research findings using the scoring model (§9.1) | Evidence, historical risk data | `Risk` (score, probability, impact, confidence) |
| Prediction | Forecasts delay/disruption/financial exposure using the trained forecasting model | Risk, historical time series | `Prediction` (forecast, confidence interval) |
| Scenario | Runs the simulation engine against likely variants of the incident (e.g. 3-day vs 7-day disruption) to bound the outcome space | Risk, Prediction, network graph | `SimulationRun[]` |
| Optimization | Ranks candidate mitigations against the multi-objective cost function | Scenario outputs, candidate action catalog | `OptimizationRun`, ranked `Recommendation[]` |
| Decision | LLM-driven synthesis: turns the optimization output + evidence into a human-readable recommendation with rationale | All prior stage outputs | `Recommendation` (title, rationale, expected benefit) |
| Approval | Routes high-impact recommendations to the Approval Center; low-impact ones may auto-apply per org policy | Recommendation, org approval policy | `Approval` (pending/decided) |
| Action | Executes the approved action against the relevant system (reroute API call, PO update, etc.) via the Integration layer | Approved `Recommendation` | Action result, updated entity state |
| Verification | Confirms the action had the intended effect (e.g. shipment risk score actually dropped) and closes the loop | Post-action state | Verification result, `Incident` closed or re-opened |

### 8.2 Orchestration & guardrails

- Each stage is a discrete, independently retryable step in the LangGraph state machine — a failure in Scenario doesn't require re-running Research.
- Every stage writes an `AgentStep` record with `tools_used`, `evidence_ids`, `findings_json`, and `confidence` **before** advancing — this is what the frontend's structured-findings panel reads; there is no separate "transcript" store, which structurally prevents chain-of-thought from leaking into the product surface (design system §7 requirement).
- Tool calls available to agents are explicitly allow-listed per agent role (e.g. the Research agent can call `search_news`, `get_supplier_profile`, `get_port_status`; it cannot call `execute_reroute` — only the Action stage's dedicated executor can).
- A confidence floor gates auto-progression: if the Risk stage's confidence is below a configurable threshold (default 0.6), the pipeline flags the incident for analyst review instead of silently continuing to Prediction/Scenario on shaky evidence.
- All LLM calls are logged with prompt/response hashes (not necessarily full text, per data-retention policy) and model/version for reproducibility and audit.

---

## 9. Core business logic

### 9.1 Risk scoring

Composite score (0–100) combines three normalized inputs:
```
risk_score = w1 * probability_score + w2 * impact_score + w3 * velocity_score
```
- `probability_score`: likelihood of the disruption materializing, from the Detection/Research stages' evidence strength and historical base rates for that signal type.
- `impact_score`: normalized blend of affected-shipment count, affected-supplier criticality, and estimated financial exposure.
- `velocity_score`: how fast the situation is escalating (rate of change of related signals over the last N hours) — this is what lets two risks with the same current severity be ranked differently by urgency.
- Default weights `w1=0.4, w2=0.4, w3=0.2`, configurable per organization in Risk Configuration settings.
- Every score recomputation is versioned (`Risk.updated_at` + a `RiskScoreHistory` time-series row in TimescaleDB) so the dashboard's sparklines and the "trend" indicators are real, not decorative.

### 9.2 Simulation engine

- **Deterministic mode:** applies the scenario's stated variables (duration, capacity reduction, affected routes) directly against the current network graph to compute delay/inventory/financial deltas — used for fast, explainable what-ifs.
- **Stochastic mode (Monte Carlo):** runs N iterations (default 1,000) sampling from historical distributions for the affected variables (e.g. actual historical variance in port-congestion clearance time) to produce a confidence band, not a single number — this is what powers the "range, never a false-precise point estimate" rule in the design system (§11).
- Baseline is always computed fresh from current live state at simulation time, never cached, so a Scenario comparison is never stale against a baseline that's since changed.

### 9.3 Optimization engine

Multi-objective ranking over candidate actions (reroute, increase inventory, switch supplier, increase safety stock, change transport mode), objective function:
```
minimize:  α * residual_risk + β * financial_loss + γ * delay_days + δ * logistics_cost
```
subject to constraints (capacity limits, supplier lead times, budget ceiling if configured). Solved via OR-Tools; the top-ranked feasible solution becomes the "Recommended Plan," with the full ranked candidate table retained for the comparison UI. Weights (`α, β, γ, δ`) are configurable per organization, and every optimization run stores the weight set used, so a plan's ranking is reproducible and explainable months later in an audit.

### 9.4 Approval workflow (state machine)

```
pending → approved → action_in_progress → verified → closed
        → rejected → closed
        → modified → pending (re-evaluated with the modification)
```
- Impact tier (from the recommendation's `expected_benefit`/`estimated_cost`) determines routing: above a configurable threshold, a recommendation **must** go through `pending → approved` by a user with the `RiskManager` or `Admin` role before Action executes; below threshold, org policy may allow `auto_applied` (still logged in `AuditLog` as an agent-actor action, never silently skipped from the trail).
- Every state transition writes an `AuditLog` row with before/after state — the Approval history view (design system §14) reads directly off this, not a separate log.

### 9.5 Notification rules

Triggered off domain events on the event bus, not polled: `risk.severity_increased`, `shipment.delay_predicted`, `supplier.risk_changed`, `approval.requested`, `recommendation.created`, `system.provider_degraded`. Each maps to one of the six Notification categories (design system §16) and a severity; delivery channel (in-app, email digest, Slack/webhook) is configurable per user per category.

---

## 10. Authentication & authorization

### 10.1 Auth flow
OIDC login (Auth0/Keycloak) → short-lived JWT access token (15 min) + rotating refresh token → NestJS guard validates on every request → WebSocket gateway validates the same JWT on connection handshake.

### 10.2 RBAC matrix (default roles — orgs can define custom roles composed of the same permission set)

| Capability | Viewer | Analyst | OpsManager | RiskManager | Admin |
|---|---|---|---|---|---|
| View dashboards, risks, shipments | ✓ | ✓ | ✓ | ✓ | ✓ |
| Run scenarios/simulations | | ✓ | ✓ | ✓ | ✓ |
| Create/edit recommendations | | ✓ | ✓ | ✓ | ✓ |
| Approve/reject high-impact actions | | | | ✓ | ✓ |
| Execute actions directly | | | ✓ | ✓ | ✓ |
| Manage users/roles/integrations | | | | | ✓ |
| View audit trail | | | | ✓ | ✓ |

### 10.3 Multi-tenant isolation
Every request resolves `org_id` from the JWT claim, never from a client-supplied parameter. Postgres RLS policies (`USING (org_id = current_setting('app.current_org_id'))`) are set per-transaction by the API layer, so isolation holds even if application-level filtering is ever missed.

---

## 11. Real-time & event architecture

- **Ingestion → Kafka topic (`riskwise.events.raw`) → Ingestion normalizer → domain event topics** (`shipment.updated`, `risk.updated`, `incident.detected`, ...).
- **Core API** consumes domain events to update Postgres and push WebSocket messages to affected org's connected clients (fan-out via Redis pub/sub across API instances).
- **AI Orchestration Service** consumes `incident.detected` to kick off the agent pipeline (§8), and publishes `agent_run.status` and `recommendation.created` events back onto the bus for the Core API to persist and push.
- This event-driven seam is what makes the "structured findings, not chain-of-thought" rule enforceable at the architecture level: the Core API only ever receives and stores the structured `AgentStep` output, never a raw model stream.

---

## 12. Third-party integrations (data ingestion)

| Source | Purpose | Notes |
|---|---|---|
| Vessel/port tracking (e.g. MarineTraffic, Windward, project44) | Live shipment position, port congestion signals | Primary source for `shipment.position` events |
| Flight tracking (e.g. FlightAware) | Air-mode shipment tracking | |
| Weather (NOAA / OpenWeather / a commercial marine-weather provider) | Storm/weather risk signals feeding Detection | |
| News / geopolitical risk feed (e.g. GDELT, a commercial risk-intel API) | Unstructured signals for the Research agent's RAG corpus | Ingested, embedded (pgvector), and made searchable — never displayed to end users as raw scraped text, only as cited, paraphrased evidence (matches the Research agent's evidence rule) |
| ERP/PO systems (SAP, Oracle, or CSV/SFTP for smaller orgs) | Supplier, inventory, and financial exposure data | Connector framework per org, configured in Settings → Integrations |
| Currency/FX | Normalizing financial exposure figures across currencies | |

Every ingested value carries a `data_provenance` flag written at ingestion time (`real` for direct sensor/API data, `estimated` if it passed through a model, `simulated` never applies to ingestion — only to Scenario output) — this is the same flag surfaced in the Shipment Control Center UI, sourced from the database, not computed client-side.

---

## 13. Environments & configuration

- **Environments:** `local` (docker-compose), `staging`, `production` — identical Terraform modules parameterized per environment.
- **Config:** 12-factor — all environment-specific values via environment variables / Secrets Manager, never hardcoded. Key variables: `DATABASE_URL`, `REDIS_URL`, `KAFKA_BROKERS`, `ANTHROPIC_API_KEY`, `AUTH0_DOMAIN`/`AUTH0_CLIENT_ID`/`AUTH0_CLIENT_SECRET`, `S3_BUCKET`, `JWT_SECRET` (or public key for asymmetric verification), per-integration API keys.
- **Feature flags:** LaunchDarkly or a simple org-level `settings_json` flag set for staged rollout of new agent stages/optimization strategies without a full deploy.

---

## 14. Deployment & CI/CD

1. PR opened → GitHub Actions: lint, typecheck, unit tests (both services + frontend), build Docker images.
2. Merge to `main` → integration tests against a docker-compose stack (Postgres, Redis, Kafka) → images pushed to ECR → auto-deploy to `staging`.
3. Manual promotion (or scheduled) → same images deployed to `production` via blue/green ECS deployment — no rebuild between staging and prod, only the promoted image.
4. Database migrations (Prisma Migrate) run as a separate, gated pipeline step before the new API revision receives traffic.
5. Rollback: previous ECS task definition revision, one command/click.

---

## 15. Security & compliance

- TLS everywhere (ALB termination + re-encryption to services).
- Secrets never in code or logs; Secrets Manager + IAM roles per service, least-privilege.
- Postgres RLS for tenant isolation (§10.3); all API queries additionally scoped in application code as defense in depth.
- Audit log is append-only (no update/delete permission at the database role level) — this is what makes the Audit Trail screen trustworthy.
- PII minimization: user profile data limited to what's needed for auth/notification; no unnecessary storage of personal data beyond org membership.
- Regular dependency scanning (Dependabot/Snyk) and container image scanning in CI.
- SOC 2 Type II readiness as a target for enterprise sales — audit logging, access control, and encryption requirements above are largely the same controls SOC 2 evaluates, so building them correctly from v1 avoids costly retrofitting.

---

## 16. Testing strategy

| Level | Tooling | Coverage target |
|---|---|---|
| Unit | Vitest (frontend), Jest (NestJS), Pytest (FastAPI) | Business logic (risk scoring, optimization objective, approval state machine) at ≥80% |
| Integration | Supertest (API), Testcontainers (Postgres/Redis/Kafka) | Every API endpoint against a real (containerized) database |
| E2E | Playwright | The 7 hero flows from the design system (§27 of the UI/UX doc): dashboard load, risk drill-down, incident investigation, digital twin interaction, scenario run, optimization comparison, approval action |
| Agent pipeline | Recorded fixture replay (golden evidence sets → expected structured findings) | Every pipeline stage tested in isolation with mocked tool responses, plus one full end-to-end pipeline test per incident type |
| Load | k6 or Locust | Dashboard and shipment-list endpoints at target concurrent-user load before each major release |

---

## 17. Phased delivery roadmap

**Phase 1 — Foundation (matches this doc's title reference)**
Core Platform API skeleton + auth + multi-tenancy; Postgres schema for §6.1–6.3; frontend shell (sidebar, top bar, routing) per design system; Suppliers, Facilities, Shipments CRUD + list/detail screens with static/seeded data; CI/CD pipeline stood up.

**Phase 2 — Risk & visibility**
Ingestion service for one real data source (start with one vessel-tracking + one weather provider); Risk scoring engine (§9.1); Risk Center, live map with WebSocket updates; Notification Center.

**Phase 3 — AI investigation**
AI Orchestration Service; Detection → Research → Risk → Prediction stages wired to real LLM calls and the RAG knowledge base; Incident Investigation screen; Agent Operations screen (partial pipeline).

**Phase 4 — Simulation & optimization**
Digital Twin (network graph model + React Flow UI); Scenario simulation engine; Optimization engine (OR-Tools); Scenario Simulation and Optimization screens.

**Phase 5 — Decision & audit**
Decision/Approval/Action/Verification stages complete the pipeline; Approval Center; full Audit Trail; Reports; production hardening (load testing, SOC 2 control review) and GA readiness.

Each phase ends with the relevant hero screens from the design system fully functional against real (not mocked) backend data — not just UI shells — before moving to the next phase.

---

## 18. Appendix

### 18.1 Key environment variables (non-exhaustive)
```
DATABASE_URL=
REDIS_URL=
KAFKA_BROKERS=
ANTHROPIC_API_KEY=
AUTH0_DOMAIN=
AUTH0_CLIENT_ID=
AUTH0_CLIENT_SECRET=
JWT_PUBLIC_KEY=
S3_BUCKET=
S3_REGION=
VESSEL_TRACKING_API_KEY=
WEATHER_API_KEY=
NEWS_FEED_API_KEY=
SENTRY_DSN=
OTEL_EXPORTER_OTLP_ENDPOINT=
```

### 18.2 Glossary
- **Agent run** — one execution of the multi-agent pipeline against a specific incident.
- **Data provenance** — whether a value is `real` (direct/live), `estimated` (model-derived), or `simulated` (scenario output).
- **Recommendation** — an AI-generated suggested action, distinct from an approved `Action`.
- **Verification** — the pipeline stage confirming an executed action had its intended effect.
