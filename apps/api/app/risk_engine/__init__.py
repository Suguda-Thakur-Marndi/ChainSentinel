"""RiskWise 2.0 Risk Engine Package (Phase 7).

Provides strongly typed application contracts, deterministic evaluation context,
evidence lineage, explainability, domain factor evaluators, baseline scoring,
registry, and pipeline orchestrator.
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
from app.risk_engine.evaluators import (
    AirRiskFactorEvaluator,
    GeneralRiskFactorEvaluator,
    IntelligenceRiskFactorEvaluator,
    LogisticsRiskFactorEvaluator,
    MaritimeRiskFactorEvaluator,
    PortRiskFactorEvaluator,
    RailRiskFactorEvaluator,
    RoadRiskFactorEvaluator,
    WeatherRiskFactorEvaluator,
    register_baseline_evaluators,
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
    BaselineRiskEngine,
    DefaultRiskScoreAggregator,
    RiskEngine,
    RiskScoreAggregatorProtocol,
)
from app.risk_engine.registry import (
    BaseRiskFactorEvaluator,
    RiskFactorRegistry,
    default_risk_factor_registry,
)
from app.risk_engine.scoring import (
    CONFLICT_MULTIPLIER,
    QUALITY_MULTIPLIERS,
    SEVERITY_TO_RISK_LEVEL,
    SEVERITY_WEIGHTS,
    SOURCE_TYPE_MULTIPLIERS,
    BaselineRiskScoreAggregator,
    compute_factor_contribution,
    score_to_risk_level,
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
    # Evaluators
    "WeatherRiskFactorEvaluator",
    "RoadRiskFactorEvaluator",
    "PortRiskFactorEvaluator",
    "MaritimeRiskFactorEvaluator",
    "AirRiskFactorEvaluator",
    "RailRiskFactorEvaluator",
    "LogisticsRiskFactorEvaluator",
    "IntelligenceRiskFactorEvaluator",
    "GeneralRiskFactorEvaluator",
    "register_baseline_evaluators",
    # Scoring
    "SEVERITY_WEIGHTS",
    "SEVERITY_TO_RISK_LEVEL",
    "QUALITY_MULTIPLIERS",
    "SOURCE_TYPE_MULTIPLIERS",
    "CONFLICT_MULTIPLIER",
    "compute_factor_contribution",
    "score_to_risk_level",
    "BaselineRiskScoreAggregator",
    # Pipeline
    "RiskEngine",
    "BaselineRiskEngine",
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
