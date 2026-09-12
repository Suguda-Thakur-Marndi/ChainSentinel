"""Golden evaluation test cases for Phase 15 Decision Agent and Candidate Synthesis (Phase 20)."""
from typing import List
from app.evaluation.contracts import DatasetCategory, EvaluationCase, EvaluationSuiteType


def get_decision_evaluation_cases() -> List[EvaluationCase]:
    """Return golden test cases for decision synthesis, candidate ranking, and policy compliance."""
    return [
        EvaluationCase(
            case_id="dec-case-001",
            suite_type=EvaluationSuiteType.DECISION_EVALUATION,
            category=DatasetCategory.NORMAL,
            name="Multi-Candidate Ranking Alignment",
            description="Decision agent ranks mitigation candidates strictly by expected risk reduction and cost.",
            input_data={
                "incident_id": "inc-suez-01",
                "candidates": [
                    {"candidate_id": "c-air", "cost_usd": 45000.0, "risk_reduction": 0.85, "lead_time_days": 3},
                    {"candidate_id": "c-cape", "cost_usd": 15000.0, "risk_reduction": 0.60, "lead_time_days": 14},
                    {"candidate_id": "c-wait", "cost_usd": 5000.0, "risk_reduction": 0.10, "lead_time_days": 21},
                ],
                "budget_cap_usd": 50000.0,
            },
            expected_output={
                "recommended_candidate_id": "c-air",
                "ranking_order": ["c-air", "c-cape", "c-wait"],
                "policy_compliant": True,
            },
            version="1.0.0",
            tags=["decision", "ranking", "synthesis"],
        ),
        EvaluationCase(
            case_id="dec-case-002",
            suite_type=EvaluationSuiteType.DECISION_EVALUATION,
            category=DatasetCategory.BOUNDARY,
            name="Policy Budget Exceeded Fail-Closed Behavior",
            description="When all mitigation options exceed policy budget limit, decision agent fails closed to human review.",
            input_data={
                "candidates": [
                    {"candidate_id": "c-expensive-1", "cost_usd": 120000.0},
                    {"candidate_id": "c-expensive-2", "cost_usd": 95000.0},
                ],
                "budget_cap_usd": 80000.0,
            },
            expected_output={
                "decision_outcome": "REQUIRE_HUMAN_OVERRIDE",
                "auto_approved": False,
                "fail_closed": True,
            },
            version="1.0.0",
            tags=["decision", "policy", "fail_closed"],
        ),
    ]
