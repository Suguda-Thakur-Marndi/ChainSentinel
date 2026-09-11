# RiskWise 2.0

> **Autonomous AI-Powered Supply Chain Risk Intelligence, Digital Twin & Decision Governance Platform**

RiskWise 2.0 is an enterprise-grade, multi-tenant control center for global supply-chain resilience. It unifies real-time external disruption tracking, automated entity normalization, deterministic composite risk scoring, hybrid retrieval-augmented generation (RAG), multi-agent LangGraph orchestrations with AWS Bedrock / Claude 3.5 Sonnet, predictive machine learning, deterministic Digital Twin graph synthesis, and human-in-the-loop approval governance with tamper-evident auditability.

---

## Monorepo Architecture & Full Directory Structure

```
riskwise/
├── .env.example                               # Environment template with required credentials and settings
├── .gitignore                                 # Git ignore patterns for Python, Node, caches, and artifacts
├── AGENTS.md                                  # Agent development guidelines and framework rules
├── CLAUDE.md                                  # Claude code assistant workspace context
├── README.md                                  # Master project documentation and directory overview
├── credentials.json                           # Google OAuth2 client secrets for user authentication
├── risk-wise.pem                              # Development SSL certificate for secure service communication
│
├── .agents/                                   # Workspace-level AI agent customization skills
│   └── skills/                                # Specialized agent skill definitions
│       ├── banner-design/                     # Visual banner and graphic creation skill
│       ├── brand/                             # Brand voice, visual identity and guidelines skill
│       ├── design/                            # Comprehensive design system and asset generation skill
│       ├── design-system/                     # Design tokens and UI specifications skill
│       ├── slides/                            # Presentation and slide deck creation skill
│       ├── ui-styling/                        # Shadcn/ui and Tailwind utility styling skill
│       └── ui-ux-pro-max/                     # UI/UX design intelligence and best practices skill
│
├── apps/                                      # Monorepo application packages
│   ├── api/                                   # Backend API service (FastAPI, Python 3.12/3.13)
│   │   ├── alembic/                           # Database schema migration environment
│   │   │   ├── versions/                      # Version-controlled schema migration scripts
│   │   │   ├── env.py                         # Alembic migration environment runtime
│   │   │   └── script.py.mako                 # Migration script template
│   │   ├── alembic.ini                        # Alembic database migration configuration
│   │   ├── pyproject.toml                     # Python dependencies, tools & packaging metadata
│   │   ├── requirements.txt                   # Frozen runtime Python dependencies
│   │   │
│   │   ├── storage/                           # Persistent local object and artifact storage
│   │   │   └── ml_artifacts/                  # Trained ML models, metadata, and scaler bundles
│   │   │
│   │   ├── app/                               # Core backend application package
│   │   │   ├── __init__.py                    # Application package initialization
│   │   │   ├── main.py                        # FastAPI entrypoint, middleware, and router mounting
│   │   │   │
│   │   │   ├── agents/                        # Multi-Agent LangGraph orchestration subsystem (Phase 9 & 10)
│   │   │   │   ├── __init__.py                # Package exports and agent registry
│   │   │   │   ├── contracts.py               # Frozen Pydantic agent state & transition schemas
│   │   │   │   ├── edges.py                   # Conditional routing edges between agent nodes
│   │   │   │   ├── errors.py                  # Agent domain error hierarchy and error types
│   │   │   │   ├── execution.py               # Graph execution runner with recovery handlers
│   │   │   │   ├── graph.py                   # Compiled LangGraph workflow state machine
│   │   │   │   ├── nodes.py                   # Node wrapper functions with state transitions
│   │   │   │   ├── observability.py           # Structured telemetry, timing, and agent logging
│   │   │   │   ├── recovery.py                # Fallback, retry, and node-level recovery policies
│   │   │   │   ├── registry.py                # Agent service and node registry
│   │   │   │   ├── routing.py                 # Graph routing predicates and decision logic
│   │   │   │   ├── security.py                # Agent action RBAC scopes and authorization guards
│   │   │   │   ├── validator.py               # State boundary and contract invariant validator
│   │   │   │   │
│   │   │   │   ├── approval/                  # Human-in-the-loop Governance & Approval Agent
│   │   │   │   │   ├── __init__.py            # Approval agent package exports
│   │   │   │   │   ├── agent.py               # Core approval agent workflow implementation
│   │   │   │   │   ├── contract.py            # Approval request, review, and decision contracts
│   │   │   │   │   ├── errors.py              # Approval domain errors
│   │   │   │   │   ├── node.py                # LangGraph node execution function
│   │   │   │   │   └── service.py             # Approval governance business service
│   │   │   │   │
│   │   │   │   ├── decision/                  # Mitigation Decision Analysis Agent
│   │   │   │   │   ├── __init__.py            # Decision agent package exports
│   │   │   │   │   ├── agent.py               # Decision recommendation logic & option ranking
│   │   │   │   │   ├── claude_contract.py     # Claude prompt/response schemas for decisions
│   │   │   │   │   ├── claude_service.py      # LLM reasoning integration for decision analysis
│   │   │   │   │   ├── contract.py            # Decision action & mitigation schema contracts
│   │   │   │   │   ├── errors.py              # Decision domain errors
│   │   │   │   │   ├── node.py                # LangGraph node execution function
│   │   │   │   │   └── rules.py               # Business rules for mitigation feasibility
│   │   │   │   │
│   │   │   │   ├── prediction/                # Predictive Impact & Delay Estimation Agent
│   │   │   │   │   ├── __init__.py            # Prediction agent package exports
│   │   │   │   │   ├── adapter.py             # ML model inference feature adapter
│   │   │   │   │   ├── agent.py               # Delay forecasting & downstream impact agent
│   │   │   │   │   ├── claude_contract.py     # Claude prompt/response schemas for prediction
│   │   │   │   │   ├── claude_service.py      # LLM synthesis for impact explanations
│   │   │   │   │   ├── contract.py            # Prediction state & impact contracts
│   │   │   │   │   ├── errors.py              # Prediction domain errors
│   │   │   │   │   ├── node.py                # LangGraph node execution function
│   │   │   │   │   └── service.py             # Prediction business service
│   │   │   │   │
│   │   │   │   ├── research/                  # Open-Source Intelligence & News Research Agent
│   │   │   │   │   ├── __init__.py            # Research agent package exports
│   │   │   │   │   ├── agent.py               # OSINT search, entity linking, and fact extraction
│   │   │   │   │   ├── analysis.py            # Sentiment and severity analysis
│   │   │   │   │   ├── claude_contract.py     # Claude prompt/response schemas for research
│   │   │   │   │   ├── claude_service.py      # Claude reasoning for external news synthesis
│   │   │   │   │   ├── contract.py            # Research query and evidence contracts
│   │   │   │   │   ├── errors.py              # Research domain errors
│   │   │   │   │   ├── evidence.py            # Evidence item formatting and provenance
│   │   │   │   │   └── node.py                # LangGraph node execution function
│   │   │   │   │
│   │   │   │   ├── risk/                      # Real-Time Supply Chain Risk Evaluation Agent
│   │   │   │   │   ├── __init__.py            # Risk agent package exports
│   │   │   │   │   ├── adapter.py             # Risk engine scoring adapter
│   │   │   │   │   ├── agent.py               # Multi-factor risk assessment orchestration
│   │   │   │   │   ├── claude_contract.py     # Claude prompt/response schemas for risk
│   │   │   │   │   ├── claude_service.py      # LLM-generated risk narratives and explanations
│   │   │   │   │   ├── contract.py            # Risk agent state contracts
│   │   │   │   │   ├── errors.py              # Risk agent domain errors
│   │   │   │   │   └── node.py                # LangGraph node execution function
│   │   │   │   │
│   │   │   │   └── scenario/                  # What-If Disruption Scenario Agent
│   │   │   │       ├── __init__.py            # Scenario agent package exports
│   │   │   │       ├── agent.py               # Scenario hypothesis formulation & evaluation
│   │   │   │       ├── claude_contract.py     # Claude prompt/response schemas for scenarios
│   │   │   │       ├── claude_service.py      # Claude reasoning for scenario disruption
│   │   │   │       ├── contract.py            # Scenario state and perturbation contracts
│   │   │   │       ├── errors.py              # Scenario domain errors
│   │   │   │       ├── generator.py           # Synthetic disruption scenario generator
│   │   │   │       └── node.py                # LangGraph node execution function
│   │   │   │
│   │   │   ├── api/                           # REST API routing & dependency injection layer
│   │   │   │   ├── __init__.py                # API package exports
│   │   │   │   ├── deps.py                    # FastAPI dependencies (database session, auth user, RBAC)
│   │   │   │   └── v1/                        # Version 1 REST API specification (60 endpoints)
│   │   │   │       ├── __init__.py            # v1 package exports
│   │   │   │       ├── router.py              # Consolidated v1 APIRouter registering all endpoints
│   │   │   │       └── endpoints/             # Domain REST controllers
│   │   │   │           ├── __init__.py        # Endpoints exports
│   │   │   │           ├── actions.py         # Autonomous and approved mitigation action dispatch
│   │   │   │           ├── approvals.py       # Human governance decision review and approval
│   │   │   │           ├── audit_logs.py      # Immutable audit trail query and inspection
│   │   │   │           ├── auth.py            # Google OAuth2 login, callback, refresh, and logout
│   │   │   │           ├── carriers.py        # Logistics carrier profiles and reliability ratings
│   │   │   │           ├── factories.py       # Manufacturing plants, throughput, and operational status
│   │   │   │           ├── health.py          # Liveness, readiness, and database probe endpoints
│   │   │   │           ├── incidents.py       # Disruption event reporting, investigation, and resolution
│   │   │   │           ├── inventory.py       # Real-time stock levels, SKU tracking, and safety stocks
│   │   │   │           ├── inventory_movements.py # Stock receipts, issues, transfers, and adjustments
│   │   │   │           ├── notifications.py   # Multi-channel stakeholder alerts and delivery status
│   │   │   │           ├── ports.py           # Maritime container terminals and congestion metrics
│   │   │   │           ├── products.py        # SKU catalog, bills of materials, and criticality
│   │   │   │           ├── recommendations.py # AI-generated mitigation option review and selection
│   │   │   │           ├── risk_assessments.py# Multi-factor risk evaluations and historical scores
│   │   │   │           ├── risk_factors.py    # Geopolitical, climatic, financial, and transit drivers
│   │   │   │           ├── risks.py           # Active risk entity profiles and compound scores
│   │   │   │           ├── routes.py          # Multi-modal transport corridors, lanes, and waypoints
│   │   │   │           ├── shipment_events.py # Real-time tracking milestones and telemetry updates
│   │   │   │           ├── shipments.py       # Consignment lifecycle, ETA calculation, and delays
│   │   │   │           ├── supplier_sites.py  # Secondary manufacturing and warehousing facilities
│   │   │   │           ├── suppliers.py       # Tier-1/2/3 vendor organizational profiles and tiers
│   │   │   │           ├── verification_results.py # Post-action execution telemetry and verification
│   │   │   │           └── warehouses.py      # Regional distribution centers and storage hubs
│   │   │   │
│   │   │   ├── core/                          # Foundational services and cross-cutting concerns
│   │   │   │   ├── __init__.py                # Core package initialization
│   │   │   │   ├── config.py                  # Pydantic Settings reading environment variables
│   │   │   │   ├── context.py                 # Async request context, correlation IDs, and tenant tracking
│   │   │   │   ├── errors.py                  # Global HTTP exceptions and structured error handlers
│   │   │   │   └── logging.py                 # Structured JSON logging with security redaction
│   │   │   │
│   │   │   ├── db/                            # Relational database persistence layer (SQLAlchemy 2.0)
│   │   │   │   ├── __init__.py                # Database package exports
│   │   │   │   ├── base.py                    # DeclarativeBase with UUID primary keys and timestamps
│   │   │   │   ├── session.py                 # PostgreSQL connection pool and session maker
│   │   │   │   └── unit_of_work.py            # Transactional Unit of Work coordinating repositories
│   │   │   │
│   │   │   ├── digital_twin/                  # Phase 12 Digital Twin Graph Subsystem
│   │   │   │   ├── __init__.py                # Digital Twin exports and facade access
│   │   │   │   ├── builder.py                 # Deterministic multi-tenant graph synthesis from DB
│   │   │   │   ├── contracts.py               # Frozen Pydantic snapshot, node, edge, and query schemas
│   │   │   │   ├── errors.py                  # Digital Twin domain error hierarchy
│   │   │   │   ├── fingerprints.py            # Deterministic RFC 4122 UUIDv5 & SHA-256 canonical hashing
│   │   │   │   ├── observability.py           # Graph build telemetry, timing, and audit log hooks
│   │   │   │   ├── query.py                   # Read-only bounded BFS traversal and pathfinding service
│   │   │   │   ├── repository.py              # Transactional persistence for twin_nodes & twin_edges
│   │   │   │   ├── service.py                 # Unified DigitalTwinService coordinator
│   │   │   │   └── validator.py               # Structural integrity, reference, and tenant validator
│   │   │   │
│   │   │   ├── integrations/                  # External data ingestion connectors (Phase 5)
│   │   │   │   ├── __init__.py                # Integrations package exports
│   │   │   │   ├── base.py                    # Base connector class with lifecycle hooks
│   │   │   │   ├── boundaries.py              # Security boundaries, secret masking, and payload checks
│   │   │   │   ├── canonical.py               # Canonical external event data structures
│   │   │   │   ├── circuit_breaker.py         # Resilience circuit breaker with exponential backoff
│   │   │   │   ├── config.py                  # Provider connection credentials and endpoint settings
│   │   │   │   ├── errors.py                  # Ingestion domain errors
│   │   │   │   ├── idempotency.py             # Event deduplication and idempotency keys
│   │   │   │   ├── normalizers.py             # Raw payload to canonical format adapters
│   │   │   │   ├── observability.py           # Ingestion metrics, throughput, and error counters
│   │   │   │   ├── rate_limiter.py            # Token-bucket rate limiter per provider
│   │   │   │   ├── registry.py                # Dynamic connector registry
│   │   │   │   ├── retry.py                   # Retry policies for transient network errors
│   │   │   │   ├── service.py                 # Unified external ingestion service
│   │   │   │   └── providers/                 # Concrete external telemetry providers
│   │   │   │       ├── __init__.py            # Providers package exports
│   │   │   │       ├── aisstream.py           # Live maritime vessel AIS positioning stream
│   │   │   │       ├── karrio.py              # Multi-carrier logistics tracking API
│   │   │   │       ├── opensky.py             # Real-time air cargo ADS-B transponder telemetry
│   │   │   │       ├── openweather.py         # Meteorological hazards, severe weather, and forecasts
│   │   │   │       ├── rail.py                # Freight rail corridor tracking and junction status
│   │   │   │       ├── tavily.py              # Real-time OSINT supply-chain disruption news
│   │   │   │       └── tomtom.py              # Road freight traffic congestion and incident delays
│   │   │   │
│   │   │   ├── llm/                           # GenAI Foundation & Model Gateway (Phase 10)
│   │   │   │   ├── __init__.py                # LLM package exports
│   │   │   │   ├── base.py                    # Abstract LLM client interface
│   │   │   │   ├── bedrock.py                 # AWS Bedrock Claude 3.5 Sonnet client
│   │   │   │   ├── contracts.py               # Strongly-typed invocation request and response schemas
│   │   │   │   ├── errors.py                  # LLM invocation, timeout, and throttling errors
│   │   │   │   ├── factory.py                 # Dynamic provider factory (Bedrock / Anthropic / Mock)
│   │   │   │   ├── invocation.py              # Invocation pipeline with schema validation
│   │   │   │   ├── mock.py                    # Deterministic offline mock LLM for testing
│   │   │   │   ├── observability.py           # Token usage tracking, latency, and cost telemetry
│   │   │   │   ├── prompts.py                 # Versioned, domain-grounded system and user prompts
│   │   │   │   ├── retry.py                   # Exponential jitter retry for rate limits
│   │   │   │   └── security.py                # Prompt injection filtering and PII masking
│   │   │   │
│   │   │   ├── ml/                            # Machine Learning Subsystem (Phase 11)
│   │   │   │   ├── __init__.py                # ML package exports
│   │   │   │   ├── config.py                  # ML model hyperparameters and storage configuration
│   │   │   │   ├── contracts.py               # Feature vector, prediction, and metric contracts
│   │   │   │   ├── errors.py                  # ML training, feature extraction, and inference errors
│   │   │   │   ├── observability.py           # Inference latency, prediction drift, and model metrics
│   │   │   │   ├── datasets/                  # Training dataset extraction & validation
│   │   │   │   │   ├── __init__.py            # Datasets package exports
│   │   │   │   │   ├── builder.py             # Operational DB extraction with temporal cutoff
│   │   │   │   │   ├── contracts.py           # Dataset schema and split specifications
│   │   │   │   │   └── validation.py          # Data quality, leakage, and missingness validation
│   │   │   │   ├── features/                  # Feature engineering and transformation
│   │   │   │   │   ├── __init__.py            # Features package exports
│   │   │   │   │   ├── contracts.py           # Feature definitions and schema contracts
│   │   │   │   │   └── shipment_delay.py      # Deterministic feature preprocessor and normalizer
│   │   │   │   ├── inference/                 # Real-time inference engine
│   │   │   │   │   ├── __init__.py            # Inference package exports
│   │   │   │   │   └── service.py             # Latency-bounded scoring service with model cache
│   │   │   │   ├── models/                    # Model estimators and predictors
│   │   │   │   │   ├── __init__.py            # Models package exports
│   │   │   │   │   ├── base.py                # Base ML model interface
│   │   │   │   │   └── shipment_delay.py      # Gradient boosting shipment delay estimator
│   │   │   │   ├── registry/                  # Model versioning and artifact store
│   │   │   │   │   ├── __init__.py            # Registry package exports
│   │   │   │   │   └── registry.py            # Semantic versioning, SHA-256 validation & rollback
│   │   │   │   └── training/                  # Repeatable training and evaluation pipelines
│   │   │   │       ├── __init__.py            # Training package exports
│   │   │   │       ├── artifacts.py           # Model artifact bundling and checksum generator
│   │   │   │       ├── pipeline.py            # End-to-end training and hyperparameter pipeline
│   │   │   │       └── validation.py          # Strict quality gates (R2, MAE, latency bounds)
│   │   │   │
│   │   │   ├── models/                        # SQLAlchemy ORM Database Models (34 Tables)
│   │   │   │   ├── __init__.py                # Model package exports and metadata registry
│   │   │   │   ├── agents.py                  # Agent runs, state checkpoints, and step logs
│   │   │   │   ├── digital_twin.py            # twin_nodes and twin_edges graph tables
│   │   │   │   ├── governance.py              # audit_logs, recommendations, approvals, actions, verifications
│   │   │   │   ├── knowledge.py               # knowledge_documents, document_chunks, embeddings
│   │   │   │   ├── logistics.py               # shipments, shipment_events, inventory, inventory_movements
│   │   │   │   ├── network.py                 # suppliers, supplier_sites, factories, warehouses, ports, carriers, routes, products
│   │   │   │   ├── risk.py                    # risks, risk_factors, risk_assessments, incidents
│   │   │   │   ├── simulation.py              # simulation_scenarios, simulation_runs, simulation_results
│   │   │   │   └── tenancy.py                 # organizations, users, user_sessions, api_keys
│   │   │   │
│   │   │   ├── normalization/                 # External Telemetry Normalization Subsystem (Phase 6)
│   │   │   │   ├── __init__.py                # Normalization package exports
│   │   │   │   ├── contract.py                # Canonical event contracts and schemas
│   │   │   │   ├── correlation.py             # Multi-source event correlation and grouping
│   │   │   │   ├── entity_resolver.py         # Deterministic entity matching against operational DB
│   │   │   │   ├── handlers.py                # Ingestion payload event handlers
│   │   │   │   ├── identifiers.py             # IMO, MMSI, ICAO, tracking code canonicalization
│   │   │   │   ├── pipeline.py                # End-to-end normalization and enrichment pipeline
│   │   │   │   ├── quality.py                 # Data completeness and validation checks
│   │   │   │   ├── status.py                  # Standardized shipment and facility statuses
│   │   │   │   └── units.py                   # Unit conversion (knots, km/h, Celsius, Fahrenheit)
│   │   │   │
│   │   │   ├── rag/                           # Retrieval-Augmented Generation Subsystem (Phase 8)
│   │   │   │   ├── __init__.py                # RAG package exports
│   │   │   │   ├── chunking.py                # Semantic text splitter with sliding token windows
│   │   │   │   ├── contracts.py               # Document, chunk, embedding, and query contracts
│   │   │   │   ├── embeddings.py              # AWS Bedrock Titan / HuggingFace text vectorization
│   │   │   │   ├── errors.py                  # RAG domain errors
│   │   │   │   ├── grounding.py               # Grounded provenance verification and citation links
│   │   │   │   ├── ingestion.py               # Document ingestion pipeline and metadata tagging
│   │   │   │   ├── parsers.py                 # PDF, Markdown, JSON, and text document parsers
│   │   │   │   ├── pipeline.py                # End-to-end ingest-to-retrieval pipeline coordinator
│   │   │   │   ├── retrieval.py               # Hybrid BM25 keyword + cosine similarity search
│   │   │   │   └── vector_store.py            # Vector similarity search engine and index
│   │   │   │
│   │   │   ├── repositories/                  # Clean Architecture Data Access Layer
│   │   │   │   ├── __init__.py                # Repository package exports
│   │   │   │   ├── audit_log.py               # Immutable append-only audit log repository
│   │   │   │   ├── base.py                    # Generic CRUD repository base class
│   │   │   │   ├── governance_repositories.py # Recommendations, approvals, actions, verifications
│   │   │   │   ├── inventory.py               # Inventory items and movement tracking repositories
│   │   │   │   ├── network_repositories.py    # Suppliers, sites, factories, warehouses, routes, carriers
│   │   │   │   ├── port.py                    # Maritime ports and terminal congestion repository
│   │   │   │   ├── query_utils.py             # Tenant filtering, pagination, and sorting utilities
│   │   │   │   ├── risk_repositories.py       # Risks, risk factors, assessments, and incidents
│   │   │   │   ├── shipment.py                # Shipments and tracking milestones repository
│   │   │   │   └── supplier.py                # Supplier profile and performance repository
│   │   │   │
│   │   │   ├── risk_engine/                   # Deterministic Supply Chain Risk Engine (Phase 7)
│   │   │   │   ├── __init__.py                # Risk engine package exports
│   │   │   │   ├── alerts.py                  # Threshold breach detection, escalation, and cooldowns
│   │   │   │   ├── context.py                 # Risk evaluation context builder
│   │   │   │   ├── contract.py                # Risk scoring contracts and input/output schemas
│   │   │   │   ├── errors.py                  # Risk engine domain errors
│   │   │   │   ├── evaluators.py              # Individual risk category evaluators (weather, transit, etc.)
│   │   │   │   ├── evidence.py                # Evidence collection, weighting, and provenance
│   │   │   │   ├── explainability.py          # Deterministic feature contribution breakdowns
│   │   │   │   ├── history.py                 # Historical risk score snapshots and tracking
│   │   │   │   ├── persistence.py             # Score and assessment database persistence
│   │   │   │   ├── pipeline.py                # End-to-end composite risk scoring pipeline
│   │   │   │   ├── recommendations.py         # Rule-based mitigation recommendation generator
│   │   │   │   ├── registry.py                # Risk evaluator and model registry
│   │   │   │   └── scoring.py                 # Multi-factor weighted composite scoring algorithms
│   │   │   │
│   │   │   ├── schemas/                       # Pydantic Request/Response Validation Schemas
│   │   │   │   ├── __init__.py                # Schemas package exports
│   │   │   │   ├── agents.py                  # Agent run requests, state inspection, and step schemas
│   │   │   │   ├── auth.py                    # Login, token response, user registration schemas
│   │   │   │   ├── common.py                  # Common pagination, sorting, and error response schemas
│   │   │   │   ├── digital_twin.py            # Digital twin graph, node, edge, and query API schemas
│   │   │   │   ├── governance.py              # Recommendations, approvals, actions, audit schemas
│   │   │   │   ├── health.py                  # Health check, readiness, and liveness schemas
│   │   │   │   ├── knowledge.py               # Document upload, chunking, and search schemas
│   │   │   │   ├── logistics.py               # Shipments, events, inventory, and movement schemas
│   │   │   │   ├── network.py                 # Suppliers, sites, factories, warehouses, ports, routes
│   │   │   │   ├── risk.py                    # Risks, factors, assessments, incidents, alert schemas
│   │   │   │   ├── session.py                 # User session and token verification schemas
│   │   │   │   ├── simulation.py              # Simulation scenario and run result schemas
│   │   │   │   └── tenancy.py                 # Organization, user profile, and API key schemas
│   │   │   │
│   │   │   └── services/                      # Domain Business Logic & Orchestration Services
│   │   │       ├── __init__.py                # Services package exports
│   │   │       ├── audit_service.py           # Immutable audit logging service with hash verification
│   │   │       ├── base.py                    # Base domain service interface
│   │   │       ├── concurrency.py             # Concurrency locks and async execution helpers
│   │   │       ├── governance_services.py     # Approval workflows, action execution, and verification
│   │   │       ├── inventory_services.py      # Stock balance, replenishment, and movement tracking
│   │   │       ├── logistics_services.py      # Shipment tracking, carrier updates, and ETA monitoring
│   │   │       ├── oauth_service.py           # Google OAuth2 token exchange and profile sync
│   │   │       ├── risk_evaluation_service.py # Orchestrates risk scoring across operational entities
│   │   │       ├── risk_services.py           # Risk assessment lifecycle and incident management
│   │   │       ├── session_service.py         # JWT session issuance, revocation, and validation
│   │   │       └── supplier.py                # Vendor tiering, risk indexing, and site management
│   │   │
│   │   └── tests/                             # Comprehensive Automated Test Suite (4,200+ tests)
│   │       ├── __init__.py                    # Test suite package root
│   │       ├── integration/                   # Integration test suite directory
│   │       ├── unit/                          # Unit test suite directory
│   │       │
│   │       ├── test_phase12_digital_twin.py   # Phase 12 Digital Twin comprehensive suite
│   │       ├── test_phase12_twin_builder.py   # Phase 12 Graph builder & entity relationship mapping
│   │       ├── test_phase12_twin_contracts.py # Phase 12 Frozen contracts, extra='forbid' validation
│   │       ├── test_phase12_twin_critical.py  # Phase 12 Mandatory invariant tests & E2E flows
│   │       ├── test_phase12_twin_fingerprints.py # Phase 12 SHA-256 canonical hashing & UUIDv5 tests
│   │       ├── test_phase12_twin_persistence.py # Phase 12 Transactional database persistence tests
│   │       ├── test_phase12_twin_query.py     # Phase 12 Bounded BFS traversal & cycle handling tests
│   │       ├── test_phase12_twin_security.py  # Phase 12 Multi-tenant isolation & security boundary tests
│   │       ├── test_phase12_twin_validation.py# Phase 12 Structural graph validation & integrity tests
│   │       │
│   │       ├── test_phase11_ml_artifacts.py   # Phase 11 ML model artifact packaging and checksums
│   │       ├── test_phase11_ml_contracts.py   # Phase 11 ML feature vector & prediction contracts
│   │       ├── test_phase11_ml_critical.py    # Phase 11 ML critical operational invariants
│   │       ├── test_phase11_ml_dataset.py     # Phase 11 ML training dataset extraction
│   │       ├── test_phase11_ml_edge_cases.py  # Phase 11 ML cold-start and missing feature cases
│   │       ├── test_phase11_ml_features.py    # Phase 11 ML deterministic feature transformation
│   │       ├── test_phase11_ml_inference.py   # Phase 11 ML real-time inference latency and accuracy
│   │       ├── test_phase11_ml_leakage.py     # Phase 11 ML temporal cutoff and data leakage checks
│   │       ├── test_phase11_ml_observability_pipeline.py # Phase 11 ML metrics & telemetry
│   │       ├── test_phase11_ml_registry.py    # Phase 11 ML model registry, rollback, and storage
│   │       ├── test_phase11_ml_security.py    # Phase 11 ML tenant isolation and input security
│   │       ├── test_phase11_ml_training.py    # Phase 11 ML repeatable model training pipeline
│   │       │
│   │       ├── test_phase10_step1_bedrock_foundation.py     # Phase 10 AWS Bedrock connection & config
│   │       ├── test_phase10_step2_claude_invocation.py     # Phase 10 Claude 3.5 Sonnet invocation
│   │       ├── test_phase10_step3_research_agent_claude.py # Phase 10 Research agent Claude reasoning
│   │       ├── test_phase10_step4_risk_explanation_claude.py# Phase 10 Risk explanation synthesis
│   │       ├── test_phase10_step5_scenario_explanation_claude.py # Phase 10 Scenario reasoning
│   │       ├── test_phase10_step6_prediction_explanation_claude.py # Phase 10 Prediction explanations
│   │       ├── test_phase10_step7_decision_explanation_claude.py # Phase 10 Decision explanations
│   │       ├── test_phase10_step7_scenario_explanation_claude.py # Phase 10 Scenario explanations
│   │       │
│   │       ├── test_phase9_approval_agent.py  # Phase 9 Human-in-the-loop approval agent
│   │       ├── test_phase9_decision_agent.py  # Phase 9 Mitigation decision agent
│   │       ├── test_phase9_prediction_agent.py# Phase 9 Impact prediction agent
│   │       ├── test_phase9_research_agent.py  # Phase 9 OSINT research agent
│   │       ├── test_phase9_risk_agent.py      # Phase 9 Composite risk agent
│   │       ├── test_phase9_scenario_agent.py  # Phase 9 Disruption scenario agent
│   │       ├── test_phase9_langgraph_agent_state_contract.py # Phase 9 State schema contracts
│   │       ├── test_phase9_langgraph_architecture_contracts.py # Phase 9 Architecture boundaries
│   │       ├── test_phase9_langgraph_node_edge_contracts.py # Phase 9 Graph nodes & edges
│   │       ├── test_phase9_step10_observability_recovery.py # Phase 9 Observability & recovery
│   │       ├── test_phase9_step11_final_validation.py # Phase 9 End-to-end validation suite
│   │       │
│   │       ├── test_phase8_rag_context_assembly_grounding.py # Phase 8 Provenance & citations
│   │       ├── test_phase8_rag_contracts.py   # Phase 8 RAG contracts and schemas
│   │       ├── test_phase8_rag_embeddings_vector_storage.py # Phase 8 Vector search & storage
│   │       ├── test_phase8_rag_evidence_pipeline.py # Phase 8 Evidence gathering pipeline
│   │       ├── test_phase8_rag_ingestion_chunking.py # Phase 8 Chunking & document parsing
│   │       ├── test_phase8_rag_retrieval_similarity_search.py # Phase 8 Hybrid retrieval
│   │       │
│   │       ├── test_phase7_baseline_scoring.py# Phase 7 Baseline risk scoring algorithms
│   │       ├── test_phase7_final_validation.py# Phase 7 Final risk engine validation
│   │       ├── test_phase7_risk_alerts_escalation.py # Phase 7 Alert generation & escalation
│   │       ├── test_phase7_risk_engine_contracts.py # Phase 7 Risk scoring schema contracts
│   │       ├── test_phase7_risk_evidence_assessment.py # Phase 7 Multi-factor evidence collection
│   │       ├── test_phase7_risk_history_trends.py # Phase 7 Historical trend analysis
│   │       ├── test_phase7_risk_persistence_api.py # Phase 7 Persistence & API integration
│   │       ├── test_phase7_risk_recommendation_foundation.py # Phase 7 Recommendation engine
│   │       │
│   │       ├── test_phase6_entity_normalization.py # Phase 6 Entity resolution & linking
│   │       ├── test_phase6_finalization.py    # Phase 6 Normalization final validation
│   │       ├── test_phase6_normalization_contract.py # Phase 6 Canonical event contracts
│   │       │
│   │       ├── test_phase5_final_validation.py# Phase 5 External telemetry validation
│   │       ├── test_aisstream_integration.py  # Phase 5 AISStream maritime connector tests
│   │       ├── test_karrio_integration.py     # Phase 5 Karrio carrier tracking tests
│   │       ├── test_opensky_integration.py    # Phase 5 OpenSky air cargo connector tests
│   │       ├── test_openweather_integration.py# Phase 5 OpenWeather hazard tests
│   │       ├── test_rail_integration.py       # Phase 5 Freight rail tracking tests
│   │       ├── test_tavily_integration.py     # Phase 5 Tavily OSINT news tests
│   │       ├── test_tomtom_integration.py     # Phase 5 TomTom traffic congestion tests
│   │       │
│   │       ├── test_phase4_final_validation.py# Phase 4 Core REST API final validation
│   │       ├── test_auth_config.py            # Phase 3/4 Google OAuth2 configuration
│   │       ├── test_auth_final_validation.py  # Phase 3 Authentication final validation
│   │       ├── test_canonical_external_events.py # External event schema tests
│   │       ├── test_crud.py                   # Generic CRUD repository tests
│   │       ├── test_database_validation.py    # Database schema, UUID, and table validation
│   │       ├── test_decision_governance_api.py# Governance & approval REST API tests
│   │       ├── test_ingestion_foundation.py   # Ingestion pipeline base tests
│   │       ├── test_ingestion_reliability_observability.py # Ingestion circuit breakers
│   │       ├── test_inventory_api.py          # Inventory & movement REST API tests
│   │       ├── test_logistics_api.py          # Shipment & tracking event REST API tests
│   │       ├── test_main.py                   # FastAPI health check and startup tests
│   │       ├── test_models.py                 # SQLAlchemy model relationship tests
│   │       ├── test_risk_api.py               # Risk assessment & incident REST API tests
│   │       ├── test_schemas.py                # Pydantic schema validation tests
│   │       ├── test_service_repository_foundations.py # Unit of work & base repository tests
│   │       ├── test_sessions_and_auth.py      # Multi-tenant JWT session tests
│   │       └── test_supplier_api.py           # Supplier, facility, and network REST API tests
│   │
│   └── web/                                   # Frontend web application (Next.js 15, React 19, TypeScript)
│       ├── .next/                             # Next.js build cache (git-ignored)
│       ├── node_modules/                      # Node.js dependencies (git-ignored)
│       ├── AGENTS.md                          # Frontend agent rules and Next.js guidelines
│       ├── CLAUDE.md                          # Frontend Claude conventions
│       ├── eslint.config.mjs                  # ESLint linting rules configuration
│       ├── next-env.d.ts                      # Next.js TypeScript environment declarations
│       ├── next.config.ts                     # Next.js compiler & routing configuration
│       ├── package.json                       # Frontend dependencies & npm scripts
│       ├── package-lock.json                  # Locked npm dependency versions
│       ├── postcss.config.mjs                 # PostCSS configuration for Tailwind CSS
│       ├── tsconfig.json                      # TypeScript compiler settings & path aliases
│       ├── tsconfig.tsbuildinfo               # Incremental TypeScript build cache
│       │
│       ├── app/                               # Next.js App Router
│       │   ├── favicon.ico                    # Platform browser favicon
│       │   ├── globals.css                    # Tailwind design system tokens, typography & animations
│       │   ├── layout.tsx                     # Root HTML layout with Google Font bindings
│       │   ├── page.tsx                       # Landing page & authenticated dashboard redirect
│       │   └── auth/                          # Authentication routes
│       │       └── page.tsx                   # Google OAuth2 sign-in & session recovery page
│       │
│       ├── components/                        # Reusable React UI component library
│       │   └── auth/                          # Authentication & security components
│       │       ├── AuthCard.tsx               # Glassmorphic authentication card container
│       │       ├── AuthErrorBanner.tsx        # Accessible error alert display
│       │       ├── AuthModeSwitch.tsx         # Sign-in / session switch controller
│       │       ├── AuthSecurityNotice.tsx     # Enterprise SOC2 / ISO compliance notice
│       │       ├── GoogleAuthButton.tsx       # Branded Google OAuth2 one-tap button
│       │       ├── ProtectedRoute.tsx         # Client-side route protection guard
│       │       └── RiskWiseLogo.tsx           # Scalable SVG brand logo and wordmark
│       │
│       ├── lib/                               # Client-side core libraries & utilities
│       │   ├── api/                           # API client layer
│       │   │   └── client.ts                  # Typed Fetch client with JWT interceptor & retry
│       │   └── auth/                          # Client-side authentication context
│       │       ├── AuthContext.tsx            # React Context provider for user session & tokens
│       │       └── types.ts                   # User profile, organization, and token TypeScript types
│       │
│       ├── public/                            # Static web assets and vector illustrations
│       │   ├── file.svg                       # File icon vector
│       │   ├── globe.svg                      # Logistics globe vector
│       │   ├── next.svg                       # Next.js brand vector
│       │   ├── vercel.svg                     # Vercel deployment vector
│       │   └── window.svg                     # Browser window vector
│       │
│       └── tests/                             # Frontend test suites
│           └── auth-integration.test.ts       # Authentication integration tests
│
├── docs/                                      # Master Architecture & Phase Specifications (65 documents)
│   ├── RiskWise_2.0_Technical_Project_Spec.md # Master functional, non-functional, and enterprise spec
│   ├── RiskWise_2.0_UI_UX_Design_System.md    # Component tokens, design guides, accessibility standards
│   ├── DESIGN.md                              # High-level architecture & clean architecture overview
│   ├── database-schema-inventory.md           # 34-table relational database schema dictionary
│   ├── database-final-validation.md           # Database constraint & migration verification report
│   ├── authentication-architecture.md         # Multi-tenant authentication & RBAC architecture
│   ├── google-authentication-architecture.md  # Google OAuth2 integration & token lifecycle design
│   ├── google-authentication-final-validation.md # Google OAuth2 security & validation report
│   ├── core-api-contract.md                   # Core REST API endpoint specifications
│   ├── core-api-service-repository-architecture.md # Service-repository Clean Architecture guide
│   ├── phase4-core-api-final-validation.md     # Phase 4 Core API verification report
│   ├── supplier-api-implementation.md         # Supplier network REST API design
│   ├── logistics-api-implementation.md        # Shipment and tracking REST API design
│   ├── inventory-api-implementation.md        # Inventory and movements REST API design
│   ├── risk-api-implementation.md             # Risk assessment and factors REST API design
│   ├── decision-governance-api-implementation.md # Governance, approvals, and actions REST API design
│   ├── phase5-canonical-event-model.md        # Canonical external event models
│   ├── phase5-ingestion-foundation.md         # Ingestion pipeline architecture
│   ├── phase5-reliability-observability.md    # Circuit breakers, rate limits, and metrics
│   ├── phase5-aisstream-integration.md        # AISStream maritime tracking integration spec
│   ├── phase5-opensky-integration.md          # OpenSky air freight tracking integration spec
│   ├── phase5-tomtom-traffic-integration.md   # TomTom road traffic integration spec
│   ├── phase5-rail-data-integration.md        # Freight rail tracking integration spec
│   ├── phase5-openweather-integration.md      # OpenWeather natural hazard integration spec
│   ├── phase5-tracking-logistics-integration.md # Karrio multi-carrier integration spec
│   ├── phase5-news-research-integration.md    # Tavily OSINT news integration spec
│   ├── phase6-normalization-architecture.md   # External event normalization architecture
│   ├── phase6-entity-normalization.md         # Entity matching, resolution, and linking spec
│   ├── phase6-normalization-finalization.md   # Normalization pipeline validation report
│   ├── phase7-risk-engine-architecture.md     # Deterministic risk scoring engine architecture
│   ├── phase7-baseline-risk-scoring.md        # Multi-factor risk calculation algorithms
│   ├── phase7-risk-evidence-assessment.md     # Evidence collection, weighting, and provenance
│   ├── phase7-risk-history-trends.md          # Historical risk score tracking & EMA trends
│   ├── phase7-risk-alerts-escalation.md       # Threshold breach alerts & escalation policies
│   ├── phase7-risk-recommendation-foundation.md # Mitigation recommendation rule engine
│   ├── phase7-risk-persistence-api-integration.md # Risk engine persistence & API integration
│   ├── phase7-final-validation-hardening.md   # Phase 7 risk engine verification report
│   ├── phase8-rag-architecture-contracts.md   # RAG pipeline architecture & data contracts
│   ├── phase8-rag-document-ingestion-chunking.md # Document ingestion & semantic chunking
│   ├── phase8-rag-embedding-vector-storage.md # Vector embeddings & similarity storage
│   ├── phase8-rag-retrieval-similarity-search.md # Hybrid BM25 & cosine retrieval spec
│   ├── phase8-rag-context-assembly-grounding.md # Grounded prompt assembly & citations
│   ├── phase8-rag-evidence-pipeline-hardening.md # Phase 8 RAG verification report
│   ├── phase9-langgraph-architecture-contracts.md # LangGraph multi-agent architecture spec
│   ├── phase9-langgraph-agent-state-contract.md # Unified agent state contract & schemas
│   ├── phase9-langgraph-node-edge-contracts.md # Agent graph nodes, edges, and routing rules
│   ├── phase9-research-agent.md               # OSINT research agent design spec
│   ├── phase9-risk-agent.md                   # Composite risk evaluation agent design spec
│   ├── phase9-scenario-agent.md               # Disruption scenario generator design spec
│   ├── phase9-prediction-agent.md             # Impact delay prediction agent design spec
│   ├── phase9-decision-flow.md                # Mitigation decision agent design spec
│   ├── phase9-human-approval.md               # Human governance & approval gate design spec
│   ├── phase9-observability-recovery.md       # Agent telemetry, state recovery & fallback
│   ├── phase9-final-validation-hardening.md   # Phase 9 LangGraph verification report
│   ├── phase10-bedrock-foundation.md          # AWS Bedrock connection & credential architecture
│   ├── phase10-prompt-invocation-layer.md     # Prompt management & Claude invocation layer
│   ├── phase10-research-agent-claude.md       # Claude reasoning for OSINT research agent
│   ├── phase10-risk-agent-claude.md           # Claude reasoning for composite risk explanations
│   ├── phase10-scenario-claude.md             # Claude reasoning for scenario generation
│   ├── phase10-prediction-claude.md           # Claude reasoning for delay impact explanations
│   ├── phase10-step7-scenario-explanation.md  # Claude reasoning for mitigation decision analysis
│   ├── phase10-bedrock-claude.md              # Phase 10 Bedrock & Claude master specification
│   ├── phase11-ml.md                          # Phase 11 Machine Learning delay prediction spec
│   └── phase12-digital-twin.md                # Phase 12 Digital Twin graph foundation spec
│
├── data/                                      # Sample operational datasets, CSV seeds & geographic boundaries
├── database/                                  # Database migrations, DDL scripts & SQL seed fixtures
├── evaluation/                                # Model benchmark datasets, test harnesses & evaluation metrics
├── event_bus/                                 # AWS EventBridge event schemas & async messaging definitions
├── infrastructure/                            # Terraform / AWS CDK infrastructure-as-code & Docker compose
├── integrations/                              # Third-party integration connector specifications
├── knowledge_graph/                           # Supply chain knowledge graph ontologies & RDF schemas
├── ml/                                        # ML model registry, feature store specs & training pipelines
├── observability/                             # Prometheus alert rules, OpenTelemetry configs & Grafana dashboards
├── rag/                                       # Vector store indexes, embeddings caches & knowledge bases
├── scripts/                                   # Automation, database provisioning, and maintenance scripts
├── security/                                  # Security compliance policies, RBAC matrices & audit checklists
├── simulation/                                # Phase 13 Simulation models & scenario perturbation configs
├── tests/                                     # Cross-service end-to-end integration and smoke test suites
└── workers/                                   # Background worker task definitions and queue consumers
```

---

## Phase Implementation Roadmap & Status

| Phase | Subsystem / Capability | Key Components | Test Count | Status |
|---|---|---|---|---|
| **Phase 1** | Foundation & Clean Architecture | Config, Logging, Security, Error Handling, Base CRUD | 45+ | Completed |
| **Phase 2** | Database & Persistence | 34 PostgreSQL Tables, UUIDv4 Primary Keys, DeclarativeBase | 85+ | Completed |
| **Phase 3** | Google Authentication & RBAC | OAuth2, Multi-Tenant Session Management, RBAC Scopes | 120+ | Completed |
| **Phase 4** | Core Operational REST APIs | 60 Endpoints: Suppliers, Shipments, Inventory, Ports, Routes | 340+ | Completed |
| **Phase 5** | External Telemetry Ingestion | AISStream, Karrio, OpenSky, OpenWeather, Rail, Tavily, TomTom | 210+ | Completed |
| **Phase 6** | Telemetry Normalization | Canonical Event Models, Deduplication, Entity Resolution | 180+ | Completed |
| **Phase 7** | Deterministic Risk Engine | Multi-Factor Scoring, Evidence Weighting, Trend Analysis, Alerts | 527 | Completed |
| **Phase 8** | Hybrid RAG Subsystem | Semantic Chunking, Bedrock Titan Embeddings, BM25 Retrieval | 231 | Completed |
| **Phase 9** | Multi-Agent LangGraph | 6 Specialized Agents (Research, Risk, Scenario, Prediction, Decision, Approval) | 1,284 | Completed |
| **Phase 10** | AWS Bedrock & Claude 3.5 Sonnet | Structured Prompt Gateway, Offline Mocks, Resilient Fallbacks | 942 | Completed |
| **Phase 11** | Machine Learning Inference | Gradient Boosting Delay Estimator, Temporal Cutoff, Leakage Prevention | 161 | Completed |
| **Phase 12** | Digital Twin Graph Synthesis | Deterministic Multi-Tenant Graph, RFC 4122 UUIDv5, Bounded BFS Traversal | 150 | Completed |
| **Phase 13** | Simulation & Perturbation Engine | Monte Carlo Disruption Simulation, Blast Radius Propagation | — | Pending |
| **Phase 14** | Mathematical Optimization | OR-Tools Rerouting, Inventory Balancing & Cost Optimization | — | Pending |
| **Phase 15** | Autonomous Decision Governance | Policy-Bounded Execution, Human Approval Escalation | — | Pending |
| **Total Passed Backend Tests** | **4,211 Passed, 1 Skipped, 0 Failed (100% Pass Rate)** | | **4,211** | **Active** |

---

## Prerequisites

- **Python**: `3.12` or `3.13` (Virtual environment recommended)
- **Node.js**: `v20.x` or later (LTS)
- **npm**: `v10.x` or later
- **PostgreSQL**: `v15` or later (or SQLite for automated unit test execution)
- **Git**

---

## Getting Started

### 1. Environment Setup

Clone the repository and copy the environment template:

```bash
cp .env.example .env
```

Configure local environment variables in `.env`. Sensitive credentials (Google OAuth secrets, AWS Bedrock keys, API tokens) must never be committed to source control.

### 2. Database Configuration

The backend connects to PostgreSQL via `DATABASE_URL` specified in `.env` (using the `postgresql+psycopg://` dialect format):

```bash
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:<port>/<dbname>
```

Alembic manages migrations from `api/` using configuration in `api/alembic.ini`:

```bash
cd api
alembic upgrade head
```

### 3. Backend Development (`api`)

Activate the Python virtual environment and launch the FastAPI development server:

```bash
cd api

# On Linux / macOS:
source .venv/bin/activate

# On Windows PowerShell:
.venv\Scripts\activate

# Start development server:
uvicorn app.main:app --reload --port 8000
```

#### API Endpoints & Interactive Documentation:
- **API v1 Liveness Probe**: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)
- **Database Readiness Probe**: [http://localhost:8000/api/v1/health/db](http://localhost:8000/api/v1/health/db)
- **Interactive Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **OpenAPI 3.1 JSON Specification**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

### 4. Frontend Development (`web`)

Install dependencies and start the Next.js development server:

```bash
cd web
npm install
npm run dev
```

The frontend web application runs at [http://localhost:3000](http://localhost:3000).

---

## Verification & Automated Testing

RiskWise 2.0 maintains a rigorous automated testing discipline with **4,211 automated backend tests** running across all completed phases.

### Run All Backend Tests (Full Regression Suite)

```bash
cd api
pytest tests/ -v
```

### Run Subsystem-Specific Test Suites

```bash
cd api

# Phase 12: Digital Twin Graph Foundation (150 tests)
pytest tests/ -k "phase12" -v    # Cross-platform (or `pytest tests/test_phase12_*.py -v` on bash)

# Phase 11: Machine Learning Delay Prediction (161 tests)
pytest tests/ -k "phase11" -v    # Cross-platform (or `pytest tests/test_phase11_*.py -v` on bash)

# Phase 10: AWS Bedrock & Claude 3.5 Sonnet Integration (942 tests)
pytest tests/ -k "phase10" -v    # Cross-platform (or `pytest tests/test_phase10_*.py -v` on bash)

# Phase 9: Multi-Agent LangGraph Orchestration (1,284 tests)
pytest tests/ -k "phase9" -v     # Cross-platform (or `pytest tests/test_phase9_*.py -v` on bash)

# Phase 8: Retrieval-Augmented Generation (231 tests)
pytest tests/ -k "phase8" -v     # Cross-platform (or `pytest tests/test_phase8_*.py -v` on bash)

# Phase 7: Deterministic Risk Engine (527 tests)
pytest tests/ -k "phase7" -v     # Cross-platform (or `pytest tests/test_phase7_*.py -v` on bash)
```

### Frontend Validation (`web`)

```bash
cd web
npx tsc --noEmit       # TypeScript type checking
npm run lint           # ESLint code quality check
npm run build          # Production Next.js bundle compilation
```

---

## Core System Architecture & Invariants

1. **Source of Truth Authority**: Operational database tables (`suppliers`, `shipments`, `inventory`, `ports`, `factories`, etc.) are the authoritative source of truth. Analytics, Digital Twin graphs, and ML models read deterministically without mutating source records.
2. **Multi-Tenant Isolation**: Every database query, API route, Digital Twin snapshot, agent state, and ML feature extraction is strictly scoped by `tenant_id`. Cross-tenant data leakage is prevented at the schema and repository levels.
3. **Deterministic Digital Twin Synthesis**: Graph nodes and edges use deterministic RFC 4122 UUIDv5 identities generated from tenant ID, source entity type, and source ID. Canonical SHA-256 fingerprinting guarantees immutable snapshot integrity.
4. **Bounded Graph Traversal**: The Digital Twin query service executes in-memory, read-only BFS path traversals with strictly enforced depth (`depth <= 10`), node (`nodes <= 500`), and edge (`edges <= 1000`) bounds, preventing infinite loops on non-DAG cyclic supply chain networks.
5. **Multi-Agent Governance**: LangGraph workflows coordinate specialized autonomous agents under strict human-in-the-loop governance. High-impact mitigation decisions require human approval before execution.
6. **Zero Drift Guarantee**: Backward compatibility is preserved across all 34 database tables and 60 REST API endpoints without schema mutations or route alterations.

---

## Documentation Directory

Explore the complete architecture and implementation specifications in [docs/](docs/):

- [Technical Project Specification](docs/RiskWise_2.0_Technical_Project_Spec.md)
- [UI / UX Design System](docs/RiskWise_2.0_UI_UX_Design_System.md)
- [High-Level Architecture Design](docs/DESIGN.md)
- [Database Schema Inventory (34 Tables)](docs/database-schema-inventory.md)
- [Phase 12: Digital Twin Architecture Specification](docs/phase12-digital-twin.md)
- [Phase 11: Machine Learning Architecture Specification](docs/phase11-ml.md)
- [Phase 10: AWS Bedrock & Claude Architecture Specification](docs/phase10-bedrock-claude.md)
- [Phase 9: LangGraph Agent State Contracts](docs/phase9-langgraph-agent-state-contract.md)
- [Phase 8: RAG Architecture & Contracts](docs/phase8-rag-architecture-contracts.md)
- [Phase 7: Risk Engine Architecture](docs/phase7-risk-engine-architecture.md)
- [Phase 6: Normalization Architecture](docs/phase6-normalization-architecture.md)
- [Phase 5: Canonical External Event Model](docs/phase5-canonical-event-model.md)
- [Multi-Tenant Authentication & RBAC Architecture](docs/authentication-architecture.md)
