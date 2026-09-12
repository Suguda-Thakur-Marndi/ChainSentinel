"""Golden evaluation cases package combining all domain benchmark datasets."""

from typing import List, Any
from app.evaluation.contracts import EvaluationCase

def _load_cases(module_name: str, var_name: str, fn_name: str) -> List[EvaluationCase]:
    import importlib
    mod = importlib.import_module(f"app.evaluation.datasets.golden.{module_name}")
    if hasattr(mod, var_name):
        return getattr(mod, var_name)
    if hasattr(mod, fn_name):
        return getattr(mod, fn_name)()
    return []

GOLDEN_AGENT_CASES: List[EvaluationCase] = _load_cases("agent_cases", "GOLDEN_AGENT_CASES", "get_agent_evaluation_cases")
GOLDEN_RESEARCH_CASES: List[EvaluationCase] = _load_cases("research_cases", "GOLDEN_RESEARCH_CASES", "get_research_evaluation_cases")
GOLDEN_RISK_CASES: List[EvaluationCase] = _load_cases("risk_cases", "GOLDEN_RISK_CASES", "get_risk_evaluation_cases")
GOLDEN_RAG_CASES: List[EvaluationCase] = _load_cases("rag_cases", "GOLDEN_RAG_CASES", "get_rag_evaluation_cases")
GOLDEN_CLAUDE_CASES: List[EvaluationCase] = _load_cases("claude_cases", "GOLDEN_CLAUDE_CASES", "get_claude_evaluation_cases")
GOLDEN_ML_CASES: List[EvaluationCase] = _load_cases("ml_cases", "GOLDEN_ML_CASES", "get_ml_evaluation_cases")
GOLDEN_DIGITAL_TWIN_CASES: List[EvaluationCase] = _load_cases("digital_twin_cases", "GOLDEN_DIGITAL_TWIN_CASES", "get_digital_twin_evaluation_cases")
GOLDEN_SIMULATION_CASES: List[EvaluationCase] = _load_cases("simulation_cases", "GOLDEN_SIMULATION_CASES", "get_simulation_evaluation_cases")
GOLDEN_OPTIMIZATION_CASES: List[EvaluationCase] = _load_cases("optimization_cases", "GOLDEN_OPTIMIZATION_CASES", "get_optimization_evaluation_cases")
GOLDEN_DECISION_CASES: List[EvaluationCase] = _load_cases("decision_cases", "GOLDEN_DECISION_CASES", "get_decision_evaluation_cases")
GOLDEN_APPROVAL_CASES: List[EvaluationCase] = _load_cases("approval_cases", "GOLDEN_APPROVAL_CASES", "get_approval_evaluation_cases")
GOLDEN_ACTION_CASES: List[EvaluationCase] = _load_cases("action_cases", "GOLDEN_ACTION_CASES", "get_action_evaluation_cases")
GOLDEN_VERIFICATION_CASES: List[EvaluationCase] = _load_cases("verification_cases", "GOLDEN_VERIFICATION_CASES", "get_verification_evaluation_cases")
GOLDEN_E2E_CASES: List[EvaluationCase] = _load_cases("e2e_cases", "GOLDEN_E2E_CASES", "get_e2e_evaluation_cases")
GOLDEN_SECURITY_CASES: List[EvaluationCase] = _load_cases("security_cases", "GOLDEN_SECURITY_CASES", "get_security_evaluation_cases")

ALL_GOLDEN_CASES: List[EvaluationCase] = (
    GOLDEN_AGENT_CASES
    + GOLDEN_RESEARCH_CASES
    + GOLDEN_RISK_CASES
    + GOLDEN_RAG_CASES
    + GOLDEN_CLAUDE_CASES
    + GOLDEN_ML_CASES
    + GOLDEN_DIGITAL_TWIN_CASES
    + GOLDEN_SIMULATION_CASES
    + GOLDEN_OPTIMIZATION_CASES
    + GOLDEN_DECISION_CASES
    + GOLDEN_APPROVAL_CASES
    + GOLDEN_ACTION_CASES
    + GOLDEN_VERIFICATION_CASES
    + GOLDEN_E2E_CASES
    + GOLDEN_SECURITY_CASES
)

__all__ = [
    "GOLDEN_AGENT_CASES",
    "GOLDEN_RESEARCH_CASES",
    "GOLDEN_RISK_CASES",
    "GOLDEN_RAG_CASES",
    "GOLDEN_CLAUDE_CASES",
    "GOLDEN_ML_CASES",
    "GOLDEN_DIGITAL_TWIN_CASES",
    "GOLDEN_SIMULATION_CASES",
    "GOLDEN_OPTIMIZATION_CASES",
    "GOLDEN_DECISION_CASES",
    "GOLDEN_APPROVAL_CASES",
    "GOLDEN_ACTION_CASES",
    "GOLDEN_VERIFICATION_CASES",
    "GOLDEN_E2E_CASES",
    "GOLDEN_SECURITY_CASES",
    "ALL_GOLDEN_CASES",
]
