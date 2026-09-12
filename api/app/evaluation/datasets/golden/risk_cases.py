"""Golden evaluation test cases for Phase 7 Deterministic Risk Engine (Phase 20)."""
from typing import List
from app.evaluation.contracts import DatasetCategory, EvaluationCase, EvaluationSuiteType


def get_risk_evaluation_cases() -> List[EvaluationCase]:
    """Return golden test cases with exact expected risk scores and factor contributions."""
    return [
        EvaluationCase(
            case_id="risk-case-001",
            suite_type=EvaluationSuiteType.RISK_EVALUATION,
            category=DatasetCategory.NORMAL,
            name="Critical Multi-Factor Disruption Scoring",
            description="Combined port closure, severe typhoon, and sole-source supplier outage yields Critical score >= 85.",
            input_data={
                "signals": [
                    {"type": "PORT_CLOSURE", "severity": "CRITICAL", "confidence": 0.95, "weight": 0.40, "score": 95.0},
                    {"type": "WEATHER_TYPHOON", "severity": "HIGH", "confidence": 0.90, "weight": 0.35, "score": 85.0},
                    {"type": "SOLE_SOURCE_SPOF", "severity": "HIGH", "confidence": 1.00, "weight": 0.25, "score": 90.0},
                ],
                "evidence_tier": "REAL",
            },
            expected_output={
                "expected_score": 90.25,
                "expected_severity": "CRITICAL",
                "evidence_precedence": "REAL",
                "deterministic_tolerance": 0.5,
            },
            version="1.0.0",
            tags=["risk_engine", "scoring", "critical"],
        ),
        EvaluationCase(
            case_id="risk-case-002",
            suite_type=EvaluationSuiteType.RISK_EVALUATION,
            category=DatasetCategory.NORMAL,
            name="Low Baseline Operational Drift",
            description="Minor customs clearance delay with low factor weight yields Low severity <= 25.",
            input_data={
                "signals": [
                    {"type": "CUSTOMS_DELAY_MINOR", "severity": "LOW", "confidence": 0.85, "weight": 1.0, "score": 18.0},
                ],
                "evidence_tier": "REAL",
            },
            expected_output={
                "expected_score": 18.0,
                "expected_severity": "LOW",
                "evidence_precedence": "REAL",
                "deterministic_tolerance": 0.1,
            },
            version="1.0.0",
            tags=["risk_engine", "scoring", "low"],
        ),
        EvaluationCase(
            case_id="risk-case-003",
            suite_type=EvaluationSuiteType.RISK_EVALUATION,
            category=DatasetCategory.CONFLICT,
            name="Evidence Precedence Hierarchy Conflict Resolution",
            description="REAL telemetry overrides conflicting SIMULATED signal according to REAL > ESTIMATED > SIMULATED.",
            input_data={
                "signals": [
                    {"source_type": "REAL", "type": "PORT_STATUS", "status": "OPEN", "risk_score": 10.0},
                    {"source_type": "SIMULATED", "type": "PORT_STATUS", "status": "CLOSED", "risk_score": 90.0},
                ],
            },
            expected_output={
                "effective_source_type": "REAL",
                "selected_risk_score": 10.0,
                "precedence_respected": True,
            },
            version="1.0.0",
            tags=["evidence_precedence", "conflict_resolution"],
        ),
        EvaluationCase(
            case_id="risk-case-004",
            suite_type=EvaluationSuiteType.RISK_EVALUATION,
            category=DatasetCategory.NORMAL,
            name="Deterministic Idempotency Verification",
            description="Evaluating identical risk input twice must yield bit-for-bit identical SHA-256 fingerprint.",
            input_data={
                "signals": [
                    {"type": "CARRIER_BANKRUPTCY", "severity": "HIGH", "score": 80.0, "weight": 0.6},
                    {"type": "ROUTE_CONGESTION", "severity": "MEDIUM", "score": 50.0, "weight": 0.4},
                ],
                "tenant_id": "org-omega",
            },
            expected_output={
                "is_idempotent": True,
                "expected_score": 68.0,
                "expected_severity": "HIGH",
            },
            version="1.0.0",
            tags=["idempotency", "fingerprint"],
        ),
        EvaluationCase(
            case_id="risk-case-005",
            suite_type=EvaluationSuiteType.RISK_EVALUATION,
            category=DatasetCategory.SECURITY,
            name="Tenant Boundary Risk Isolation",
            description="Tenant A evaluation must never incorporate tenant B supplier risk signals.",
            input_data={
                "target_tenant": "tenant-acme",
                "candidate_signals": [
                    {"tenant_id": "tenant-acme", "signal_id": "sig-1", "score": 75.0},
                    {"tenant_id": "tenant-rogue", "signal_id": "sig-2", "score": 99.0},
                ],
            },
            expected_output={
                "included_signal_ids": ["sig-1"],
                "excluded_signal_ids": ["sig-2"],
                "cross_tenant_leakage": False,
            },
            version="1.0.0",
            tags=["tenancy", "security"],
        ),
    ]
