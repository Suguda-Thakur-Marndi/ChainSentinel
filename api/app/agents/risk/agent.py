"""Risk Agent orchestrator for Phase 9 Step 5.

Coordinates the research→risk handoff by:
1. Validating RiskAgentRequest tenant and research result boundary.
2. Translating ResearchResult findings to NormalizedRiskSignal objects.
3. Invoking the Phase 7 Risk Engine via RiskEngineAdapter.
4. Extracting RiskAgentResult from the authoritative RiskEvaluationResult.
5. Preserving exact score, risk_level, factors, alerts, recommendations — unmodified.

The RiskAgent does NOT compute risk scores. It only orchestrates and relays.
"""

from __future__ import annotations

from typing import Any, Optional

from app.agents.contracts import AgentLimitation, LimitationCategory
from app.agents.research.contract import ResearchResult
from app.agents.risk.adapter import ResearchRiskAdapter, RiskEngineAdapter
from app.agents.risk.contract import RiskAgentRequest, RiskAgentResult
from app.agents.risk.errors import (
    InvalidRiskRequestError,
    RiskEngineAdapterError,
    RiskInputValidationError,
    RiskTenantIsolationError,
)


def _extract_alert_ids(alerts: list) -> list:
    """Extract deterministic alert IDs from Phase 7 RiskAlert objects."""
    ids = []
    for alert in alerts:
        aid = getattr(alert, "alert_id", None)
        if aid:
            ids.append(str(aid))
    return ids


def _extract_recommendation_ids(recommendations: list) -> list:
    """Extract deterministic recommendation IDs from Phase 7 RiskRecommendation objects."""
    ids = []
    for rec in recommendations:
        rid = getattr(rec, "recommendation_id", None)
        if rid:
            ids.append(str(rid))
    return ids


class RiskAgent:
    """Risk Agent orchestrator — research→risk handoff coordinator.

    Delegates all risk computation to the Phase 7 BaselineRiskEngine.
    Preserves authoritative score, level, factors, fingerprint, alerts, and
    recommendations without modification.
    """

    def __init__(self) -> None:
        self._engine_adapter = RiskEngineAdapter()

    def execute(
        self,
        request: RiskAgentRequest,
        research_result: Optional[ResearchResult] = None,
        previous_assessment: Optional[Any] = None,
    ) -> RiskAgentResult:
        """Execute risk evaluation using research findings as Risk Engine input.

        Args:
            request: Validated RiskAgentRequest.
            research_result: ResearchResult from the Research Agent (may also be embedded
                in request.research_result).
            previous_assessment: Optional prior RiskAssessment for trend comparison.

        Returns:
            RiskAgentResult with authoritative risk references.

        Raises:
            RiskTenantIsolationError: If cross-tenant data is detected (NON_RETRYABLE).
            InvalidRiskRequestError: If input is malformed (NON_RETRYABLE).
            RiskInputValidationError: If no mappable signals are available (NON_RETRYABLE).
            RiskEngineAdapterError: If the Phase 7 engine raises (RETRYABLE).
        """
        if not isinstance(request, RiskAgentRequest):
            raise InvalidRiskRequestError(
                f"Expected RiskAgentRequest, got {type(request).__name__}."
            )

        # Resolve research result (from argument or embedded in request)
        resolved_result = research_result or request.research_result
        if resolved_result is None:
            raise InvalidRiskRequestError(
                "RiskAgent.execute() requires a ResearchResult — none provided.",
                details={"risk_request_id": request.risk_request_id},
            )

        # Tenant isolation: research result must belong to same org
        if resolved_result.organization_id != request.organization_id:
            raise RiskTenantIsolationError(
                f"ResearchResult tenant '{resolved_result.organization_id}' does not match "
                f"RiskAgentRequest tenant '{request.organization_id}'.",
                details={"risk_request_id": request.risk_request_id},
            )

        # Step 1: Translate research findings → NormalizedRiskSignal objects
        signals, translation_limitations = ResearchRiskAdapter.translate(
            research_result=resolved_result,
            organization_id=request.organization_id,
            run_id=request.risk_request_id,
            correlation_id=request.correlation_id,
            trace_id=request.trace_id,
        )

        all_limitations = list(translation_limitations)

        # Step 2: Handle case where all findings were unmapped
        if not signals:
            # Produce a structured result with INSUFFICIENT_EVIDENCE status
            all_limitations.append(
                AgentLimitation(
                    limitation_id=f"lim_no_signals_{request.risk_request_id[:12]}",
                    category=LimitationCategory.INSUFFICIENT_EVIDENCE,
                    description=(
                        "No ResearchFinding categories could be translated into valid Risk Engine signals. "
                        "All findings were UNKNOWN, DATA_GAP, or had unmapped categories. "
                        "Risk evaluation cannot produce a score without at least one mappable signal."
                    ),
                    affected_nodes=["risk_agent"],
                    mitigation_or_impact=(
                        "Risk assessment is incomplete. Downstream agents should treat risk level as UNKNOWN."
                    ),
                )
            )

            # Return a INSUFFICIENT_EVIDENCE result without calling the engine
            return RiskAgentResult(
                risk_request_id=request.risk_request_id,
                organization_id=request.organization_id,
                status="INSUFFICIENT_EVIDENCE",
                assessment_id=f"assessment_none_{request.risk_request_id[:12]}",
                assessment_fingerprint=None,
                risk_score=None,
                risk_level=None,
                confidence=0.0,
                factor_count=0,
                factor_ids=[],
                evidence_count=0,
                evidence_ids=[],
                alert_ids=[],
                recommendation_ids=[],
                limitations=all_limitations,
                provenance={
                    "research_id": request.research_id or "",
                    "evidence_bundle_id": request.evidence_bundle_id or "",
                    "signals_produced": 0,
                    "translation_limitations": len(translation_limitations),
                },
            )

        # Step 3: Invoke Phase 7 Risk Engine via adapter
        evaluation_result = self._engine_adapter.evaluate(
            request=request,
            signals=signals,
            previous_assessment=previous_assessment,
        )

        # Step 4: Extract authoritative references from RiskEvaluationResult
        assessment = evaluation_result.assessment
        alerts = evaluation_result.alerts or []
        recommendations = evaluation_result.recommendations or []

        # Extract factor IDs from authoritative assessment
        factor_ids = [
            f.factor_id for f in assessment.factors if f.factor_id
        ]

        # Extract evidence IDs from authoritative assessment
        evidence_ids = [
            e.evidence_id for e in assessment.evidence if e.evidence_id
        ]

        # Extract alert and recommendation IDs (references only — not duplicated objects)
        alert_ids = _extract_alert_ids(alerts)
        recommendation_ids = _extract_recommendation_ids(recommendations)

        # Carry forward any engine-level limitations
        for lim_str in assessment.limitations:
            all_limitations.append(
                AgentLimitation(
                    limitation_id=f"lim_engine_{hash(lim_str) % 10**8:08d}",
                    category=LimitationCategory.STALE_DATA
                    if "stale" in lim_str.lower()
                    else LimitationCategory.CONFLICTING_SOURCES
                    if "conflict" in lim_str.lower()
                    else LimitationCategory.INCOMPLETE_CORRELATION,
                    description=lim_str[:4096],
                    affected_nodes=["risk_agent"],
                )
            )

        # Preserve exact score and level from Phase 7 — no modification
        risk_score = assessment.score  # uses property → overall_score.score
        risk_level = assessment.risk_level.value if assessment.risk_level else None
        fingerprint = assessment.fingerprint
        confidence = assessment.confidence

        return RiskAgentResult(
            risk_request_id=request.risk_request_id,
            organization_id=request.organization_id,
            status="COMPLETED",
            assessment_id=assessment.assessment_id,
            assessment_fingerprint=fingerprint,
            risk_score=risk_score,
            risk_level=risk_level,
            confidence=confidence,
            factor_count=len(assessment.factors),
            factor_ids=factor_ids,
            evidence_count=len(assessment.evidence),
            evidence_ids=evidence_ids,
            alert_ids=alert_ids,
            recommendation_ids=recommendation_ids,
            limitations=all_limitations,
            assessment=assessment,
            provenance={
                "research_id": request.research_id or "",
                "evidence_bundle_id": request.evidence_bundle_id or "",
                "signals_produced": len(signals),
                "translation_limitations": len(translation_limitations),
                "assessment_id": assessment.assessment_id,
                "assessment_scope": assessment.scope,
                "evaluation_id": getattr(
                    getattr(evaluation_result, "context", None), "evaluation_id", None
                ) or "",
            },
        )
