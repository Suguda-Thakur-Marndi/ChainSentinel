"""Risk Engine deterministic pipeline orchestrator for RiskWise 2.0.

Coordinates validation, signal evaluation routing, factor collection,
score aggregation stub (Step 1), explainability, and assessment assembly.
"""

from __future__ import annotations

import abc
import logging
import time
from typing import Any, Dict, List, Optional

from app.normalization.contract import NormalizedRiskSignal
from app.risk_engine.context import RiskEvaluationContext
from app.risk_engine.contract import (
    RiskAssessment,
    RiskFactor,
    RiskScore,
    generate_deterministic_assessment_id,
)
from app.risk_engine.errors import InvalidContextError, RiskEngineInputError
from app.risk_engine.evidence import RiskEvidence
from app.risk_engine.explainability import RiskExplanation
from app.risk_engine.registry import RiskFactorRegistry, default_risk_factor_registry

logger = logging.getLogger("riskwise.risk_engine.pipeline")


class RiskScoreAggregatorProtocol(abc.ABC):
    """Extension interface for aggregating evaluated risk factors into a composite RiskScore."""

    @abc.abstractmethod
    def aggregate(
        self,
        factors: List[RiskFactor],
        evidence: List[RiskEvidence],
        context: RiskEvaluationContext,
    ) -> RiskScore:
        """Aggregate factors and evidence into a typed RiskScore.

        Step 1 provides a clean stub; Step 2 will implement actual scoring logic.
        """
        pass


class DefaultRiskScoreAggregator(RiskScoreAggregatorProtocol):
    """Step 1 stub aggregator preserving factor lineage without implementing scoring algorithms."""

    def aggregate(
        self,
        factors: List[RiskFactor],
        evidence: List[RiskEvidence],
        context: RiskEvaluationContext,
    ) -> RiskScore:
        """Produce an uncommitted RiskScore stub in compliance with Step 1 boundaries."""
        min_confidence = min((f.confidence for f in factors), default=1.0)
        return RiskScore(
            score=None,
            risk_level=None,
            probability=None,
            impact=None,
            confidence=min_confidence,
            factors=factors,
            evidence=evidence,
            timestamp=context.evaluation_time,
        )


class RiskEngine:
    """Deterministic, multi-tenant Risk Engine pipeline orchestrator."""

    def __init__(
        self,
        registry: Optional[RiskFactorRegistry] = None,
        aggregator: Optional[RiskScoreAggregatorProtocol] = None,
    ) -> None:
        self.registry = registry or default_risk_factor_registry
        self.aggregator = aggregator or DefaultRiskScoreAggregator()

    def evaluate(self, context: RiskEvaluationContext) -> RiskAssessment:
        """Execute a deterministic risk evaluation run over the provided context.

        Pipeline Stages:
        1. Validate Context & Input Boundary
        2. Validate & Deduplicate Normalized Signals
        3. Route Signals to Applicable Factor Evaluators
        4. Collect Risk Factors & Associate Traceable Evidence
        5. Aggregate Composite RiskScore (Aggregator Protocol)
        6. Generate Deterministic RiskExplanation
        7. Assemble & Return Authoritative RiskAssessment
        """
        start_time = time.perf_counter()

        if not isinstance(context, RiskEvaluationContext):
            raise RiskEngineInputError(
                f"Strict boundary violated: Expected RiskEvaluationContext, got {type(context).__name__}."
            )

        if not context.organization_id:
            raise InvalidContextError("RiskEvaluationContext missing required organization_id.")

        # Collect and analyze input signals
        signals: List[NormalizedRiskSignal] = context.signals
        conflict_records: List[Dict[str, Any]] = []
        limitations: List[str] = []
        source_signal_ids: List[str] = []
        simulated_signals_count = 0

        for sig in signals:
            source_signal_ids.append(sig.signal_id)
            if getattr(sig, "has_conflict", False):
                conflict_records.append(
                    {
                        "signal_id": sig.signal_id,
                        "conflict_type": getattr(sig, "conflict_type", None),
                        "details": getattr(sig, "conflict_details", {}),
                    }
                )
            if getattr(sig, "source_type", None) == "SIMULATED":
                simulated_signals_count += 1

        if simulated_signals_count > 0:
            limitations.append(
                f"Contains {simulated_signals_count} simulated signal(s) which represent synthetic scenarios."
            )

        # Stage 3 & 4: Route signals to factor evaluators and collect factors + evidence
        evaluated_factors: List[RiskFactor] = []
        all_evidence_map: Dict[str, RiskEvidence] = {}

        for signal in signals:
            evaluators = self.registry.resolve_evaluators(
                domain=signal.domain,
                signal_type=signal.signal_type,
            )
            for evaluator in evaluators:
                if evaluator.can_evaluate(signal, context):
                    factor = evaluator.evaluate(signal, context)
                    if factor is not None:
                        evaluated_factors.append(factor)
                        for ev in factor.evidence:
                            if ev.evidence_id not in all_evidence_map:
                                all_evidence_map[ev.evidence_id] = ev

        # Stage 5: Score Aggregation
        sorted_evidence = [all_evidence_map[k] for k in sorted(all_evidence_map.keys())]
        overall_score = self.aggregator.aggregate(
            factors=evaluated_factors,
            evidence=sorted_evidence,
            context=context,
        )

        # Stage 6: Deterministic Explanation
        explanation = RiskExplanation.generate_deterministic(
            factors=evaluated_factors,
            evidence=sorted_evidence,
            conflicts=conflict_records if conflict_records else None,
            limitations=limitations if limitations else None,
            score=overall_score.score,
            risk_level=overall_score.risk_level,
        )

        # Stage 7: Deterministic Assessment Assembly
        assessment_id = generate_deterministic_assessment_id(
            organization_id=context.organization_id,
            scope=context.scope,
            signal_ids=source_signal_ids,
            eval_time=context.evaluation_time,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        is_baseline = self.aggregator.__class__.__name__ == "BaselineRiskScoreAggregator"
        scoring_algo = "2.0-baseline-deterministic" if is_baseline else (
            "UNCOMMITTED_STEP1_STUB" if isinstance(self.aggregator, DefaultRiskScoreAggregator) else type(self.aggregator).__name__
        )
        pipeline_ver = "2.0-baseline" if is_baseline else "2.0-step1"

        metadata: Dict[str, Any] = {
            "evaluation_duration_ms": round(elapsed_ms, 2),
            "signal_count": len(signals),
            "factor_count": len(evaluated_factors),
            "evidence_count": len(sorted_evidence),
            "conflict_count": len(conflict_records),
            "simulated_count": simulated_signals_count,
            "correlation_id": context.correlation_id,
            "trace_id": context.trace_id,
            "pipeline_version": pipeline_ver,
            "scoring_algorithm": scoring_algo,
        }
        metadata.update(context.metadata)

        return RiskAssessment(
            assessment_id=assessment_id,
            organization_id=context.organization_id,
            evaluated_at=context.evaluation_time,
            scope=context.scope,
            scope_entity_id=context.scope_entity_id,
            scope_entity_type=context.scope_entity_type,
            overall_score=overall_score,
            risk_level=overall_score.risk_level,
            probability=overall_score.probability,
            impact=overall_score.impact,
            confidence=overall_score.confidence,
            factors=evaluated_factors,
            evidence=sorted_evidence,
            explanation=explanation,
            source_signals=source_signal_ids,
            metadata=metadata,
        )


class BaselineRiskEngine(RiskEngine):
    """Phase 7 Step 2 baseline Risk Engine pre-configured with 9 baseline domain evaluators."""

    def __init__(
        self,
        registry: Optional[RiskFactorRegistry] = None,
        aggregator: Optional[RiskScoreAggregatorProtocol] = None,
    ) -> None:
        from app.risk_engine.evaluators import register_baseline_evaluators
        from app.risk_engine.scoring import BaselineRiskScoreAggregator

        reg = registry or RiskFactorRegistry()
        if len(reg.list_evaluators()) == 0:
            register_baseline_evaluators(reg)
        agg = aggregator or BaselineRiskScoreAggregator()
        super().__init__(registry=reg, aggregator=agg)

