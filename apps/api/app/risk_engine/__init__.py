"""RiskWise 2.0 Risk Engine Package (Phase 7 Step 1).

Provides strongly typed application contracts, deterministic evaluation context,
evidence lineage, explainability, evaluator interfaces, registry, and pipeline orchestrator.
"""

from app.risk_engine.context import (
    RiskEvaluationContext,
    generate_deterministic_evaluation_id,
)
from app.risk_engine.contract import (
    RiskAssessment,
    RiskFactor,
    RiskLevel,
    RiskScore,
    generate_deterministic_assessment_id,
    generate_deterministic_factor_id,
)
from app.risk_engine.errors import (
    EvaluatorRegistrationError,
    InvalidContextError,
    InvalidSignalQualityError,
    RiskEngineError,
    RiskEngineInputError,
    TenantMismatchError,
)
from app.risk_engine.evidence import (
    RiskEvidence,
    generate_deterministic_evidence_id,
)
from app.risk_engine.explainability import (
    FactorExplanation,
    RiskExplanation,
)
from app.risk_engine.pipeline import (
    DefaultRiskScoreAggregator,
    RiskEngine,
    RiskScoreAggregatorProtocol,
)
from app.risk_engine.registry import (
    BaseRiskFactorEvaluator,
    RiskFactorRegistry,
    default_risk_factor_registry,
)

__all__ = [
    # Contracts
    "RiskLevel",
    "RiskFactor",
    "RiskScore",
    "RiskAssessment",
    "generate_deterministic_factor_id",
    "generate_deterministic_assessment_id",
    # Context
    "RiskEvaluationContext",
    "generate_deterministic_evaluation_id",
    # Evidence
    "RiskEvidence",
    "generate_deterministic_evidence_id",
    # Explainability
    "FactorExplanation",
    "RiskExplanation",
    # Registry & Evaluator Interface
    "BaseRiskFactorEvaluator",
    "RiskFactorRegistry",
    "default_risk_factor_registry",
    # Pipeline
    "RiskEngine",
    "RiskScoreAggregatorProtocol",
    "DefaultRiskScoreAggregator",
    # Errors
    "RiskEngineError",
    "RiskEngineInputError",
    "TenantMismatchError",
    "InvalidContextError",
    "InvalidSignalQualityError",
    "EvaluatorRegistrationError",
]
