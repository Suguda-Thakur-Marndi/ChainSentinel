"""Risk Engine deterministic pipeline orchestrator for RiskWise 2.0.

Coordinates validation, signal evaluation routing, factor collection,
score aggregation, source summary compilation, explainability, and assessment assembly.
"""

from __future__ import annotations

import abc
import logging
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.canonical import EventQuality, EventSourceType
from app.normalization.contract import NormalizedRiskSignal
from app.risk_engine.context import RiskEvaluationContext
from app.risk_engine.contract import (
    AssessmentSourceSummary,
    RiskAssessment,
    RiskFactor,
    RiskScore,
    generate_assessment_fingerprint,
    generate_deterministic_assessment_id,
    select_primary_risk_driver,
    sort_factors_deterministically,
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
        """Aggregate factors and evidence into a typed RiskScore."""
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
            organization_id=context.organization_id,
            primary_factor_id=None,
            factor_contributions=[],
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
        5. Build Deterministic AssessmentSourceSummary
        6. Aggregate Composite RiskScore (Aggregator Protocol)
        7. Select Primary Risk Driver & Generate Deterministic RiskExplanation
        8. Assemble & Return Authoritative RiskAssessment
        """
        start_time = time.perf_counter()

        if not isinstance(context, RiskEvaluationContext):
            raise RiskEngineInputError(
                f"Strict boundary violated: Expected RiskEvaluationContext, got {type(context).__name__}."
            )

        if not context.organization_id:
            raise InvalidContextError("RiskEvaluationContext missing required organization_id.")

        signals: List[NormalizedRiskSignal] = context.signals
        conflict_records: List[Dict[str, Any]] = []
        limitations: List[str] = []
        source_signal_ids: List[str] = []
        simulated_signals_count = 0
        estimated_signals_count = 0
        partial_signals_count = 0
        missing_location_count = 0
        stale_signals_count = 0

        # Stage 2: Signal validation & limitation audit
        for sig in signals:
            source_signal_ids.append(sig.signal_id)

            if getattr(sig, "has_conflict", False) or (getattr(sig, "conflicts", None) and len(sig.conflicts) > 0):
                conflict_records.append(
                    {
                        "signal_id": sig.signal_id,
                        "source": sig.source,
                        "provider": sig.provider,
                        "source_type": sig.source_type.value if hasattr(sig.source_type, "value") else str(sig.source_type),
                        "conflict_type": getattr(sig, "conflict_type", None) or "PROVIDER_DISAGREEMENT",
                        "conflicts": getattr(sig, "conflicts", []),
                        "uncertainty_multiplier": 0.85,
                    }
                )

            if sig.source_type == EventSourceType.SIMULATED:
                simulated_signals_count += 1
            elif sig.source_type == EventSourceType.ESTIMATED:
                estimated_signals_count += 1

            if sig.quality == EventQuality.PARTIAL:
                partial_signals_count += 1

            if sig.latitude is None and sig.longitude is None and not sig.location_name:
                missing_location_count += 1

            if sig.event_time and (context.evaluation_time - sig.event_time) > timedelta(hours=24):
                stale_signals_count += 1

        # Register deterministic limitations
        if simulated_signals_count > 0:
            limitations.append(
                f"Contains {simulated_signals_count} SIMULATED signal(s) which represent synthetic scenarios."
            )
        if estimated_signals_count > 0:
            limitations.append(
                f"Contains {estimated_signals_count} ESTIMATED signal(s) based on modeled or inferred observations."
            )
        if partial_signals_count > 0:
            limitations.append(
                f"Contains {partial_signals_count} PARTIAL quality signal(s) with incomplete data."
            )
        if missing_location_count > 0:
            limitations.append(
                f"{missing_location_count} signal(s) lack spatial coordinates or location names."
            )
        if stale_signals_count > 0:
            limitations.append(
                f"{stale_signals_count} signal(s) have observation timestamps older than 24 hours."
            )
        if conflict_records:
            limitations.append(
                f"Identified {len(conflict_records)} multi-source conflict(s); applied 0.85 uncertainty discount."
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

        sorted_evidence = [all_evidence_map[k] for k in sorted(all_evidence_map.keys())]

        # Stage 5: Compile deterministic AssessmentSourceSummary
        real_sources_set: Set[str] = set()
        estimated_sources_set: Set[str] = set()
        simulated_sources_set: Set[str] = set()
        all_independent_sources: Set[str] = set()
        corroborating_sources_set: Set[str] = set()
        unique_sources: Set[str] = set()
        unique_providers: Set[str] = set()

        for ev in sorted_evidence:
            src_key = ev.provider or ev.source
            all_independent_sources.add(src_key)
            if ev.source:
                unique_sources.add(ev.source)
            if ev.provider:
                unique_providers.add(ev.provider)

            if ev.source_type == EventSourceType.REAL:
                real_sources_set.add(src_key)
            elif ev.source_type == EventSourceType.ESTIMATED:
                estimated_sources_set.add(src_key)
            elif ev.source_type == EventSourceType.SIMULATED:
                simulated_sources_set.add(src_key)

            # Corroborating sources from supporting traces (SIMULATED never counted as real corroboration)
            for supp in ev.supporting_sources:
                supp_prov = supp.get("provider") or supp.get("source")
                supp_type = supp.get("source_type")
                if supp_prov and supp_prov != ev.provider and supp_type != "SIMULATED":
                    corroborating_sources_set.add(supp_prov)

        source_summary = AssessmentSourceSummary(
            evidence_count=len(sorted_evidence),
            independent_sources_count=len(all_independent_sources),
            real_sources_count=len(real_sources_set),
            estimated_sources_count=len(estimated_sources_set),
            simulated_sources_count=len(simulated_sources_set),
            corroborating_sources_count=len(corroborating_sources_set),
            conflicts_count=len(conflict_records),
            sources=sorted(list(unique_sources)),
            providers=sorted(list(unique_providers)),
        )

        # Stage 6: Sort factors deterministically & Aggregate Composite RiskScore
        sorted_factors = sort_factors_deterministically(evaluated_factors)
        overall_score = self.aggregator.aggregate(
            factors=sorted_factors,
            evidence=sorted_evidence,
            context=context,
        )

        # Stage 7: Select Primary Risk Driver & Generate Deterministic RiskExplanation
        primary_factor = select_primary_risk_driver(overall_score.factors)
        primary_factor_id = primary_factor.factor_id if primary_factor else None

        explanation = RiskExplanation.generate_deterministic(
            factors=overall_score.factors,
            evidence=sorted_evidence,
            conflicts=conflict_records if conflict_records else None,
            limitations=limitations if limitations else None,
            score=overall_score.score,
            risk_level=overall_score.risk_level,
            primary_factor=primary_factor,
            factor_contributions=overall_score.factor_contributions,
            source_summary=source_summary,
        )

        # Stage 8: Deterministic Assessment Assembly
        assessment_id = generate_deterministic_assessment_id(
            organization_id=context.organization_id,
            scope=context.scope,
            signal_ids=source_signal_ids,
            eval_time=context.evaluation_time,
        )

        assessment_fingerprint = generate_assessment_fingerprint(
            organization_id=context.organization_id,
            scope=context.scope,
            signal_ids=source_signal_ids,
            factor_ids=[f.factor_id for f in overall_score.factors],
            score=overall_score.score,
            risk_level=overall_score.risk_level.value if overall_score.risk_level else None,
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
            "factor_count": len(overall_score.factors),
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
            primary_factor_id=primary_factor_id,
            primary_factor=primary_factor,
            factors=overall_score.factors,
            evidence=sorted_evidence,
            explanation=explanation,
            source_summary=source_summary,
            limitations=limitations,
            conflicts=conflict_records,
            source_signals=source_signal_ids,
            fingerprint=assessment_fingerprint,
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

    def evaluate_full(
        self,
        context: RiskEvaluationContext,
        previous: Optional[RiskAssessment] = None,
    ) -> RiskEvaluationResult:
        """Execute end-to-end risk evaluation yielding assessment, alerts, recommendations, and comparison.

        Pure-domain pipeline execution requiring no active database connection.
        """
        from app.risk_engine.alerts import RiskAlertEvaluator
        from app.risk_engine.history import HistoricalRiskComparator
        from app.risk_engine.recommendations import RiskRecommendationEvaluator

        assessment = self.evaluate(context)

        comparison = None
        if previous is not None:
            comparison = HistoricalRiskComparator.compare(current=assessment, previous=previous)

        alerts = RiskAlertEvaluator.evaluate_alerts(current=assessment, previous=previous)
        recommendations = RiskRecommendationEvaluator.evaluate_recommendations(
            current=assessment,
            previous=previous,
            alerts=alerts,
        )

        return RiskEvaluationResult(
            assessment=assessment,
            alerts=alerts,
            recommendations=recommendations,
            comparison=comparison,
        )


class RiskEvaluationResult(BaseModel):
    """Encapsulates the complete pure-domain end-to-end evaluation outcome.

    Includes the calculated RiskAssessment, evaluated RiskAlerts,
    derived operational RiskRecommendations, and optional AssessmentComparison.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    assessment: RiskAssessment
    alerts: List[Any] = Field(default_factory=list)
    recommendations: List[Any] = Field(default_factory=list)
    comparison: Optional[Any] = None


RiskEvaluationResult.model_rebuild()
