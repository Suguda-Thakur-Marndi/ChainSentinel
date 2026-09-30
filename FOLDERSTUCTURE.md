# ChainSentinel / RiskWise — Full Folder Structure & File Directory

> **Repository Scope**: Complete structural inventory of all codebase modules, AI agent subsystems, API routers, database entities, UI views, tests, and configurations.

## Table of Contents
- [1. Architecture Overview](#1-architecture-overview)
- [2. High-Level Directory Tree](#2-high-level-directory-tree)
- [3. Root Project Files](#3-root-project-files)
- [4. Backend Root & Config (`api/`)](#4-backend-root--config-api)
- [5. Backend Database Migrations (`api/alembic/`)](#5-backend-database-migrations-apialembic)
- [6. Backend Core Infrastructure (`api/app/core/`, `api/app/db/`)](#6-backend-core-infrastructure-apiappcore-apiappdb)
- [7. Backend Database Models (`api/app/models/`)](#7-backend-database-models-apiappmodels)
- [8. Backend Data Repositories (`api/app/repositories/`)](#8-backend-data-repositories-apiapprepositories)
- [9. Backend API Schemas (`api/app/schemas/`)](#9-backend-api-schemas-apiappschemas)
- [10. Backend Services (`api/app/services/`)](#10-backend-services-apiappservices)
- [11. Backend REST API Endpoints (`api/app/api/`)](#11-backend-rest-api-endpoints-apiappapi)
- [12. Backend Multi-Agent System (`api/app/agents/`)](#12-backend-multi-agent-system-apiappagents)
- [13. Backend Digital Twin Domain (`api/app/digital_twin/`)](#13-backend-digital-twin-domain-apiappdigitaltwin)
- [14. Backend Risk Engine (`api/app/risk_engine/`)](#14-backend-risk-engine-apiappriskengine)
- [15. Backend Optimization Engine (`api/app/optimization/`)](#15-backend-optimization-engine-apiappoptimization)
- [16. Backend Simulation Engine (`api/app/simulation/`)](#16-backend-simulation-engine-apiappsimulation)
- [17. Backend Machine Learning (`api/app/ml/`)](#17-backend-machine-learning-apiappml)
- [18. Backend RAG & Knowledge Assembly (`api/app/rag/`)](#18-backend-rag--knowledge-assembly-apiapprag)
- [19. Backend LLM Gateway & Providers (`api/app/llm/`)](#19-backend-llm-gateway--providers-apiappllm)
- [20. Backend Third-Party Integrations (`api/app/integrations/`)](#20-backend-third-party-integrations-apiappintegrations)
- [21. Backend Ingestion & Normalization (`api/app/normalization/`)](#21-backend-ingestion--normalization-apiappnormalization)
- [22. Backend Evaluation & Governance (`api/app/evaluation/`)](#22-backend-evaluation--governance-apiappevaluation)
- [23. Backend Storage & Database Files (`api/storage/`)](#23-backend-storage--database-files-apistorage)
- [24. Backend Automated Test Suites (`api/tests/`)](#24-backend-automated-test-suites-apitests)
- [25. Frontend Root & Configurations (`web/`)](#25-frontend-root--configurations-web)
- [26. Frontend App Router Pages (`web/app/`)](#26-frontend-app-router-pages-webapp)
- [27. Frontend Components (`web/components/`)](#27-frontend-components-webcomponents)
- [28. Frontend Libraries & State Contexts (`web/lib/`)](#28-frontend-libraries--state-contexts-weblib)
- [29. Frontend Public Assets (`web/public/`)](#29-frontend-public-assets-webpublic)
- [30. Frontend Automated Tests (`web/tests/`)](#30-frontend-automated-tests-webtests)
- [31. Project Documentation & Architecture Specs (`docs/`)](#31-project-documentation--architecture-specs-docs)
- [32. Infrastructure & Deployments (`infra/`)](#32-infrastructure--deployments-infra)
- [33. Artifacts & Exports (`artifacts/`, `storage/`)](#33-artifacts--exports-artifacts-storage)

---

## 1. Architecture Overview

ChainSentinel / RiskWise is an enterprise-grade autonomous supply chain risk intelligence, simulation, and decision-automation platform. The repository is organized into three primary operational tiers:

1. **Backend Service (`api/`)**: Built with **FastAPI**, **SQLAlchemy**, and **Pydantic**. Houses the domain core, database repositories, external integrations (TomTom, Tavily, Rail), mathematical solvers (PuLP/SciPy), Monte Carlo disruption simulations, and a **LangGraph** autonomous multi-agent system comprising 7 specialized agents (Action, Approval, Decision, Prediction, Research, Risk, Scenario).
2. **Frontend Control Tower (`web/`)**: Built with **Next.js 16 (App Router)**, **React 19**, **TypeScript**, and **Tailwind CSS**. Provides a dark-mode glassmorphic interface with 38 dedicated routes covering Real-time Incident Monitoring, Digital Twin Graph Visualization, Route Optimization, What-If Simulation Sandboxes, Policy Audits, and Human-in-the-Loop Approval Queues.
3. **Governance & Documentation (`docs/`)**: Rigorous phase-by-phase architectural specifications, API schemas, integration contracts, and security compliance matrices.

---

## 2. High-Level Directory Tree

```text
riskwise/
├── api/                         # FastAPI Backend & Agent Architecture
│   ├── alembic/                 # Database Schema Migration Scripts
│   ├── app/                     # Core Backend Application Source
│   │   ├── agents/              # LangGraph Autonomous Multi-Agent Network
│   │   │   ├── action/          # Automated Remediation Action Dispatcher
│   │   │   ├── approval/        # Human-in-the-Loop Approval Engine
│   │   │   ├── decision/        # Policy-Compliant Decision Recommender
│   │   │   ├── prediction/      # ETA Delay & Disruption Forecaster
│   │   │   ├── research/        # Web OSINT & News Research Agent
│   │   │   ├── risk/            # Multi-Factor Supply Chain Risk Evaluator
│   │   │   └── scenario/        # What-If Disruption Scenario Simulator
│   │   ├── api/v1/endpoints/    # REST API Controllers & Endpoints
│   │   ├── core/                # Configuration, JWT Security, & Context
│   │   ├── db/                  # Session Lifecycles & Unit of Work
│   │   ├── digital_twin/        # Network Graph Model (Nodes & Lanes)
│   │   ├── evaluation/          # Evaluation Suites, Metrics, & Datasets
│   │   ├── integrations/        # TomTom, Tavily, Rail, Weather Clients
│   │   ├── llm/                 # Model Gateway, Prompting, & Fallbacks
│   │   ├── ml/                  # Feature Extraction & Delay Prediction
│   │   ├── models/              # SQLAlchemy Database ORM Models
│   │   ├── normalization/       # Ingestion Contracts & Entity Parsers
│   │   ├── optimization/        # Linear Programming & Route Solvers
│   │   ├── rag/                 # Vector Store Ingestion & Grounding
│   │   ├── repositories/        # Database CRUD Data Access Layer
│   │   ├── risk_engine/         # Baseline Scoring & Anomaly Detection
│   │   ├── schemas/             # Pydantic Input/Output Schemas
│   │   ├── services/            # Transactional Business Workflows
│   │   └── simulation/          # Monte Carlo Supply Chain Disruption Engine
│   └── tests/                   # 130+ Automated Test Suites (Phases 1-21)
├── web/                         # Next.js 16 Web Application
│   ├── app/                     # Next.js App Router (38 UI Routes)
│   ├── components/              # Design System, Layouts, & 3D Visuals
│   ├── lib/                     # API Clients, Auth Contexts, & Types
│   ├── public/                  # SVG Icons & Static Web Assets
│   └── tests/                   # Frontend Integration & Control Tower Tests
├── docs/                        # Architectural Specifications & Reports
├── infra/                       # Docker & Orchestration Manifests
└── ...                          # Root Configurations & Credentials
```

---

## 3. Root Project Files
*Total Files: 10*

| File Path | Description / Role |
| :--- | :--- |
| [`.env`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/.env) | Local environment variables for credentials, API tokens, database URIs, and service configuration. |
| [`.env.example`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/.env.example) | Template environment variables file showing required and optional system configuration keys. |
| [`.gitignore`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/.gitignore) | Specifies intentionally untracked files to ignore from Git version control. |
| [`AGENTS.md`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/AGENTS.md) | Operational guidelines, environment rules, and context instructions for AI coding agents. |
| [`CLEANUP-REPORT.md`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/CLEANUP-REPORT.md) | Hygiene verification report documenting removed deprecated scripts and cleaned modules. |
| [`FOLDERSTUCTURE.md`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/FOLDERSTUCTURE.md) | Comprehensive directory structure and file reference for the entire ChainSentinel / RiskWise repository. |
| [`README.md`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/README.md) | Primary project overview, architecture diagram, features, technology stack, and setup instructions. |
| [`UI-REPORT.md`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/UI-REPORT.md) | Frontend UI audit report validating typography, color palette, design systems, and page layouts. |
| [`credentials.json`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/credentials.json) | Google OAuth and service credential keys. |
| [`risk-wise.pem`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/risk-wise.pem) | Security certificate / private key for authenticated transport. |

---

## 4. Backend Root & Config (`api/`)
*Total Files: 9*

| File Path | Description / Role |
| :--- | :--- |
| [`api/.dockerignore`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/.dockerignore) | Exclusion patterns for Docker container image builds of the backend service. |
| [`api/.env`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/.env) | Local environment configuration specific to FastAPI backend execution. |
| [`api/Dockerfile`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/Dockerfile) | Containerization blueprint for packaging and deploying the FastAPI backend application. |
| [`api/alembic.ini`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/alembic.ini) | Configuration settings for Alembic database migration management. |
| [`api/pyproject.toml`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/pyproject.toml) | Python package build configuration, dependencies, and pytest runtime settings. |
| [`api/requirements.txt`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/requirements.txt) | Pinned Python library dependencies for the backend services and AI agents. |
| [`api/riskwise_local.db`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/riskwise_local.db) | Local SQLite database used for offline development and testing fallback. |
| [`api/app/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/__init__.py) | Package initializer for the core RiskWise backend application. |
| [`api/app/main.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/main.py) | FastAPI application entry point configuring middleware, CORS, lifespan, and API v1 routers. |

---

## 5. Backend Database Migrations (`api/alembic/`)
*Total Files: 3*

| File Path | Description / Role |
| :--- | :--- |
| [`api/alembic/env.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/alembic/env.py) | Alembic runtime environment script setting up SQLAlchemy metadata and migrations. |
| [`api/alembic/script.py.mako`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/alembic/script.py.mako) | Alembic template used to generate new schema migration scripts. |
| [`api/alembic/versions/.gitkeep`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/alembic/versions/.gitkeep) | Placeholder preserving the versions directory in version control. |

---

## 6. Backend Core Infrastructure (`api/app/core/`, `api/app/db/`)
*Total Files: 12*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/core/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/core/__init__.py) | Core configuration and utilities. |
| [`api/app/core/config.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/core/config.py) | Core system utility, configuration, security, or context handler for Config. |
| [`api/app/core/context.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/core/context.py) | Execution and authentication context definitions for RiskWise. |
| [`api/app/core/encryption.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/core/encryption.py) | Core system utility, configuration, security, or context handler for Encryption. |
| [`api/app/core/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/core/errors.py) | Core system utility, configuration, security, or context handler for Errors. |
| [`api/app/core/logging.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/core/logging.py) | Central application logging configuration for RiskWise API. |
| [`api/app/core/rate_limit.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/core/rate_limit.py) | Core system utility, configuration, security, or context handler for Rate Limit. |
| [`api/app/core/telemetry.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/core/telemetry.py) | Production-Grade OpenTelemetry Observability & GenAI Semantic Conventions. |
| [`api/app/db/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/db/__init__.py) | Database connection, session handling, and Declarative Base package. |
| [`api/app/db/base.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/db/base.py) | SQLAlchemy Declarative Base for RiskWise 2.0. |
| [`api/app/db/session.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/db/session.py) | Database connection and session configuration for PostgreSQL. |
| [`api/app/db/unit_of_work.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/db/unit_of_work.py) | Database session lifecycle, engine configuration, or unit of work for Unit Of Work. |

---

## 7. Backend Database Models (`api/app/models/`)
*Total Files: 11*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/models/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/models/__init__.py) | SQLAlchemy database models package. |
| [`api/app/models/agents.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/models/agents.py) | SQLAlchemy models for multi-agent autonomous investigation runs, tasks, and tool call audits. |
| [`api/app/models/digital_twin.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/models/digital_twin.py) | SQLAlchemy models for the supply chain Digital Twin topology graph (Nodes and Edges). |
| [`api/app/models/evaluation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/models/evaluation.py) | SQLAlchemy database models for Phase 20 Evaluation Framework. |
| [`api/app/models/governance.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/models/governance.py) | SQLAlchemy ORM entity model defining database schema for Governance. |
| [`api/app/models/knowledge.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/models/knowledge.py) | SQLAlchemy models for knowledge base documents, chunks, and semantic embeddings. |
| [`api/app/models/logistics.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/models/logistics.py) | SQLAlchemy models for logistics, freight tracking, telemetry, and inventory management. |
| [`api/app/models/network.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/models/network.py) | SQLAlchemy models for supply chain network entities (Suppliers, Facilities, Ports, Routes, Carriers, Products). |
| [`api/app/models/risk.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/models/risk.py) | SQLAlchemy models for risk intelligence, risk factors, assessments, and disruption incidents. |
| [`api/app/models/simulation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/models/simulation.py) | SQLAlchemy models for scenarios, simulation projections, and prescriptive optimization runs. |
| [`api/app/models/tenancy.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/models/tenancy.py) | SQLAlchemy models for multi-tenant organizations and users. |

---

## 8. Backend Data Repositories (`api/app/repositories/`)
*Total Files: 11*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/repositories/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/repositories/__init__.py) | Repository layer exports for RiskWise 2.0 API. |
| [`api/app/repositories/audit_log.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/repositories/audit_log.py) | Repository for AuditLog entity data access. |
| [`api/app/repositories/base.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/repositories/base.py) | Repository pattern data access layer implementing CRUD queries for Base. |
| [`api/app/repositories/governance_repositories.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/repositories/governance_repositories.py) | Repository pattern data access layer implementing CRUD queries for Governance Repositories. |
| [`api/app/repositories/inventory.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/repositories/inventory.py) | Repositories for Inventory and InventoryMovement data access, query allowlists, and atomic concurrency. |
| [`api/app/repositories/network_repositories.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/repositories/network_repositories.py) | Repository pattern data access layer implementing CRUD queries for Network Repositories. |
| [`api/app/repositories/port.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/repositories/port.py) | Repository for Port global reference entity data access. |
| [`api/app/repositories/query_utils.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/repositories/query_utils.py) | Repository pattern data access layer implementing CRUD queries for Query Utils. |
| [`api/app/repositories/risk_repositories.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/repositories/risk_repositories.py) | Repositories for Risk intelligence, RiskFactor child entity, RiskAssessment, and Incident resources. |
| [`api/app/repositories/shipment.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/repositories/shipment.py) | Repository pattern data access layer implementing CRUD queries for Shipment. |
| [`api/app/repositories/supplier.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/repositories/supplier.py) | Repository for Supplier entity data access and lifecycle operations. |

---

## 9. Backend API Schemas (`api/app/schemas/`)
*Total Files: 14*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/schemas/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/schemas/__init__.py) | Package initializer and module exports for `schemas`. |
| [`api/app/schemas/agents.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/schemas/agents.py) | Pydantic schemas for multi-agent autonomous investigation runs, tasks, and tool call audits. |
| [`api/app/schemas/auth.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/schemas/auth.py) | Pydantic schemas for request validation and response serialization of Auth. |
| [`api/app/schemas/common.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/schemas/common.py) | Common and reusable Pydantic schemas for pagination, sorting, and standardized errors. |
| [`api/app/schemas/digital_twin.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/schemas/digital_twin.py) | Pydantic schemas for supply chain Digital Twin topology graph (Nodes and Edges). |
| [`api/app/schemas/governance.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/schemas/governance.py) | Pydantic schemas for governance, recommendations, approvals, actions, verification, audit trails, and notifications. |
| [`api/app/schemas/health.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/schemas/health.py) | Pydantic schemas for health check endpoints. |
| [`api/app/schemas/knowledge.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/schemas/knowledge.py) | Pydantic schemas for knowledge base documents and text chunks for RAG. |
| [`api/app/schemas/logistics.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/schemas/logistics.py) | Pydantic schemas for request validation and response serialization of Logistics. |
| [`api/app/schemas/network.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/schemas/network.py) | Pydantic schemas for supply chain network resources (Suppliers, Sites, Facilities, Ports, Carriers, Products, Routes). |
| [`api/app/schemas/risk.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/schemas/risk.py) | Pydantic schemas for risk intelligence, risk factors, assessments, and incidents. |
| [`api/app/schemas/session.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/schemas/session.py) | Pydantic schemas for application session management (Phase 3 Step 4). |
| [`api/app/schemas/simulation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/schemas/simulation.py) | Pydantic schemas for scenarios, simulation projections, and prescriptive optimization runs. |
| [`api/app/schemas/tenancy.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/schemas/tenancy.py) | Pydantic schemas for multi-tenant organizations and users. |

---

## 10. Backend Services (`api/app/services/`)
*Total Files: 12*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/services/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/services/__init__.py) | Service layer exports for RiskWise 2.0 API. |
| [`api/app/services/audit_service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/services/audit_service.py) | Business logic service encapsulating operations and transactions for Audit Service. |
| [`api/app/services/base.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/services/base.py) | Business logic service encapsulating operations and transactions for Base. |
| [`api/app/services/concurrency.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/services/concurrency.py) | Concurrency utilities for row locking, atomic arithmetic, and idempotent state transitions. |
| [`api/app/services/governance_services.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/services/governance_services.py) | Business logic service encapsulating operations and transactions for Governance Services. |
| [`api/app/services/inventory_services.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/services/inventory_services.py) | Domain services for Inventory and InventoryMovement entities with atomic concurrency and ledger immutability. |
| [`api/app/services/logistics_services.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/services/logistics_services.py) | Business logic service encapsulating operations and transactions for Logistics Services. |
| [`api/app/services/oauth_service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/services/oauth_service.py) | Business logic service encapsulating operations and transactions for Oauth Service. |
| [`api/app/services/risk_evaluation_service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/services/risk_evaluation_service.py) | Business logic service encapsulating operations and transactions for Risk Evaluation Service. |
| [`api/app/services/risk_services.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/services/risk_services.py) | Domain services for Risk intelligence, RiskFactor child entity, RiskAssessment, and Incident resources. |
| [`api/app/services/session_service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/services/session_service.py) | Business logic service encapsulating operations and transactions for Session Service. |
| [`api/app/services/supplier.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/services/supplier.py) | Business logic service encapsulating operations and transactions for Supplier. |

---

## 11. Backend REST API Endpoints (`api/app/api/`)
*Total Files: 34*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/api/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/__init__.py) | API routing package. |
| [`api/app/api/deps.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/deps.py) | Reusable FastAPI dependencies for authentication, tenancy, and authorization (Phase 3 Step 4). |
| [`api/app/api/v1/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/__init__.py) | API v1 package. |
| [`api/app/api/v1/router.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/router.py) | Central API v1 router for RiskWise API. |
| [`api/app/api/v1/endpoints/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/__init__.py) | API v1 endpoints package. |
| [`api/app/api/v1/endpoints/actions.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/actions.py) | FastAPI REST endpoints and route handlers for Actions operations. |
| [`api/app/api/v1/endpoints/approvals.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/approvals.py) | Approvals API endpoints for RiskWise 2.0 (Phase 4 Step 7 & Phase 16 Human Approval). |
| [`api/app/api/v1/endpoints/audit_logs.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/audit_logs.py) | Audit Logs API endpoints for RiskWise 2.0 (Phase 4 Step 7). |
| [`api/app/api/v1/endpoints/auth.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/auth.py) | FastAPI REST endpoints and route handlers for Auth operations. |
| [`api/app/api/v1/endpoints/carriers.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/carriers.py) | Carriers API endpoints for RiskWise 2.0 (Phase 4 Step 4). |
| [`api/app/api/v1/endpoints/decisions.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/decisions.py) | FastAPI REST endpoints and route handlers for Decisions operations. |
| [`api/app/api/v1/endpoints/digital_twin.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/digital_twin.py) | FastAPI REST endpoints and route handlers for Digital Twin operations. |
| [`api/app/api/v1/endpoints/evaluations.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/evaluations.py) | FastAPI REST endpoints and route handlers for Evaluations operations. |
| [`api/app/api/v1/endpoints/factories.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/factories.py) | Factories API endpoints for RiskWise 2.0 (Phase 4 Step 4). |
| [`api/app/api/v1/endpoints/health.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/health.py) | Health check endpoints for RiskWise API v1. |
| [`api/app/api/v1/endpoints/incidents.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/incidents.py) | Incidents API endpoints for RiskWise 2.0 (Phase 4 Step 6). |
| [`api/app/api/v1/endpoints/inventory.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/inventory.py) | Inventory API endpoints for RiskWise 2.0 (Phase 4 Step 5). |
| [`api/app/api/v1/endpoints/inventory_movements.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/inventory_movements.py) | Inventory Movements API endpoints for RiskWise 2.0 (Phase 4 Step 5). |
| [`api/app/api/v1/endpoints/notifications.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/notifications.py) | Notifications API endpoints for RiskWise 2.0 (Phase 4 Step 7). |
| [`api/app/api/v1/endpoints/optimization.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/optimization.py) | FastAPI endpoints for RiskWise Optimization Subsystem (Phase 14). |
| [`api/app/api/v1/endpoints/ports.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/ports.py) | Ports API endpoints for RiskWise 2.0 (Phase 4 Step 4). |
| [`api/app/api/v1/endpoints/products.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/products.py) | Products API endpoints for RiskWise 2.0 (Phase 4 Step 4). |
| [`api/app/api/v1/endpoints/recommendations.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/recommendations.py) | FastAPI REST endpoints and route handlers for Recommendations operations. |
| [`api/app/api/v1/endpoints/risk_assessments.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/risk_assessments.py) | FastAPI REST endpoints and route handlers for Risk Assessments operations. |
| [`api/app/api/v1/endpoints/risk_factors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/risk_factors.py) | Risk Factors API endpoints for RiskWise 2.0 (Phase 4 Step 6). |
| [`api/app/api/v1/endpoints/risks.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/risks.py) | FastAPI REST endpoints and route handlers for Risks operations. |
| [`api/app/api/v1/endpoints/routes.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/routes.py) | Routes API endpoints for RiskWise 2.0 (Phase 4 Step 4). |
| [`api/app/api/v1/endpoints/shipment_events.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/shipment_events.py) | Shipment Events API endpoints for RiskWise 2.0 (Phase 4 Step 4). |
| [`api/app/api/v1/endpoints/shipments.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/shipments.py) | FastAPI REST endpoints and route handlers for Shipments operations. |
| [`api/app/api/v1/endpoints/simulation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/simulation.py) | FastAPI REST endpoints and route handlers for Simulation operations. |
| [`api/app/api/v1/endpoints/supplier_sites.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/supplier_sites.py) | Supplier Sites API endpoints for RiskWise 2.0 (Phase 4 Step 4). |
| [`api/app/api/v1/endpoints/suppliers.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/suppliers.py) | Supplier API endpoints for RiskWise 2.0 (Phase 4 Step 3). |
| [`api/app/api/v1/endpoints/verification_results.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/verification_results.py) | FastAPI REST endpoints and route handlers for Verification Results operations. |
| [`api/app/api/v1/endpoints/warehouses.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/api/v1/endpoints/warehouses.py) | Warehouses API endpoints for RiskWise 2.0 (Phase 4 Step 4). |

---

## 12. Backend Multi-Agent System (`api/app/agents/`)
*Total Files: 82*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/agents/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/__init__.py) | Package initializer and module exports for `agents`. |
| [`api/app/agents/checkpointer.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/checkpointer.py) | Thread and checkpoint persistence for LangGraph agent workflow state. |
| [`api/app/agents/contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/contracts.py) | Core Pydantic schemas, agent state contracts, and protocol interfaces. |
| [`api/app/agents/edges.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/edges.py) | Conditional routing edges and transition logic between LangGraph agent nodes. |
| [`api/app/agents/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/errors.py) | Custom exception classes and error taxonomy for the multi-agent system. |
| [`api/app/agents/execution.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/execution.py) | Execution manager and workflow orchestration runner for agent jobs. |
| [`api/app/agents/graph.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/graph.py) | Foundational LangGraph graph builder, execution lifecycle, and checkpointing boundary. |
| [`api/app/agents/nodes.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/nodes.py) | Node execution handlers executing individual agent actions and state updates. |
| [`api/app/agents/observability.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/observability.py) | Telemetry, tracing, and token usage metrics instrumentation for agents. |
| [`api/app/agents/recovery.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/recovery.py) | Deterministic failure recovery, bounded retries, state integrity, and checkpointing. |
| [`api/app/agents/registry.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/registry.py) | Node registration architecture and explicit allowlisting for LangGraph nodes. |
| [`api/app/agents/routing.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/routing.py) | Deterministic routing contracts and fail-closed route evaluation for LangGraph. |
| [`api/app/agents/security.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/security.py) | Security guardrails, prompt injection sanitization, and output validation. |
| [`api/app/agents/validator.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/validator.py) | Verification contracts and schema validation for agent inputs and outputs. |
| [`api/app/agents/action/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/action/__init__.py) | RiskWise 2.0 Action Agent Subsystem (Phase 17). |
| [`api/app/agents/action/agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/action/agent.py) | Autonomous agent logic and decision engine for `agent`. |
| [`api/app/agents/action/contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/action/contract.py) | Domain contracts, schemas, enums, and deterministic identifiers for the RiskWise Action Agent (Phase 17). |
| [`api/app/agents/action/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/action/errors.py) | Custom exception classes and error taxonomy for the multi-agent system. |
| [`api/app/agents/action/executors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/action/executors.py) | Execution adapters and allowlisted provider integrations for the Action Agent (Phase 17). |
| [`api/app/agents/action/node.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/action/node.py) | LangGraph execution node for `node`. |
| [`api/app/agents/action/persistence.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/action/persistence.py) | State persistence and historical checkpoint handlers for `persistence`. |
| [`api/app/agents/action/policy.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/action/policy.py) | Policy rules, guardrails, and compliance thresholds for `policy`. |
| [`api/app/agents/approval/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/approval/__init__.py) | Human Approval package for RiskWise 2.0 LangGraph multi-agent pipeline. |
| [`api/app/agents/approval/agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/approval/agent.py) | Human Approval orchestration agent producing structured governance findings. |
| [`api/app/agents/approval/contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/approval/contract.py) | Pydantic contracts and payload schemas for `contract`. |
| [`api/app/agents/approval/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/approval/errors.py) | Strongly typed exceptions for the RiskWise Human Approval boundary (Phase 9 Step 9). |
| [`api/app/agents/approval/node.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/approval/node.py) | LangGraph execution node for `node`. |
| [`api/app/agents/approval/persistence.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/approval/persistence.py) | Transactional persistence and query repository for RiskWise Human Approval Subsystem (Phase 16). |
| [`api/app/agents/approval/service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/approval/service.py) | Domain service governing human approval operations, RBAC verification, and transactional audit trails. |
| [`api/app/agents/decision/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/decision/__init__.py) | Public interface for the RiskWise Decision Agent (Phase 9 Step 8 & Phase 10 Step 7). |
| [`api/app/agents/decision/agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/decision/agent.py) | Autonomous agent logic and decision engine for `agent`. |
| [`api/app/agents/decision/claude_contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/decision/claude_contract.py) | Strongly typed contracts for Claude Decision Analysis & Explanation Layer (Phase 10 Step 7). |
| [`api/app/agents/decision/claude_service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/decision/claude_service.py) | Business service layer orchestrating workflows for `claude_service`. |
| [`api/app/agents/decision/contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/decision/contract.py) | Strongly typed domain contracts for the RiskWise Decision Agent (Phase 9 Step 8). |
| [`api/app/agents/decision/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/decision/errors.py) | Custom exception classes and error taxonomy for the multi-agent system. |
| [`api/app/agents/decision/node.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/decision/node.py) | LangGraph execution node for `node`. |
| [`api/app/agents/decision/persistence.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/decision/persistence.py) | Transactional persistence for RiskWise Decision Agent (Phase 15). |
| [`api/app/agents/decision/policy.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/decision/policy.py) | Policy rules, guardrails, and compliance thresholds for `policy`. |
| [`api/app/agents/decision/rules.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/decision/rules.py) | Configuration or source file: `rules.py`. |
| [`api/app/agents/prediction/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/prediction/__init__.py) | Prediction Agent package for RiskWise 2.0 (Phase 9 Step 6). |
| [`api/app/agents/prediction/adapter.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/prediction/adapter.py) | Configuration or source file: `adapter.py`. |
| [`api/app/agents/prediction/agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/prediction/agent.py) | Autonomous agent logic and decision engine for `agent`. |
| [`api/app/agents/prediction/claude_contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/prediction/claude_contract.py) | Pydantic contracts and payload schemas for `claude_contract`. |
| [`api/app/agents/prediction/claude_service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/prediction/claude_service.py) | Business service layer orchestrating workflows for `claude_service`. |
| [`api/app/agents/prediction/contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/prediction/contract.py) | Pydantic contracts and payload schemas for `contract`. |
| [`api/app/agents/prediction/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/prediction/errors.py) | Custom exception classes and error taxonomy for the multi-agent system. |
| [`api/app/agents/prediction/node.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/prediction/node.py) | LangGraph execution node for `node`. |
| [`api/app/agents/prediction/service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/prediction/service.py) | Business service layer orchestrating workflows for `service`. |
| [`api/app/agents/research/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/research/__init__.py) | Research Agent package for RiskWise LangGraph orchestration. |
| [`api/app/agents/research/agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/research/agent.py) | Core domain service for the RiskWise Research Agent. |
| [`api/app/agents/research/analysis.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/research/analysis.py) | Deterministic evidence analysis and structured finding synthesis for Research Agent. |
| [`api/app/agents/research/claude_contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/research/claude_contract.py) | Strongly typed contracts for structured Claude research synthesis outputs. |
| [`api/app/agents/research/claude_service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/research/claude_service.py) | Business service layer orchestrating workflows for `claude_service`. |
| [`api/app/agents/research/contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/research/contract.py) | Pydantic contracts and payload schemas for `contract`. |
| [`api/app/agents/research/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/research/errors.py) | Strongly typed error taxonomy for the RiskWise Research Agent. |
| [`api/app/agents/research/evidence.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/research/evidence.py) | Configuration or source file: `evidence.py`. |
| [`api/app/agents/research/node.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/research/node.py) | LangGraph execution node for `node`. |
| [`api/app/agents/risk/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/risk/__init__.py) | RiskWise Risk Agent Package — Phase 9 Step 5 & Phase 10 Step 4. |
| [`api/app/agents/risk/adapter.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/risk/adapter.py) | Configuration or source file: `adapter.py`. |
| [`api/app/agents/risk/agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/risk/agent.py) | Autonomous agent logic and decision engine for `agent`. |
| [`api/app/agents/risk/claude_contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/risk/claude_contract.py) | Pydantic contracts and payload schemas for `claude_contract`. |
| [`api/app/agents/risk/claude_service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/risk/claude_service.py) | Claude Risk Explanation Service for Phase 10 Step 4. |
| [`api/app/agents/risk/contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/risk/contract.py) | Pydantic contracts and payload schemas for `contract`. |
| [`api/app/agents/risk/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/risk/errors.py) | Strongly typed error taxonomy for the RiskWise Risk Agent. |
| [`api/app/agents/risk/node.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/risk/node.py) | LangGraph execution node for `node`. |
| [`api/app/agents/scenario/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/scenario/__init__.py) | Public interface for the RiskWise Scenario Agent (Phase 9 Step 7). |
| [`api/app/agents/scenario/agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/scenario/agent.py) | Scenario Agent execution and orchestration layer. |
| [`api/app/agents/scenario/claude_contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/scenario/claude_contract.py) | Strongly typed contracts for Claude Scenario Analysis & Explanation Layer (Phase 10 Step 5). |
| [`api/app/agents/scenario/claude_service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/scenario/claude_service.py) | Business service layer orchestrating workflows for `claude_service`. |
| [`api/app/agents/scenario/contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/scenario/contract.py) | Pydantic contracts and payload schemas for `contract`. |
| [`api/app/agents/scenario/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/scenario/errors.py) | Custom exception classes and error taxonomy for the multi-agent system. |
| [`api/app/agents/scenario/generator.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/scenario/generator.py) | Configuration or source file: `generator.py`. |
| [`api/app/agents/scenario/node.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/scenario/node.py) | LangGraph execution node for `node`. |
| [`api/app/agents/verification/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/verification/__init__.py) | RiskWise Verification Agent (Phase 18). |
| [`api/app/agents/verification/agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/verification/agent.py) | Core orchestrator for the RiskWise Verification Agent (Phase 18). |
| [`api/app/agents/verification/contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/verification/contract.py) | Pydantic contracts and payload schemas for `contract`. |
| [`api/app/agents/verification/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/verification/errors.py) | Error hierarchy for the Verification Agent (Phase 18). |
| [`api/app/agents/verification/evidence.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/verification/evidence.py) | Configuration or source file: `evidence.py`. |
| [`api/app/agents/verification/node.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/verification/node.py) | LangGraph execution node for `node`. |
| [`api/app/agents/verification/persistence.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/verification/persistence.py) | Authoritative persistence and idempotency manager for the Verification Agent (Phase 18). |
| [`api/app/agents/verification/policy.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/verification/policy.py) | Authoritative verification policy orchestrator for Phase 18. |
| [`api/app/agents/verification/verifiers.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/agents/verification/verifiers.py) | Configuration or source file: `verifiers.py`. |

---

## 13. Backend Digital Twin Domain (`api/app/digital_twin/`)
*Total Files: 10*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/digital_twin/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/digital_twin/__init__.py) | RiskWise 2.0 Digital Twin subsystem. |
| [`api/app/digital_twin/builder.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/digital_twin/builder.py) | Digital twin domain logic, network graph modeling, and state tracking for Builder. |
| [`api/app/digital_twin/contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/digital_twin/contracts.py) | Digital twin domain logic, network graph modeling, and state tracking for Contracts. |
| [`api/app/digital_twin/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/digital_twin/errors.py) | Typed exception hierarchy for the RiskWise Digital Twin subsystem. |
| [`api/app/digital_twin/fingerprints.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/digital_twin/fingerprints.py) | Deterministic identity generators and canonical SHA-256 fingerprinting for Digital Twin. |
| [`api/app/digital_twin/observability.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/digital_twin/observability.py) | Digital twin domain logic, network graph modeling, and state tracking for Observability. |
| [`api/app/digital_twin/query.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/digital_twin/query.py) | Digital twin domain logic, network graph modeling, and state tracking for Query. |
| [`api/app/digital_twin/repository.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/digital_twin/repository.py) | Digital twin domain logic, network graph modeling, and state tracking for Repository. |
| [`api/app/digital_twin/service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/digital_twin/service.py) | Digital twin domain logic, network graph modeling, and state tracking for Service. |
| [`api/app/digital_twin/validator.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/digital_twin/validator.py) | Digital twin domain logic, network graph modeling, and state tracking for Validator. |

---

## 14. Backend Risk Engine (`api/app/risk_engine/`)
*Total Files: 14*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/risk_engine/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/risk_engine/__init__.py) | RiskWise 2.0 Risk Engine Package (Phase 7). |
| [`api/app/risk_engine/alerts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/risk_engine/alerts.py) | Risk assessment, baseline calculation, and anomaly detection rules for Alerts. |
| [`api/app/risk_engine/context.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/risk_engine/context.py) | Risk evaluation context contract and tenant isolation boundaries for RiskWise Risk Engine. |
| [`api/app/risk_engine/contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/risk_engine/contract.py) | Risk assessment, baseline calculation, and anomaly detection rules for Contract. |
| [`api/app/risk_engine/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/risk_engine/errors.py) | Centralized typed exception definitions for RiskWise Risk Engine. |
| [`api/app/risk_engine/evaluators.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/risk_engine/evaluators.py) | Risk assessment, baseline calculation, and anomaly detection rules for Evaluators. |
| [`api/app/risk_engine/evidence.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/risk_engine/evidence.py) | Risk assessment, baseline calculation, and anomaly detection rules for Evidence. |
| [`api/app/risk_engine/explainability.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/risk_engine/explainability.py) | Risk assessment, baseline calculation, and anomaly detection rules for Explainability. |
| [`api/app/risk_engine/history.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/risk_engine/history.py) | Historical assessment analysis, deterministic comparisons, and trend evaluation for Phase 7 Step 5. |
| [`api/app/risk_engine/persistence.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/risk_engine/persistence.py) | Risk assessment, baseline calculation, and anomaly detection rules for Persistence. |
| [`api/app/risk_engine/pipeline.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/risk_engine/pipeline.py) | Risk assessment, baseline calculation, and anomaly detection rules for Pipeline. |
| [`api/app/risk_engine/recommendations.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/risk_engine/recommendations.py) | Deterministic decision and recommendation foundation for RiskWise 2.0 Risk Engine. |
| [`api/app/risk_engine/registry.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/risk_engine/registry.py) | Risk factor evaluator interface and deterministic registry for RiskWise Risk Engine. |
| [`api/app/risk_engine/scoring.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/risk_engine/scoring.py) | Risk assessment, baseline calculation, and anomaly detection rules for Scoring. |

---

## 15. Backend Optimization Engine (`api/app/optimization/`)
*Total Files: 15*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/optimization/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/__init__.py) | RiskWise Optimization Subsystem (Phase 14). |
| [`api/app/optimization/config.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/config.py) | Configuration and resource bounding limits for RiskWise Optimization Subsystem (Phase 14). |
| [`api/app/optimization/constraints.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/constraints.py) | Constraint formulations for RiskWise Optimization Subsystem (Phase 14). |
| [`api/app/optimization/contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/contracts.py) | Strongly typed Pydantic contracts for RiskWise Optimization Subsystem (Phase 14). |
| [`api/app/optimization/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/errors.py) | Typed exception hierarchy for RiskWise Optimization Subsystem (Phase 14). |
| [`api/app/optimization/fingerprints.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/fingerprints.py) | Deterministic SHA-256 canonical fingerprint and UUID generation for Phase 14 Optimization. |
| [`api/app/optimization/integration.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/integration.py) | Mathematical optimization solver and constraint modeling for Integration. |
| [`api/app/optimization/model.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/model.py) | Mathematical problem model assembly for RiskWise Optimization Subsystem (Phase 14). |
| [`api/app/optimization/objectives.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/objectives.py) | Mathematical objective function formulations for RiskWise Optimization Subsystem (Phase 14). |
| [`api/app/optimization/persistence.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/persistence.py) | Transactional persistence for Phase 14 Optimization in the optimization_runs table. |
| [`api/app/optimization/result.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/result.py) | Mathematical optimization solver and constraint modeling for Result. |
| [`api/app/optimization/service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/service.py) | Mathematical optimization solver and constraint modeling for Service. |
| [`api/app/optimization/solver.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/solver.py) | Google OR-Tools solver integration for RiskWise Optimization Subsystem (Phase 14). |
| [`api/app/optimization/validators.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/validators.py) | Input validation and security boundary checks for Phase 14 Optimization. |
| [`api/app/optimization/variables.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/optimization/variables.py) | Decision variable formulations for RiskWise Optimization Subsystem (Phase 14). |

---

## 16. Backend Simulation Engine (`api/app/simulation/`)
*Total Files: 19*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/simulation/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/__init__.py) | RiskWise 2.0 Simulation Engine (Phase 13). |
| [`api/app/simulation/config.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/config.py) | Configuration and hard safety limits for RiskWise Simulation Engine (Phase 13). |
| [`api/app/simulation/contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/contracts.py) | Disruption modeling, scenario simulation, and Monte Carlo algorithms for Contracts. |
| [`api/app/simulation/effects.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/effects.py) | Effect definitions and cataloging for simulation propagation. |
| [`api/app/simulation/engine.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/engine.py) | Disruption modeling, scenario simulation, and Monte Carlo algorithms for Engine. |
| [`api/app/simulation/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/errors.py) | Typed exception hierarchy for RiskWise Simulation Engine (Phase 13). |
| [`api/app/simulation/fingerprints.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/fingerprints.py) | Deterministic SHA-256 fingerprinting and UUIDv5 identity generation for Simulation Engine. |
| [`api/app/simulation/integration.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/integration.py) | Disruption modeling, scenario simulation, and Monte Carlo algorithms for Integration. |
| [`api/app/simulation/metrics.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/metrics.py) | Metric calculation and scenario comparison logic for RiskWise Simulation Engine. |
| [`api/app/simulation/observability.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/observability.py) | Structured observability, logging, and audit emission for Simulation Engine. |
| [`api/app/simulation/persistence.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/persistence.py) | Persistence module re-export for RiskWise Simulation Engine. |
| [`api/app/simulation/propagation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/propagation.py) | Deterministic, bounded graph effect propagation engine for what-if scenarios. |
| [`api/app/simulation/repository.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/repository.py) | Disruption modeling, scenario simulation, and Monte Carlo algorithms for Repository. |
| [`api/app/simulation/scenario.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/scenario.py) | Scenario builders and multi-change composition utilities. |
| [`api/app/simulation/scenarios.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/scenarios.py) | Scenarios module re-export for RiskWise Simulation Engine. |
| [`api/app/simulation/service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/service.py) | Disruption modeling, scenario simulation, and Monte Carlo algorithms for Service. |
| [`api/app/simulation/state.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/state.py) | Disruption modeling, scenario simulation, and Monte Carlo algorithms for State. |
| [`api/app/simulation/validation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/validation.py) | Disruption modeling, scenario simulation, and Monte Carlo algorithms for Validation. |
| [`api/app/simulation/validators.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/simulation/validators.py) | Validators module re-export for RiskWise Simulation Engine. |

---

## 17. Backend Machine Learning (`api/app/ml/`)
*Total Files: 23*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/ml/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/__init__.py) | RiskWise 2.0 Machine Learning Subsystem (Phase 11). |
| [`api/app/ml/config.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/config.py) | Typed configuration settings for the RiskWise ML subsystem. |
| [`api/app/ml/contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/contracts.py) | Machine learning feature processor, model pipeline, or inference logic for Contracts. |
| [`api/app/ml/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/errors.py) | Strongly typed error hierarchy for the RiskWise ML subsystem. |
| [`api/app/ml/observability.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/observability.py) | Telemetry, structured logging, and audit event emission for the RiskWise ML layer. |
| [`api/app/ml/datasets/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/datasets/__init__.py) | ML dataset contracts, validators, and builders. |
| [`api/app/ml/datasets/builder.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/datasets/builder.py) | Dataset builder for shipment delay prediction. |
| [`api/app/ml/datasets/contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/datasets/contracts.py) | Contracts for ML datasets and data partitions. |
| [`api/app/ml/datasets/validation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/datasets/validation.py) | Machine learning feature processor, model pipeline, or inference logic for Validation. |
| [`api/app/ml/features/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/features/__init__.py) | ML feature pipelines and schema specifications. |
| [`api/app/ml/features/contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/features/contracts.py) | Contracts and interfaces for ML feature engineering pipelines. |
| [`api/app/ml/features/shipment_delay.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/features/shipment_delay.py) | Deterministic feature pipeline for shipment delay regression. |
| [`api/app/ml/inference/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/inference/__init__.py) | ML inference services. |
| [`api/app/ml/inference/service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/inference/service.py) | Machine learning feature processor, model pipeline, or inference logic for Service. |
| [`api/app/ml/models/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/models/__init__.py) | ML models and baseline estimators. |
| [`api/app/ml/models/base.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/models/base.py) | Abstract base model contract for all RiskWise ML prediction models. |
| [`api/app/ml/models/shipment_delay.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/models/shipment_delay.py) | Shipment delay prediction model implementation. |
| [`api/app/ml/registry/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/registry/__init__.py) | ML Model Registry. |
| [`api/app/ml/registry/registry.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/registry/registry.py) | Lightweight, tenant-aware model registry. |
| [`api/app/ml/training/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/training/__init__.py) | Training pipelines, validation, and artifact management. |
| [`api/app/ml/training/artifacts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/training/artifacts.py) | Machine learning feature processor, model pipeline, or inference logic for Artifacts. |
| [`api/app/ml/training/pipeline.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/training/pipeline.py) | Machine learning feature processor, model pipeline, or inference logic for Pipeline. |
| [`api/app/ml/training/validation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/ml/training/validation.py) | Model validation and qualification checks before registration. |

---

## 18. Backend RAG & Knowledge Assembly (`api/app/rag/`)
*Total Files: 11*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/rag/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/rag/__init__.py) | RiskWise 2.0 RAG (Retrieval-Augmented Generation) Subsystem. |
| [`api/app/rag/chunking.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/rag/chunking.py) | Retrieval-Augmented Generation (RAG) chunking, vector embedding, or search for Chunking. |
| [`api/app/rag/contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/rag/contracts.py) | Retrieval-Augmented Generation (RAG) chunking, vector embedding, or search for Contracts. |
| [`api/app/rag/embeddings.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/rag/embeddings.py) | Retrieval-Augmented Generation (RAG) chunking, vector embedding, or search for Embeddings. |
| [`api/app/rag/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/rag/errors.py) | Retrieval-Augmented Generation (RAG) chunking, vector embedding, or search for Errors. |
| [`api/app/rag/grounding.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/rag/grounding.py) | Retrieval-Augmented Generation (RAG) chunking, vector embedding, or search for Grounding. |
| [`api/app/rag/ingestion.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/rag/ingestion.py) | Retrieval-Augmented Generation (RAG) chunking, vector embedding, or search for Ingestion. |
| [`api/app/rag/parsers.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/rag/parsers.py) | Retrieval-Augmented Generation (RAG) chunking, vector embedding, or search for Parsers. |
| [`api/app/rag/pipeline.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/rag/pipeline.py) | Retrieval-Augmented Generation (RAG) chunking, vector embedding, or search for Pipeline. |
| [`api/app/rag/retrieval.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/rag/retrieval.py) | RAG Retrieval & Similarity Search service for RiskWise 2.0 subsystem. |
| [`api/app/rag/vector_store.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/rag/vector_store.py) | Retrieval-Augmented Generation (RAG) chunking, vector embedding, or search for Vector Store. |

---

## 19. Backend LLM Gateway & Providers (`api/app/llm/`)
*Total Files: 13*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/llm/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/llm/__init__.py) | RiskWise LLM Provider Abstraction & Safe Claude Invocation Layer (Phase 10 Steps 1 & 2). |
| [`api/app/llm/base.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/llm/base.py) | Provider-neutral abstract base class for LLM backends. |
| [`api/app/llm/bedrock.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/llm/bedrock.py) | AWS Bedrock Runtime LLM Provider implementation for Anthropic Claude models. |
| [`api/app/llm/contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/llm/contracts.py) | Strongly typed contracts for LLM requests, responses, streaming chunks, and messages. |
| [`api/app/llm/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/llm/errors.py) | LLM client gateway, provider integration, or prompt template for Errors. |
| [`api/app/llm/factory.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/llm/factory.py) | Central provider factory for resolving and constructing LLM backends. |
| [`api/app/llm/gemini.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/llm/gemini.py) | LLM client gateway, provider integration, or prompt template for Gemini. |
| [`api/app/llm/invocation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/llm/invocation.py) | LLM client gateway, provider integration, or prompt template for Invocation. |
| [`api/app/llm/mock.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/llm/mock.py) | LLM client gateway, provider integration, or prompt template for Mock. |
| [`api/app/llm/observability.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/llm/observability.py) | LLM client gateway, provider integration, or prompt template for Observability. |
| [`api/app/llm/prompts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/llm/prompts.py) | Strongly typed prompt contracts and deterministic prompt construction for Claude. |
| [`api/app/llm/retry.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/llm/retry.py) | Configurable exponential backoff and retry policy for Bedrock LLM invocation. |
| [`api/app/llm/security.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/llm/security.py) | LLM client gateway, provider integration, or prompt template for Security. |

---

## 20. Backend Third-Party Integrations (`api/app/integrations/`)
*Total Files: 22*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/integrations/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/__init__.py) | Package initializer and module exports for `integrations`. |
| [`api/app/integrations/base.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/base.py) | Provider-agnostic interface, data models, and contracts for external signal ingestion. |
| [`api/app/integrations/boundaries.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/boundaries.py) | Integration client, API adapter, and response parser for Boundaries. |
| [`api/app/integrations/canonical.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/canonical.py) | Canonical external event models and provider-independent taxonomy. |
| [`api/app/integrations/circuit_breaker.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/circuit_breaker.py) | Integration client, API adapter, and response parser for Circuit Breaker. |
| [`api/app/integrations/config.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/config.py) | Provider configuration, authentication definitions, and secure runtime secret resolution. |
| [`api/app/integrations/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/errors.py) | Integration client, API adapter, and response parser for Errors. |
| [`api/app/integrations/idempotency.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/idempotency.py) | Idempotency engine and deterministic SHA-256 fingerprinting for external signal deduplication. |
| [`api/app/integrations/normalizers.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/normalizers.py) | Normalization abstractions and pipeline for external supply-chain signals. |
| [`api/app/integrations/observability.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/observability.py) | Integration client, API adapter, and response parser for Observability. |
| [`api/app/integrations/rate_limiter.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/rate_limiter.py) | Integration client, API adapter, and response parser for Rate Limiter. |
| [`api/app/integrations/registry.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/registry.py) | Provider registry and factory. |
| [`api/app/integrations/retry.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/retry.py) | Bounded exponential backoff retry policy with jitter and Retry-After support. |
| [`api/app/integrations/service.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/service.py) | Central ingestion service coordinating provider data retrieval, |
| [`api/app/integrations/providers/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/providers/__init__.py) | Provider adapters and provider-specific normalization packages. |
| [`api/app/integrations/providers/aisstream.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/providers/aisstream.py) | Integration client, API adapter, and response parser for Aisstream. |
| [`api/app/integrations/providers/karrio.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/providers/karrio.py) | Integration client, API adapter, and response parser for Karrio. |
| [`api/app/integrations/providers/opensky.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/providers/opensky.py) | Integration client, API adapter, and response parser for Opensky. |
| [`api/app/integrations/providers/openweather.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/providers/openweather.py) | Integration client, API adapter, and response parser for Openweather. |
| [`api/app/integrations/providers/rail.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/providers/rail.py) | Integration client, API adapter, and response parser for Rail. |
| [`api/app/integrations/providers/tavily.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/providers/tavily.py) | Integration client, API adapter, and response parser for Tavily. |
| [`api/app/integrations/providers/tomtom.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/integrations/providers/tomtom.py) | Integration client, API adapter, and response parser for Tomtom. |

---

## 21. Backend Ingestion & Normalization (`api/app/normalization/`)
*Total Files: 10*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/normalization/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/normalization/__init__.py) | Phase 6 Semantic Normalization Package. |
| [`api/app/normalization/contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/normalization/contract.py) | Configuration or source file: `contract.py`. |
| [`api/app/normalization/correlation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/normalization/correlation.py) | Configuration or source file: `correlation.py`. |
| [`api/app/normalization/entity_resolver.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/normalization/entity_resolver.py) | Configuration or source file: `entity_resolver.py`. |
| [`api/app/normalization/handlers.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/normalization/handlers.py) | Domain-specific normalization handlers and registry for Phase 6. |
| [`api/app/normalization/identifiers.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/normalization/identifiers.py) | Configuration or source file: `identifiers.py`. |
| [`api/app/normalization/pipeline.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/normalization/pipeline.py) | Configuration or source file: `pipeline.py`. |
| [`api/app/normalization/quality.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/normalization/quality.py) | Configuration or source file: `quality.py`. |
| [`api/app/normalization/status.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/normalization/status.py) | Controlled status normalization and vocabulary mapping for Phase 6. |
| [`api/app/normalization/units.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/normalization/units.py) | Configuration or source file: `units.py`. |

---

## 22. Backend Evaluation & Governance (`api/app/evaluation/`)
*Total Files: 41*

| File Path | Description / Role |
| :--- | :--- |
| [`api/app/evaluation/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/__init__.py) | RiskWise 2.0 — Phase 20: Evaluation & Quality Assurance Framework. |
| [`api/app/evaluation/contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/contracts.py) | Benchmark evaluation metric, dataset contract, or runner suite for Contracts. |
| [`api/app/evaluation/errors.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/errors.py) | Domain exceptions for RiskWise 2.0 Evaluation & Quality Assurance (Phase 20). |
| [`api/app/evaluation/metrics.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/metrics.py) | Benchmark evaluation metric, dataset contract, or runner suite for Metrics. |
| [`api/app/evaluation/runner.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/runner.py) | Benchmark evaluation metric, dataset contract, or runner suite for Runner. |
| [`api/app/evaluation/datasets/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/__init__.py) | Evaluation datasets package for RiskWise 2.0. |
| [`api/app/evaluation/datasets/contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/contracts.py) | Contracts for versioned golden evaluation datasets (Phase 20). |
| [`api/app/evaluation/datasets/registry.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/registry.py) | Dataset Registry for RiskWise 2.0 Evaluation. |
| [`api/app/evaluation/datasets/golden/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/__init__.py) | Golden evaluation cases package combining all domain benchmark datasets. |
| [`api/app/evaluation/datasets/golden/action_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/action_cases.py) | Golden evaluation test cases for Phase 17 Action Execution and Safety (Phase 20). |
| [`api/app/evaluation/datasets/golden/agent_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/agent_cases.py) | Benchmark evaluation metric, dataset contract, or runner suite for Agent Cases. |
| [`api/app/evaluation/datasets/golden/approval_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/approval_cases.py) | Golden evaluation test cases for Phase 16 Human-in-the-Loop Approval Governance (Phase 20). |
| [`api/app/evaluation/datasets/golden/claude_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/claude_cases.py) | Golden evaluation test cases for Claude Explanation and Non-Authority Boundary (Phase 20). |
| [`api/app/evaluation/datasets/golden/decision_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/decision_cases.py) | Golden evaluation test cases for Phase 15 Decision Agent and Candidate Synthesis (Phase 20). |
| [`api/app/evaluation/datasets/golden/digital_twin_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/digital_twin_cases.py) | Golden evaluation test cases for Phase 12 Digital Twin Network Topology (Phase 20). |
| [`api/app/evaluation/datasets/golden/e2e_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/e2e_cases.py) | Benchmark evaluation metric, dataset contract, or runner suite for E2E Cases. |
| [`api/app/evaluation/datasets/golden/ml_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/ml_cases.py) | Golden evaluation test cases for Phase 11 ML delay prediction and leakage detection (Phase 20). |
| [`api/app/evaluation/datasets/golden/optimization_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/optimization_cases.py) | Golden evaluation test cases for Phase 14 OR-Tools Prescriptive Optimization (Phase 20). |
| [`api/app/evaluation/datasets/golden/rag_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/rag_cases.py) | Benchmark evaluation metric, dataset contract, or runner suite for Rag Cases. |
| [`api/app/evaluation/datasets/golden/research_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/research_cases.py) | Golden evaluation cases for Research Agent evaluation. |
| [`api/app/evaluation/datasets/golden/risk_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/risk_cases.py) | Golden evaluation test cases for Phase 7 Deterministic Risk Engine (Phase 20). |
| [`api/app/evaluation/datasets/golden/security_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/security_cases.py) | Benchmark evaluation metric, dataset contract, or runner suite for Security Cases. |
| [`api/app/evaluation/datasets/golden/simulation_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/simulation_cases.py) | Golden evaluation test cases for Phase 13 Simulation and Propagation (Phase 20). |
| [`api/app/evaluation/datasets/golden/verification_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/datasets/golden/verification_cases.py) | Golden evaluation test cases for Phase 18 Ground-Truth Physical Verification (Phase 20). |
| [`api/app/evaluation/suites/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/__init__.py) | Evaluation suites package for RiskWise 2.0. |
| [`api/app/evaluation/suites/action_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/action_suite.py) | Benchmark evaluation metric, dataset contract, or runner suite for Action Suite. |
| [`api/app/evaluation/suites/agent_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/agent_suite.py) | Benchmark evaluation metric, dataset contract, or runner suite for Agent Suite. |
| [`api/app/evaluation/suites/approval_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/approval_suite.py) | Benchmark evaluation metric, dataset contract, or runner suite for Approval Suite. |
| [`api/app/evaluation/suites/base.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/base.py) | Base Evaluation Suite for RiskWise 2.0 Evaluation Framework. |
| [`api/app/evaluation/suites/claude_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/claude_suite.py) | Benchmark evaluation metric, dataset contract, or runner suite for Claude Suite. |
| [`api/app/evaluation/suites/decision_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/decision_suite.py) | Decision Engine Evaluation Suite for RiskWise 2.0. |
| [`api/app/evaluation/suites/digital_twin_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/digital_twin_suite.py) | Benchmark evaluation metric, dataset contract, or runner suite for Digital Twin Suite. |
| [`api/app/evaluation/suites/e2e_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/e2e_suite.py) | End-to-End Workflow Evaluation Suite for RiskWise 2.0. |
| [`api/app/evaluation/suites/ml_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/ml_suite.py) | Benchmark evaluation metric, dataset contract, or runner suite for Ml Suite. |
| [`api/app/evaluation/suites/optimization_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/optimization_suite.py) | Benchmark evaluation metric, dataset contract, or runner suite for Optimization Suite. |
| [`api/app/evaluation/suites/rag_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/rag_suite.py) | Benchmark evaluation metric, dataset contract, or runner suite for Rag Suite. |
| [`api/app/evaluation/suites/research_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/research_suite.py) | Benchmark evaluation metric, dataset contract, or runner suite for Research Suite. |
| [`api/app/evaluation/suites/risk_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/risk_suite.py) | Benchmark evaluation metric, dataset contract, or runner suite for Risk Suite. |
| [`api/app/evaluation/suites/security_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/security_suite.py) | Benchmark evaluation metric, dataset contract, or runner suite for Security Suite. |
| [`api/app/evaluation/suites/simulation_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/simulation_suite.py) | Benchmark evaluation metric, dataset contract, or runner suite for Simulation Suite. |
| [`api/app/evaluation/suites/verification_suite.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/app/evaluation/suites/verification_suite.py) | Verification Agent Evaluation Suite for RiskWise 2.0. |

---

## 23. Backend Storage & Database Files (`api/storage/`)
*Total Files: 6*

| File Path | Description / Role |
| :--- | :--- |
| [`api/storage/ml_artifacts/delay_baseline_v1.joblib`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/storage/ml_artifacts/delay_baseline_v1.joblib) | Configuration or source file: `delay_baseline_v1.joblib`. |
| [`api/storage/ml_artifacts/delay_custom_v1.joblib`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/storage/ml_artifacts/delay_custom_v1.joblib) | Configuration or source file: `delay_custom_v1.joblib`. |
| [`api/storage/ml_artifacts/repro_m.joblib`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/storage/ml_artifacts/repro_m.joblib) | Configuration or source file: `repro_m.joblib`. |
| [`api/storage/ml_artifacts/retrain_m1.joblib`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/storage/ml_artifacts/retrain_m1.joblib) | Configuration or source file: `retrain_m1.joblib`. |
| [`api/storage/ml_artifacts/retrain_m2.joblib`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/storage/ml_artifacts/retrain_m2.joblib) | Configuration or source file: `retrain_m2.joblib`. |
| [`api/storage/ml_artifacts/shipment_delay_ridge_1.0.0_org_acme.joblib`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/storage/ml_artifacts/shipment_delay_ridge_1.0.0_org_acme.joblib) | Configuration or source file: `shipment_delay_ridge_1.0.0_org_acme.joblib`. |

---

## 24. Backend Automated Test Suites (`api/tests/`)
*Total Files: 133*

| File Path | Description / Role |
| :--- | :--- |
| [`api/tests/__init__.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/__init__.py) | Backend test suite. |
| [`api/tests/test_aisstream_integration.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_aisstream_integration.py) | Automated test suite verifying functionality, integration, and contracts for Aisstream Integration. |
| [`api/tests/test_auth_config.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_auth_config.py) | Tests for Google OAuth 2.0 configuration layer (Phase 3 Step 2). |
| [`api/tests/test_auth_final_validation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_auth_final_validation.py) | Automated test suite verifying functionality, integration, and contracts for Auth Final Validation. |
| [`api/tests/test_canonical_external_events.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_canonical_external_events.py) | Automated test suite verifying functionality, integration, and contracts for Canonical External Events. |
| [`api/tests/test_crud.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_crud.py) | Automated test suite verifying functionality, integration, and contracts for Crud. |
| [`api/tests/test_database_validation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_database_validation.py) | Comprehensive final database test suite for RiskWise 2.0 (Phase 2 Step 6). |
| [`api/tests/test_decision_governance_api.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_decision_governance_api.py) | Automated test suite verifying functionality, integration, and contracts for Decision Governance Api. |
| [`api/tests/test_gemini_provider.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_gemini_provider.py) | Automated test suite verifying functionality, integration, and contracts for Gemini Provider. |
| [`api/tests/test_ingestion_foundation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_ingestion_foundation.py) | Automated test suite verifying functionality, integration, and contracts for Ingestion Foundation. |
| [`api/tests/test_ingestion_reliability_observability.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_ingestion_reliability_observability.py) | Automated test suite verifying functionality, integration, and contracts for Ingestion Reliability Observability. |
| [`api/tests/test_inventory_api.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_inventory_api.py) | Automated test suite verifying functionality, integration, and contracts for Inventory Api. |
| [`api/tests/test_karrio_integration.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_karrio_integration.py) | Automated test suite verifying functionality, integration, and contracts for Karrio Integration. |
| [`api/tests/test_logistics_api.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_logistics_api.py) | Automated test suite verifying functionality, integration, and contracts for Logistics Api. |
| [`api/tests/test_main.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_main.py) | Automated test suite verifying functionality, integration, and contracts for Main. |
| [`api/tests/test_models.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_models.py) | Unit tests for SQLAlchemy models, Base metadata registration, and schema integrity. |
| [`api/tests/test_opensky_integration.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_opensky_integration.py) | Automated test suite verifying functionality, integration, and contracts for Opensky Integration. |
| [`api/tests/test_openweather_integration.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_openweather_integration.py) | Automated test suite verifying functionality, integration, and contracts for Openweather Integration. |
| [`api/tests/test_phase10_step1_bedrock_foundation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase10_step1_bedrock_foundation.py) | Automated test suite verifying functionality, integration, and contracts for Phase10 Step1 Bedrock Foundation. |
| [`api/tests/test_phase10_step2_claude_invocation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase10_step2_claude_invocation.py) | Comprehensive unit and integration test suite for RiskWise 2.0 Phase 10 Step 2. |
| [`api/tests/test_phase10_step3_research_agent_claude.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase10_step3_research_agent_claude.py) | Automated test suite verifying functionality, integration, and contracts for Phase10 Step3 Research Agent Claude. |
| [`api/tests/test_phase10_step4_risk_explanation_claude.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase10_step4_risk_explanation_claude.py) | Automated test suite verifying functionality, integration, and contracts for Phase10 Step4 Risk Explanation Claude. |
| [`api/tests/test_phase10_step5_scenario_explanation_claude.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase10_step5_scenario_explanation_claude.py) | Comprehensive focused test suite for Phase 10 Step 5: Claude Scenario Analysis & Explanation Layer. |
| [`api/tests/test_phase10_step6_prediction_explanation_claude.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase10_step6_prediction_explanation_claude.py) | Automated test suite verifying functionality, integration, and contracts for Phase10 Step6 Prediction Explanation Claude. |
| [`api/tests/test_phase10_step7_decision_explanation_claude.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase10_step7_decision_explanation_claude.py) | Automated test suite verifying functionality, integration, and contracts for Phase10 Step7 Decision Explanation Claude. |
| [`api/tests/test_phase10_step7_scenario_explanation_claude.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase10_step7_scenario_explanation_claude.py) | Comprehensive test suite for RiskWise 2.0 Phase 10 Step 7. |
| [`api/tests/test_phase11_ml_artifacts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase11_ml_artifacts.py) | Unit tests for ML model artifact management, integrity verification, and security defenses. |
| [`api/tests/test_phase11_ml_contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase11_ml_contracts.py) | Automated test suite verifying functionality, integration, and contracts for Phase11 Ml Contracts. |
| [`api/tests/test_phase11_ml_critical.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase11_ml_critical.py) | The 20 Mandatory Critical Tests and End-to-End Integration for Phase 11 ML. |
| [`api/tests/test_phase11_ml_dataset.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase11_ml_dataset.py) | Automated test suite verifying functionality, integration, and contracts for Phase11 Ml Dataset. |
| [`api/tests/test_phase11_ml_edge_cases.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase11_ml_edge_cases.py) | Extensive edge-case, boundary, and robustness tests for the Phase 11 ML subsystem. |
| [`api/tests/test_phase11_ml_features.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase11_ml_features.py) | Automated test suite verifying functionality, integration, and contracts for Phase11 Ml Features. |
| [`api/tests/test_phase11_ml_inference.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase11_ml_inference.py) | Unit tests for MLPredictionService inference, tenant isolation, uncertainty, and fallback. |
| [`api/tests/test_phase11_ml_leakage.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase11_ml_leakage.py) | Unit tests for temporal data leakage defenses and time-aware dataset splitting. |
| [`api/tests/test_phase11_ml_observability_pipeline.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase11_ml_observability_pipeline.py) | Phase 11 ML Observability, Audit, Feature Pipeline, and Lifecycle Tests. |
| [`api/tests/test_phase11_ml_registry.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase11_ml_registry.py) | Automated test suite verifying functionality, integration, and contracts for Phase11 Ml Registry. |
| [`api/tests/test_phase11_ml_security.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase11_ml_security.py) | Automated test suite verifying functionality, integration, and contracts for Phase11 Ml Security. |
| [`api/tests/test_phase11_ml_training.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase11_ml_training.py) | Unit tests for ML model training, evaluation, validation, and pipeline reproducibility. |
| [`api/tests/test_phase12_digital_twin.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase12_digital_twin.py) | Comprehensive test suite for RiskWise 2.0 Phase 12 Digital Twin subsystem. |
| [`api/tests/test_phase12_twin_api.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase12_twin_api.py) | Automated test suite verifying functionality, integration, and contracts for Phase12 Twin Api. |
| [`api/tests/test_phase12_twin_builder.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase12_twin_builder.py) | Unit tests for Phase 12 Digital Twin Builder: entity conversion, relationship mapping, and idempotency. |
| [`api/tests/test_phase12_twin_contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase12_twin_contracts.py) | Automated test suite verifying functionality, integration, and contracts for Phase12 Twin Contracts. |
| [`api/tests/test_phase12_twin_critical.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase12_twin_critical.py) | Automated test suite verifying functionality, integration, and contracts for Phase12 Twin Critical. |
| [`api/tests/test_phase12_twin_fingerprints.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase12_twin_fingerprints.py) | Automated test suite verifying functionality, integration, and contracts for Phase12 Twin Fingerprints. |
| [`api/tests/test_phase12_twin_persistence.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase12_twin_persistence.py) | Automated test suite verifying functionality, integration, and contracts for Phase12 Twin Persistence. |
| [`api/tests/test_phase12_twin_query.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase12_twin_query.py) | Unit tests for Phase 12 Digital Twin Query Service, BFS traversal, and cycle handling. |
| [`api/tests/test_phase12_twin_security.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase12_twin_security.py) | Unit tests for Phase 12 Digital Twin Security, tenant isolation, and bounding protections. |
| [`api/tests/test_phase12_twin_validation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase12_twin_validation.py) | Automated test suite verifying functionality, integration, and contracts for Phase12 Twin Validation. |
| [`api/tests/test_phase13_api.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase13_api.py) | Automated test suite verifying functionality, integration, and contracts for Phase13 Api. |
| [`api/tests/test_phase13_comprehensive_validation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase13_comprehensive_validation.py) | Comprehensive validation and property test suite for RiskWise Phase 13 Simulation Engine. |
| [`api/tests/test_phase13_contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase13_contracts.py) | Unit tests for RiskWise Phase 13 Simulation Engine contracts, validation, and fingerprints. |
| [`api/tests/test_phase13_contracts_extended.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase13_contracts_extended.py) | Automated test suite verifying functionality, integration, and contracts for Phase13 Contracts Extended. |
| [`api/tests/test_phase13_integrations.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase13_integrations.py) | Automated test suite verifying functionality, integration, and contracts for Phase13 Integrations. |
| [`api/tests/test_phase13_persistence.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase13_persistence.py) | Unit and integration tests for RiskWise Phase 13 simulation persistence and scenario comparison. |
| [`api/tests/test_phase13_simulation_engine.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase13_simulation_engine.py) | Core engine and propagation tests for RiskWise Phase 13 Simulation Engine. |
| [`api/tests/test_phase14_contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase14_contracts.py) | Automated test suite verifying functionality, integration, and contracts for Phase14 Contracts. |
| [`api/tests/test_phase14_domains.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase14_domains.py) | Automated test suite verifying functionality, integration, and contracts for Phase14 Domains. |
| [`api/tests/test_phase14_extended.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase14_extended.py) | Automated test suite verifying functionality, integration, and contracts for Phase14 Extended. |
| [`api/tests/test_phase14_integrations.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase14_integrations.py) | Phase 14 Test Suite: Digital Twin, Simulation, Risk Engine, and ML Integrations. |
| [`api/tests/test_phase14_persistence_api.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase14_persistence_api.py) | Automated test suite verifying functionality, integration, and contracts for Phase14 Persistence Api. |
| [`api/tests/test_phase14_security_adversarial.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase14_security_adversarial.py) | Automated test suite verifying functionality, integration, and contracts for Phase14 Security Adversarial. |
| [`api/tests/test_phase14_solver.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase14_solver.py) | Automated test suite verifying functionality, integration, and contracts for Phase14 Solver. |
| [`api/tests/test_phase15_agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase15_agent.py) | Automated test suite verifying functionality, integration, and contracts for Phase15 Agent. |
| [`api/tests/test_phase15_claude.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase15_claude.py) | Automated test suite verifying functionality, integration, and contracts for Phase15 Claude. |
| [`api/tests/test_phase15_contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase15_contracts.py) | Phase 15 Test Suite 1: Strongly Typed Decision Contracts & Pydantic V2 Invariants. |
| [`api/tests/test_phase15_integration.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase15_integration.py) | Phase 15 Test Suite 4: End-to-End Multi-Phase LangGraph Integration. |
| [`api/tests/test_phase15_persistence_api.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase15_persistence_api.py) | Automated test suite verifying functionality, integration, and contracts for Phase15 Persistence Api. |
| [`api/tests/test_phase15_policy.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase15_policy.py) | Automated test suite verifying functionality, integration, and contracts for Phase15 Policy. |
| [`api/tests/test_phase15_security_adversarial.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase15_security_adversarial.py) | Automated test suite verifying functionality, integration, and contracts for Phase15 Security Adversarial. |
| [`api/tests/test_phase16_contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase16_contracts.py) | Automated test suite verifying functionality, integration, and contracts for Phase16 Contracts. |
| [`api/tests/test_phase16_integration.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase16_integration.py) | Automated test suite verifying functionality, integration, and contracts for Phase16 Integration. |
| [`api/tests/test_phase16_persistence_api.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase16_persistence_api.py) | Phase 16 Test Suite: REST API Endpoints, RBAC, and Persistence for Human Approval. |
| [`api/tests/test_phase16_security_rbac.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase16_security_rbac.py) | Automated test suite verifying functionality, integration, and contracts for Phase16 Security Rbac. |
| [`api/tests/test_phase17_approval_enforcement.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase17_approval_enforcement.py) | Automated test suite verifying functionality, integration, and contracts for Phase17 Approval Enforcement. |
| [`api/tests/test_phase17_contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase17_contracts.py) | Automated test suite verifying functionality, integration, and contracts for Phase17 Contracts. |
| [`api/tests/test_phase17_executors_idempotency.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase17_executors_idempotency.py) | Phase 17 Test Suite: Execution Adapters, Success Semantics, and Idempotency. |
| [`api/tests/test_phase17_integration.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase17_integration.py) | Automated test suite verifying functionality, integration, and contracts for Phase17 Integration. |
| [`api/tests/test_phase17_persistence_api.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase17_persistence_api.py) | Automated test suite verifying functionality, integration, and contracts for Phase17 Persistence Api. |
| [`api/tests/test_phase17_security_adversarial.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase17_security_adversarial.py) | Automated test suite verifying functionality, integration, and contracts for Phase17 Security Adversarial. |
| [`api/tests/test_phase18_contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase18_contracts.py) | Automated test suite verifying functionality, integration, and contracts for Phase18 Contracts. |
| [`api/tests/test_phase18_evidence.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase18_evidence.py) | Automated test suite verifying functionality, integration, and contracts for Phase18 Evidence. |
| [`api/tests/test_phase18_langgraph_claude.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase18_langgraph_claude.py) | Tests for Phase 18 LangGraph Node Integration and Claude Explanation Boundary. |
| [`api/tests/test_phase18_persistence_api.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase18_persistence_api.py) | Automated test suite verifying functionality, integration, and contracts for Phase18 Persistence Api. |
| [`api/tests/test_phase18_security.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase18_security.py) | Tests for Phase 18 adversarial security, tenant boundaries, approval bindings, and injection protections. |
| [`api/tests/test_phase18_verifiers.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase18_verifiers.py) | Automated test suite verifying functionality, integration, and contracts for Phase18 Verifiers. |
| [`api/tests/test_phase20_contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase20_contracts.py) | Tests for Phase 20 Evaluation Contracts, Pydantic Models, and Fingerprinting. |
| [`api/tests/test_phase20_datasets.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase20_datasets.py) | Tests for Phase 20 Golden Datasets, Registry, and Anti-Contamination Guards. |
| [`api/tests/test_phase20_metrics.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase20_metrics.py) | Tests for Phase 20 MetricEngine (Deterministic Calculations & Not-Available Rules). |
| [`api/tests/test_phase20_runner_persistence_api.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase20_runner_persistence_api.py) | Tests for Phase 20 EvaluationRunner, Minimal Persistence, and API Endpoints. |
| [`api/tests/test_phase20_suites_agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase20_suites_agent.py) | Tests for Agent, Research, Risk, RAG, and Claude Evaluation Suites (Phase 20). |
| [`api/tests/test_phase20_suites_domain.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase20_suites_domain.py) | Tests for ML, Digital Twin, Simulation, Optimization, and Decision Suites (Phase 20). |
| [`api/tests/test_phase20_suites_governance_e2e.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase20_suites_governance_e2e.py) | Tests for Approval, Action, Verification, End-to-End, and Security Suites (Phase 20). |
| [`api/tests/test_phase21_production_hardening.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase21_production_hardening.py) | Phase 21 Comprehensive Production Hardening & Disaster Recovery Failure-Injection Test Suite. |
| [`api/tests/test_phase4_final_validation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase4_final_validation.py) | Automated test suite verifying functionality, integration, and contracts for Phase4 Final Validation. |
| [`api/tests/test_phase5_final_validation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase5_final_validation.py) | Automated test suite verifying functionality, integration, and contracts for Phase5 Final Validation. |
| [`api/tests/test_phase6_entity_normalization.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase6_entity_normalization.py) | Automated test suite verifying functionality, integration, and contracts for Phase6 Entity Normalization. |
| [`api/tests/test_phase6_finalization.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase6_finalization.py) | Comprehensive focused test suite for Phase 6 Step 4: |
| [`api/tests/test_phase6_normalization_contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase6_normalization_contract.py) | Automated test suite verifying functionality, integration, and contracts for Phase6 Normalization Contract. |
| [`api/tests/test_phase7_baseline_scoring.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase7_baseline_scoring.py) | Automated test suite verifying functionality, integration, and contracts for Phase7 Baseline Scoring. |
| [`api/tests/test_phase7_final_validation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase7_final_validation.py) | Automated test suite verifying functionality, integration, and contracts for Phase7 Final Validation. |
| [`api/tests/test_phase7_risk_alerts_escalation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase7_risk_alerts_escalation.py) | Automated test suite verifying functionality, integration, and contracts for Phase7 Risk Alerts Escalation. |
| [`api/tests/test_phase7_risk_engine_contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase7_risk_engine_contracts.py) | Automated test suite verifying functionality, integration, and contracts for Phase7 Risk Engine Contracts. |
| [`api/tests/test_phase7_risk_evidence_assessment.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase7_risk_evidence_assessment.py) | Comprehensive focused test suite for Phase 7 Step 3: |
| [`api/tests/test_phase7_risk_history_trends.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase7_risk_history_trends.py) | Automated test suite verifying functionality, integration, and contracts for Phase7 Risk History Trends. |
| [`api/tests/test_phase7_risk_persistence_api.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase7_risk_persistence_api.py) | Comprehensive focused test suite for Phase 7 Step 4: |
| [`api/tests/test_phase7_risk_recommendation_foundation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase7_risk_recommendation_foundation.py) | Automated test suite verifying functionality, integration, and contracts for Phase7 Risk Recommendation Foundation. |
| [`api/tests/test_phase8_rag_context_assembly_grounding.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase8_rag_context_assembly_grounding.py) | Automated test suite verifying functionality, integration, and contracts for Phase8 Rag Context Assembly Grounding. |
| [`api/tests/test_phase8_rag_contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase8_rag_contracts.py) | Comprehensive unit and contract test suite for RiskWise 2.0 Phase 8 Step 1 (RAG Architecture & Contracts). |
| [`api/tests/test_phase8_rag_embeddings_vector_storage.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase8_rag_embeddings_vector_storage.py) | Automated test suite verifying functionality, integration, and contracts for Phase8 Rag Embeddings Vector Storage. |
| [`api/tests/test_phase8_rag_evidence_pipeline.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase8_rag_evidence_pipeline.py) | Comprehensive test suite for RiskWise 2.0 Phase 8 Step 6: RAG Research Evidence Pipeline & Downstream Integration. |
| [`api/tests/test_phase8_rag_ingestion_chunking.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase8_rag_ingestion_chunking.py) | Comprehensive test suite for RiskWise 2.0 Phase 8 Step 2: RAG Document Ingestion & Chunking. |
| [`api/tests/test_phase8_rag_retrieval_similarity_search.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase8_rag_retrieval_similarity_search.py) | Automated test suite verifying functionality, integration, and contracts for Phase8 Rag Retrieval Similarity Search. |
| [`api/tests/test_phase9_approval_agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase9_approval_agent.py) | Automated test suite verifying functionality, integration, and contracts for Phase9 Approval Agent. |
| [`api/tests/test_phase9_decision_agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase9_decision_agent.py) | Automated test suite verifying functionality, integration, and contracts for Phase9 Decision Agent. |
| [`api/tests/test_phase9_langgraph_agent_state_contract.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase9_langgraph_agent_state_contract.py) | Automated test suite verifying functionality, integration, and contracts for Phase9 Langgraph Agent State Contract. |
| [`api/tests/test_phase9_langgraph_architecture_contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase9_langgraph_architecture_contracts.py) | Automated test suite verifying functionality, integration, and contracts for Phase9 Langgraph Architecture Contracts. |
| [`api/tests/test_phase9_langgraph_node_edge_contracts.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase9_langgraph_node_edge_contracts.py) | Phase 9 Step 3 — LangGraph Node & Edge Contracts Test Suite. |
| [`api/tests/test_phase9_prediction_agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase9_prediction_agent.py) | Automated test suite verifying functionality, integration, and contracts for Phase9 Prediction Agent. |
| [`api/tests/test_phase9_research_agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase9_research_agent.py) | Automated test suite verifying functionality, integration, and contracts for Phase9 Research Agent. |
| [`api/tests/test_phase9_risk_agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase9_risk_agent.py) | Automated test suite verifying functionality, integration, and contracts for Phase9 Risk Agent. |
| [`api/tests/test_phase9_scenario_agent.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase9_scenario_agent.py) | Automated test suite verifying functionality, integration, and contracts for Phase9 Scenario Agent. |
| [`api/tests/test_phase9_step10_observability_recovery.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase9_step10_observability_recovery.py) | Automated test suite verifying functionality, integration, and contracts for Phase9 Step10 Observability Recovery. |
| [`api/tests/test_phase9_step11_final_validation.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_phase9_step11_final_validation.py) | Automated test suite verifying functionality, integration, and contracts for Phase9 Step11 Final Validation. |
| [`api/tests/test_rail_integration.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_rail_integration.py) | Comprehensive unit test suite for RiskWise 2.0 Phase 5 Step 7: Rail Data Integration. |
| [`api/tests/test_risk_api.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_risk_api.py) | Automated test suite verifying functionality, integration, and contracts for Risk Api. |
| [`api/tests/test_schemas.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_schemas.py) | Unit tests validating Pydantic schemas, validation rules, pagination, and error contracts for RiskWise 2.0 Core API Contract. |
| [`api/tests/test_service_repository_foundations.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_service_repository_foundations.py) | Comprehensive tests for RiskWise 2.0 Service Layer & Repository Foundations (Phase 4 Step 2). |
| [`api/tests/test_sessions_and_auth.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_sessions_and_auth.py) | Automated test suite verifying functionality, integration, and contracts for Sessions And Auth. |
| [`api/tests/test_supplier_api.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_supplier_api.py) | Production Supplier API security, multi-tenancy, and domain tests (Phase 4 Step 3). |
| [`api/tests/test_tavily_integration.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_tavily_integration.py) | Automated test suite verifying functionality, integration, and contracts for Tavily Integration. |
| [`api/tests/test_tomtom_integration.py`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/test_tomtom_integration.py) | Automated test suite verifying functionality, integration, and contracts for Tomtom Integration. |
| [`api/tests/integration/.gitkeep`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/integration/.gitkeep) | Automated test suite verifying functionality, integration, and contracts for .Gitkeep. |
| [`api/tests/unit/.gitkeep`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/api/tests/unit/.gitkeep) | Automated test suite verifying functionality, integration, and contracts for .Gitkeep. |

---

## 25. Frontend Root & Configurations (`web/`)
*Total Files: 12*

| File Path | Description / Role |
| :--- | :--- |
| [`web/.dockerignore`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/.dockerignore) | Configuration or source file: `.dockerignore`. |
| [`web/.env.local`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/.env.local) | Next.js local environment variables for API endpoints and auth configuration. |
| [`web/AGENTS.md`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/AGENTS.md) | Configuration or source file: `AGENTS.md`. |
| [`web/Dockerfile`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/Dockerfile) | Configuration or source file: `Dockerfile`. |
| [`web/eslint.config.mjs`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/eslint.config.mjs) | ESLint flat configuration file defining linting rules for TypeScript and React. |
| [`web/next-env.d.ts`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/next-env.d.ts) | TypeScript declarations automatically generated by Next.js compiler. |
| [`web/next.config.ts`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/next.config.ts) | Next.js framework configuration, output mode, and backend API proxy rewrites. |
| [`web/package-lock.json`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/package-lock.json) | Deterministic dependency lockfile for reproducible frontend installations. |
| [`web/package.json`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/package.json) | Node.js dependencies, scripts (dev, build, lint), and project metadata. |
| [`web/postcss.config.mjs`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/postcss.config.mjs) | PostCSS plugin configuration for Tailwind CSS and autoprefixer. |
| [`web/tsconfig.json`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/tsconfig.json) | TypeScript compiler settings, path aliases (@/*), and strict checking rules. |
| [`web/tsconfig.tsbuildinfo`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/tsconfig.tsbuildinfo) | Configuration or source file: `tsconfig.tsbuildinfo`. |

---

## 26. Frontend App Router Pages (`web/app/`)
*Total Files: 51*

| File Path | Description / Role |
| :--- | :--- |
| [`web/app/favicon.ico`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/favicon.ico) | Configuration or source file: `favicon.ico`. |
| [`web/app/globals.css`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/globals.css) | Configuration or source file: `globals.css`. |
| [`web/app/layout.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/layout.tsx) | Shared layout wrapper and header/sidebar scaffold for Root. |
| [`web/app/not-found.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/not-found.tsx) | 404 Not Found page view for unrecognized routing paths. |
| [`web/app/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/page.tsx) | Next.js App Router page view rendering the `Root /` interface. |
| [`web/app/actions/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/actions/page.tsx) | Next.js App Router page view rendering the `/actions` interface. |
| [`web/app/actions/[id]/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/actions/[id]/page.tsx) | Next.js App Router page view rendering the `/actions/[id]` interface. |
| [`web/app/admin/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/admin/page.tsx) | Next.js App Router page view rendering the `/admin` interface. |
| [`web/app/agent-runs/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/agent-runs/page.tsx) | Next.js App Router page view rendering the `/agent-runs` interface. |
| [`web/app/agent-runs/[id]/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/agent-runs/[id]/page.tsx) | Next.js App Router page view rendering the `/agent-runs/[id]` interface. |
| [`web/app/api/health/route.ts`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/api/health/route.ts) | Configuration or source file: `route.ts`. |
| [`web/app/approvals/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/approvals/page.tsx) | Next.js App Router page view rendering the `/approvals` interface. |
| [`web/app/audit/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/audit/page.tsx) | Next.js App Router page view rendering the `/audit` interface. |
| [`web/app/audit-logs/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/audit-logs/page.tsx) | Next.js App Router page view rendering the `/audit-logs` interface. |
| [`web/app/auth/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/auth/page.tsx) | Next.js App Router page view rendering the `/auth` interface. |
| [`web/app/carriers/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/carriers/page.tsx) | Next.js App Router page view rendering the `/carriers` interface. |
| [`web/app/dashboard/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/dashboard/page.tsx) | Next.js App Router page view rendering the `/dashboard` interface. |
| [`web/app/decisions/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/decisions/page.tsx) | Next.js App Router page view rendering the `/decisions` interface. |
| [`web/app/decisions/[id]/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/decisions/[id]/page.tsx) | Next.js App Router page view rendering the `/decisions/[id]` interface. |
| [`web/app/digital-twin/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/digital-twin/page.tsx) | Next.js App Router page view rendering the `/digital-twin` interface. |
| [`web/app/evaluation/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/evaluation/page.tsx) | Next.js App Router page view rendering the `/evaluation` interface. |
| [`web/app/factories/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/factories/page.tsx) | Next.js App Router page view rendering the `/factories` interface. |
| [`web/app/incidents/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/incidents/page.tsx) | Next.js App Router page view rendering the `/incidents` interface. |
| [`web/app/incidents/[id]/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/incidents/[id]/page.tsx) | Next.js App Router page view rendering the `/incidents/[id]` interface. |
| [`web/app/inventory/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/inventory/page.tsx) | Next.js App Router page view rendering the `/inventory` interface. |
| [`web/app/map/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/map/page.tsx) | Next.js App Router page view rendering the `/map` interface. |
| [`web/app/mcp-tools/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/mcp-tools/page.tsx) | Next.js App Router page view rendering the `/mcp-tools` interface. |
| [`web/app/mcp-tools/[id]/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/mcp-tools/[id]/page.tsx) | Next.js App Router page view rendering the `/mcp-tools/[id]` interface. |
| [`web/app/notifications/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/notifications/page.tsx) | Next.js App Router page view rendering the `/notifications` interface. |
| [`web/app/optimization/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/optimization/page.tsx) | Next.js App Router page view rendering the `/optimization` interface. |
| [`web/app/optimization/[id]/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/optimization/[id]/page.tsx) | Next.js App Router page view rendering the `/optimization/[id]` interface. |
| [`web/app/overview/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/overview/page.tsx) | Next.js App Router page view rendering the `/overview` interface. |
| [`web/app/policy-inspector/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/policy-inspector/page.tsx) | Next.js App Router page view rendering the `/policy-inspector` interface. |
| [`web/app/policy-inspector/[id]/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/policy-inspector/[id]/page.tsx) | Next.js App Router page view rendering the `/policy-inspector/[id]` interface. |
| [`web/app/ports/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/ports/page.tsx) | Next.js App Router page view rendering the `/ports` interface. |
| [`web/app/products/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/products/page.tsx) | Next.js App Router page view rendering the `/products` interface. |
| [`web/app/recommendations/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/recommendations/page.tsx) | Next.js App Router page view rendering the `/recommendations` interface. |
| [`web/app/recommendations/[id]/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/recommendations/[id]/page.tsx) | Next.js App Router page view rendering the `/recommendations/[id]` interface. |
| [`web/app/risks/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/risks/page.tsx) | Next.js App Router page view rendering the `/risks` interface. |
| [`web/app/risks/[id]/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/risks/[id]/page.tsx) | Next.js App Router page view rendering the `/risks/[id]` interface. |
| [`web/app/routes/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/routes/page.tsx) | Next.js App Router page view rendering the `/routes` interface. |
| [`web/app/settings/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/settings/page.tsx) | Next.js App Router page view rendering the `/settings` interface. |
| [`web/app/shipments/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/shipments/page.tsx) | Next.js App Router page view rendering the `/shipments` interface. |
| [`web/app/shipments/[id]/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/shipments/[id]/page.tsx) | Next.js App Router page view rendering the `/shipments/[id]` interface. |
| [`web/app/simulations/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/simulations/page.tsx) | Next.js App Router page view rendering the `/simulations` interface. |
| [`web/app/simulations/[id]/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/simulations/[id]/page.tsx) | Next.js App Router page view rendering the `/simulations/[id]` interface. |
| [`web/app/suppliers/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/suppliers/page.tsx) | Next.js App Router page view rendering the `/suppliers` interface. |
| [`web/app/system-health/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/system-health/page.tsx) | Next.js App Router page view rendering the `/system-health` interface. |
| [`web/app/verification/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/verification/page.tsx) | Next.js App Router page view rendering the `/verification` interface. |
| [`web/app/verification/[id]/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/verification/[id]/page.tsx) | Next.js App Router page view rendering the `/verification/[id]` interface. |
| [`web/app/warehouses/page.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/app/warehouses/page.tsx) | Next.js App Router page view rendering the `/warehouses` interface. |

---

## 27. Frontend Components (`web/components/`)
*Total Files: 21*

| File Path | Description / Role |
| :--- | :--- |
| [`web/components/auth/AuthCard.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/auth/AuthCard.tsx) | Authentication interface component: Authcard. |
| [`web/components/auth/AuthErrorBanner.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/auth/AuthErrorBanner.tsx) | Authentication interface component: Autherrorbanner. |
| [`web/components/auth/AuthModeSwitch.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/auth/AuthModeSwitch.tsx) | Authentication interface component: Authmodeswitch. |
| [`web/components/auth/AuthSecurityNotice.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/auth/AuthSecurityNotice.tsx) | Authentication interface component: Authsecuritynotice. |
| [`web/components/auth/GoogleAuthButton.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/auth/GoogleAuthButton.tsx) | Authentication interface component: Googleauthbutton. |
| [`web/components/auth/ProtectedRoute.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/auth/ProtectedRoute.tsx) | Authentication interface component: Protectedroute. |
| [`web/components/auth/RiskWiseLogo.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/auth/RiskWiseLogo.tsx) | Authentication interface component: Riskwiselogo. |
| [`web/components/layout/AppShell.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/layout/AppShell.tsx) | Global layout and navigation component: Appshell. |
| [`web/components/layout/GlobalSearchModal.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/layout/GlobalSearchModal.tsx) | Global layout and navigation component: Globalsearchmodal. |
| [`web/components/layout/Sidebar.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/layout/Sidebar.tsx) | Global layout and navigation component: Sidebar. |
| [`web/components/layout/TopBar.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/layout/TopBar.tsx) | Global layout and navigation component: Topbar. |
| [`web/components/map/MapCard.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/map/MapCard.tsx) | Supply chain mapping and geographic visualization: Mapcard. |
| [`web/components/ui/AceternityCard.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/ui/AceternityCard.tsx) | Design system component: Aceternitycard. |
| [`web/components/ui/ArchitecturalComponents.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/ui/ArchitecturalComponents.tsx) | ========================================== |
| [`web/components/ui/Badges.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/ui/Badges.tsx) | ========================================================================= |
| [`web/components/ui/DataTable.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/ui/DataTable.tsx) | Design system component: Datatable. |
| [`web/components/ui/FeedbackStates.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/ui/FeedbackStates.tsx) | Design system component: Feedbackstates. |
| [`web/components/ui/MagicComponents.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/ui/MagicComponents.tsx) | Magic UI: BorderBeam |
| [`web/components/ui/MetricCard.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/ui/MetricCard.tsx) | Design system component: Metriccard. |
| [`web/components/ui/OperationalPipeline.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/ui/OperationalPipeline.tsx) | Design system component: Operationalpipeline. |
| [`web/components/visualization/SecurityMachine3D.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/components/visualization/SecurityMachine3D.tsx) | Interactive 3D / graphic visualization: Securitymachine3D. |

---

## 28. Frontend Libraries & State Contexts (`web/lib/`)
*Total Files: 6*

| File Path | Description / Role |
| :--- | :--- |
| [`web/lib/api/client.ts`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/lib/api/client.ts) | Unified API Client for RiskWise 2.0 (Phase 19). |
| [`web/lib/api/index.ts`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/lib/api/index.ts) | Type-safe API client and endpoint bindings for Index. |
| [`web/lib/api/types.ts`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/lib/api/types.ts) | Comprehensive TypeScript API Contracts for RiskWise 2.0 (Phase 19). |
| [`web/lib/auth/AuthContext.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/lib/auth/AuthContext.tsx) | Determine granular enterprise authentication state |
| [`web/lib/auth/types.ts`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/lib/auth/types.ts) | Frontend Authentication & Identity Types for RiskWise 2.0 (Phase 3 Step 6). |
| [`web/lib/theme/ThemeContext.tsx`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/lib/theme/ThemeContext.tsx) | Theme mode (dark/light) context and style providers for Themecontext. |

---

## 29. Frontend Public Assets (`web/public/`)
*Total Files: 5*

| File Path | Description / Role |
| :--- | :--- |
| [`web/public/file.svg`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/public/file.svg) | Configuration or source file: `file.svg`. |
| [`web/public/globe.svg`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/public/globe.svg) | Configuration or source file: `globe.svg`. |
| [`web/public/next.svg`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/public/next.svg) | Configuration or source file: `next.svg`. |
| [`web/public/vercel.svg`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/public/vercel.svg) | Configuration or source file: `vercel.svg`. |
| [`web/public/window.svg`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/public/window.svg) | Configuration or source file: `window.svg`. |

---

## 30. Frontend Automated Tests (`web/tests/`)
*Total Files: 4*

| File Path | Description / Role |
| :--- | :--- |
| [`web/tests/audit-runner.js`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/tests/audit-runner.js) | Frontend test suite verifying Audit Runner. |
| [`web/tests/auth-integration.test.ts`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/tests/auth-integration.test.ts) | Comprehensive Frontend Authentication Integration Test Suite |
| [`web/tests/frontend-backend-integration.test.ts`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/tests/frontend-backend-integration.test.ts) | RiskWise 2.0 Frontend ↔ Backend Integration & Contract Validation Test Suite |
| [`web/tests/phase19-control-tower.test.ts`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/web/tests/phase19-control-tower.test.ts) | Frontend test suite verifying Phase19 Control Tower. |

---

## 31. Project Documentation & Architecture Specs (`docs/`)
*Total Files: 72*

| File Path | Description / Role |
| :--- | :--- |
| [`docs/RiskWise_2.0_UI_UX_Design_System.md`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/RiskWise_2.0_UI_UX_Design_System.md) | Technical specification, architectural design, or milestone report for Riskwise 2.0 Ui Ux Design System. |
| [`docs/architecture.md`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/architecture.md) | Technical specification, architectural design, or milestone report for Architecture. |
| [`docs/deployment.md`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/deployment.md) | Technical specification, architectural design, or milestone report for Deployment. |
| [`docs/development.md`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/development.md) | Technical specification, architectural design, or milestone report for Development. |
| [`docs/security.md`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/security.md) | Technical specification, architectural design, or milestone report for Security. |
| [`docs/testing.md`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/testing.md) | Technical specification, architectural design, or milestone report for Testing. |
| [`docs/screenshots/admin_rbac_page.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/admin_rbac_page.png) | Technical specification, architectural design, or milestone report for Admin Rbac Page. |
| [`docs/screenshots/agent_run_result_1790712052608.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/agent_run_result_1790712052608.png) | Technical specification, architectural design, or milestone report for Agent Run Result 1790712052608. |
| [`docs/screenshots/agent_runs_page_1790711989466.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/agent_runs_page_1790711989466.png) | Technical specification, architectural design, or milestone report for Agent Runs Page 1790711989466. |
| [`docs/screenshots/approvals_queue_page.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/approvals_queue_page.png) | Technical specification, architectural design, or milestone report for Approvals Queue Page. |
| [`docs/screenshots/audit_index.json`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/audit_index.json) | Technical specification, architectural design, or milestone report for Audit Index. |
| [`docs/screenshots/audit_ledger_page.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/audit_ledger_page.png) | Technical specification, architectural design, or milestone report for Audit Ledger Page. |
| [`docs/screenshots/auth_login_page.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/auth_login_page.png) | Technical specification, architectural design, or milestone report for Auth Login Page. |
| [`docs/screenshots/dark_theme_dashboard_1790711903068.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/dark_theme_dashboard_1790711903068.png) | Technical specification, architectural design, or milestone report for Dark Theme Dashboard 1790711903068. |
| [`docs/screenshots/dashboard_initial_1790711717850.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/dashboard_initial_1790711717850.png) | Technical specification, architectural design, or milestone report for Dashboard Initial 1790711717850. |
| [`docs/screenshots/dashboard_obsidian_mode.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/dashboard_obsidian_mode.png) | Technical specification, architectural design, or milestone report for Dashboard Obsidian Mode. |
| [`docs/screenshots/dashboard_scrolled_1_1790711816320.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/dashboard_scrolled_1_1790711816320.png) | Technical specification, architectural design, or milestone report for Dashboard Scrolled 1 1790711816320. |
| [`docs/screenshots/dashboard_warm_ivory_mode.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/dashboard_warm_ivory_mode.png) | Technical specification, architectural design, or milestone report for Dashboard Warm Ivory Mode. |
| [`docs/screenshots/live_map_page.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/live_map_page.png) | Technical specification, architectural design, or milestone report for Live Map Page. |
| [`docs/screenshots/mcp_tool_inspect_modal_1790712139675.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/mcp_tool_inspect_modal_1790712139675.png) | Technical specification, architectural design, or milestone report for Mcp Tool Inspect Modal 1790712139675. |
| [`docs/screenshots/mcp_tools_page_1790712106654.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/mcp_tools_page_1790712106654.png) | Technical specification, architectural design, or milestone report for Mcp Tools Page 1790712106654. |
| [`docs/screenshots/optimization_engine_page.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/optimization_engine_page.png) | Technical specification, architectural design, or milestone report for Optimization Engine Page. |
| [`docs/screenshots/policy_inspector_page_1790712228691.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/policy_inspector_page_1790712228691.png) | Technical specification, architectural design, or milestone report for Policy Inspector Page 1790712228691. |
| [`docs/screenshots/policy_rules_table_1790712268003.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/policy_rules_table_1790712268003.png) | Technical specification, architectural design, or milestone report for Policy Rules Table 1790712268003. |
| [`docs/screenshots/root_dashboard_1790711778599.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/root_dashboard_1790711778599.png) | Technical specification, architectural design, or milestone report for Root Dashboard 1790711778599. |
| [`docs/screenshots/shipments_monitor_page.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/shipments_monitor_page.png) | Technical specification, architectural design, or milestone report for Shipments Monitor Page. |
| [`docs/screenshots/shipments_register_modal.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/shipments_register_modal.png) | Technical specification, architectural design, or milestone report for Shipments Register Modal. |
| [`docs/screenshots/simulations_engine_page.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/simulations_engine_page.png) | Technical specification, architectural design, or milestone report for Simulations Engine Page. |
| [`docs/screenshots/simulations_wizard_modal.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/simulations_wizard_modal.png) | Technical specification, architectural design, or milestone report for Simulations Wizard Modal. |
| [`docs/screenshots/suppliers_directory_page.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/suppliers_directory_page.png) | Technical specification, architectural design, or milestone report for Suppliers Directory Page. |
| [`docs/screenshots/suppliers_register_modal.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/suppliers_register_modal.png) | Technical specification, architectural design, or milestone report for Suppliers Register Modal. |
| [`docs/screenshots/system_health_page_1790712332628.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/system_health_page_1790712332628.png) | Technical specification, architectural design, or milestone report for System Health Page 1790712332628. |
| [`docs/screenshots/ui_redesign_qa_1790711636641.webp`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/screenshots/ui_redesign_qa_1790711636641.webp) | Technical specification, architectural design, or milestone report for Ui Redesign Qa 1790711636641. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/autonomous_supply_chain_operations_command/DESIGN.md`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/autonomous_supply_chain_operations_command/DESIGN.md) | Technical specification, architectural design, or milestone report for Design. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/control_tower_operations_command/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/control_tower_operations_command/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/control_tower_operations_command/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/control_tower_operations_command/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/global_live_map_telemetry_ais_tracking/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/global_live_map_telemetry_ais_tracking/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/global_live_map_telemetry_ais_tracking/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/global_live_map_telemetry_ais_tracking/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/governance_human_approval_cryptographic_sign_off/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/governance_human_approval_cryptographic_sign_off/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/governance_human_approval_cryptographic_sign_off/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/governance_human_approval_cryptographic_sign_off/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/immutable_audit_log_cryptographic_ledger/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/immutable_audit_log_cryptographic_ledger/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/immutable_audit_log_cryptographic_ledger/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/immutable_audit_log_cryptographic_ledger/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/incident_command_disruption_register/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/incident_command_disruption_register/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/incident_command_disruption_register/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/incident_command_disruption_register/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/incident_detail_war_room_inc_9902/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/incident_detail_war_room_inc_9902/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/incident_detail_war_room_inc_9902/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/incident_detail_war_room_inc_9902/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/optimization_run_detail_pareto_frontier_trade_off_analysis/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/optimization_run_detail_pareto_frontier_trade_off_analysis/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/optimization_run_detail_pareto_frontier_trade_off_analysis/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/optimization_run_detail_pareto_frontier_trade_off_analysis/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/phase_18_verification_deterministic_policy_engine/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/phase_18_verification_deterministic_policy_engine/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/phase_18_verification_deterministic_policy_engine/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/phase_18_verification_deterministic_policy_engine/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/recommendation_review_mitigation_decision_ai_synthesis/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/recommendation_review_mitigation_decision_ai_synthesis/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/recommendation_review_mitigation_decision_ai_synthesis/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/recommendation_review_mitigation_decision_ai_synthesis/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/riskwise_2.0_enterprise_authentication_gateway/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/riskwise_2.0_enterprise_authentication_gateway/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/riskwise_2.0_enterprise_authentication_gateway/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/riskwise_2.0_enterprise_authentication_gateway/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/risk_detail_rsk_9902_bab_el_mandeb_interdiction_dossier/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/risk_detail_rsk_9902_bab_el_mandeb_interdiction_dossier/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/risk_detail_rsk_9902_bab_el_mandeb_interdiction_dossier/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/risk_detail_rsk_9902_bab_el_mandeb_interdiction_dossier/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/risk_register_multi_axis_exposure_matrix/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/risk_register_multi_axis_exposure_matrix/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/risk_register_multi_axis_exposure_matrix/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/risk_register_multi_axis_exposure_matrix/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipments_tracker_active_global_freight/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipments_tracker_active_global_freight/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipments_tracker_active_global_freight/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipments_tracker_active_global_freight/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipments_tracker_high_density_logistics_monitor/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipments_tracker_high_density_logistics_monitor/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipments_tracker_high_density_logistics_monitor/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipments_tracker_high_density_logistics_monitor/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipment_detail_shp_9921_x_asml_euv_3nm_sub_components/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipment_detail_shp_9921_x_asml_euv_3nm_sub_components/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipment_detail_shp_9921_x_asml_euv_3nm_sub_components/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipment_detail_shp_9921_x_asml_euv_3nm_sub_components/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipment_dossier_shp_9921_x_telemetry_ml_prediction/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipment_dossier_shp_9921_x_telemetry_ml_prediction/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipment_dossier_shp_9921_x_telemetry_ml_prediction/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/shipment_dossier_shp_9921_x_telemetry_ml_prediction/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/simulation_results_monte_carlo_analytics_riskwise_2.0/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/simulation_results_monte_carlo_analytics_riskwise_2.0/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/simulation_results_monte_carlo_analytics_riskwise_2.0/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/simulation_results_monte_carlo_analytics_riskwise_2.0/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/simulation_setup_wizard_riskwise_2.0/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/simulation_setup_wizard_riskwise_2.0/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/simulation_setup_wizard_riskwise_2.0/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/simulation_setup_wizard_riskwise_2.0/screen.png) | Technical specification, architectural design, or milestone report for Screen. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/topology_canvas_digital_twin_network_graph/code.html`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/topology_canvas_digital_twin_network_graph/code.html) | Technical specification, architectural design, or milestone report for Code. |
| [`docs/stitch_reference/stitch_riskwise_2.0_control_tower/topology_canvas_digital_twin_network_graph/screen.png`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/docs/stitch_reference/stitch_riskwise_2.0_control_tower/topology_canvas_digital_twin_network_graph/screen.png) | Technical specification, architectural design, or milestone report for Screen. |

---

## 32. Infrastructure & Deployments (`infra/`)
*Total Files: 3*

| File Path | Description / Role |
| :--- | :--- |
| [`infra/terraform/main.tf`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/infra/terraform/main.tf) | Infrastructure, orchestration, or container deployment configuration: `main.tf`. |
| [`infra/terraform/outputs.tf`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/infra/terraform/outputs.tf) | Infrastructure, orchestration, or container deployment configuration: `outputs.tf`. |
| [`infra/terraform/variables.tf`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/infra/terraform/variables.tf) | Infrastructure, orchestration, or container deployment configuration: `variables.tf`. |

---

## 33. Artifacts & Exports (`artifacts/`, `storage/`)
*Total Files: 12*

| File Path | Description / Role |
| :--- | :--- |
| [`artifacts/qa/FINAL_ACCEPTANCE_REPORT.md`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/artifacts/qa/FINAL_ACCEPTANCE_REPORT.md) | Generated project artifact, architecture map, or visual export: `FINAL_ACCEPTANCE_REPORT.md`. |
| [`artifacts/qa/api-inventory.json`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/artifacts/qa/api-inventory.json) | Generated project artifact, architecture map, or visual export: `api-inventory.json`. |
| [`artifacts/qa/browser-console.json`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/artifacts/qa/browser-console.json) | Generated project artifact, architecture map, or visual export: `browser-console.json`. |
| [`artifacts/qa/feature-inventory.json`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/artifacts/qa/feature-inventory.json) | Generated project artifact, architecture map, or visual export: `feature-inventory.json`. |
| [`artifacts/qa/network-failures.json`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/artifacts/qa/network-failures.json) | Generated project artifact, architecture map, or visual export: `network-failures.json`. |
| [`artifacts/qa/route-inventory.json`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/artifacts/qa/route-inventory.json) | Generated project artifact, architecture map, or visual export: `route-inventory.json`. |
| [`storage/ml_artifacts/delay_baseline_v1.joblib`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/storage/ml_artifacts/delay_baseline_v1.joblib) | Persistent data store or local database cache: `delay_baseline_v1.joblib`. |
| [`storage/ml_artifacts/delay_custom_v1.joblib`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/storage/ml_artifacts/delay_custom_v1.joblib) | Persistent data store or local database cache: `delay_custom_v1.joblib`. |
| [`storage/ml_artifacts/repro_m.joblib`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/storage/ml_artifacts/repro_m.joblib) | Persistent data store or local database cache: `repro_m.joblib`. |
| [`storage/ml_artifacts/retrain_m1.joblib`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/storage/ml_artifacts/retrain_m1.joblib) | Persistent data store or local database cache: `retrain_m1.joblib`. |
| [`storage/ml_artifacts/retrain_m2.joblib`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/storage/ml_artifacts/retrain_m2.joblib) | Persistent data store or local database cache: `retrain_m2.joblib`. |
| [`storage/ml_artifacts/shipment_delay_ridge_1.0.0_org_acme.joblib`](file:///c:/Users/sugud/OneDrive/Documents/riskwise/storage/ml_artifacts/shipment_delay_ridge_1.0.0_org_acme.joblib) | Persistent data store or local database cache: `shipment_delay_ridge_1.0.0_org_acme.joblib`. |

---
