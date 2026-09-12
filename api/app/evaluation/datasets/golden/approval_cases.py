"""Golden evaluation test cases for Phase 16 Human-in-the-Loop Approval Governance (Phase 20)."""
from typing import List
from app.evaluation.contracts import DatasetCategory, EvaluationCase, EvaluationSuiteType


def get_approval_evaluation_cases() -> List[EvaluationCase]:
    """Return golden test cases for RBAC role gating, decision fingerprint binding, and non-LLM approval invariant."""
    return [
        EvaluationCase(
            case_id="appr-case-001",
            suite_type=EvaluationSuiteType.APPROVAL_EVALUATION,
            category=DatasetCategory.NORMAL,
            name="Authorized RiskManager Approval Execution",
            description="User with RISKMANAGER role successfully signs off on mitigation recommendation.",
            input_data={
                "user_role": "RISKMANAGER",
                "recommendation_id": "rec-101",
                "decision": "APPROVE",
                "comments": "Approved after consulting logistics ops.",
            },
            expected_output={
                "is_permitted": True,
                "approval_status": "APPROVED",
                "rbac_passed": True,
            },
            version="1.0.0",
            tags=["approval", "rbac", "authorized"],
        ),
        EvaluationCase(
            case_id="appr-case-002",
            suite_type=EvaluationSuiteType.APPROVAL_EVALUATION,
            category=DatasetCategory.SECURITY,
            name="Unauthorized Viewer Role Rejection",
            description="User with VIEWER role attempting to approve action is rejected with 403 Forbidden.",
            input_data={
                "user_role": "VIEWER",
                "recommendation_id": "rec-101",
                "decision": "APPROVE",
            },
            expected_output={
                "is_permitted": False,
                "expected_status_code": 403,
                "approval_recorded": False,
            },
            version="1.0.0",
            tags=["approval", "rbac", "security"],
        ),
        EvaluationCase(
            case_id="appr-case-003",
            suite_type=EvaluationSuiteType.APPROVAL_EVALUATION,
            category=DatasetCategory.SECURITY,
            name="Non-LLM Invariant: Agent Cannot Approve Action",
            description="AI agents or automated processes attempting self-approval are strictly rejected.",
            input_data={
                "requester_type": "AI_AGENT",
                "agent_name": "DecisionAgent_Claude",
                "recommendation_id": "rec-102",
            },
            expected_output={
                "allow_agent_approval": False,
                "human_in_the_loop_preserved": True,
                "error_reason": "AI_AGENT_CANNOT_APPROVE_DECISION",
            },
            version="1.0.0",
            tags=["approval", "governance", "non_llm_invariant"],
        ),
        EvaluationCase(
            case_id="appr-case-004",
            suite_type=EvaluationSuiteType.APPROVAL_EVALUATION,
            category=DatasetCategory.CONFLICT,
            name="Stale Decision Fingerprint Rejection",
            description="Approving an altered decision whose cryptographic fingerprint does not match raises error.",
            input_data={
                "approval_target_fingerprint": "a1b2c3d4e5f6...",
                "current_decision_fingerprint": "f6e5d4c3b2a1...",
            },
            expected_output={
                "is_valid": False,
                "fingerprint_match": False,
                "rejection_reason": "DECISION_STATE_CHANGED_STALE_APPROVAL",
            },
            version="1.0.0",
            tags=["approval", "fingerprint", "stale_rejection"],
        ),
    ]
