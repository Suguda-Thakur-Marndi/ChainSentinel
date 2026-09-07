# RiskWise 2.0

> **AI-Powered Supply Chain Risk Intelligence & Decision Platform**

RiskWise 2.0 is a multi-tenant enterprise control center for supply-chain risk intelligence. It provides real-time disruption visibility, multi-agent AI investigations, digital-twin scenario simulations, mitigation optimizations, and human-in-the-loop approval governance with full auditability.

---

## Monorepo Architecture

```
riskwise/
├── apps/
│   ├── web/               # Frontend: Next.js (TypeScript, App Router, Tailwind CSS)
│   └── api/               # Backend: FastAPI (Python, Pydantic, SQLAlchemy)
│
├── agents/                # AI agent definitions and orchestration pipelines
├── ml/                    # Machine learning models, training, and inference scripts
├── rag/                   # Retrieval-augmented generation and vector store indexes
├── simulation/            # Digital twin and supply chain network simulation engines
├── knowledge_graph/       # Supply chain entity-relationship knowledge graph
├── data/                  # Data pipelines, schemas, and processing tasks
├── integrations/          # External connectors (Project44, AISStream, Weather, etc.)
├── workers/               # Asynchronous task workers and consumers
├── event_bus/             # Event bus schemas and messaging infrastructure
├── database/              # Relational schemas, migrations, and seed scripts
├── security/              # Security policies, RBAC definitions, and audit controls
├── observability/         # Telemetry, OpenTelemetry, metrics, and tracing configs
├── evaluation/            # AI evaluation datasets and benchmark harnesses
├── infrastructure/        # Cloud infrastructure as code (Terraform / CDK / Docker)
├── scripts/               # Developer automation, setup, and maintenance scripts
├── docs/                  # Technical specifications, design systems, and architecture docs
└── tests/                 # End-to-end and cross-service integration test suites
```

---

## Prerequisites

- **Node.js**: `v20.x` or later
- **Python**: `3.12` or `3.13`
- **Git**

---

## Getting Started

### 1. Environment Setup

Copy the example environment template:

```bash
cp .env.example .env
```

Configure local environment variables. Sensitive secrets are never committed.

### 2. Database Configuration

The backend connects to PostgreSQL via `DATABASE_URL` specified in `.env` (using the `postgresql+psycopg://` dialect format):

```bash
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:<port>/<dbname>
```

Alembic manages migrations from `apps/api/` using configuration in `apps/api/alembic.ini`.

### 3. Frontend Development

Located in `apps/web/`:

```bash
cd apps/web
npm install
npm run dev
```

The frontend web application runs at [http://localhost:3000](http://localhost:3000).

### 4. Backend Development

Located in `apps/api/`:

```bash
cd apps/api
# On Linux/macOS:
source .venv/bin/activate
# On Windows PowerShell:
.venv\Scripts\activate

uvicorn app.main:app --reload --port 8000
```

- API v1 Health Check: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)
- Database Health Check: [http://localhost:8000/api/v1/health/db](http://localhost:8000/api/v1/health/db)
- Interactive API Docs (Swagger UI): [http://localhost:8000/docs](http://localhost:8000/docs)
- OpenAPI Specification: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

---

## Development Validation Commands

### Frontend Validation (`apps/web`)
```bash
cd apps/web
npx tsc --noEmit   # Type check
npm run lint       # ESLint check
npm run build      # Next.js production build
```

### Backend Validation (`apps/api`)
```bash
cd apps/api
python -m pytest tests/ -v  # Run test suite
```

---

## Documentation

- [Technical Project Specification](docs/RiskWise_2.0_Technical_Project_Spec.md)
- [UI / UX Design System](docs/RiskWise_2.0_UI_UX_Design_System.md)
- [High-Level Architecture Design](docs/DESIGN.md)

