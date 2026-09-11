"""Persistence boundary and mapping adapter for Risk Engine domain contracts.

Translates between pure domain objects (RiskAssessment, RiskFactor, RiskEvidence, RiskScore)
and SQLAlchemy ORM models (RiskAssessment, RiskFactor, Risk) without introducing database
session dependencies into the core Risk Engine.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.integrations.canonical import EventQuality, EventSourceType
from app.models.risk import Risk as ORMRisk
from app.models.risk import RiskAssessment as ORMRiskAssessment
from app.models.risk import RiskFactor as ORMRiskFactor
from app.normalization.contract import EntityType, SignalDomain
from app.risk_engine.contract import (
    AssessmentSourceSummary,
    FactorContribution,
    RiskAssessment,
    RiskFactor,
    RiskLevel,
    RiskScore,
)
from app.risk_engine.evidence import EvidenceRelevance, RiskEvidence
from app.risk_engine.explainability import RiskExplanation

logger = logging.getLogger("riskwise.risk_engine.persistence")

# Blocklist of sensitive keys to scrub from persisted evidence metadata
SENSITIVE_KEY_PATTERNS = {
    "authorization",
    "auth",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "secret",
    "client_secret",
    "password",
    "passwd",
    "credential",
    "credentials",
    "private_key",
    "cookie",
}


def scrub_secrets(data: Any) -> Any:
    """Recursively scrub any sensitive keys, credentials, or secrets from dictionaries/lists."""
    if isinstance(data, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in data.items():
            k_lower = str(k).lower().strip()
            if any(pattern in k_lower for pattern in SENSITIVE_KEY_PATTERNS):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = scrub_secrets(v)
        return cleaned
    elif isinstance(data, list):
        return [scrub_secrets(item) for item in data]
    return data


class RiskAssessmentPersistenceAdapter:
    """Pure domain-to-ORM and ORM-to-domain mapping adapter for Risk Engine entities."""

    @classmethod
    def serialize_evidence(cls, evidence: RiskEvidence) -> Dict[str, Any]:
        """Convert a RiskEvidence domain object to a sanitized, persisted JSON dictionary."""
        loc = evidence.location or {}
        loc_dict = loc if isinstance(loc, dict) else {}
        return {
            "evidence_id": evidence.evidence_id,
            "organization_id": evidence.organization_id,
            "normalized_signal_id": evidence.normalized_signal_id,
            "signal_id": evidence.normalized_signal_id,
            "factor_id": evidence.factor_id,
            "domain": evidence.domain.value if hasattr(evidence.domain, "value") else str(evidence.domain),
            "relevance": evidence.relevance.value if hasattr(evidence.relevance, "value") else str(evidence.relevance),
            "source": evidence.source,
            "provider": evidence.provider,
            "source_type": evidence.source_type.value if hasattr(evidence.source_type, "value") else str(evidence.source_type),
            "quality": evidence.quality.value if hasattr(evidence.quality, "value") else str(evidence.quality),
            "confidence": evidence.confidence,
            "location": loc_dict,
            "location_name": loc_dict.get("location_name") or evidence.location_name,
            "latitude": loc_dict.get("latitude") if loc_dict.get("latitude") is not None else evidence.latitude,
            "longitude": loc_dict.get("longitude") if loc_dict.get("longitude") is not None else evidence.longitude,
            "event_time": evidence.event_time.isoformat() if isinstance(evidence.event_time, datetime) else str(evidence.event_time),
            "observed_at": evidence.event_time.isoformat() if isinstance(evidence.event_time, datetime) else str(evidence.event_time),
            "has_conflict": evidence.has_conflict,
            "conflicts": scrub_secrets(copy.deepcopy(evidence.conflicts)),
            "limitations": list(evidence.limitations),
            "metadata": scrub_secrets(copy.deepcopy(evidence.metadata)),
        }

    @classmethod
    def deserialize_evidence(cls, data: Dict[str, Any]) -> RiskEvidence:
        """Reconstruct a pure RiskEvidence domain object from a persisted dictionary."""
        event_time = data.get("event_time") or data.get("observed_at")
        if isinstance(event_time, str):
            try:
                event_time_dt = datetime.fromisoformat(event_time)
            except Exception:
                event_time_dt = datetime.now(timezone.utc)
        elif isinstance(event_time, datetime):
            event_time_dt = event_time
        else:
            event_time_dt = datetime.now(timezone.utc)

        domain_str = data.get("domain", "LOGISTICS")
        try:
            domain = SignalDomain(domain_str)
        except Exception:
            domain = SignalDomain.LOGISTICS

        rel_val = data.get("relevance", "CORROBORATING")
        if isinstance(rel_val, str):
            try:
                relevance = EvidenceRelevance(rel_val)
            except Exception:
                relevance = EvidenceRelevance.CORROBORATING
        else:
            relevance = rel_val

        source_type_val = data.get("source_type", "REAL")
        if isinstance(source_type_val, str):
            try:
                source_type = EventSourceType(source_type_val)
            except Exception:
                source_type = EventSourceType.REAL
        else:
            source_type = source_type_val

        quality_val = data.get("quality", "VALID")
        if isinstance(quality_val, str):
            try:
                quality = EventQuality(quality_val)
            except Exception:
                quality = EventQuality.VALID
        else:
            quality = quality_val

        sig_id = data.get("normalized_signal_id") or data.get("signal_id", "sig_unknown")
        location_data = data.get("location")
        if location_data is None:
            if data.get("location_name") or data.get("latitude") is not None or data.get("longitude") is not None:
                location_data = {
                    "location_name": data.get("location_name"),
                    "latitude": data.get("latitude"),
                    "longitude": data.get("longitude"),
                }

        return RiskEvidence(
            evidence_id=data["evidence_id"],
            normalized_signal_id=sig_id,
            organization_id=data.get("organization_id"),
            factor_id=data.get("factor_id"),
            source=data.get("source", "UNKNOWN"),
            provider=data.get("provider", "UNKNOWN"),
            source_type=source_type,
            event_time=event_time_dt,
            relevance=relevance,
            quality=quality,
            confidence=float(data.get("confidence", 1.0)),
            location=location_data,
            has_conflict=bool(data.get("has_conflict", False)),
            conflicts=data.get("conflicts", []),
            limitations=data.get("limitations", []),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def serialize_factor(cls, factor: RiskFactor) -> Dict[str, Any]:
        """Convert a RiskFactor domain object to a persisted dictionary."""
        serialized_evidence = [cls.serialize_evidence(e) for e in factor.evidence]
        return {
            "factor_id": factor.factor_id,
            "factor_type": factor.factor_type,
            "domain": factor.domain.value if hasattr(factor.domain, "value") else str(factor.domain),
            "name": factor.name,
            "description": factor.description,
            "contribution": factor.contribution,
            "severity": factor.severity.value if hasattr(factor.severity, "value") else str(factor.severity),
            "confidence": factor.confidence,
            "organization_id": factor.organization_id,
            "evidence_ids": list(factor.evidence_ids),
            "evidence": serialized_evidence,
            "metadata": scrub_secrets(copy.deepcopy(factor.metadata)),
        }

    @classmethod
    def deserialize_factor(cls, data: Dict[str, Any]) -> RiskFactor:
        """Reconstruct a pure RiskFactor domain object from a persisted dictionary."""
        domain_str = data.get("domain", "LOGISTICS")
        try:
            domain = SignalDomain(domain_str)
        except Exception:
            domain = SignalDomain.LOGISTICS

        sev_str = data.get("severity", "MEDIUM")
        try:
            severity = RiskLevel(sev_str)
        except Exception:
            severity = RiskLevel.MEDIUM

        raw_evidence = data.get("evidence", [])
        evidence_objects = [cls.deserialize_evidence(e) for e in raw_evidence]

        return RiskFactor(
            factor_id=data["factor_id"],
            factor_type=data["factor_type"],
            domain=domain,
            name=data["name"],
            description=data.get("description"),
            contribution=data.get("contribution"),
            severity=severity,
            confidence=float(data.get("confidence", 1.0)),
            organization_id=data.get("organization_id"),
            evidence_ids=data.get("evidence_ids", [e.evidence_id for e in evidence_objects]),
            evidence=evidence_objects,
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def to_orm(
        cls,
        assessment: RiskAssessment,
        risk_id: str,
    ) -> Tuple[ORMRiskAssessment, List[ORMRiskFactor]]:
        """Map a domain RiskAssessment to ORMRiskAssessment and associated ORMRiskFactor entities.

        Args:
            assessment: Pure domain RiskAssessment instance.
            risk_id: Parent foreign key Risk entity ID.

        Returns:
            Tuple of (ORMRiskAssessment, List[ORMRiskFactor]).
        """
        # Serialize factor contributions
        factor_contribs: List[Dict[str, Any]] = []
        if assessment.overall_score and assessment.overall_score.factor_contributions:
            for fc in assessment.overall_score.factor_contributions:
                factor_contribs.append(
                    {
                        "factor_id": fc.factor_id,
                        "factor_type": fc.factor_type,
                        "name": fc.name,
                        "raw_contribution": fc.raw_contribution,
                        "weighted_contribution": fc.weighted_contribution,
                        "rank": fc.rank,
                        "evidence_ids": list(fc.evidence_ids),
                        "severity": fc.severity.value if hasattr(fc.severity, "value") else str(fc.severity),
                        "confidence": fc.confidence,
                        "metadata": scrub_secrets(copy.deepcopy(fc.metadata)),
                    }
                )

        # Serialize source summary
        source_summary_dict: Optional[Dict[str, Any]] = None
        if assessment.source_summary:
            source_summary_dict = {
                "evidence_count": assessment.source_summary.evidence_count,
                "independent_sources_count": assessment.source_summary.independent_sources_count,
                "real_sources_count": assessment.source_summary.real_sources_count,
                "estimated_sources_count": assessment.source_summary.estimated_sources_count,
                "simulated_sources_count": assessment.source_summary.simulated_sources_count,
                "corroborating_sources_count": assessment.source_summary.corroborating_sources_count,
                "conflicts_count": assessment.source_summary.conflicts_count,
                "sources": list(assessment.source_summary.sources),
                "providers": list(assessment.source_summary.providers),
            }

        # Serialize explanation
        explanation_dict: Optional[Dict[str, Any]] = None
        if assessment.explanation:
            if hasattr(assessment.explanation, "model_dump"):
                explanation_dict = scrub_secrets(assessment.explanation.model_dump())
            elif isinstance(assessment.explanation, dict):
                explanation_dict = scrub_secrets(copy.deepcopy(assessment.explanation))

        # Primary driver
        primary_driver_dict: Optional[Dict[str, Any]] = None
        if assessment.primary_factor:
            primary_driver_dict = {
                "factor_id": assessment.primary_factor.factor_id,
                "name": assessment.primary_factor.name,
                "factor_type": assessment.primary_factor.factor_type,
                "severity": assessment.primary_factor.severity.value,
                "contribution": assessment.primary_factor.contribution,
            }

        # Serialized factors & evidence
        serialized_factors = [cls.serialize_factor(f) for f in assessment.factors]
        serialized_evidence = [cls.serialize_evidence(e) for e in assessment.evidence]

        # Build comprehensive findings document
        findings: Dict[str, Any] = {
            "assessment_id": assessment.assessment_id,
            "deterministic_fingerprint": assessment.fingerprint,
            "scope": assessment.scope,
            "scope_entity_id": assessment.scope_entity_id,
            "scope_entity_type": assessment.scope_entity_type.value if assessment.scope_entity_type else None,
            "risk_level": assessment.risk_level.value if assessment.risk_level else None,
            "probability": None,  # Phase 7 boundary: strictly None
            "impact": None,       # Phase 7 boundary: strictly None
            "primary_factor_id": assessment.primary_factor_id,
            "primary_driver": primary_driver_dict,
            "factor_contributions": factor_contribs,
            "factors": serialized_factors,
            "evidence": serialized_evidence,
            "source_summary": source_summary_dict,
            "limitations": list(assessment.limitations),
            "conflicts": scrub_secrets(copy.deepcopy(assessment.conflicts)),
            "source_signals": list(assessment.source_signals),
            "explanation": explanation_dict,
            "metadata": scrub_secrets(copy.deepcopy(assessment.metadata)),
        }

        # Overall numerical score: defaults to 0.0 if not evaluated
        score_val = assessment.score if assessment.score is not None else 0.0

        orm_assessment = ORMRiskAssessment(
            id=assessment.assessment_id,
            org_id=assessment.organization_id,
            risk_id=risk_id,
            assessor_type="DETERMINISTIC_ENGINE",
            assessor_id="riskwise-baseline-risk-engine-2.0",
            methodology="2.0-baseline-deterministic",
            findings=findings,
            score=round(float(score_val), 2),
            confidence=round(float(assessment.confidence), 4),
            created_at=assessment.evaluated_at,
        )

        # Build ORMRiskFactor records
        orm_factors: List[ORMRiskFactor] = []
        # Index contributions by factor_id for rich factor scoring
        contrib_map = {fc["factor_id"]: fc for fc in factor_contribs}

        for f in assessment.factors:
            fc = contrib_map.get(f.factor_id, {})
            raw_contrib = fc.get("raw_contribution", f.contribution or 0.0)
            weighted_contrib = fc.get("weighted_contribution", raw_contrib * 100.0)
            rank = fc.get("rank", 1)

            evidence_json = {
                "organization_id": assessment.organization_id,
                "factor_id": f.factor_id,
                "factor_type": f.factor_type,
                "severity": f.severity.value,
                "confidence": f.confidence,
                "raw_contribution": raw_contrib,
                "weighted_contribution": weighted_contrib,
                "rank": rank,
                "evidence_ids": list(f.evidence_ids),
                "evidence": [cls.serialize_evidence(e) for e in f.evidence],
                "metadata": scrub_secrets(copy.deepcopy(f.metadata)),
            }

            orm_factor = ORMRiskFactor(
                id=f.factor_id,
                risk_id=risk_id,
                name=f.name[:255],
                category=f.factor_type[:100],
                weight=round(float(raw_contrib), 4),
                score=round(float(weighted_contrib), 2),
                evidence_json=evidence_json,
                created_at=assessment.evaluated_at,
            )
            orm_factors.append(orm_factor)

        return orm_assessment, orm_factors

    @classmethod
    def from_orm(
        cls,
        orm_assessment: ORMRiskAssessment,
        orm_factors: Optional[List[ORMRiskFactor]] = None,
    ) -> RiskAssessment:
        """Reconstruct an authoritative pure domain RiskAssessment from an ORMRiskAssessment entity.

        Args:
            orm_assessment: Persisted SQLAlchemy RiskAssessment instance.
            orm_factors: Optional list of associated ORMRiskFactor records.

        Returns:
            Authoritative RiskAssessment domain model.
        """
        findings = orm_assessment.findings or {}

        # Reconstruct factors
        factors: List[RiskFactor] = []
        raw_factors = findings.get("factors", [])
        if raw_factors:
            for fd in raw_factors:
                factors.append(cls.deserialize_factor(fd))
        elif orm_factors:
            for of in orm_factors:
                ev_json = of.evidence_json or {}
                raw_ev = ev_json.get("evidence", [])
                ev_objs = [cls.deserialize_evidence(e) for e in raw_ev]
                factors.append(
                    RiskFactor(
                        factor_id=of.id,
                        factor_type=of.category or "UNKNOWN",
                        domain=SignalDomain.LOGISTICS,
                        name=of.name,
                        contribution=of.weight,
                        severity=RiskLevel(ev_json.get("severity", "MEDIUM")),
                        confidence=float(ev_json.get("confidence", 1.0)),
                        organization_id=orm_assessment.org_id,
                        evidence_ids=ev_json.get("evidence_ids", [e.evidence_id for e in ev_objs]),
                        evidence=ev_objs,
                        metadata=ev_json.get("metadata", {}),
                    )
                )

        # Reconstruct evidence
        all_evidence: List[RiskEvidence] = []
        raw_evidence = findings.get("evidence", [])
        if raw_evidence:
            for ed in raw_evidence:
                all_evidence.append(cls.deserialize_evidence(ed))
        else:
            for f in factors:
                all_evidence.extend(f.evidence)

        # Reconstruct FactorContribution items
        factor_contribs: List[FactorContribution] = []
        for fcd in findings.get("factor_contributions", []):
            sev_str = fcd.get("severity", "MEDIUM")
            try:
                sev = RiskLevel(sev_str)
            except Exception:
                sev = RiskLevel.MEDIUM

            factor_contribs.append(
                FactorContribution(
                    factor_id=fcd["factor_id"],
                    factor_type=fcd["factor_type"],
                    name=fcd["name"],
                    raw_contribution=float(fcd["raw_contribution"]),
                    weighted_contribution=float(fcd["weighted_contribution"]),
                    rank=int(fcd["rank"]),
                    evidence_ids=fcd.get("evidence_ids", []),
                    severity=sev,
                    confidence=float(fcd.get("confidence", 1.0)),
                    metadata=fcd.get("metadata", {}),
                )
            )

        # Reconstruct source summary
        source_summary: Optional[AssessmentSourceSummary] = None
        ssd = findings.get("source_summary")
        if ssd:
            source_summary = AssessmentSourceSummary(
                evidence_count=ssd.get("evidence_count", 0),
                independent_sources_count=ssd.get("independent_sources_count", 0),
                real_sources_count=ssd.get("real_sources_count", 0),
                estimated_sources_count=ssd.get("estimated_sources_count", 0),
                simulated_sources_count=ssd.get("simulated_sources_count", 0),
                corroborating_sources_count=ssd.get("corroborating_sources_count", 0),
                conflicts_count=ssd.get("conflicts_count", 0),
                sources=ssd.get("sources", []),
                providers=ssd.get("providers", []),
            )

        # Reconstruct explanation
        explanation_obj: Optional[Any] = None
        exp_dict = findings.get("explanation")
        if exp_dict:
            try:
                explanation_obj = RiskExplanation(**exp_dict)
            except Exception:
                explanation_obj = exp_dict

        # Evaluation instant
        eval_time = orm_assessment.created_at
        if eval_time is None:
            eval_time = datetime.now(timezone.utc)
        elif eval_time.tzinfo is None:
            eval_time = eval_time.replace(tzinfo=timezone.utc)

        # Risk level
        risk_level_str = findings.get("risk_level")
        risk_level: Optional[RiskLevel] = None
        if risk_level_str:
            try:
                risk_level = RiskLevel(risk_level_str)
            except Exception:
                pass

        # Reconstruct composite score
        overall_score = RiskScore(
            score=float(orm_assessment.score),
            risk_level=risk_level,
            probability=None,
            impact=None,
            confidence=float(orm_assessment.confidence),
            organization_id=orm_assessment.org_id,
            primary_factor_id=findings.get("primary_factor_id"),
            factor_contributions=factor_contribs,
            factors=factors,
            evidence=all_evidence,
            timestamp=eval_time,
        )

        scope_type_str = findings.get("scope_entity_type")
        scope_entity_type: Optional[EntityType] = None
        if scope_type_str:
            try:
                scope_entity_type = EntityType(scope_type_str)
            except Exception:
                pass

        # Primary factor
        primary_factor: Optional[RiskFactor] = None
        primary_id = findings.get("primary_factor_id")
        if primary_id:
            for f in factors:
                if f.factor_id == primary_id:
                    primary_factor = f
                    break

        return RiskAssessment(
            assessment_id=orm_assessment.id,
            organization_id=orm_assessment.org_id or "global",
            evaluated_at=eval_time,
            scope=findings.get("scope", "GLOBAL"),
            scope_entity_id=findings.get("scope_entity_id"),
            scope_entity_type=scope_entity_type,
            overall_score=overall_score,
            risk_level=risk_level,
            probability=None,
            impact=None,
            confidence=float(orm_assessment.confidence),
            primary_factor_id=findings.get("primary_factor_id"),
            primary_factor=primary_factor,
            factors=factors,
            evidence=all_evidence,
            explanation=explanation_obj,
            source_summary=source_summary,
            limitations=findings.get("limitations", []),
            conflicts=findings.get("conflicts", []),
            source_signals=findings.get("source_signals", []),
            fingerprint=findings.get("deterministic_fingerprint"),
            metadata=findings.get("metadata", {}),
        )

    @classmethod
    def to_detail_dict(cls, orm_assessment: ORMRiskAssessment) -> Dict[str, Any]:
        """Produce a complete detail response representation matching API expectations."""
        findings = orm_assessment.findings or {}

        eval_time = orm_assessment.created_at
        if eval_time and eval_time.tzinfo is None:
            eval_time = eval_time.replace(tzinfo=timezone.utc)

        return {
            "id": orm_assessment.id,
            "assessment_id": orm_assessment.id,
            "org_id": orm_assessment.org_id,
            "risk_id": orm_assessment.risk_id,
            "assessor_type": orm_assessment.assessor_type,
            "assessor_id": orm_assessment.assessor_id,
            "methodology": orm_assessment.methodology,
            "score": orm_assessment.score,
            "risk_level": findings.get("risk_level"),
            "probability": None,  # Always None in Phase 7
            "impact": None,       # Always None in Phase 7
            "confidence": orm_assessment.confidence,
            "primary_factor_id": findings.get("primary_factor_id"),
            "primary_driver": findings.get("primary_driver"),
            "factor_contributions": findings.get("factor_contributions", []),
            "factors": findings.get("factors", []),
            "evidence": findings.get("evidence", []),
            "source_summary": findings.get("source_summary"),
            "limitations": findings.get("limitations", []),
            "conflicts": findings.get("conflicts", []),
            "source_signals": findings.get("source_signals", []),
            "explanation": findings.get("explanation"),
            "fingerprint": findings.get("deterministic_fingerprint"),
            "findings": findings,
            "created_at": eval_time,
        }
