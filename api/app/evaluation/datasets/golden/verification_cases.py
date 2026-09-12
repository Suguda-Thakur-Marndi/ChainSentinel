"""Golden evaluation test cases for Phase 18 Ground-Truth Physical Verification (Phase 20)."""
from typing import List
from app.evaluation.contracts import DatasetCategory, EvaluationCase, EvaluationSuiteType


def get_verification_evaluation_cases() -> List[EvaluationCase]:
    """Return golden test cases for deterministic verification, evidence precedence, and ground-truth validation."""
    return [
        EvaluationCase(
            case_id="ver-case-001",
            suite_type=EvaluationSuiteType.VERIFICATION_EVALUATION,
            category=DatasetCategory.NORMAL,
            name="Deterministic Ground Truth AIS Verification",
            description="Vessel arrival AIS transponder event matching destination port within temporal window yields VERIFIED.",
            input_data={
                "action": {"type": "CARRIER_REROUTE", "expected_destination": "port-sin-01"},
                "evidence": [
                    {
                        "source_type": "REAL",
                        "source_provider": "AISSTREAM",
                        "event_type": "BERTH_ARRIVED",
                        "location_id": "port-sin-01",
                        "timestamp": "2026-09-12T10:00:00Z",
                    }
                ],
            },
            expected_output={
                "verification_status": "VERIFIED",
                "evidence_provenance": "REAL",
                "deterministic_match": True,
                "ai_determined": False,  # Deterministic oracle, AI does not decide outcome
            },
            version="1.0.0",
            tags=["verification", "ground_truth", "deterministic"],
        ),
        EvaluationCase(
            case_id="ver-case-002",
            suite_type=EvaluationSuiteType.VERIFICATION_EVALUATION,
            category=DatasetCategory.SECURITY,
            name="Simulated Evidence Cannot Prove Real-World Outcome",
            description="Verification agent rejects SIMULATED evidence trying to verify real physical shipment arrival.",
            input_data={
                "action": {"type": "CARRIER_REROUTE", "expected_destination": "port-sin-01"},
                "evidence": [
                    {
                        "source_type": "SIMULATED",
                        "event_type": "BERTH_ARRIVED",
                        "location_id": "port-sin-01",
                    }
                ],
            },
            expected_output={
                "verification_status": "FAILED",
                "failure_reason": "SIMULATED_EVIDENCE_CANNOT_PROVE_REAL_OUTCOME",
                "verified": False,
            },
            version="1.0.0",
            tags=["verification", "evidence_hierarchy", "security"],
        ),
        EvaluationCase(
            case_id="ver-case-003",
            suite_type=EvaluationSuiteType.VERIFICATION_EVALUATION,
            category=DatasetCategory.CONFLICT,
            name="Conflicting Telemetry Evidence Resolution",
            description="Conflicting ground truth (real GPS says transit, carrier EDI says delivered) marks CONFLICT.",
            input_data={
                "action": {"type": "DELIVER_PARCEL", "expected_destination": "warehouse-01"},
                "evidence": [
                    {"source_type": "REAL", "source_provider": "GPS", "status": "IN_TRANSIT", "timestamp": "12:00:00"},
                    {"source_type": "ESTIMATED", "source_provider": "EDI", "status": "DELIVERED", "timestamp": "12:05:00"},
                ],
            },
            expected_output={
                "verification_status": "CONFLICT",
                "has_conflict": True,
                "higher_precedence_source": "GPS",
            },
            version="1.0.0",
            tags=["verification", "conflict"],
        ),
    ]
