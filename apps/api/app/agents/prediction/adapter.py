"""Deterministic feature extractor for the Prediction Agent.

CRITICAL ARCHITECTURAL BOUNDARY:
Research prose must NEVER automatically become a numeric ML feature.
All features must be derived via explicit, deterministic transformations
from authoritative RiskAssessment references, structured findings, or validated inputs.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.agents.contracts import AgentFinding, AgentGraphStateDict, AgentLimitation, LimitationCategory
from app.agents.prediction.contract import PredictionFeature
from app.agents.prediction.errors import FeatureValidationError, PredictionTenantIsolationError


RISK_LEVEL_SEVERITY_MAP = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


class PredictionFeatureExtractor:
    """Extracts strongly typed PredictionFeature objects from validated upstream graph state."""

    @staticmethod
    def extract_features(
        state: AgentGraphStateDict,
        organization_id: str,
    ) -> Tuple[List[PredictionFeature], List[AgentLimitation]]:
        """Extract deterministic features from state.

        Returns:
            Tuple of (extracted_features, limitations)
        """
        if not organization_id or not organization_id.strip():
            raise PredictionTenantIsolationError("organization_id must be non-empty for feature extraction.")

        state_org = state.get("organization_id", "").strip()
        if state_org and state_org != organization_id.strip():
            raise PredictionTenantIsolationError(
                f"State organization_id '{state_org}' does not match requested organization_id '{organization_id}'."
            )

        features: List[PredictionFeature] = []
        limitations: List[AgentLimitation] = []

        # 1. Extract from Authoritative Risk Assessment
        risk_ref = state.get("risk_assessment_reference") or state.get("risk_assessment")
        risk_score = None
        risk_level = None
        factor_count = 0
        risk_ev_ids: List[str] = []

        if isinstance(risk_ref, dict):
            ref_org = risk_ref.get("organization_id")
            if ref_org and ref_org != organization_id:
                raise PredictionTenantIsolationError(
                    f"Risk assessment reference belongs to tenant '{ref_org}', not '{organization_id}'."
                )

            risk_score = risk_ref.get("risk_score")
            risk_level = risk_ref.get("risk_level")
            factor_count = risk_ref.get("factor_count", 0)
            risk_ev_ids = risk_ref.get("evidence_ids") or state.get("evidence_references", [])
            assessment_id = risk_ref.get("assessment_id", "unknown_assessment")

            if risk_score is not None and isinstance(risk_score, (int, float)):
                if math.isnan(risk_score) or math.isinf(risk_score):
                    raise FeatureValidationError("risk_composite_score feature value is non-finite.")
                features.append(
                    PredictionFeature(
                        feature_name="risk_composite_score",
                        value=float(risk_score),
                        unit="score",
                        source=f"RiskAssessment:{assessment_id}",
                        source_type="RISK_ENGINE",
                        timestamp=datetime.now(timezone.utc),
                        evidence_references=risk_ev_ids,
                        organization_id=organization_id,
                        provenance={"field": "risk_score", "assessment_id": assessment_id},
                    )
                )

            if risk_level and isinstance(risk_level, str):
                severity_val = RISK_LEVEL_SEVERITY_MAP.get(risk_level.upper())
                if severity_val is not None:
                    features.append(
                        PredictionFeature(
                            feature_name="risk_level_severity",
                            value=severity_val,
                            unit="rank",
                            source=f"RiskAssessment:{assessment_id}",
                            source_type="RISK_ENGINE",
                            timestamp=datetime.now(timezone.utc),
                            evidence_references=risk_ev_ids,
                            organization_id=organization_id,
                            provenance={"field": "risk_level", "raw_level": risk_level},
                        )
                    )

            if isinstance(factor_count, int) and factor_count >= 0:
                features.append(
                    PredictionFeature(
                        feature_name="risk_factor_count",
                        value=factor_count,
                        unit="count",
                        source=f"RiskAssessment:{assessment_id}",
                        source_type="RISK_ENGINE",
                        timestamp=datetime.now(timezone.utc),
                        evidence_references=risk_ev_ids,
                        organization_id=organization_id,
                        provenance={"field": "factor_count"},
                    )
                )

        # 2. Extract deterministic indicators from structured findings
        structured_findings = state.get("structured_findings", [])
        port_disruption = False
        logistics_delay = False
        weather_disruption = False
        confidences: List[float] = []
        finding_ev_ids: List[str] = []

        for f in structured_findings:
            if isinstance(f, dict):
                category = str(f.get("category", "")).upper()
                ev_ids = f.get("evidence_ids", [])
                finding_ev_ids.extend(ev_ids)
                conf = f.get("confidence")
                if conf is not None and isinstance(conf, (int, float)):
                    if not math.isnan(conf) and not math.isinf(conf):
                        confidences.append(float(conf))

                if "PORT" in category or "CONGESTION" in category or "PORT_DISRUPTION" in category:
                    port_disruption = True
                if "LOGISTICS" in category or "DELAY" in category or "TRANSIT" in category:
                    logistics_delay = True
                if "WEATHER" in category or "STORM" in category:
                    weather_disruption = True

        if structured_findings:
            features.append(
                PredictionFeature(
                    feature_name="port_disruption_detected",
                    value=1.0 if port_disruption else 0.0,
                    unit="binary",
                    source="StructuredFindings",
                    source_type="RESEARCH_AGENT",
                    timestamp=datetime.now(timezone.utc),
                    evidence_references=sorted(list(set(finding_ev_ids))),
                    organization_id=organization_id,
                    provenance={"detection_rule": "PORT/CONGESTION keyword in finding categories"},
                )
            )
            features.append(
                PredictionFeature(
                    feature_name="logistics_delay_detected",
                    value=1.0 if logistics_delay else 0.0,
                    unit="binary",
                    source="StructuredFindings",
                    source_type="RESEARCH_AGENT",
                    timestamp=datetime.now(timezone.utc),
                    evidence_references=sorted(list(set(finding_ev_ids))),
                    organization_id=organization_id,
                    provenance={"detection_rule": "LOGISTICS/DELAY keyword in finding categories"},
                )
            )
            features.append(
                PredictionFeature(
                    feature_name="weather_disruption_detected",
                    value=1.0 if weather_disruption else 0.0,
                    unit="binary",
                    source="StructuredFindings",
                    source_type="RESEARCH_AGENT",
                    timestamp=datetime.now(timezone.utc),
                    evidence_references=sorted(list(set(finding_ev_ids))),
                    organization_id=organization_id,
                    provenance={"detection_rule": "WEATHER keyword in finding categories"},
                )
            )
            if confidences:
                avg_conf = sum(confidences) / len(confidences)
                features.append(
                    PredictionFeature(
                        feature_name="disruption_confidence_avg",
                        value=round(avg_conf, 4),
                        unit="ratio",
                        source="StructuredFindings",
                        source_type="RESEARCH_AGENT",
                        timestamp=datetime.now(timezone.utc),
                        evidence_references=sorted(list(set(finding_ev_ids))),
                        organization_id=organization_id,
                        provenance={"sample_count": len(confidences)},
                    )
                )

        # 3. Extract from input_references if valid numeric transit duration present
        input_refs = state.get("input_references", {})
        if isinstance(input_refs, dict):
            transit_hours = input_refs.get("scheduled_transit_hours")
            if transit_hours is not None and isinstance(transit_hours, (int, float)):
                if not math.isnan(transit_hours) and not math.isinf(transit_hours) and transit_hours > 0:
                    features.append(
                        PredictionFeature(
                            feature_name="scheduled_transit_hours",
                            value=float(transit_hours),
                            unit="hours",
                            source="InputReferences",
                            source_type="OPERATIONAL_DATA",
                            timestamp=datetime.now(timezone.utc),
                            evidence_references=[],
                            organization_id=organization_id,
                            provenance={"field": "scheduled_transit_hours"},
                        )
                    )

        # Check sufficiency: if no features could be extracted
        if not features:
            limitations.append(
                AgentLimitation(
                    limitation_id=f"lim-insuff-feat-{organization_id[:8]}",
                    category=LimitationCategory.INSUFFICIENT_FEATURES,
                    description="No usable numeric risk scores, structured findings, or operational inputs available for feature extraction.",
                    affected_nodes=["prediction_agent"],
                    mitigation_or_impact="Ensure Research and Risk Agent steps execute before Prediction Agent.",
                )
            )

        return features, limitations
