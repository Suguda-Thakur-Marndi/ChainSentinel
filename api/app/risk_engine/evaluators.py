"""Deterministic domain baseline risk factor evaluators for RiskWise 2.0.

Provides provider-independent evaluators for weather, road, port, maritime,
air, rail, logistics, intelligence, and general domains.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.integrations.canonical import EventSeverity
from app.normalization.contract import (
    NormalizedRiskSignal,
    SignalDomain,
    SignalStatus,
    SignalType,
)
from app.risk_engine.context import RiskEvaluationContext
from app.risk_engine.contract import (
    RiskFactor,
    RiskLevel,
    generate_deterministic_factor_id,
)
from app.risk_engine.evidence import RiskEvidence
from app.risk_engine.registry import BaseRiskFactorEvaluator, RiskFactorRegistry
from app.risk_engine.scoring import (
    SEVERITY_TO_RISK_LEVEL,
    compute_factor_contribution,
)

logger = logging.getLogger("riskwise.risk_engine.evaluators")


def _is_benign_status(signal: NormalizedRiskSignal) -> bool:
    """Check if signal represents a purely routine/normal status update with no adverse indicators."""
    return (
        signal.severity == EventSeverity.INFO
        and signal.status == SignalStatus.NORMAL
        and not getattr(signal, "has_conflict", False)
        and (
            signal.measurements is None
            or (
                (signal.measurements.delay_minutes is None or signal.measurements.delay_minutes <= 0.0)
                and (signal.measurements.disruption_level is None or signal.measurements.disruption_level <= 0.0)
            )
        )
    )


# =============================================================================
# 1. Weather Risk Factor Evaluator
# =============================================================================

class WeatherRiskFactorEvaluator(BaseRiskFactorEvaluator):
    """Evaluates adverse weather conditions, storms, cyclones, and extreme temperatures."""

    @property
    def evaluator_id(self) -> str:
        return "evaluator.baseline.weather"

    @property
    def name(self) -> str:
        return "Baseline Weather Risk Evaluator"

    @property
    def target_domains(self) -> List[SignalDomain]:
        return [SignalDomain.WEATHER]

    def evaluate(
        self,
        signal: NormalizedRiskSignal,
        context: RiskEvaluationContext,
    ) -> Optional[RiskFactor]:
        if _is_benign_status(signal):
            return None

        # Check for meaningful weather hazards
        meas = signal.measurements
        is_hazard = signal.signal_type in (SignalType.HAZARD, SignalType.DISRUPTION, SignalType.INCIDENT)
        has_disruption = meas and meas.disruption_level and meas.disruption_level > 0.20
        high_wind = meas and meas.speed_kmh and meas.speed_kmh >= 60.0
        extreme_temp = meas and meas.temperature_celsius and (meas.temperature_celsius < -20.0 or meas.temperature_celsius > 45.0)

        if not (is_hazard or has_disruption or high_wind or extreme_temp or signal.severity != EventSeverity.INFO):
            return None

        contribution, meta = compute_factor_contribution(signal)
        severity = SEVERITY_TO_RISK_LEVEL.get(signal.severity, RiskLevel.MEDIUM)
        evidence = [RiskEvidence.from_normalized_signal(signal, organization_id=context.organization_id)]
        factor_id = generate_deterministic_factor_id(
            organization_id=context.organization_id,
            factor_type="WEATHER_DISRUPTION",
            evidence_ids=[ev.evidence_id for ev in evidence],
        )

        loc = signal.location_name or "operational region"
        reason = f"Weather event '{signal.event_type}' at {loc} with severity {signal.severity.value}."

        meta["reason"] = reason
        meta["weather_indicators"] = {
            "high_wind": bool(high_wind),
            "extreme_temperature": bool(extreme_temp),
            "disruption_level": meas.disruption_level if meas else None,
        }

        return RiskFactor(
            factor_id=factor_id,
            factor_type="WEATHER_DISRUPTION",
            domain=SignalDomain.WEATHER,
            name=f"Weather Disruption: {signal.event_type.replace('_', ' ').title()}",
            description=reason,
            contribution=contribution,
            severity=severity,
            confidence=signal.confidence,
            organization_id=context.organization_id,
            evidence=evidence,
            metadata=meta,
        )


# =============================================================================
# 2. Road Risk Factor Evaluator
# =============================================================================

class RoadRiskFactorEvaluator(BaseRiskFactorEvaluator):
    """Evaluates highway closures, major road incidents, and severe traffic congestion."""

    @property
    def evaluator_id(self) -> str:
        return "evaluator.baseline.road"

    @property
    def name(self) -> str:
        return "Baseline Road Risk Evaluator"

    @property
    def target_domains(self) -> List[SignalDomain]:
        return [SignalDomain.ROAD]

    def evaluate(
        self,
        signal: NormalizedRiskSignal,
        context: RiskEvaluationContext,
    ) -> Optional[RiskFactor]:
        if _is_benign_status(signal):
            return None

        meas = signal.measurements
        delay_min = meas.delay_minutes if (meas and meas.delay_minutes) else 0.0
        is_incident = signal.signal_type in (SignalType.INCIDENT, SignalType.DISRUPTION, SignalType.CONGESTION, SignalType.DELAY)

        if not (is_incident or delay_min > 15.0 or signal.severity != EventSeverity.INFO):
            return None

        contribution, meta = compute_factor_contribution(signal)
        severity = SEVERITY_TO_RISK_LEVEL.get(signal.severity, RiskLevel.MEDIUM)
        evidence = [RiskEvidence.from_normalized_signal(signal, organization_id=context.organization_id)]
        factor_id = generate_deterministic_factor_id(
            organization_id=context.organization_id,
            factor_type="ROAD_DISRUPTION",
            evidence_ids=[ev.evidence_id for ev in evidence],
        )

        loc = signal.location_name or "evaluated corridor"
        delay_text = f" ({round(delay_min, 1)} min delay)" if delay_min > 0.0 else ""
        reason = f"Road incident '{signal.event_type}' at {loc}{delay_text} with severity {signal.severity.value}."
        meta["reason"] = reason
        meta["delay_minutes"] = delay_min

        return RiskFactor(
            factor_id=factor_id,
            factor_type="ROAD_DISRUPTION",
            domain=SignalDomain.ROAD,
            name=f"Road Disruption: {signal.event_type.replace('_', ' ').title()}",
            description=reason,
            contribution=contribution,
            severity=severity,
            confidence=signal.confidence,
            organization_id=context.organization_id,
            evidence=evidence,
            metadata=meta,
        )


# =============================================================================
# 3. Port Risk Factor Evaluator
# =============================================================================

class PortRiskFactorEvaluator(BaseRiskFactorEvaluator):
    """Evaluates maritime port closures, berth congestion, and maritime terminal delays."""

    @property
    def evaluator_id(self) -> str:
        return "evaluator.baseline.port"

    @property
    def name(self) -> str:
        return "Baseline Port Risk Evaluator"

    @property
    def target_domains(self) -> List[SignalDomain]:
        return [SignalDomain.OCEAN, SignalDomain.LOGISTICS]

    def can_evaluate(self, signal: NormalizedRiskSignal, context: RiskEvaluationContext) -> bool:
        if signal.domain not in self.target_domains:
            return False
        # Match port semantics: port in event type, port_id set, or location indicates port
        has_port_event = "PORT" in signal.event_type.upper()
        has_port_id = bool(getattr(signal.entities, "port_id", None))
        has_port_loc = "PORT" in (signal.location_name or "").upper() or "TERMINAL" in (signal.location_name or "").upper()
        return has_port_event or has_port_id or has_port_loc

    def evaluate(
        self,
        signal: NormalizedRiskSignal,
        context: RiskEvaluationContext,
    ) -> Optional[RiskFactor]:
        if _is_benign_status(signal):
            return None

        meas = signal.measurements
        delay_min = meas.delay_minutes if (meas and meas.delay_minutes) else 0.0
        disruption_lvl = meas.disruption_level if (meas and meas.disruption_level) else 0.0

        if delay_min <= 0.0 and disruption_lvl <= 0.0 and signal.severity == EventSeverity.INFO:
            return None

        contribution, meta = compute_factor_contribution(signal)
        severity = SEVERITY_TO_RISK_LEVEL.get(signal.severity, RiskLevel.MEDIUM)
        evidence = [RiskEvidence.from_normalized_signal(signal, organization_id=context.organization_id)]
        factor_id = generate_deterministic_factor_id(
            organization_id=context.organization_id,
            factor_type="PORT_DISRUPTION",
            evidence_ids=[ev.evidence_id for ev in evidence],
        )

        port_name = signal.location_name or (signal.entities.port_id if signal.entities else "marine terminal")
        reason = f"Port operational bottleneck at {port_name}: {signal.event_type} (severity: {signal.severity.value})."
        meta["reason"] = reason
        meta["delay_minutes"] = delay_min

        return RiskFactor(
            factor_id=factor_id,
            factor_type="PORT_DISRUPTION",
            domain=SignalDomain.OCEAN,
            name=f"Port Disruption: {signal.event_type.replace('_', ' ').title()}",
            description=reason,
            contribution=contribution,
            severity=severity,
            confidence=signal.confidence,
            organization_id=context.organization_id,
            evidence=evidence,
            metadata=meta,
        )


# =============================================================================
# 4. Maritime / Ocean Risk Factor Evaluator
# =============================================================================

class MaritimeRiskFactorEvaluator(BaseRiskFactorEvaluator):
    """Evaluates vessel hazards, navigation warnings, and maritime casualties.

    Routine AIS position pings are classified as benign and do not produce risk factors.
    """

    @property
    def evaluator_id(self) -> str:
        return "evaluator.baseline.maritime"

    @property
    def name(self) -> str:
        return "Baseline Maritime Risk Evaluator"

    @property
    def target_domains(self) -> List[SignalDomain]:
        return [SignalDomain.OCEAN]

    def can_evaluate(self, signal: NormalizedRiskSignal, context: RiskEvaluationContext) -> bool:
        if signal.domain != SignalDomain.OCEAN:
            return False
        # Pure port events are evaluated by PortRiskFactorEvaluator
        if "PORT" in signal.event_type.upper():
            return False
        return True

    def evaluate(
        self,
        signal: NormalizedRiskSignal,
        context: RiskEvaluationContext,
    ) -> Optional[RiskFactor]:
        # Routine AIS pings without adverse events are benign
        if signal.signal_type == SignalType.STATUS_UPDATE and signal.severity == EventSeverity.INFO:
            return None
        if _is_benign_status(signal):
            return None

        is_hazard = signal.signal_type in (SignalType.HAZARD, SignalType.INCIDENT, SignalType.DISRUPTION, SignalType.DELAY)
        if not (is_hazard or signal.severity != EventSeverity.INFO):
            return None

        contribution, meta = compute_factor_contribution(signal)
        severity = SEVERITY_TO_RISK_LEVEL.get(signal.severity, RiskLevel.MEDIUM)
        evidence = [RiskEvidence.from_normalized_signal(signal, organization_id=context.organization_id)]
        factor_id = generate_deterministic_factor_id(
            organization_id=context.organization_id,
            factor_type="MARITIME_DISRUPTION",
            evidence_ids=[ev.evidence_id for ev in evidence],
        )

        vessel_ref = signal.entities.carrier_id if signal.entities else "vessel"
        reason = f"Maritime disruption for {vessel_ref}: {signal.event_type} ({signal.severity.value})."
        meta["reason"] = reason

        return RiskFactor(
            factor_id=factor_id,
            factor_type="MARITIME_DISRUPTION",
            domain=SignalDomain.OCEAN,
            name=f"Maritime Hazard: {signal.event_type.replace('_', ' ').title()}",
            description=reason,
            contribution=contribution,
            severity=severity,
            confidence=signal.confidence,
            organization_id=context.organization_id,
            evidence=evidence,
            metadata=meta,
        )


# =============================================================================
# 5. Air Freight Risk Factor Evaluator
# =============================================================================

class AirRiskFactorEvaluator(BaseRiskFactorEvaluator):
    """Evaluates air cargo flight cancellations, airport ground stops, and flight delays.

    Routine aircraft position tracking updates are classified as benign.
    """

    @property
    def evaluator_id(self) -> str:
        return "evaluator.baseline.air"

    @property
    def name(self) -> str:
        return "Baseline Air Risk Evaluator"

    @property
    def target_domains(self) -> List[SignalDomain]:
        return [SignalDomain.AIR]

    def evaluate(
        self,
        signal: NormalizedRiskSignal,
        context: RiskEvaluationContext,
    ) -> Optional[RiskFactor]:
        if signal.signal_type == SignalType.STATUS_UPDATE and signal.severity == EventSeverity.INFO:
            return None
        if _is_benign_status(signal):
            return None

        meas = signal.measurements
        delay_min = meas.delay_minutes if (meas and meas.delay_minutes) else 0.0
        is_disruption = signal.signal_type in (SignalType.DISRUPTION, SignalType.DELAY, SignalType.INCIDENT)

        if not (is_disruption or delay_min > 30.0 or signal.severity in (EventSeverity.HIGH, EventSeverity.CRITICAL)):
            return None

        contribution, meta = compute_factor_contribution(signal)
        severity = SEVERITY_TO_RISK_LEVEL.get(signal.severity, RiskLevel.MEDIUM)
        evidence = [RiskEvidence.from_normalized_signal(signal, organization_id=context.organization_id)]
        factor_id = generate_deterministic_factor_id(
            organization_id=context.organization_id,
            factor_type="AIR_DISRUPTION",
            evidence_ids=[ev.evidence_id for ev in evidence],
        )

        reason = f"Aviation disruption: {signal.event_type} with delay {round(delay_min, 1)}m ({signal.severity.value})."
        meta["reason"] = reason
        meta["delay_minutes"] = delay_min

        return RiskFactor(
            factor_id=factor_id,
            factor_type="AIR_DISRUPTION",
            domain=SignalDomain.AIR,
            name=f"Aviation Delay: {signal.event_type.replace('_', ' ').title()}",
            description=reason,
            contribution=contribution,
            severity=severity,
            confidence=signal.confidence,
            organization_id=context.organization_id,
            evidence=evidence,
            metadata=meta,
        )


# =============================================================================
# 6. Rail Risk Factor Evaluator
# =============================================================================

class RailRiskFactorEvaluator(BaseRiskFactorEvaluator):
    """Evaluates freight rail delays, derailments, and track disruptions."""

    @property
    def evaluator_id(self) -> str:
        return "evaluator.baseline.rail"

    @property
    def name(self) -> str:
        return "Baseline Rail Risk Evaluator"

    @property
    def target_domains(self) -> List[SignalDomain]:
        return [SignalDomain.RAIL]

    def evaluate(
        self,
        signal: NormalizedRiskSignal,
        context: RiskEvaluationContext,
    ) -> Optional[RiskFactor]:
        if _is_benign_status(signal):
            return None

        meas = signal.measurements
        delay_min = meas.delay_minutes if (meas and meas.delay_minutes) else 0.0
        is_adverse = signal.signal_type in (SignalType.DISRUPTION, SignalType.DELAY, SignalType.INCIDENT, SignalType.HAZARD)

        if not (is_adverse or delay_min > 20.0 or signal.severity != EventSeverity.INFO):
            return None

        contribution, meta = compute_factor_contribution(signal)
        severity = SEVERITY_TO_RISK_LEVEL.get(signal.severity, RiskLevel.MEDIUM)
        evidence = [RiskEvidence.from_normalized_signal(signal, organization_id=context.organization_id)]
        factor_id = generate_deterministic_factor_id(
            organization_id=context.organization_id,
            factor_type="RAIL_DISRUPTION",
            evidence_ids=[ev.evidence_id for ev in evidence],
        )

        loc = signal.location_name or "rail corridor"
        reason = f"Rail service disruption: {signal.event_type} along {loc} ({signal.severity.value})."
        meta["reason"] = reason
        meta["delay_minutes"] = delay_min

        return RiskFactor(
            factor_id=factor_id,
            factor_type="RAIL_DISRUPTION",
            domain=SignalDomain.RAIL,
            name=f"Rail Disruption: {signal.event_type.replace('_', ' ').title()}",
            description=reason,
            contribution=contribution,
            severity=severity,
            confidence=signal.confidence,
            organization_id=context.organization_id,
            evidence=evidence,
            metadata=meta,
        )


# =============================================================================
# 7. Logistics & Shipment Tracking Risk Factor Evaluator
# =============================================================================

class LogisticsRiskFactorEvaluator(BaseRiskFactorEvaluator):
    """Evaluates shipment delays, delivery exceptions, and milestone anomalies."""

    @property
    def evaluator_id(self) -> str:
        return "evaluator.baseline.logistics"

    @property
    def name(self) -> str:
        return "Baseline Logistics Risk Evaluator"

    @property
    def target_domains(self) -> List[SignalDomain]:
        return [SignalDomain.LOGISTICS]

    def can_evaluate(self, signal: NormalizedRiskSignal, context: RiskEvaluationContext) -> bool:
        if signal.domain != SignalDomain.LOGISTICS:
            return False
        # Ignore port events handled by port evaluator
        if "PORT" in signal.event_type.upper():
            return False
        return True

    def evaluate(
        self,
        signal: NormalizedRiskSignal,
        context: RiskEvaluationContext,
    ) -> Optional[RiskFactor]:
        if _is_benign_status(signal):
            return None

        meas = signal.measurements
        delay_min = meas.delay_minutes if (meas and meas.delay_minutes) else 0.0
        is_exception = signal.status in (SignalStatus.DELAYED, SignalStatus.DISRUPTED) or signal.signal_type in (
            SignalType.DELAY,
            SignalType.DISRUPTION,
            SignalType.INCIDENT,
        )

        if not (is_exception or delay_min > 30.0 or signal.severity != EventSeverity.INFO):
            return None

        contribution, meta = compute_factor_contribution(signal)
        severity = SEVERITY_TO_RISK_LEVEL.get(signal.severity, RiskLevel.MEDIUM)
        evidence = [RiskEvidence.from_normalized_signal(signal, organization_id=context.organization_id)]
        factor_id = generate_deterministic_factor_id(
            organization_id=context.organization_id,
            factor_type="SHIPMENT_DELAY",
            evidence_ids=[ev.evidence_id for ev in evidence],
        )

        shipment_ref = signal.entities.shipment_id if signal.entities else "parcel"
        reason = f"Logistics delay/exception on {shipment_ref}: {signal.event_type} ({round(delay_min, 1)}m delay)."
        meta["reason"] = reason
        meta["delay_minutes"] = delay_min

        return RiskFactor(
            factor_id=factor_id,
            factor_type="SHIPMENT_DELAY",
            domain=SignalDomain.LOGISTICS,
            name=f"Shipment Delay: {signal.event_type.replace('_', ' ').title()}",
            description=reason,
            contribution=contribution,
            severity=severity,
            confidence=signal.confidence,
            organization_id=context.organization_id,
            evidence=evidence,
            metadata=meta,
        )


# =============================================================================
# 8. Intelligence & Geopolitical Risk Factor Evaluator
# =============================================================================

class IntelligenceRiskFactorEvaluator(BaseRiskFactorEvaluator):
    """Evaluates news intelligence, labor strikes, and geopolitical notices conservatively."""

    @property
    def evaluator_id(self) -> str:
        return "evaluator.baseline.intelligence"

    @property
    def name(self) -> str:
        return "Baseline Intelligence Risk Evaluator"

    @property
    def target_domains(self) -> List[SignalDomain]:
        return [SignalDomain.INTELLIGENCE]

    def evaluate(
        self,
        signal: NormalizedRiskSignal,
        context: RiskEvaluationContext,
    ) -> Optional[RiskFactor]:
        # News articles must NOT automatically produce high risk scores without strong severity
        if signal.severity in (EventSeverity.INFO, EventSeverity.LOW):
            return None

        contribution, meta = compute_factor_contribution(signal)
        # Apply conservative research weighting (15% discount for unstructured open-source intelligence)
        contribution = round(contribution * 0.85, 4)
        meta["intelligence_conservative_discount"] = 0.85
        meta["calculated_contribution"] = contribution

        severity = SEVERITY_TO_RISK_LEVEL.get(signal.severity, RiskLevel.MEDIUM)
        evidence = [RiskEvidence.from_normalized_signal(signal, organization_id=context.organization_id)]
        factor_id = generate_deterministic_factor_id(
            organization_id=context.organization_id,
            factor_type="GEOPOLITICAL_ALERT",
            evidence_ids=[ev.evidence_id for ev in evidence],
        )

        reason = f"Intelligence notice: {signal.event_type} ({signal.severity.value}) from {signal.provider}."
        meta["reason"] = reason

        return RiskFactor(
            factor_id=factor_id,
            factor_type="GEOPOLITICAL_ALERT",
            domain=SignalDomain.INTELLIGENCE,
            name=f"Intelligence Alert: {signal.event_type.replace('_', ' ').title()}",
            description=reason,
            contribution=contribution,
            severity=severity,
            confidence=signal.confidence,
            organization_id=context.organization_id,
            evidence=evidence,
            metadata=meta,
        )


# =============================================================================
# 9. General / Fallback Risk Factor Evaluator
# =============================================================================

class GeneralRiskFactorEvaluator(BaseRiskFactorEvaluator):
    """Safe fallback evaluator for general supply chain conditions."""

    @property
    def evaluator_id(self) -> str:
        return "evaluator.baseline.general"

    @property
    def name(self) -> str:
        return "Baseline General Risk Evaluator"

    @property
    def target_domains(self) -> List[SignalDomain]:
        return [SignalDomain.GENERAL]

    def evaluate(
        self,
        signal: NormalizedRiskSignal,
        context: RiskEvaluationContext,
    ) -> Optional[RiskFactor]:
        if signal.severity == EventSeverity.INFO or signal.status == SignalStatus.NORMAL:
            return None

        contribution, meta = compute_factor_contribution(signal)
        severity = SEVERITY_TO_RISK_LEVEL.get(signal.severity, RiskLevel.LOW)
        evidence = [RiskEvidence.from_normalized_signal(signal, organization_id=context.organization_id)]
        factor_id = generate_deterministic_factor_id(
            organization_id=context.organization_id,
            factor_type="OPERATIONAL_ANOMALY",
            evidence_ids=[ev.evidence_id for ev in evidence],
        )

        reason = f"General operational anomaly: {signal.event_type} ({signal.severity.value})."
        meta["reason"] = reason

        return RiskFactor(
            factor_id=factor_id,
            factor_type="OPERATIONAL_ANOMALY",
            domain=SignalDomain.GENERAL,
            name=f"Operational Anomaly: {signal.event_type.replace('_', ' ').title()}",
            description=reason,
            contribution=contribution,
            severity=severity,
            confidence=signal.confidence,
            organization_id=context.organization_id,
            evidence=evidence,
            metadata=meta,
        )


# =============================================================================
# Helper: Register All Baseline Evaluators
# =============================================================================

def register_baseline_evaluators(registry: RiskFactorRegistry) -> None:
    """Register all 9 provider-independent baseline evaluators into a registry."""
    evaluators = [
        WeatherRiskFactorEvaluator(),
        RoadRiskFactorEvaluator(),
        PortRiskFactorEvaluator(),
        MaritimeRiskFactorEvaluator(),
        AirRiskFactorEvaluator(),
        RailRiskFactorEvaluator(),
        LogisticsRiskFactorEvaluator(),
        IntelligenceRiskFactorEvaluator(),
        GeneralRiskFactorEvaluator(),
    ]
    for ev in evaluators:
        registry.register(ev, overwrite=True)
