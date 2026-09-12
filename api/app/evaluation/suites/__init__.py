"""Evaluation suites package for RiskWise 2.0."""

from typing import Dict, Type
from app.evaluation.contracts import EvaluationSuiteType
from app.evaluation.suites.base import BaseEvaluationSuite
from app.evaluation.suites.agent_suite import AgentEvaluationSuite
from app.evaluation.suites.research_suite import ResearchEvaluationSuite
from app.evaluation.suites.risk_suite import RiskEvaluationSuite
from app.evaluation.suites.rag_suite import RAGEvaluationSuite
from app.evaluation.suites.claude_suite import ClaudeEvaluationSuite
from app.evaluation.suites.ml_suite import MLEvaluationSuite
from app.evaluation.suites.digital_twin_suite import DigitalTwinEvaluationSuite
from app.evaluation.suites.simulation_suite import SimulationEvaluationSuite
from app.evaluation.suites.optimization_suite import OptimizationEvaluationSuite
from app.evaluation.suites.decision_suite import DecisionEvaluationSuite
from app.evaluation.suites.approval_suite import ApprovalEvaluationSuite
from app.evaluation.suites.action_suite import ActionEvaluationSuite
from app.evaluation.suites.verification_suite import VerificationEvaluationSuite
from app.evaluation.suites.e2e_suite import EndToEndEvaluationSuite
from app.evaluation.suites.security_suite import SecurityEvaluationSuite

SUITE_REGISTRY: Dict[EvaluationSuiteType, Type[BaseEvaluationSuite]] = {
    EvaluationSuiteType.AGENT_EVALUATION: AgentEvaluationSuite,
    EvaluationSuiteType.RESEARCH_EVALUATION: ResearchEvaluationSuite,
    EvaluationSuiteType.RISK_EVALUATION: RiskEvaluationSuite,
    EvaluationSuiteType.RAG_EVALUATION: RAGEvaluationSuite,
    EvaluationSuiteType.CLAUDE_EVALUATION: ClaudeEvaluationSuite,
    EvaluationSuiteType.ML_EVALUATION: MLEvaluationSuite,
    EvaluationSuiteType.DIGITAL_TWIN_EVALUATION: DigitalTwinEvaluationSuite,
    EvaluationSuiteType.SIMULATION_EVALUATION: SimulationEvaluationSuite,
    EvaluationSuiteType.OPTIMIZATION_EVALUATION: OptimizationEvaluationSuite,
    EvaluationSuiteType.DECISION_EVALUATION: DecisionEvaluationSuite,
    EvaluationSuiteType.APPROVAL_EVALUATION: ApprovalEvaluationSuite,
    EvaluationSuiteType.ACTION_EVALUATION: ActionEvaluationSuite,
    EvaluationSuiteType.VERIFICATION_EVALUATION: VerificationEvaluationSuite,
    EvaluationSuiteType.END_TO_END_EVALUATION: EndToEndEvaluationSuite,
    EvaluationSuiteType.SECURITY_EVALUATION: SecurityEvaluationSuite,
}


def get_suite(suite_type: EvaluationSuiteType) -> BaseEvaluationSuite:
    suite_cls = SUITE_REGISTRY.get(suite_type)
    if not suite_cls:
        raise KeyError(f"Evaluation suite for type '{suite_type}' not found in registry")
    return suite_cls()


__all__ = [
    "BaseEvaluationSuite",
    "AgentEvaluationSuite",
    "ResearchEvaluationSuite",
    "RiskEvaluationSuite",
    "RAGEvaluationSuite",
    "ClaudeEvaluationSuite",
    "MLEvaluationSuite",
    "DigitalTwinEvaluationSuite",
    "SimulationEvaluationSuite",
    "OptimizationEvaluationSuite",
    "DecisionEvaluationSuite",
    "ApprovalEvaluationSuite",
    "ActionEvaluationSuite",
    "VerificationEvaluationSuite",
    "EndToEndEvaluationSuite",
    "SecurityEvaluationSuite",
    "SUITE_REGISTRY",
    "get_suite",
]
