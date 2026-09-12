"""Golden evaluation test cases for Phase 17 Action Execution and Safety (Phase 20)."""
from typing import List
from app.evaluation.contracts import DatasetCategory, EvaluationCase, EvaluationSuiteType


def get_action_evaluation_cases() -> List[EvaluationCase]:
    """Return golden test cases for action approval checking, allowlist verification, idempotency, and SSRF."""
    return [
        EvaluationCase(
            case_id="act-case-001",
            suite_type=EvaluationSuiteType.ACTION_EVALUATION,
            category=DatasetCategory.NORMAL,
            name="Approved Carrier Booking Action Execution",
            description="Approved CARRIER_REROUTE action executes via registered adapter and transitions to SUBMITTED.",
            input_data={
                "action_type": "CARRIER_REROUTE",
                "is_approved": True,
                "approval_id": "appr-201",
                "target_shipment_id": "shp-101",
                "idempotency_key": "idemp-reroute-shp-101-v1",
            },
            expected_output={
                "execution_status": "SUBMITTED",
                "is_verified": False,  # SUBMITTED != VERIFIED invariant
                "audit_recorded": True,
            },
            version="1.0.0",
            tags=["action", "execution", "submitted_invariant"],
        ),
        EvaluationCase(
            case_id="act-case-002",
            suite_type=EvaluationSuiteType.ACTION_EVALUATION,
            category=DatasetCategory.SECURITY,
            name="Unapproved Action Execution Rejection",
            description="Attempting to execute an unapproved action fails closed immediately.",
            input_data={
                "action_type": "EXPEDITE_AIR_FREIGHT",
                "is_approved": False,
                "approval_id": None,
            },
            expected_output={
                "execution_allowed": False,
                "error_reason": "UNAPPROVED_ACTION_REJECTED",
                "dispatched_to_adapter": False,
            },
            version="1.0.0",
            tags=["action", "approval_enforcement", "security"],
        ),
        EvaluationCase(
            case_id="act-case-003",
            suite_type=EvaluationSuiteType.ACTION_EVALUATION,
            category=DatasetCategory.NORMAL,
            name="Action Execution Idempotency Verification",
            description="Re-submitting action with duplicate idempotency key returns existing record without duplicate external API call.",
            input_data={
                "idempotency_key": "idemp-repeat-test-01",
                "attempts": 2,
            },
            expected_output={
                "is_duplicate_prevented": True,
                "external_calls_count": 1,
                "status": "SUBMITTED",
            },
            version="1.0.0",
            tags=["action", "idempotency"],
        ),
        EvaluationCase(
            case_id="act-case-004",
            suite_type=EvaluationSuiteType.ACTION_EVALUATION,
            category=DatasetCategory.ADVERSARIAL,
            name="SSRF Webhook Exfiltration Protection",
            description="Malicious action payload containing internal AWS metadata URL (http://169.254.169.254) is blocked.",
            input_data={
                "action_type": "WEBHOOK_NOTIFY",
                "destination_url": "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            },
            expected_output={
                "blocked_by_ssrf_filter": True,
                "network_request_made": False,
                "security_violation_flagged": True,
            },
            version="1.0.0",
            tags=["action", "ssrf", "security"],
        ),
    ]
