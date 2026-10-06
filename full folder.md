# RiskWise / ChainSentinel — Complete Repository Folder Structure

> This document provides the complete, authoritative directory and file structure of the **RiskWise / ChainSentinel** platform.

## 1. High-Level Architectural Layout

```text
riskwise/
├── api/                # FastAPI backend, multi-agent orchestration, ML, simulation, optimization
├── web/                # Next.js 16 App Router executive dashboard, live map, control tower
├── infra/              # Terraform AWS deployment (RDS PostgreSQL, Valkey, VPC)
├── storage/            # Serialized ML models, RAG vector embeddings, local data
├── docs/               # Platform architecture, testing, API documentation
├── .agents/            # Antigravity IDE agent skills and workflows
└── [Root Configs]      # Environment templates, markdown guides, audit reports
```

## 2. Root Directory Files

```text
├── .env
├── .env.example
├── .gitignore
├── AGENTS.md
├── IMPLEMENTATION-REPORT.md
├── README.md
├── REMAINING-TASKS.md
├── credentials copy.json
├── credentials.json
├── full folder.md
├── risk-wise.pem
├── riskwise_local.db
```

## 3. Backend (`api/`) Structure

The `api/` directory houses the complete Python backend built on FastAPI, SQLAlchemy 2.0, Alembic, LangGraph, Google OR-Tools, Scikit-learn, and the official Google Gemini SDK.

```text
api/
├── alembic/
│   ├── versions/
│   │   ├── .gitkeep
│   │   ├── d11e5e8a65df_initial_schema.py
│   │   └── e22f6f9b76ea_add_signals_table.py
│   ├── env.py
│   └── script.py.mako
├── app/
│   ├── agents/
│   │   ├── action/
│   │   │   ├── __init__.py
│   │   │   ├── agent.py
│   │   │   ├── contract.py
│   │   │   ├── errors.py
│   │   │   ├── executors.py
│   │   │   ├── node.py
│   │   │   ├── persistence.py
│   │   │   └── policy.py
│   │   ├── approval/
│   │   │   ├── __init__.py
│   │   │   ├── agent.py
│   │   │   ├── contract.py
│   │   │   ├── errors.py
│   │   │   ├── node.py
│   │   │   ├── persistence.py
│   │   │   └── service.py
│   │   ├── decision/
│   │   │   ├── __init__.py
│   │   │   ├── agent.py
│   │   │   ├── claude_contract.py
│   │   │   ├── claude_service.py
│   │   │   ├── contract.py
│   │   │   ├── decision_contract.py
│   │   │   ├── decision_explanation_service.py
│   │   │   ├── errors.py
│   │   │   ├── node.py
│   │   │   ├── persistence.py
│   │   │   ├── policy.py
│   │   │   └── rules.py
│   │   ├── optimization/
│   │   │   ├── __init__.py
│   │   │   └── node.py
│   │   ├── prediction/
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py
│   │   │   ├── agent.py
│   │   │   ├── claude_contract.py
│   │   │   ├── claude_service.py
│   │   │   ├── contract.py
│   │   │   ├── errors.py
│   │   │   ├── node.py
│   │   │   ├── prediction_contract.py
│   │   │   ├── prediction_explanation_service.py
│   │   │   └── service.py
│   │   ├── research/
│   │   │   ├── __init__.py
│   │   │   ├── agent.py
│   │   │   ├── analysis.py
│   │   │   ├── claude_contract.py
│   │   │   ├── claude_service.py
│   │   │   ├── contract.py
│   │   │   ├── errors.py
│   │   │   ├── evidence.py
│   │   │   ├── node.py
│   │   │   ├── research_contract.py
│   │   │   └── research_service.py
│   │   ├── risk/
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py
│   │   │   ├── agent.py
│   │   │   ├── claude_contract.py
│   │   │   ├── claude_service.py
│   │   │   ├── contract.py
│   │   │   ├── errors.py
│   │   │   └── node.py
│   │   ├── scenario/
│   │   │   ├── __init__.py
│   │   │   ├── agent.py
│   │   │   ├── claude_contract.py
│   │   │   ├── claude_service.py
│   │   │   ├── contract.py
│   │   │   ├── errors.py
│   │   │   ├── generator.py
│   │   │   └── node.py
│   │   ├── simulation/
│   │   │   ├── __init__.py
│   │   │   └── node.py
│   │   ├── verification/
│   │   │   ├── __init__.py
│   │   │   ├── agent.py
│   │   │   ├── contract.py
│   │   │   ├── errors.py
│   │   │   ├── evidence.py
│   │   │   ├── node.py
│   │   │   ├── persistence.py
│   │   │   ├── policy.py
│   │   │   └── verifiers.py
│   │   ├── __init__.py
│   │   ├── checkpointer.py
│   │   ├── contracts.py
│   │   ├── edges.py
│   │   ├── errors.py
│   │   ├── execution.py
│   │   ├── graph.py
│   │   ├── nodes.py
│   │   ├── observability.py
│   │   ├── recovery.py
│   │   ├── registry.py
│   │   ├── routing.py
│   │   ├── security.py
│   │   └── validator.py
│   ├── api/
│   │   ├── v1/
│   │   │   ├── endpoints/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── actions.py
│   │   │   │   ├── agents.py
│   │   │   │   ├── approvals.py
│   │   │   │   ├── audit_logs.py
│   │   │   │   ├── auth.py
│   │   │   │   ├── carriers.py
│   │   │   │   ├── decisions.py
│   │   │   │   ├── digital_twin.py
│   │   │   │   ├── evaluations.py
│   │   │   │   ├── factories.py
│   │   │   │   ├── health.py
│   │   │   │   ├── incidents.py
│   │   │   │   ├── inventory.py
│   │   │   │   ├── inventory_movements.py
│   │   │   │   ├── map.py
│   │   │   │   ├── notifications.py
│   │   │   │   ├── optimization.py
│   │   │   │   ├── ports.py
│   │   │   │   ├── products.py
│   │   │   │   ├── recommendations.py
│   │   │   │   ├── risk_assessments.py
│   │   │   │   ├── risk_factors.py
│   │   │   │   ├── risks.py
│   │   │   │   ├── routes.py
│   │   │   │   ├── shipment_events.py
│   │   │   │   ├── shipments.py
│   │   │   │   ├── signals.py
│   │   │   │   ├── simulation.py
│   │   │   │   ├── supplier_sites.py
│   │   │   │   ├── suppliers.py
│   │   │   │   ├── verification_results.py
│   │   │   │   └── warehouses.py
│   │   │   ├── __init__.py
│   │   │   └── router.py
│   │   ├── __init__.py
│   │   └── deps.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── context.py
│   │   ├── database.py
│   │   ├── encryption.py
│   │   ├── errors.py
│   │   ├── logging.py
│   │   ├── rate_limit.py
│   │   └── telemetry.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── session.py
│   │   └── unit_of_work.py
│   ├── digital_twin/
│   │   ├── __init__.py
│   │   ├── builder.py
│   │   ├── contracts.py
│   │   ├── errors.py
│   │   ├── fingerprints.py
│   │   ├── observability.py
│   │   ├── query.py
│   │   ├── repository.py
│   │   ├── service.py
│   │   └── validator.py
│   ├── evaluation/
│   │   ├── datasets/
│   │   │   ├── golden/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── action_cases.py
│   │   │   │   ├── agent_cases.py
│   │   │   │   ├── approval_cases.py
│   │   │   │   ├── claude_cases.py
│   │   │   │   ├── decision_cases.py
│   │   │   │   ├── digital_twin_cases.py
│   │   │   │   ├── e2e_cases.py
│   │   │   │   ├── ml_cases.py
│   │   │   │   ├── optimization_cases.py
│   │   │   │   ├── rag_cases.py
│   │   │   │   ├── research_cases.py
│   │   │   │   ├── risk_cases.py
│   │   │   │   ├── security_cases.py
│   │   │   │   ├── simulation_cases.py
│   │   │   │   └── verification_cases.py
│   │   │   ├── __init__.py
│   │   │   ├── contracts.py
│   │   │   └── registry.py
│   │   ├── suites/
│   │   │   ├── __init__.py
│   │   │   ├── action_suite.py
│   │   │   ├── agent_suite.py
│   │   │   ├── approval_suite.py
│   │   │   ├── base.py
│   │   │   ├── claude_suite.py
│   │   │   ├── decision_suite.py
│   │   │   ├── digital_twin_suite.py
│   │   │   ├── e2e_suite.py
│   │   │   ├── ml_suite.py
│   │   │   ├── optimization_suite.py
│   │   │   ├── rag_suite.py
│   │   │   ├── research_suite.py
│   │   │   ├── risk_suite.py
│   │   │   ├── security_suite.py
│   │   │   ├── simulation_suite.py
│   │   │   └── verification_suite.py
│   │   ├── __init__.py
│   │   ├── contracts.py
│   │   ├── errors.py
│   │   ├── metrics.py
│   │   └── runner.py
│   ├── integrations/
│   │   ├── providers/
│   │   │   ├── __init__.py
│   │   │   ├── aisstream.py
│   │   │   ├── karrio.py
│   │   │   ├── opensky.py
│   │   │   ├── openweather.py
│   │   │   ├── rail.py
│   │   │   ├── tavily.py
│   │   │   └── tomtom.py
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── boundaries.py
│   │   ├── canonical.py
│   │   ├── circuit_breaker.py
│   │   ├── config.py
│   │   ├── errors.py
│   │   ├── idempotency.py
│   │   ├── normalizers.py
│   │   ├── observability.py
│   │   ├── rate_limiter.py
│   │   ├── registry.py
│   │   ├── retry.py
│   │   ├── service.py
│   │   └── worker.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── bedrock.py
│   │   ├── contracts.py
│   │   ├── errors.py
│   │   ├── factory.py
│   │   ├── gemini.py
│   │   ├── invocation.py
│   │   ├── mock.py
│   │   ├── observability.py
│   │   ├── prompts.py
│   │   ├── retry.py
│   │   └── security.py
│   ├── ml/
│   │   ├── datasets/
│   │   │   ├── __init__.py
│   │   │   ├── builder.py
│   │   │   ├── contracts.py
│   │   │   └── validation.py
│   │   ├── features/
│   │   │   ├── __init__.py
│   │   │   ├── contracts.py
│   │   │   └── shipment_delay.py
│   │   ├── inference/
│   │   │   ├── __init__.py
│   │   │   └── service.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   └── shipment_delay.py
│   │   ├── registry/
│   │   │   ├── __init__.py
│   │   │   └── registry.py
│   │   ├── training/
│   │   │   ├── __init__.py
│   │   │   ├── artifacts.py
│   │   │   ├── pipeline.py
│   │   │   └── validation.py
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── contracts.py
│   │   ├── errors.py
│   │   └── observability.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── agents.py
│   │   ├── digital_twin.py
│   │   ├── evaluation.py
│   │   ├── governance.py
│   │   ├── knowledge.py
│   │   ├── logistics.py
│   │   ├── network.py
│   │   ├── risk.py
│   │   ├── simulation.py
│   │   └── tenancy.py
│   ├── normalization/
│   │   ├── __init__.py
│   │   ├── contract.py
│   │   ├── correlation.py
│   │   ├── entity_resolver.py
│   │   ├── handlers.py
│   │   ├── identifiers.py
│   │   ├── pipeline.py
│   │   ├── quality.py
│   │   ├── status.py
│   │   └── units.py
│   ├── optimization/
│   │   ├── __init__.py
│   │   ├── candidates.py
│   │   ├── config.py
│   │   ├── constraints.py
│   │   ├── contracts.py
│   │   ├── errors.py
│   │   ├── fingerprints.py
│   │   ├── integration.py
│   │   ├── model.py
│   │   ├── objectives.py
│   │   ├── persistence.py
│   │   ├── result.py
│   │   ├── service.py
│   │   ├── solver.py
│   │   ├── validators.py
│   │   └── variables.py
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── chunking.py
│   │   ├── contracts.py
│   │   ├── embeddings.py
│   │   ├── errors.py
│   │   ├── grounding.py
│   │   ├── ingestion.py
│   │   ├── parsers.py
│   │   ├── pipeline.py
│   │   ├── retrieval.py
│   │   └── vector_store.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── audit_log.py
│   │   ├── base.py
│   │   ├── governance_repositories.py
│   │   ├── inventory.py
│   │   ├── network_repositories.py
│   │   ├── port.py
│   │   ├── query_utils.py
│   │   ├── risk_repositories.py
│   │   ├── shipment.py
│   │   ├── signal_repository.py
│   │   └── supplier.py
│   ├── risk_engine/
│   │   ├── __init__.py
│   │   ├── alerts.py
│   │   ├── context.py
│   │   ├── contract.py
│   │   ├── errors.py
│   │   ├── evaluators.py
│   │   ├── evidence.py
│   │   ├── explainability.py
│   │   ├── history.py
│   │   ├── persistence.py
│   │   ├── pipeline.py
│   │   ├── recommendations.py
│   │   ├── registry.py
│   │   └── scoring.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── agents.py
│   │   ├── auth.py
│   │   ├── common.py
│   │   ├── digital_twin.py
│   │   ├── governance.py
│   │   ├── health.py
│   │   ├── knowledge.py
│   │   ├── logistics.py
│   │   ├── network.py
│   │   ├── risk.py
│   │   ├── session.py
│   │   ├── signal.py
│   │   ├── simulation.py
│   │   └── tenancy.py
│   ├── services/
│   │   ├── tracking/
│   │   │   ├── __init__.py
│   │   │   ├── aggregator.py
│   │   │   ├── aircraft_provider.py
│   │   │   ├── aisstream_provider.py
│   │   │   ├── base.py
│   │   │   ├── internal_provider.py
│   │   │   ├── mobility_provider.py
│   │   │   ├── models.py
│   │   │   ├── project44_provider.py
│   │   │   ├── tomtom_provider.py
│   │   │   └── weather_provider.py
│   │   ├── __init__.py
│   │   ├── audit_service.py
│   │   ├── base.py
│   │   ├── concurrency.py
│   │   ├── governance_services.py
│   │   ├── inventory_services.py
│   │   ├── logistics_services.py
│   │   ├── oauth_service.py
│   │   ├── risk_evaluation_service.py
│   │   ├── risk_services.py
│   │   ├── session_service.py
│   │   └── supplier.py
│   ├── simulation/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── contracts.py
│   │   ├── effects.py
│   │   ├── engine.py
│   │   ├── errors.py
│   │   ├── fingerprints.py
│   │   ├── integration.py
│   │   ├── metrics.py
│   │   ├── observability.py
│   │   ├── persistence.py
│   │   ├── propagation.py
│   │   ├── repository.py
│   │   ├── scenario.py
│   │   ├── scenarios.py
│   │   ├── service.py
│   │   ├── state.py
│   │   ├── validation.py
│   │   └── validators.py
│   ├── __init__.py
│   └── main.py
├── scripts/
│   ├── audit_e2e_workflow.py
│   ├── test_pg_application.py
│   ├── verify_pg_enums.py
│   ├── verify_pg_fks.py
│   ├── verify_pg_indexes.py
│   ├── verify_pg_migration.py
│   └── verify_real_langgraph_execution.py
├── storage/
│   └── ml_artifacts/
│       ├── delay_baseline_v1.joblib
│       ├── delay_custom_v1.joblib
│       ├── repro_m.joblib
│       ├── retrain_m1.joblib
│       ├── retrain_m2.joblib
│       └── shipment_delay_ridge_1.0.0_org_acme.joblib
├── tests/
│   ├── integration/
│   │   └── .gitkeep
│   ├── unit/
│   │   └── .gitkeep
│   ├── __init__.py
│   ├── test_aisstream_integration.py
│   ├── test_auth_config.py
│   ├── test_auth_final_validation.py
│   ├── test_canonical_external_events.py
│   ├── test_crud.py
│   ├── test_database_validation.py
│   ├── test_decision_governance_api.py
│   ├── test_e2e_autonomous_pipeline.py
│   ├── test_e2e_closed_loop.py
│   ├── test_gemini_provider.py
│   ├── test_ingestion_foundation.py
│   ├── test_ingestion_reliability_observability.py
│   ├── test_inventory_api.py
│   ├── test_karrio_integration.py
│   ├── test_live_map_tracking.py
│   ├── test_logistics_api.py
│   ├── test_main.py
│   ├── test_models.py
│   ├── test_opensky_integration.py
│   ├── test_openweather_integration.py
│   ├── test_phase11_ml_artifacts.py
│   ├── test_phase11_ml_contracts.py
│   ├── test_phase11_ml_critical.py
│   ├── test_phase11_ml_dataset.py
│   ├── test_phase11_ml_edge_cases.py
│   ├── test_phase11_ml_features.py
│   ├── test_phase11_ml_inference.py
│   ├── test_phase11_ml_leakage.py
│   ├── test_phase11_ml_observability_pipeline.py
│   ├── test_phase11_ml_registry.py
│   ├── test_phase11_ml_security.py
│   ├── test_phase11_ml_training.py
│   ├── test_phase12_digital_twin.py
│   ├── test_phase12_twin_api.py
│   ├── test_phase12_twin_builder.py
│   ├── test_phase12_twin_contracts.py
│   ├── test_phase12_twin_critical.py
│   ├── test_phase12_twin_fingerprints.py
│   ├── test_phase12_twin_persistence.py
│   ├── test_phase12_twin_query.py
│   ├── test_phase12_twin_security.py
│   ├── test_phase12_twin_validation.py
│   ├── test_phase13_api.py
│   ├── test_phase13_comprehensive_validation.py
│   ├── test_phase13_contracts.py
│   ├── test_phase13_contracts_extended.py
│   ├── test_phase13_integrations.py
│   ├── test_phase13_persistence.py
│   ├── test_phase13_simulation_engine.py
│   ├── test_phase14_contracts.py
│   ├── test_phase14_domains.py
│   ├── test_phase14_extended.py
│   ├── test_phase14_integrations.py
│   ├── test_phase14_persistence_api.py
│   ├── test_phase14_security_adversarial.py
│   ├── test_phase14_solver.py
│   ├── test_phase15_agent.py
│   ├── test_phase15_claude.py
│   ├── test_phase15_contracts.py
│   ├── test_phase15_integration.py
│   ├── test_phase15_persistence_api.py
│   ├── test_phase15_policy.py
│   ├── test_phase15_security_adversarial.py
│   ├── test_phase16_contracts.py
│   ├── test_phase16_integration.py
│   ├── test_phase16_persistence_api.py
│   ├── test_phase16_security_rbac.py
│   ├── test_phase17_approval_enforcement.py
│   ├── test_phase17_contracts.py
│   ├── test_phase17_executors_idempotency.py
│   ├── test_phase17_integration.py
│   ├── test_phase17_persistence_api.py
│   ├── test_phase17_security_adversarial.py
│   ├── test_phase18_contracts.py
│   ├── test_phase18_evidence.py
│   ├── test_phase18_langgraph_claude.py
│   ├── test_phase18_persistence_api.py
│   ├── test_phase18_security.py
│   ├── test_phase18_verifiers.py
│   ├── test_phase20_contracts.py
│   ├── test_phase20_datasets.py
│   ├── test_phase20_metrics.py
│   ├── test_phase20_runner_persistence_api.py
│   ├── test_phase20_suites_agent.py
│   ├── test_phase20_suites_domain.py
│   ├── test_phase20_suites_governance_e2e.py
│   ├── test_phase21_production_hardening.py
│   ├── test_phase6_entity_normalization.py
│   ├── test_phase6_normalization_contract.py
│   ├── test_phase7_baseline_scoring.py
│   ├── test_phase7_risk_alerts_escalation.py
│   ├── test_phase7_risk_engine_contracts.py
│   ├── test_phase7_risk_evidence_assessment.py
│   ├── test_phase7_risk_history_trends.py
│   ├── test_phase7_risk_persistence_api.py
│   ├── test_phase7_risk_recommendation_foundation.py
│   ├── test_phase8_rag_context_assembly_grounding.py
│   ├── test_phase8_rag_contracts.py
│   ├── test_phase8_rag_embeddings_vector_storage.py
│   ├── test_phase8_rag_evidence_pipeline.py
│   ├── test_phase8_rag_ingestion_chunking.py
│   ├── test_phase8_rag_retrieval_similarity_search.py
│   ├── test_phase9_approval_agent.py
│   ├── test_phase9_decision_agent.py
│   ├── test_phase9_langgraph_agent_state_contract.py
│   ├── test_phase9_langgraph_architecture_contracts.py
│   ├── test_phase9_langgraph_node_edge_contracts.py
│   ├── test_phase9_prediction_agent.py
│   ├── test_phase9_research_agent.py
│   ├── test_phase9_risk_agent.py
│   ├── test_phase9_scenario_agent.py
│   ├── test_phase9_step10_observability_recovery.py
│   ├── test_rail_integration.py
│   ├── test_risk_api.py
│   ├── test_schemas.py
│   ├── test_service_repository_foundations.py
│   ├── test_sessions_and_auth.py
│   ├── test_supplier_api.py
│   ├── test_tavily_integration.py
│   └── test_tomtom_integration.py
├── .dockerignore
├── .env
├── .env.example
├── Dockerfile
├── alembic.ini
├── pyproject.toml
├── requirements.txt
└── riskwise_local.db
```

## 4. Frontend (`web/`) Structure

The `web/` directory contains the modern Next.js 16 App Router application styled with Tailwind / CSS, Lucide icons, Vitest test suites, and client-side geospatial map integration.

```text
web/
├── app/
│   ├── actions/
│   │   ├── [id]/
│   │   │   └── page.tsx
│   │   └── page.tsx
│   ├── admin/
│   │   └── page.tsx
│   ├── agent-runs/
│   │   ├── [id]/
│   │   │   └── page.tsx
│   │   └── page.tsx
│   ├── api/
│   │   └── health/
│   │       └── route.ts
│   ├── approvals/
│   │   └── page.tsx
│   ├── audit/
│   │   └── page.tsx
│   ├── audit-logs/
│   │   └── page.tsx
│   ├── auth/
│   │   └── page.tsx
│   ├── carriers/
│   │   └── page.tsx
│   ├── dashboard/
│   │   └── page.tsx
│   ├── decisions/
│   │   ├── [id]/
│   │   │   └── page.tsx
│   │   └── page.tsx
│   ├── digital-twin/
│   │   └── page.tsx
│   ├── evaluation/
│   │   └── page.tsx
│   ├── factories/
│   │   └── page.tsx
│   ├── incidents/
│   │   ├── [id]/
│   │   │   └── page.tsx
│   │   └── page.tsx
│   ├── inventory/
│   │   └── page.tsx
│   ├── map/
│   │   └── page.tsx
│   ├── notifications/
│   │   └── page.tsx
│   ├── optimization/
│   │   ├── [id]/
│   │   │   └── page.tsx
│   │   └── page.tsx
│   ├── overview/
│   │   └── page.tsx
│   ├── policy-inspector/
│   │   ├── [id]/
│   │   │   └── page.tsx
│   │   └── page.tsx
│   ├── ports/
│   │   └── page.tsx
│   ├── products/
│   │   └── page.tsx
│   ├── recommendations/
│   │   ├── [id]/
│   │   │   └── page.tsx
│   │   └── page.tsx
│   ├── risks/
│   │   ├── [id]/
│   │   │   └── page.tsx
│   │   └── page.tsx
│   ├── routes/
│   │   └── page.tsx
│   ├── settings/
│   │   └── page.tsx
│   ├── shipments/
│   │   ├── [id]/
│   │   │   └── page.tsx
│   │   └── page.tsx
│   ├── simulations/
│   │   ├── [id]/
│   │   │   └── page.tsx
│   │   └── page.tsx
│   ├── suppliers/
│   │   └── page.tsx
│   ├── system-health/
│   │   └── page.tsx
│   ├── verification/
│   │   ├── [id]/
│   │   │   └── page.tsx
│   │   └── page.tsx
│   ├── warehouses/
│   │   └── page.tsx
│   ├── favicon.ico
│   ├── globals.css
│   ├── layout.tsx
│   ├── not-found.tsx
│   └── page.tsx
├── components/
│   ├── auth/
│   │   ├── AuthCard.tsx
│   │   ├── AuthErrorBanner.tsx
│   │   ├── AuthModeSwitch.tsx
│   │   ├── AuthSecurityNotice.tsx
│   │   ├── GoogleAuthButton.tsx
│   │   ├── ProtectedRoute.tsx
│   │   └── RiskWiseLogo.tsx
│   ├── layout/
│   │   ├── AppShell.tsx
│   │   ├── GlobalSearchModal.tsx
│   │   ├── Sidebar.tsx
│   │   └── TopBar.tsx
│   ├── map/
│   │   └── MapCard.tsx
│   ├── ui/
│   │   ├── AceternityCard.tsx
│   │   ├── ArchitecturalComponents.tsx
│   │   ├── Badges.tsx
│   │   ├── DataTable.tsx
│   │   ├── FeedbackStates.tsx
│   │   ├── MagicComponents.tsx
│   │   ├── MetricCard.tsx
│   │   └── OperationalPipeline.tsx
│   └── visualization/
│       └── SecurityMachine3D.tsx
├── lib/
│   ├── api/
│   │   ├── client.ts
│   │   ├── index.ts
│   │   └── types.ts
│   ├── auth/
│   │   ├── AuthContext.tsx
│   │   └── types.ts
│   └── theme/
│       └── ThemeContext.tsx
├── public/
├── tests/
│   ├── auth-integration.test.ts
│   ├── frontend-backend-integration.test.ts
│   ├── live-map-contract.test.ts
│   └── phase19-control-tower.test.ts
├── .dockerignore
├── .env.example
├── .env.local
├── AGENTS.md
├── Dockerfile
├── eslint.config.mjs
├── next-env.d.ts
├── next.config.ts
├── package-lock.json
├── package.json
├── postcss.config.mjs
├── tsconfig.json
└── tsconfig.tsbuildinfo
```

## 5. Infrastructure (`infra/`) Structure

Terraform configuration for deploying production cloud components in AWS `ap-southeast-2`.

```text
infra/
└── terraform/
    ├── main.tf
    ├── outputs.tf
    └── variables.tf
```

## 6. Storage & Machine Learning Artifacts (`storage/`)

Pre-trained Scikit-learn Ridge regression models, vector embedding caches, and baseline datasets.

```text
storage/
└── ml_artifacts/
    ├── delay_baseline_v1.joblib
    ├── delay_custom_v1.joblib
    ├── repro_m.joblib
    ├── retrain_m1.joblib
    ├── retrain_m2.joblib
    └── shipment_delay_ridge_1.0.0_org_acme.joblib
```

## 7. Documentation (`docs/`)

Technical architectural guides and test reports.

```text
docs/
├── RiskWise_2.0_UI_UX_Design_System.md
├── architecture.md
├── deployment.md
├── development.md
├── security.md
└── testing.md
```

## 8. Agent Skills (`.agents/`)

Curated agent skills for design, brand, and automated development workflows.

```text
.agents/
└── skills/
    ├── banner-design/
    │   ├── references/
    │   │   └── banner-sizes-and-styles.md
    │   └── SKILL.md
    ├── brand/
    │   ├── references/
    │   │   ├── approval-checklist.md
    │   │   ├── asset-organization.md
    │   │   ├── brand-guideline-template.md
    │   │   ├── color-palette-management.md
    │   │   ├── consistency-checklist.md
    │   │   ├── logo-usage-rules.md
    │   │   ├── messaging-framework.md
    │   │   ├── typography-specifications.md
    │   │   ├── update.md
    │   │   ├── visual-identity.md
    │   │   └── voice-framework.md
    │   ├── scripts/
    │   │   ├── tests/
    │   │   │   └── test_sync_brand_to_tokens.py
    │   │   ├── extract-colors.cjs
    │   │   ├── inject-brand-context.cjs
    │   │   ├── sync-brand-to-tokens.cjs
    │   │   └── validate-asset.cjs
    │   ├── templates/
    │   │   └── brand-guidelines-starter.md
    │   └── SKILL.md
    ├── design/
    │   ├── data/
    │   │   ├── cip/
    │   │   │   ├── deliverables.csv
    │   │   │   ├── industries.csv
    │   │   │   ├── mockup-contexts.csv
    │   │   │   └── styles.csv
    │   │   ├── icon/
    │   │   │   └── styles.csv
    │   │   └── logo/
    │   │       ├── colors.csv
    │   │       ├── industries.csv
    │   │       └── styles.csv
    │   ├── references/
    │   │   ├── banner-sizes-and-styles.md
    │   │   ├── cip-deliverable-guide.md
    │   │   ├── cip-design.md
    │   │   ├── cip-prompt-engineering.md
    │   │   ├── cip-style-guide.md
    │   │   ├── design-routing.md
    │   │   ├── icon-design.md
    │   │   ├── logo-color-psychology.md
    │   │   ├── logo-design.md
    │   │   ├── logo-prompt-engineering.md
    │   │   ├── logo-style-guide.md
    │   │   ├── slides-copywriting-formulas.md
    │   │   ├── slides-create.md
    │   │   ├── slides-html-template.md
    │   │   ├── slides-layout-patterns.md
    │   │   ├── slides-strategies.md
    │   │   ├── slides.md
    │   │   └── social-photos-design.md
    │   ├── scripts/
    │   │   ├── cip/
    │   │   │   ├── core.py
    │   │   │   ├── generate.py
    │   │   │   ├── render-html.py
    │   │   │   └── search.py
    │   │   ├── icon/
    │   │   │   └── generate.py
    │   │   └── logo/
    │   │       ├── core.py
    │   │       ├── generate.py
    │   │       └── search.py
    │   └── SKILL.md
    ├── design-system/
    │   ├── data/
    │   │   ├── slide-backgrounds.csv
    │   │   ├── slide-charts.csv
    │   │   ├── slide-color-logic.csv
    │   │   ├── slide-copy.csv
    │   │   ├── slide-layout-logic.csv
    │   │   ├── slide-layouts.csv
    │   │   ├── slide-strategies.csv
    │   │   └── slide-typography.csv
    │   ├── references/
    │   │   ├── component-specs.md
    │   │   ├── component-tokens.md
    │   │   ├── primitive-tokens.md
    │   │   ├── semantic-tokens.md
    │   │   ├── states-and-variants.md
    │   │   ├── tailwind-integration.md
    │   │   └── token-architecture.md
    │   ├── scripts/
    │   │   ├── tests/
    │   │   │   └── test_validate_tokens.py
    │   │   ├── embed-tokens.cjs
    │   │   ├── fetch-background.py
    │   │   ├── generate-slide.py
    │   │   ├── generate-tokens.cjs
    │   │   ├── html-token-validator.py
    │   │   ├── search-slides.py
    │   │   ├── slide-token-validator.py
    │   │   ├── slide_search_core.py
    │   │   └── validate-tokens.cjs
    │   ├── templates/
    │   │   └── design-tokens-starter.json
    │   └── SKILL.md
    ├── design-taste-frontend/
    │   └── SKILL.md
    ├── no-slop-design/
    │   ├── .claude-plugin/
    │   │   ├── marketplace.json
    │   │   └── plugin.json
    │   ├── .github/
    │   │   └── workflows/
    │   │       └── ci.yml
    │   ├── docs/
    │   │   └── images/
    │   │       ├── banner-dark.png
    │   │       ├── banner-light.png
    │   │       ├── board-ten-industries.png
    │   │       ├── output-billing.png
    │   │       ├── output-ceramics.png
    │   │       ├── output-dance.png
    │   │       ├── output-devtool.png
    │   │       ├── output-festival.png
    │   │       ├── output-hotel.png
    │   │       ├── output-ios.png
    │   │       ├── output-law.png
    │   │       ├── output-ramen.png
    │   │       ├── output-restaurant.png
    │   │       ├── output-sahil.png
    │   │       └── output-tax.png
    │   ├── evals/
    │   │   ├── fixtures/
    │   │   │   ├── indigo-accent.json
    │   │   │   ├── ledger-site.html
    │   │   │   └── slop-sample.html
    │   │   ├── 01-new-saas-landing.md
    │   │   ├── 02-existing-system-feature.md
    │   │   ├── 03-ios-screen.md
    │   │   ├── 04-expressive-register.md
    │   │   ├── 05-signature-interaction.md
    │   │   ├── 06-design-language.md
    │   │   └── README.md
    │   ├── references/
    │   │   ├── accessibility.md
    │   │   ├── anti-slop.md
    │   │   ├── color.md
    │   │   ├── components.md
    │   │   ├── content-microcopy.md
    │   │   ├── design-language.md
    │   │   ├── design-tokens.md
    │   │   ├── discovery.md
    │   │   ├── existing-design-system.md
    │   │   ├── expression-register.md
    │   │   ├── handoff.md
    │   │   ├── inspiration-sources.md
    │   │   ├── interaction-depth.md
    │   │   ├── mini-user-research.md
    │   │   ├── mobile-android.md
    │   │   ├── mobile-ios.md
    │   │   ├── moodboard.md
    │   │   ├── motion.md
    │   │   ├── review-checklist.md
    │   │   ├── spacing-layout.md
    │   │   ├── typography.md
    │   │   ├── ux-patterns.md
    │   │   ├── visual-material.md
    │   │   └── web-frontend.md
    │   ├── scripts/
    │   │   ├── audit_repo.py
    │   │   ├── build_tokens.py
    │   │   ├── contrast.py
    │   │   ├── crit_board.py
    │   │   ├── design_log.py
    │   │   ├── selftest.py
    │   │   ├── shoot.py
    │   │   ├── slop_lint.py
    │   │   └── type_scale.py
    │   ├── templates/
    │   │   ├── tokens/
    │   │   │   ├── components.json
    │   │   │   ├── primitives.json
    │   │   │   ├── semantic.dark.json
    │   │   │   └── semantic.json
    │   │   ├── DESIGN.md
    │   │   ├── assets.md
    │   │   ├── component-spec.md
    │   │   ├── contrast-pairs.txt
    │   │   ├── design-brief.md
    │   │   ├── design-log.json
    │   │   ├── moodboard.html
    │   │   ├── research-synthesis.md
    │   │   └── review-report.md
    │   ├── .gitignore
    │   ├── CHANGELOG.md
    │   ├── CONTRIBUTING.md
    │   ├── LICENSE
    │   ├── README.md
    │   └── SKILL.md
    ├── slides/
    │   ├── references/
    │   │   ├── copywriting-formulas.md
    │   │   ├── create.md
    │   │   ├── html-template.md
    │   │   ├── layout-patterns.md
    │   │   └── slide-strategies.md
    │   └── SKILL.md
    ├── ui-styling/
    │   ├── references/
    │   │   ├── canvas-design-system.md
    │   │   ├── shadcn-accessibility.md
    │   │   ├── shadcn-components.md
    │   │   ├── shadcn-theming.md
    │   │   ├── tailwind-customization.md
    │   │   ├── tailwind-responsive.md
    │   │   └── tailwind-utilities.md
    │   ├── scripts/
    │   │   ├── tests/
    │   │   │   ├── coverage-ui.json
    │   │   │   ├── requirements.txt
    │   │   │   ├── test_shadcn_add.py
    │   │   │   └── test_tailwind_config_gen.py
    │   │   ├── requirements.txt
    │   │   ├── shadcn_add.py
    │   │   └── tailwind_config_gen.py
    │   ├── LICENSE.txt
    │   └── SKILL.md
    └── ui-ux-pro-max/
        ├── data/
        │   ├── stacks/
        │   │   ├── angular.csv
        │   │   ├── astro.csv
        │   │   ├── avalonia.csv
        │   │   ├── flutter.csv
        │   │   ├── html-tailwind.csv
        │   │   ├── javafx.csv
        │   │   ├── jetpack-compose.csv
        │   │   ├── laravel.csv
        │   │   ├── nextjs.csv
        │   │   ├── nuxt-ui.csv
        │   │   ├── nuxtjs.csv
        │   │   ├── react-native.csv
        │   │   ├── react.csv
        │   │   ├── shadcn.csv
        │   │   ├── svelte.csv
        │   │   ├── swiftui.csv
        │   │   ├── threejs.csv
        │   │   ├── uno.csv
        │   │   ├── uwp.csv
        │   │   ├── vue.csv
        │   │   ├── winui.csv
        │   │   └── wpf.csv
        │   ├── app-interface.csv
        │   ├── catalog-summary.json
        │   ├── charts.csv
        │   ├── colors.csv
        │   ├── data-provenance.json
        │   ├── google-font-licenses.json
        │   ├── google-fonts.csv
        │   ├── icons.csv
        │   ├── landing.csv
        │   ├── motion.csv
        │   ├── phosphor-icons-upstream.json
        │   ├── products.csv
        │   ├── react-performance.csv
        │   ├── styles.csv
        │   ├── typography.csv
        │   ├── ui-reasoning.csv
        │   └── ux-guidelines.csv
        ├── scripts/
        │   ├── tests/
        │   │   ├── fixtures/
        │   │   │   ├── catalogs/
        │   │   │   │   ├── google-api.json
        │   │   │   │   ├── google-catalog.json
        │   │   │   │   ├── google-existing.csv
        │   │   │   │   ├── google-metadata.json
        │   │   │   │   ├── google-overrides.json
        │   │   │   │   ├── icons-curated.csv
        │   │   │   │   ├── phosphor-core.json
        │   │   │   │   ├── phosphor-package.json
        │   │   │   │   ├── phosphor-react-exports.json
        │   │   │   │   └── phosphor-react-package.json
        │   │   │   ├── relevance-baseline.json
        │   │   │   ├── relevance-cases.json
        │   │   │   └── relevance-thresholds.json
        │   │   ├── test_catalog_refresh.py
        │   │   ├── test_core.py
        │   │   ├── test_core_data_quality.py
        │   │   ├── test_data_contracts.py
        │   │   ├── test_design_system_mode.py
        │   │   ├── test_native_desktop_stack_freshness.py
        │   │   ├── test_relevance_evaluator.py
        │   │   ├── test_style_taxonomy.py
        │   │   ├── test_text_layout_resilience.py
        │   │   └── test_web_stack_freshness.py
        │   ├── core.py
        │   ├── design_system.py
        │   ├── reasoning_contract.py
        │   ├── search.py
        │   └── validate_data.py
        └── SKILL.md
```

