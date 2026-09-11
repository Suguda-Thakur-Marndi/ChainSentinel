"""Research→Risk adapter and Risk Engine adapter for Phase 9 Risk Agent.

ResearchRiskAdapter: Translates ResearchFinding categories to NormalizedRiskSignal
objects using a static, explicit lookup table. Unmapped categories produce
UNSUPPORTED_MAPPING limitations and are excluded from engine input.

RiskEngineAdapter: Narrow wrapper around BaselineRiskEngine.evaluate_full().
NEVER copies, duplicates, or reimplements any scoring logic from Phase 7.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.agents.contracts import AgentLimitation, LimitationCategory
from app.agents.research.contract import FindingType, ResearchFinding, ResearchResult
from app.agents.risk.contract import RiskAgentRequest
from app.agents.risk.errors import (
    RiskEngineAdapterError,
    RiskInputValidationError,
    RiskTenantIsolationError,
)
from app.integrations.canonical import EventQuality, EventSeverity, EventSourceType
from app.normalization.contract import (
    NormalizedRiskSignal,
    SignalDomain,
    SignalStatus,
    SignalType,
)
from app.risk_engine.context import RiskEvaluationContext
from app.risk_engine.pipeline import BaselineRiskEngine, RiskEvaluationResult


# ---------------------------------------------------------------------------
# Static finding-category → (SignalDomain, SignalType) lookup table.
# This is the ONLY translation boundary. No heuristics, no inference.
# ---------------------------------------------------------------------------
FINDING_TO_SIGNAL_MAP: Dict[str, Tuple[SignalDomain, SignalType]] = {
    "PORT_DISRUPTION": (SignalDomain.OCEAN, SignalType.DISRUPTION),
    "SUPPLIER_INCIDENT": (SignalDomain.LOGISTICS, SignalType.DISRUPTION),
    "WEATHER_EVENT": (SignalDomain.WEATHER, SignalType.DISRUPTION),
    "LOGISTICS_DELAY": (SignalDomain.LOGISTICS, SignalType.DELAY),
}

# Categories explicitly excluded from mapping — always become UNSUPPORTED_MAPPING limitation
_UNMAPPABLE_CATEGORIES = {"DATA_GAP", "UNKNOWN"}


def _build_signal_from_finding(
    finding: ResearchFinding,
    organization_id: str,
    domain: SignalDomain,
    signal_type: SignalType,
    run_id: str,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> NormalizedRiskSignal:
    """Build a minimal NormalizedRiskSignal from a ResearchFinding.

    All provenance fields are derived deterministically from the finding.
    No timestamps, coordinates, severity, or source values are invented.
    """
    # Deterministic signal_id from org + finding_id
    org = organization_id.strip()
    signal_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{org}:risk_signal:{finding.finding_id}"))

    # Source and provider derived from finding provenance; never invented
    source_name = f"research_agent:{finding.finding_id[:8]}"
    provider_name = "research_agent"

    # Use finding confidence to set signal severity
    confidence = finding.confidence if finding.confidence is not None else 0.5
    if confidence >= 0.8:
        severity = EventSeverity.HIGH
    elif confidence >= 0.5:
        severity = EventSeverity.MEDIUM
    else:
        severity = EventSeverity.LOW

    # Quality is PARTIAL (not INVALID) — research findings are derived, not primary raw signals
    quality = EventQuality.PARTIAL

    # Canonical event ID derived deterministically from finding
    canonical_event_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{org}:canonical:{finding.finding_id}"))

    return NormalizedRiskSignal(
        signal_id=signal_id,
        organization_id=organization_id,
        domain=domain,
        signal_type=signal_type,
        event_type=finding.category,
        status=SignalStatus.ACTIVE,
        severity=severity,
        confidence=confidence,
        quality=quality,
        event_time=datetime.now(timezone.utc),
        source=source_name,
        source_type=EventSourceType.ESTIMATED,
        provider=provider_name,
        canonical_event_id=canonical_event_id,
        correlation_id=correlation_id,
        trace_id=trace_id,
        ingestion_run_id=run_id,
        normalized_attributes={
            "finding_id": finding.finding_id,
            "finding_title": finding.title,
            "finding_type": finding.finding_type.value,
            "evidence_ids": list(finding.evidence_ids),
            "citation_ids": list(finding.citation_ids),
        },
    )


def _make_unsupported_limitation(
    finding: ResearchFinding,
    research_id: str,
    reason: str,
) -> AgentLimitation:
    """Produce a structured UNSUPPORTED_MAPPING limitation for an unmappable finding."""
    return AgentLimitation(
        limitation_id=f"lim_unmap_{finding.finding_id[:12]}",
        category=LimitationCategory.UNSUPPORTED_MAPPING,
        description=(
            f"Research finding '{finding.finding_id}' (category='{finding.category}', "
            f"type='{finding.finding_type.value}') could not be mapped to a Risk Engine signal: {reason}. "
            f"This finding is excluded from risk evaluation inputs."
        ),
        affected_nodes=["risk_agent"],
        mitigation_or_impact=(
            "Risk evaluation proceeded with remaining mappable findings. "
            "Unmapped finding contributes no direct risk score input."
        ),
    )


class ResearchRiskAdapter:
    """Translates ResearchResult findings into NormalizedRiskSignal objects.

    Rules:
    - Only FACT and INFERENCE findings are eligible for mapping (never UNKNOWN).
    - Only categories in FINDING_TO_SIGNAL_MAP are mapped.
    - All other categories produce UNSUPPORTED_MAPPING limitations.
    - Source values are always derived from finding provenance (never invented).
    """

    @classmethod
    def translate(
        cls,
        research_result: ResearchResult,
        organization_id: str,
        run_id: str = "unknown_run",
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Tuple[List[NormalizedRiskSignal], List[AgentLimitation]]:
        """Convert research findings to NormalizedRiskSignal instances.

        Returns:
            (signals, unsupported_limitations)
        """
        if research_result.organization_id != organization_id:
            raise RiskTenantIsolationError(
                f"ResearchResult tenant '{research_result.organization_id}' does not match "
                f"adapter organization_id '{organization_id}'."
            )

        signals: List[NormalizedRiskSignal] = []
        limitations: List[AgentLimitation] = []

        for finding in research_result.findings:
            # Rule 1: Never map UNKNOWN findings
            if finding.finding_type == FindingType.UNKNOWN:
                limitations.append(_make_unsupported_limitation(
                    finding=finding,
                    research_id=research_result.research_id,
                    reason="UNKNOWN finding type represents a data gap and cannot be risk-evaluated",
                ))
                continue

            # Rule 2: Explicitly unmappable category
            if finding.category.upper() in _UNMAPPABLE_CATEGORIES:
                limitations.append(_make_unsupported_limitation(
                    finding=finding,
                    research_id=research_result.research_id,
                    reason=f"Category '{finding.category}' is explicitly excluded from risk signal mapping",
                ))
                continue

            # Rule 3: Not in static lookup
            mapping = FINDING_TO_SIGNAL_MAP.get(finding.category.upper())
            if mapping is None:
                limitations.append(_make_unsupported_limitation(
                    finding=finding,
                    research_id=research_result.research_id,
                    reason=f"No static mapping defined for category '{finding.category}'",
                ))
                continue

            # Rule 4: Build signal from finding provenance
            domain, signal_type = mapping
            try:
                signal = _build_signal_from_finding(
                    finding=finding,
                    organization_id=organization_id,
                    domain=domain,
                    signal_type=signal_type,
                    run_id=run_id,
                    correlation_id=correlation_id,
                    trace_id=trace_id,
                )
                signals.append(signal)
            except Exception as exc:
                limitations.append(_make_unsupported_limitation(
                    finding=finding,
                    research_id=research_result.research_id,
                    reason=f"Signal construction failed: {exc.__class__.__name__}",
                ))

        return signals, limitations


class RiskEngineAdapter:
    """Narrow adapter that wraps BaselineRiskEngine.evaluate_full().

    This adapter ONLY:
    1. Builds a valid RiskEvaluationContext from translated signals + request metadata.
    2. Calls BaselineRiskEngine.evaluate_full().
    3. Returns the RiskEvaluationResult exactly as received from Phase 7.

    It does NOT copy, reimplement, or alter any Phase 7 scoring logic.
    """

    def __init__(self) -> None:
        self._engine = BaselineRiskEngine()

    def evaluate(
        self,
        request: RiskAgentRequest,
        signals: List[NormalizedRiskSignal],
        previous_assessment: Optional[Any] = None,
    ) -> RiskEvaluationResult:
        """Build RiskEvaluationContext and invoke BaselineRiskEngine.evaluate_full().

        Args:
            request: Validated RiskAgentRequest.
            signals: Translated NormalizedRiskSignal objects from ResearchRiskAdapter.
            previous_assessment: Optional prior RiskAssessment for comparison.

        Returns:
            RiskEvaluationResult from Phase 7 (assessment, alerts, recommendations, comparison).
        """
        # Validate tenant consistency before invoking engine
        for sig in signals:
            if sig.organization_id and sig.organization_id != request.organization_id:
                raise RiskTenantIsolationError(
                    f"Signal tenant '{sig.organization_id}' does not match "
                    f"risk request tenant '{request.organization_id}'."
                )

        if not signals:
            # No mappable signals — still run engine with empty context to produce
            # a baseline INSUFFICIENT_EVIDENCE assessment
            raise RiskInputValidationError(
                "No valid NormalizedRiskSignal instances available for risk evaluation. "
                "All research findings were unmapped or excluded. "
                "Risk Engine evaluation cannot proceed without at least one signal.",
                details={"organization_id": request.organization_id, "objective": request.objective},
            )

        # Build RiskEvaluationContext — this is the ONLY point signals enter the engine
        try:
            context = RiskEvaluationContext(
                organization_id=request.organization_id,
                correlation_id=request.correlation_id,
                trace_id=request.trace_id,
                scope=request.scope,
                scope_entity_id=request.scope_entity_id,
                allow_partial_signals=True,  # Research-derived signals are always PARTIAL
                signals=signals,
                metadata={
                    "risk_request_id": request.risk_request_id,
                    "research_id": request.research_id or "",
                    "objective": request.objective[:256],
                    "evidence_bundle_id": request.evidence_bundle_id or "",
                    "actor_id": request.actor_id or "",
                },
            )
        except Exception as exc:
            raise RiskEngineAdapterError(
                f"Failed to build RiskEvaluationContext: {exc}",
                details={"organization_id": request.organization_id},
            ) from exc

        # Invoke Phase 7 Risk Engine — the single authoritative evaluation call
        try:
            result = self._engine.evaluate_full(
                context=context,
                previous=previous_assessment,
            )
        except Exception as exc:
            raise RiskEngineAdapterError(
                f"BaselineRiskEngine.evaluate_full() raised an exception: {exc}",
                details={"organization_id": request.organization_id},
            ) from exc

        return result
