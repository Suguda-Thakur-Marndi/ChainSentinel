# RiskWise 2.0 — Local Development Guide

## 1. Prerequisites

Before setting up RiskWise 2.0 locally, ensure you have the following installed:

- **Python**: Version 3.12 or 3.13 (`python --version`)
- **Node.js**: Version 20.x or 24.x LTS (`node --version`)
- **npm**: Version 10+ (`npm --version`)
- **Git**: Version 2.40+ (`git --version`)
- **Operating System**: Linux, macOS, or Windows (PowerShell)

---

## 2. Monorepo Structure

```
riskwise/
├── .github/
│   └── workflows/
│       └── production.yml       # Production CI/CD Pipeline
├── .agents/
│   └── skills/                  # IDE Agent Skills
├── api/                         # FastAPI Backend
│   ├── alembic/                 # Database Migrations
│   ├── app/                     # Backend Source Code
│   │   ├── agents/              # LangGraph Multi-Agent Workflows
│   │   ├── api/v1/              # REST Endpoints
│   │   ├── core/                # Config, Security, Telemetry
│   │   ├── db/                  # Session, Engine
│   │   ├── digital_twin/        # Network Graph Model
│   │   ├── evaluation/          # Evaluation Harness
│   │   ├── integrations/        # Telemetry Ingestion Connectors
│   │   ├── llm/                 # Gemini 2.5 Flash Provider
│   │   ├── ml/                  # Delay Regression Models
│   │   ├── models/              # SQLAlchemy ORM Models
│   │   ├── normalization/       # Canonical Event Processing
│   │   ├── optimization/        # Google OR-Tools MILP Solver
│   │   ├── rag/                 # Vector Retrieval & Documents
│   │   ├── repositories/        # Database Access Layer
│   │   ├── risk_engine/         # Multi-Factor Scoring
│   │   ├── schemas/             # Pydantic Contracts
│   │   ├── services/            # Domain Business Logic
│   │   └── simulation/          # Monte Carlo Disruption Engine
│   ├── storage/                 # Local ML Models & Cache
│   ├── tests/                   # Pytest Regression Suite (4,500+ tests)
│   ├── Dockerfile               # Backend Container Definition
│   ├── pyproject.toml           # Python Packaging
│   └── requirements.txt         # Production & Test Dependencies
├── docs/                        # Authoritative Technical Documentation
│   ├── architecture.md          # System Architecture & Subsystem Specs
│   ├── development.md           # Local Setup & Engineering Guide (this file)
│   ├── deployment.md            # Production Infrastructure & CI/CD
│   ├── testing.md               # Testing Strategy & Quality Assurance
│   ├── security.md              # Auth, RBAC, Encryption & Threat Model
│   └── RiskWise_2.0_UI_UX_Design_System.md # Comprehensive UI/UX Design System
├── infra/
│   └── terraform/               # AWS Infrastructure as Code
└── web/                         # Next.js 16 Frontend
    ├── app/                     # Next.js App Router (36 Routes)
    ├── components/              # UI, Layout, Map & Auth Components
    ├── lib/                     # API Client, Types, Contexts
    ├── public/                  # Static SVG Assets
    ├── tests/                   # Frontend Integration Tests
    ├── package.json             # Frontend Dependencies & Scripts
    └── tsconfig.json            # TypeScript Configuration
```

---

## 3. Environment Setup

### 3.1 Backend Setup (`api/`)

1. **Navigate to the API directory**:
   ```bash
   cd api
   ```

2. **Create and activate a virtual environment**:
   - **Linux / macOS**:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
   - **Windows (PowerShell)**:
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```

3. **Install dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   Create `api/.env` (or copy from root `.env.example`):
   ```env
   ENVIRONMENT=development
   DEBUG=true
   PROJECT_NAME=RiskWise 2.0
   DATABASE_URL=sqlite:///./riskwise_local.db
   REDIS_URL=redis://127.0.0.1:6379/0
   GEMINI_API_KEY=your_gemini_api_key_here
   LLM_PROVIDER=gemini
   GEMINI_MODEL=gemini-2.5-flash
   GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your_google_client_secret
   GOOGLE_REDIRECT_URI=http://localhost:3000/auth/callback
   JWT_SECRET=development_secret_key_change_in_production_32_chars_min
   ```

5. **Run database migrations**:
   ```bash
   alembic upgrade head
   ```

6. **Start the backend development server**:
   ```bash
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```
   - **API Documentation**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
   - **Health Probe**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
   - **Readiness Probe**: [http://127.0.0.1:8000/ready](http://127.0.0.1:8000/ready)

---

### 3.2 Frontend Setup (`web/`)

1. **Navigate to the Web directory**:
   ```bash
   cd web
   ```

2. **Install Node dependencies**:
   ```bash
   npm install
   ```

3. **Configure frontend environment variables**:
   Create `web/.env.local`:
   ```env
   NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
   NEXT_PUBLIC_GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com
   ```

4. **Start the frontend development server**:
   ```bash
   npm run dev
   ```
   - **Control Tower UI**: [http://localhost:3000](http://localhost:3000)

---

## 4. Development Workflows

### 4.1 Running Tests

- **Backend Pytest Suite**:
  ```bash
  cd api
  python -m pytest tests/ -v --tb=short
  ```
- **Frontend Integration Tests**:
  ```bash
  cd web
  npm test
  ```

### 4.2 Code Quality & Verification

- **Frontend Linting & Type Checking**:
  ```bash
  cd web
  npm run lint
  npx tsc --noEmit
  ```
- **Production Build Validation**:
  ```bash
  cd web
  npm run build
  ```

### 4.3 Database Migrations

When altering SQLAlchemy models in `api/app/models/`:

1. **Generate migration script**:
   ```bash
   cd api
   alembic revision --autogenerate -m "describe_change"
   ```
2. **Review generated script** in `api/alembic/versions/`.
3. **Apply migration**:
   ```bash
   alembic upgrade head
   ```

---

## 5. UI/UX Design System & Tokens

RiskWise 2.0 adheres to a high-density, mission-critical operational dark theme:

- **Background Colors**: Deep navy & space slate (`#0B0F19`, `#111827`, `#1F2937`)
- **Accent Colors**:
  - Primary Electric Indigo: `#4F46E5` / `#6366F1`
  - Success Emerald: `#10B981` (Low Risk / Operational)
  - Warning Amber: `#F59E0B` (Medium Risk / Pending Approval)
  - Danger Rose: `#EF4444` (High/Critical Risk / Interdicted)
  - Info Cyan: `#06B6D4` (Telemetry / Active Tracking)
- **Typography**: Inter (Body), Outfit / JetBrains Mono (Telemetry & Metrics)
- **Component Guidelines**: See `docs/RiskWise_2.0_UI_UX_Design_System.md` for full component specifications.
