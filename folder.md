# Full Project Structure & Repository Architecture

> **Project:** RiskWise / ChainSentinel  
> **Type:** Monorepo - Autonomous Multi-Agent Supply Chain Risk & Logistics Intelligence Platform  
> **Exclusions:** Build artifacts & dependencies (`node_modules/`, `.venv/`, `.next/`, `__pycache__/`, `.git/`, `.pytest_cache/`, `.turbo/`)

---

## 📊 Summary Statistics

| Category | Metric |
| :--- | :--- |
| **Total Tracked Directories** | `91` |
| **Total Tracked Files** | `653` |
| **Backend Stack** | Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, Redis, Celery |
| **Frontend Stack** | Next.js 15+ (App Router), React 19, TypeScript, Tailwind CSS, Lucide Icons |
| **Intelligence Stack** | LangGraph, AWS Bedrock (Claude 3.5 Sonnet), Scikit-Learn, NetworkX / Digital Twin, Simulation Engine |
| **Primary Workspaces** | `api/` (Backend), `web/` (Frontend), `docs/` (Architecture & Specs), `.agents/` (Agent Skills) |

---

## 🌳 Full Project Structure Tree

```
riskwise/
├── .agents/
│   └── skills/
│       ├── banner-design/
│       │   ├── SKILL.md
│       │   └── references/
│       │       └── banner-sizes-and-styles.md
│       ├── brand/
│       │   ├── SKILL.md
│       │   ├── references/
│       │   │   ├── approval-checklist.md
│       │   │   ├── asset-organization.md
│       │   │   ├── brand-guideline-template.md
│       │   │   ├── color-palette-management.md
│       │   │   ├── consistency-checklist.md
│       │   │   ├── logo-usage-rules.md
│       │   │   ├── messaging-framework.md
│       │   │   ├── typography-specifications.md
│       │   │   ├── update.md
│       │   │   ├── visual-identity.md
│       │   │   └── voice-framework.md
│       │   ├── scripts/
│       │   │   ├── extract-colors.cjs
│       │   │   ├── inject-brand-context.cjs
│       │   │   ├── sync-brand-to-tokens.cjs
│       │   │   ├── tests/
│       │   │   │   └── test_sync_brand_to_tokens.py
│       │   │   └── validate-asset.cjs
│       │   └── templates/
│       │       └── brand-guidelines-starter.md
│       ├── design/
│       │   ├── SKILL.md
│       │   ├── data/
│       │   │   ├── cip/
│       │   │   │   ├── deliverables.csv
│       │   │   │   ├── industries.csv
│       │   │   │   ├── mockup-contexts.csv
│       │   │   │   └── styles.csv
│       │   │   ├── icon/
│       │   │   │   └── styles.csv
│       │   │   └── logo/
│       │   │       ├── colors.csv
│       │   │       ├── industries.csv
│       │   │       └── styles.csv
│       │   ├── references/
│       │   │   ├── banner-sizes-and-styles.md
│       │   │   ├── cip-deliverable-guide.md
│       │   │   ├── cip-design.md
│       │   │   ├── cip-prompt-engineering.md
│       │   │   ├── cip-style-guide.md
│       │   │   ├── design-routing.md
│       │   │   ├── icon-design.md
│       │   │   ├── logo-color-psychology.md
│       │   │   ├── logo-design.md
│       │   │   ├── logo-prompt-engineering.md
│       │   │   ├── logo-style-guide.md
│       │   │   ├── slides-copywriting-formulas.md
│       │   │   ├── slides-create.md
│       │   │   ├── slides-html-template.md
│       │   │   ├── slides-layout-patterns.md
│       │   │   ├── slides-strategies.md
│       │   │   ├── slides.md
│       │   │   └── social-photos-design.md
│       │   └── scripts/
│       │       ├── cip/
│       │       │   ├── core.py
│       │       │   ├── generate.py
│       │       │   ├── render-html.py
│       │       │   └── search.py
│       │       ├── icon/
│       │       │   └── generate.py
│       │       └── logo/
│       │           ├── core.py
│       │           ├── generate.py
│       │           └── search.py
│       ├── design-system/
│       │   ├── SKILL.md
│       │   ├── data/
│       │   │   ├── slide-backgrounds.csv
│       │   │   ├── slide-charts.csv
│       │   │   ├── slide-color-logic.csv
│       │   │   ├── slide-copy.csv
│       │   │   ├── slide-layout-logic.csv
│       │   │   ├── slide-layouts.csv
│       │   │   ├── slide-strategies.csv
│       │   │   └── slide-typography.csv
│       │   ├── references/
│       │   │   ├── component-specs.md
│       │   │   ├── component-tokens.md
│       │   │   ├── primitive-tokens.md
│       │   │   ├── semantic-tokens.md
│       │   │   ├── states-and-variants.md
│       │   │   ├── tailwind-integration.md
│       │   │   └── token-architecture.md
│       │   ├── scripts/
│       │   │   ├── embed-tokens.cjs
│       │   │   ├── fetch-background.py
│       │   │   ├── generate-slide.py
│       │   │   ├── generate-tokens.cjs
│       │   │   ├── html-token-validator.py
│       │   │   ├── search-slides.py
│       │   │   ├── slide-token-validator.py
│       │   │   ├── slide_search_core.py
│       │   │   ├── tests/
│       │   │   │   └── test_validate_tokens.py
│       │   │   └── validate-tokens.cjs
│       │   └── templates/
│       │       └── design-tokens-starter.json
│       ├── slides/
│       │   ├── SKILL.md
│       │   └── references/
│       │       ├── copywriting-formulas.md
│       │       ├── create.md
│       │       ├── html-template.md
│       │       ├── layout-patterns.md
│       │       └── slide-strategies.md
│       ├── ui-styling/
│       │   ├── LICENSE.txt
│       │   ├── SKILL.md
│       │   ├── references/
│       │   │   ├── canvas-design-system.md
│       │   │   ├── shadcn-accessibility.md
│       │   │   ├── shadcn-components.md
│       │   │   ├── shadcn-theming.md
│       │   │   ├── tailwind-customization.md
│       │   │   ├── tailwind-responsive.md
│       │   │   └── tailwind-utilities.md
│       │   └── scripts/
│       │       ├── requirements.txt
│       │       ├── shadcn_add.py
│       │       ├── tailwind_config_gen.py
│       │       └── tests/
│       │           ├── coverage-ui.json
│       │           ├── requirements.txt
│       │           ├── test_shadcn_add.py
│       │           └── test_tailwind_config_gen.py
│       └── ui-ux-pro-max/
│           ├── SKILL.md
│           ├── data/
│           │   ├── app-interface.csv
│           │   ├── catalog-summary.json
│           │   ├── charts.csv
│           │   ├── colors.csv
│           │   ├── data-provenance.json
│           │   ├── google-font-licenses.json
│           │   ├── google-fonts.csv
│           │   ├── icons.csv
│           │   ├── landing.csv
│           │   ├── motion.csv
│           │   ├── phosphor-icons-upstream.json
│           │   ├── products.csv
│           │   ├── react-performance.csv
│           │   ├── stacks/
│           │   │   ├── angular.csv
│           │   │   ├── astro.csv
│           │   │   ├── avalonia.csv
│           │   │   ├── flutter.csv
│           │   │   ├── html-tailwind.csv
│           │   │   ├── javafx.csv
│           │   │   ├── jetpack-compose.csv
│           │   │   ├── laravel.csv
│           │   │   ├── nextjs.csv
│           │   │   ├── nuxt-ui.csv
│           │   │   ├── nuxtjs.csv
│           │   │   ├── react-native.csv
│           │   │   ├── react.csv
│           │   │   ├── shadcn.csv
│           │   │   ├── svelte.csv
│           │   │   ├── swiftui.csv
│           │   │   ├── threejs.csv
│           │   │   ├── uno.csv
│           │   │   ├── uwp.csv
│           │   │   ├── vue.csv
│           │   │   ├── winui.csv
│           │   │   └── wpf.csv
│           │   ├── styles.csv
│           │   ├── typography.csv
│           │   ├── ui-reasoning.csv
│           │   └── ux-guidelines.csv
│           └── scripts/
│               ├── core.py
│               ├── design_system.py
│               ├── reasoning_contract.py
│               ├── search.py
│               ├── tests/
│               │   ├── fixtures/
│               │   │   ├── catalogs/
│               │   │   │   ├── google-api.json
│               │   │   │   ├── google-catalog.json
│               │   │   │   ├── google-existing.csv
│               │   │   │   ├── google-metadata.json
│               │   │   │   ├── google-overrides.json
│               │   │   │   ├── icons-curated.csv
│               │   │   │   ├── phosphor-core.json
│               │   │   │   ├── phosphor-package.json
│               │   │   │   ├── phosphor-react-exports.json
│               │   │   │   └── phosphor-react-package.json
│               │   │   ├── relevance-baseline.json
│               │   │   ├── relevance-cases.json
│               │   │   └── relevance-thresholds.json
│               │   ├── test_catalog_refresh.py
│               │   ├── test_core.py
│               │   ├── test_core_data_quality.py
│               │   ├── test_data_contracts.py
│               │   ├── test_design_system_mode.py
│               │   ├── test_native_desktop_stack_freshness.py
│               │   ├── test_relevance_evaluator.py
│               │   ├── test_style_taxonomy.py
│               │   ├── test_text_layout_resilience.py
│               │   └── test_web_stack_freshness.py
│               └── validate_data.py
├── .env
├── .env.example
├── .gitignore
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── api/
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── .gitkeep
│   ├── alembic.ini
│   ├── app/
│   │   ├── __init__.py
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── approval/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── agent.py
│   │   │   │   ├── contract.py
│   │   │   │   ├── errors.py
│   │   │   │   ├── node.py
│   │   │   │   └── service.py
│   │   │   ├── contracts.py
│   │   │   ├── decision/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── agent.py
│   │   │   │   ├── claude_contract.py
│   │   │   │   ├── claude_service.py
│   │   │   │   ├── contract.py
│   │   │   │   ├── errors.py
│   │   │   │   ├── node.py
│   │   │   │   └── rules.py
│   │   │   ├── edges.py
│   │   │   ├── errors.py
│   │   │   ├── execution.py
│   │   │   ├── graph.py
│   │   │   ├── nodes.py
│   │   │   ├── observability.py
│   │   │   ├── prediction/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── adapter.py
│   │   │   │   ├── agent.py
│   │   │   │   ├── claude_contract.py
│   │   │   │   ├── claude_service.py
│   │   │   │   ├── contract.py
│   │   │   │   ├── errors.py
│   │   │   │   ├── node.py
│   │   │   │   └── service.py
│   │   │   ├── recovery.py
│   │   │   ├── registry.py
│   │   │   ├── research/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── agent.py
│   │   │   │   ├── analysis.py
│   │   │   │   ├── claude_contract.py
│   │   │   │   ├── claude_service.py
│   │   │   │   ├── contract.py
│   │   │   │   ├── errors.py
│   │   │   │   ├── evidence.py
│   │   │   │   └── node.py
│   │   │   ├── risk/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── adapter.py
│   │   │   │   ├── agent.py
│   │   │   │   ├── claude_contract.py
│   │   │   │   ├── claude_service.py
│   │   │   │   ├── contract.py
│   │   │   │   ├── errors.py
│   │   │   │   └── node.py
│   │   │   ├── routing.py
│   │   │   ├── scenario/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── agent.py
│   │   │   │   ├── claude_contract.py
│   │   │   │   ├── claude_service.py
│   │   │   │   ├── contract.py
│   │   │   │   ├── errors.py
│   │   │   │   ├── generator.py
│   │   │   │   └── node.py
│   │   │   ├── security.py
│   │   │   └── validator.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── deps.py
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── endpoints/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── actions.py
│   │   │       │   ├── approvals.py
│   │   │       │   ├── audit_logs.py
│   │   │       │   ├── auth.py
│   │   │       │   ├── carriers.py
│   │   │       │   ├── digital_twin.py
│   │   │       │   ├── factories.py
│   │   │       │   ├── health.py
│   │   │       │   ├── incidents.py
│   │   │       │   ├── inventory.py
│   │   │       │   ├── inventory_movements.py
│   │   │       │   ├── notifications.py
│   │   │       │   ├── ports.py
│   │   │       │   ├── products.py
│   │   │       │   ├── recommendations.py
│   │   │       │   ├── risk_assessments.py
│   │   │       │   ├── risk_factors.py
│   │   │       │   ├── risks.py
│   │   │       │   ├── routes.py
│   │   │       │   ├── shipment_events.py
│   │   │       │   ├── shipments.py
│   │   │       │   ├── simulation.py
│   │   │       │   ├── supplier_sites.py
│   │   │       │   ├── suppliers.py
│   │   │       │   ├── verification_results.py
│   │   │       │   └── warehouses.py
│   │   │       └── router.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── context.py
│   │   │   ├── errors.py
│   │   │   └── logging.py
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── session.py
│   │   │   └── unit_of_work.py
│   │   ├── digital_twin/
│   │   │   ├── __init__.py
│   │   │   ├── builder.py
│   │   │   ├── contracts.py
│   │   │   ├── errors.py
│   │   │   ├── fingerprints.py
│   │   │   ├── observability.py
│   │   │   ├── query.py
│   │   │   ├── repository.py
│   │   │   ├── service.py
│   │   │   └── validator.py
│   │   ├── integrations/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── boundaries.py
│   │   │   ├── canonical.py
│   │   │   ├── circuit_breaker.py
│   │   │   ├── config.py
│   │   │   ├── errors.py
│   │   │   ├── idempotency.py
│   │   │   ├── normalizers.py
│   │   │   ├── observability.py
│   │   │   ├── providers/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── aisstream.py
│   │   │   │   ├── karrio.py
│   │   │   │   ├── opensky.py
│   │   │   │   ├── openweather.py
│   │   │   │   ├── rail.py
│   │   │   │   ├── tavily.py
│   │   │   │   └── tomtom.py
│   │   │   ├── rate_limiter.py
│   │   │   ├── registry.py
│   │   │   ├── retry.py
│   │   │   └── service.py
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── bedrock.py
│   │   │   ├── contracts.py
│   │   │   ├── errors.py
│   │   │   ├── factory.py
│   │   │   ├── invocation.py
│   │   │   ├── mock.py
│   │   │   ├── observability.py
│   │   │   ├── prompts.py
│   │   │   ├── retry.py
│   │   │   └── security.py
│   │   ├── main.py
│   │   ├── ml/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── contracts.py
│   │   │   ├── datasets/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── builder.py
│   │   │   │   ├── contracts.py
│   │   │   │   └── validation.py
│   │   │   ├── errors.py
│   │   │   ├── features/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── contracts.py
│   │   │   │   └── shipment_delay.py
│   │   │   ├── inference/
│   │   │   │   ├── __init__.py
│   │   │   │   └── service.py
│   │   │   ├── models/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py
│   │   │   │   └── shipment_delay.py
│   │   │   ├── observability.py
│   │   │   ├── registry/
│   │   │   │   ├── __init__.py
│   │   │   │   └── registry.py
│   │   │   └── training/
│   │   │       ├── __init__.py
│   │   │       ├── artifacts.py
│   │   │       ├── pipeline.py
│   │   │       └── validation.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── agents.py
│   │   │   ├── digital_twin.py
│   │   │   ├── governance.py
│   │   │   ├── knowledge.py
│   │   │   ├── logistics.py
│   │   │   ├── network.py
│   │   │   ├── risk.py
│   │   │   ├── simulation.py
│   │   │   └── tenancy.py
│   │   ├── normalization/
│   │   │   ├── __init__.py
│   │   │   ├── contract.py
│   │   │   ├── correlation.py
│   │   │   ├── entity_resolver.py
│   │   │   ├── handlers.py
│   │   │   ├── identifiers.py
│   │   │   ├── pipeline.py
│   │   │   ├── quality.py
│   │   │   ├── status.py
│   │   │   └── units.py
│   │   ├── rag/
│   │   │   ├── __init__.py
│   │   │   ├── chunking.py
│   │   │   ├── contracts.py
│   │   │   ├── embeddings.py
│   │   │   ├── errors.py
│   │   │   ├── grounding.py
│   │   │   ├── ingestion.py
│   │   │   ├── parsers.py
│   │   │   ├── pipeline.py
│   │   │   ├── retrieval.py
│   │   │   └── vector_store.py
│   │   ├── repositories/
│   │   │   ├── __init__.py
│   │   │   ├── audit_log.py
│   │   │   ├── base.py
│   │   │   ├── governance_repositories.py
│   │   │   ├── inventory.py
│   │   │   ├── network_repositories.py
│   │   │   ├── port.py
│   │   │   ├── query_utils.py
│   │   │   ├── risk_repositories.py
│   │   │   ├── shipment.py
│   │   │   └── supplier.py
│   │   ├── risk_engine/
│   │   │   ├── __init__.py
│   │   │   ├── alerts.py
│   │   │   ├── context.py
│   │   │   ├── contract.py
│   │   │   ├── errors.py
│   │   │   ├── evaluators.py
│   │   │   ├── evidence.py
│   │   │   ├── explainability.py
│   │   │   ├── history.py
│   │   │   ├── persistence.py
│   │   │   ├── pipeline.py
│   │   │   ├── recommendations.py
│   │   │   ├── registry.py
│   │   │   └── scoring.py
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── agents.py
│   │   │   ├── auth.py
│   │   │   ├── common.py
│   │   │   ├── digital_twin.py
│   │   │   ├── governance.py
│   │   │   ├── health.py
│   │   │   ├── knowledge.py
│   │   │   ├── logistics.py
│   │   │   ├── network.py
│   │   │   ├── risk.py
│   │   │   ├── session.py
│   │   │   ├── simulation.py
│   │   │   └── tenancy.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── audit_service.py
│   │   │   ├── base.py
│   │   │   ├── concurrency.py
│   │   │   ├── governance_services.py
│   │   │   ├── inventory_services.py
│   │   │   ├── logistics_services.py
│   │   │   ├── oauth_service.py
│   │   │   ├── risk_evaluation_service.py
│   │   │   ├── risk_services.py
│   │   │   ├── session_service.py
│   │   │   └── supplier.py
│   │   └── simulation/
│   │       ├── __init__.py
│   │       ├── contracts.py
│   │       ├── effects.py
│   │       ├── engine.py
│   │       ├── errors.py
│   │       ├── fingerprints.py
│   │       ├── metrics.py
│   │       ├── observability.py
│   │       ├── propagation.py
│   │       ├── repository.py
│   │       ├── scenario.py
│   │       ├── service.py
│   │       ├── state.py
│   │       └── validation.py
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── storage/
│   │   └── ml_artifacts/
│   │       ├── delay_baseline_v1.joblib
│   │       ├── delay_custom_v1.joblib
│   │       ├── repro_m.joblib
│   │       ├── retrain_m1.joblib
│   │       ├── retrain_m2.joblib
│   │       └── shipment_delay_ridge_1.0.0_org_acme.joblib
│   └── tests/
│       ├── __init__.py
│       ├── integration/
│       │   └── .gitkeep
│       ├── test_aisstream_integration.py
│       ├── test_auth_config.py
│       ├── test_auth_final_validation.py
│       ├── test_canonical_external_events.py
│       ├── test_crud.py
│       ├── test_database_validation.py
│       ├── test_decision_governance_api.py
│       ├── test_ingestion_foundation.py
│       ├── test_ingestion_reliability_observability.py
│       ├── test_inventory_api.py
│       ├── test_karrio_integration.py
│       ├── test_logistics_api.py
│       ├── test_main.py
│       ├── test_models.py
│       ├── test_opensky_integration.py
│       ├── test_openweather_integration.py
│       ├── test_phase10_step1_bedrock_foundation.py
│       ├── test_phase10_step2_claude_invocation.py
│       ├── test_phase10_step3_research_agent_claude.py
│       ├── test_phase10_step4_risk_explanation_claude.py
│       ├── test_phase10_step5_scenario_explanation_claude.py
│       ├── test_phase10_step6_prediction_explanation_claude.py
│       ├── test_phase10_step7_decision_explanation_claude.py
│       ├── test_phase10_step7_scenario_explanation_claude.py
│       ├── test_phase11_ml_artifacts.py
│       ├── test_phase11_ml_contracts.py
│       ├── test_phase11_ml_critical.py
│       ├── test_phase11_ml_dataset.py
│       ├── test_phase11_ml_edge_cases.py
│       ├── test_phase11_ml_features.py
│       ├── test_phase11_ml_inference.py
│       ├── test_phase11_ml_leakage.py
│       ├── test_phase11_ml_observability_pipeline.py
│       ├── test_phase11_ml_registry.py
│       ├── test_phase11_ml_security.py
│       ├── test_phase11_ml_training.py
│       ├── test_phase12_digital_twin.py
│       ├── test_phase12_twin_api.py
│       ├── test_phase12_twin_builder.py
│       ├── test_phase12_twin_contracts.py
│       ├── test_phase12_twin_critical.py
│       ├── test_phase12_twin_fingerprints.py
│       ├── test_phase12_twin_persistence.py
│       ├── test_phase12_twin_query.py
│       ├── test_phase12_twin_security.py
│       ├── test_phase12_twin_validation.py
│       ├── test_phase13_api.py
│       ├── test_phase13_contracts.py
│       ├── test_phase13_persistence.py
│       ├── test_phase13_simulation_engine.py
│       ├── test_phase4_final_validation.py
│       ├── test_phase5_final_validation.py
│       ├── test_phase6_entity_normalization.py
│       ├── test_phase6_finalization.py
│       ├── test_phase6_normalization_contract.py
│       ├── test_phase7_baseline_scoring.py
│       ├── test_phase7_final_validation.py
│       ├── test_phase7_risk_alerts_escalation.py
│       ├── test_phase7_risk_engine_contracts.py
│       ├── test_phase7_risk_evidence_assessment.py
│       ├── test_phase7_risk_history_trends.py
│       ├── test_phase7_risk_persistence_api.py
│       ├── test_phase7_risk_recommendation_foundation.py
│       ├── test_phase8_rag_context_assembly_grounding.py
│       ├── test_phase8_rag_contracts.py
│       ├── test_phase8_rag_embeddings_vector_storage.py
│       ├── test_phase8_rag_evidence_pipeline.py
│       ├── test_phase8_rag_ingestion_chunking.py
│       ├── test_phase8_rag_retrieval_similarity_search.py
│       ├── test_phase9_approval_agent.py
│       ├── test_phase9_decision_agent.py
│       ├── test_phase9_langgraph_agent_state_contract.py
│       ├── test_phase9_langgraph_architecture_contracts.py
│       ├── test_phase9_langgraph_node_edge_contracts.py
│       ├── test_phase9_prediction_agent.py
│       ├── test_phase9_research_agent.py
│       ├── test_phase9_risk_agent.py
│       ├── test_phase9_scenario_agent.py
│       ├── test_phase9_step10_observability_recovery.py
│       ├── test_phase9_step11_final_validation.py
│       ├── test_rail_integration.py
│       ├── test_risk_api.py
│       ├── test_schemas.py
│       ├── test_service_repository_foundations.py
│       ├── test_sessions_and_auth.py
│       ├── test_supplier_api.py
│       ├── test_tavily_integration.py
│       ├── test_tomtom_integration.py
│       └── unit/
│           └── .gitkeep
├── credentials.json
├── docs/
│   ├── DESIGN.md
│   ├── RiskWise_2.0_Technical_Project_Spec.md
│   ├── RiskWise_2.0_UI_UX_Design_System.md
│   ├── authentication-architecture.md
│   ├── core-api-contract.md
│   ├── core-api-service-repository-architecture.md
│   ├── database-final-validation.md
│   ├── database-schema-inventory.md
│   ├── decision-governance-api-implementation.md
│   ├── google-authentication-architecture.md
│   ├── google-authentication-final-validation.md
│   ├── inventory-api-implementation.md
│   ├── logistics-api-implementation.md
│   ├── phase10-bedrock-claude.md
│   ├── phase10-bedrock-foundation.md
│   ├── phase10-prediction-claude.md
│   ├── phase10-prompt-invocation-layer.md
│   ├── phase10-research-agent-claude.md
│   ├── phase10-risk-agent-claude.md
│   ├── phase10-scenario-claude.md
│   ├── phase10-step7-scenario-explanation.md
│   ├── phase11-ml.md
│   ├── phase12-digital-twin.md
│   ├── phase13-simulation.md
│   ├── phase4-core-api-final-validation.md
│   ├── phase5-aisstream-integration.md
│   ├── phase5-canonical-event-model.md
│   ├── phase5-ingestion-foundation.md
│   ├── phase5-news-research-integration.md
│   ├── phase5-opensky-integration.md
│   ├── phase5-openweather-integration.md
│   ├── phase5-rail-data-integration.md
│   ├── phase5-reliability-observability.md
│   ├── phase5-tomtom-traffic-integration.md
│   ├── phase5-tracking-logistics-integration.md
│   ├── phase6-entity-normalization.md
│   ├── phase6-normalization-architecture.md
│   ├── phase6-normalization-finalization.md
│   ├── phase7-baseline-risk-scoring.md
│   ├── phase7-final-validation-hardening.md
│   ├── phase7-risk-alerts-escalation.md
│   ├── phase7-risk-engine-architecture.md
│   ├── phase7-risk-evidence-assessment.md
│   ├── phase7-risk-history-trends.md
│   ├── phase7-risk-persistence-api-integration.md
│   ├── phase7-risk-recommendation-foundation.md
│   ├── phase8-rag-architecture-contracts.md
│   ├── phase8-rag-context-assembly-grounding.md
│   ├── phase8-rag-document-ingestion-chunking.md
│   ├── phase8-rag-embedding-vector-storage.md
│   ├── phase8-rag-evidence-pipeline-hardening.md
│   ├── phase8-rag-retrieval-similarity-search.md
│   ├── phase9-decision-flow.md
│   ├── phase9-final-validation-hardening.md
│   ├── phase9-human-approval.md
│   ├── phase9-langgraph-agent-state-contract.md
│   ├── phase9-langgraph-architecture-contracts.md
│   ├── phase9-langgraph-node-edge-contracts.md
│   ├── phase9-observability-recovery.md
│   ├── phase9-prediction-agent.md
│   ├── phase9-research-agent.md
│   ├── phase9-risk-agent.md
│   ├── phase9-scenario-agent.md
│   ├── risk-api-implementation.md
│   └── supplier-api-implementation.md
├── folder.md
├── risk-wise.pem
├── storage/
│   └── ml_artifacts/
│       ├── delay_baseline_v1.joblib
│       ├── delay_custom_v1.joblib
│       ├── repro_m.joblib
│       ├── retrain_m1.joblib
│       ├── retrain_m2.joblib
│       └── shipment_delay_ridge_1.0.0_org_acme.joblib
├── tools_fix_folder.py
└── web/
    ├── AGENTS.md
    ├── CLAUDE.md
    ├── app/
    │   ├── auth/
    │   │   └── page.tsx
    │   ├── favicon.ico
    │   ├── globals.css
    │   ├── layout.tsx
    │   └── page.tsx
    ├── components/
    │   └── auth/
    │       ├── AuthCard.tsx
    │       ├── AuthErrorBanner.tsx
    │       ├── AuthModeSwitch.tsx
    │       ├── AuthSecurityNotice.tsx
    │       ├── GoogleAuthButton.tsx
    │       ├── ProtectedRoute.tsx
    │       └── RiskWiseLogo.tsx
    ├── eslint.config.mjs
    ├── lib/
    │   ├── api/
    │   │   └── client.ts
    │   └── auth/
    │       ├── AuthContext.tsx
    │       └── types.ts
    ├── next-env.d.ts
    ├── next.config.ts
    ├── package-lock.json
    ├── package.json
    ├── postcss.config.mjs
    ├── public/
    │   ├── file.svg
    │   ├── globe.svg
    │   ├── next.svg
    │   ├── vercel.svg
    │   └── window.svg
    ├── tests/
    │   └── auth-integration.test.ts
    ├── tsconfig.json
    └── tsconfig.tsbuildinfo
```

---

## 🏛️ Deep-Dive Architecture Breakdown

### 1. `api/` — Backend API & Intelligence Engine

The backend is built with **FastAPI** using a modular Clean / Hexagonal Architecture separating schemas, models, repositories, and business services:

- **`alembic/`**: Database schema migration scripts and revisions managed via SQLAlchemy (`env.py`, `script.py.mako`, `versions/`).
- **`app/agents/`**: Autonomous multi-agent network orchestrated via LangGraph:
  - `approval/`: Human-in-the-loop workflows, governance, escalation approval matrices.
  - `decision/`: Automated risk-mitigation decision formulation and prioritization.
  - `prediction/`: Disruption predictions, delay forecasting, and anomaly detection.
  - `research/`: Intelligence gathering from news, maritime, aviation, and weather APIs.
  - `risk/`: Multi-dimensional risk analysis (financial, operational, geopolitical, environmental).
  - `scenario/`: Stress-testing and 'what-if' simulation agent graphs.
- **`app/api/`**: HTTP layer:
  - `v1/endpoints/`: Modular REST endpoints for authentication, suppliers, logistics, risks, inventory, decisions, agents, digital twin, and simulation.
- **`app/core/`**: Application configuration (Pydantic Settings), JWT authentication, security utilities, and logging.
- **`app/db/`**: Database connection sessions, SQLAlchemy async engine, base declarative model.
- **`app/digital_twin/`**: Digital twin engine modeling physical supply chain entities (factories, ports, transit routes, inventory nodes) as an active graph (Phase 12).
- **`app/simulation/`**: Bounded what-if scenario simulation engine computing graph disruption propagation, scenario cascades, recovery metrics, and deterministic SHA-256 fingerprints (Phase 13).
- **`app/integrations/`**: Third-party external data ingestion adapters:
  - Telemetry: AISStream (vessels), OpenSky (air freight), TomTom (road traffic), OpenWeather (severe weather alerts), Karrio (multi-carrier freight tracking), Rail.
- **`app/llm/`**: Large language model integration layer supporting AWS Bedrock (Claude 3.5 Sonnet) with prompt versioning and structured output parsing.
- **`app/ml/`**: Machine learning sub-framework:
  - `datasets/`: Dataset definitions and feature extractors.
  - `features/`: Feature store calculations and real-time transformations.
  - `inference/`: Prediction pipelines and low-latency inference services.
  - `models/`: Trained model definitions (XGBoost, Random Forest, Ridge).
  - `registry/`: Model versioning and checkpoint management.
  - `training/`: Training harnesses and evaluation pipelines.
- **`app/models/`**: SQLAlchemy ORM models representing entities (Users, Suppliers, Shipments, Nodes, Risks, Audits, Policies, Scenarios).
- **`app/normalization/`**: Entity resolution, coordinate mapping, supplier deduplication, and raw event normalization.
- **`app/rag/`**: Retrieval-Augmented Generation subsystem:
  - Vector embeddings, document chunking, context assembly, grounding evidence, and hybrid search.
- **`app/repositories/`**: Repository layer abstracting database queries away from services.
- **`app/risk_engine/`**: Real-time risk evaluation engine calculating composite multi-factor risk scores and dispatching alerts.
- **`app/schemas/`**: Pydantic v2 schemas validating request/response bodies and internal contracts.
- **`app/services/`**: Core business domain services binding repositories, external integrations, and agent workflows.
- **`tests/`**: Comprehensive test suite covering units, schemas, services, API endpoints, authentication, digital twin (Phase 12), and simulation (Phase 13).

### 2. `web/` — Frontend Web Application

The frontend is a modern web application built on **Next.js 15 (App Router)** and **React 19**:

- **`app/`**: Next.js App Router root:
  - Route groups and pages for the supply chain dashboard, shipment tracking, risk monitor, agent command center, digital twin, and simulation view.
  - Global styles (`globals.css`) and root layouts.
- **`components/`**: Reusable UI components:
  - Interactive risk cards, heatmaps, agent conversation streams, geospatial charts, modals, and telemetry graphs.
- **`lib/`**: Frontend utility functions, API clients, React hooks, state management, and constant definitions.
- **`public/`**: Static assets, SVG icons, brand graphics, and logos.
- **`tests/`**: Frontend component and integration tests.

### 3. `docs/` — Project Architecture & Specifications

Extensive engineering documentation detailing the multi-phase implementation roadmap:

- **Core Architecture:** `RiskWise_2.0_Technical_Project_Spec.md`, `DESIGN.md`, `RiskWise_2.0_UI_UX_Design_System.md`.
- **API & Database Contracts:** `core-api-contract.md`, `core-api-service-repository-architecture.md`, `database-schema-inventory.md`.
- **Phase Implementation Guides:**
  - **Phase 4:** Core API final validation & hardening.
  - **Phase 5:** External data ingestion (AISStream, OpenSky, OpenWeather, TomTom, Freight).
  - **Phase 6:** Entity resolution, normalization architecture & contracts.
  - **Phase 7:** Baseline risk scoring, escalation engine, history trends, and alerts.
  - **Phase 8:** RAG architecture, vector storage, context assembly, and document chunking.
  - **Phase 9:** LangGraph multi-agent decision flow, human approval, state contracts, and recovery.
  - **Phase 10:** AWS Bedrock & Claude 3.5 Sonnet foundation, prompt invocation, and agent reasoning.
  - **Phase 11:** Machine learning models, training, and inference.
  - **Phase 12:** Supply chain Digital Twin simulation and network modeling.
  - **Phase 13:** Bounded what-if Simulation Engine, disruption cascade propagation, and scenario analysis.

### 4. `.agents/` — Agent Customizations & Skills

Workspace-specific AI agent extensions and design system toolkits:

- **`skills/banner-design/`**: Creative banner and social asset generator.
- **`skills/brand/`**: Corporate identity, messaging framework, and voice guidelines.
- **`skills/design/`**: Comprehensive design tokens, CIP mockups, and logo specifications.
- **`skills/design-system/`**: Multi-tier design token architecture and styling tokens.
- **`skills/slides/`**: HTML presentation and pitch deck builders.
- **`skills/ui-styling/`**: Radix UI + Tailwind CSS component patterns.
- **`skills/ui-ux-pro-max/`**: Extensive UI/UX catalogs, palettes, font pairings, and stack-specific rules.

### 5. Root Configuration & Storage

- **`storage/`**: Local cache and persistence for trained ML models (`ml_artifacts/*.joblib`).
- **Root configs:** `.env`, `.env.example`, `.gitignore`, `AGENTS.md`, `CLAUDE.md`, `credentials.json`, `folder.md`, `README.md`, `risk-wise.pem`.

---

*(Autogenerated authoritative project structure)*
