"""Deterministic Decision Rule Engine for RiskWise 2.0 Decision Agent (Phase 9 Step 8).

Transforms validated scenario, prediction, risk, and recommendation context into
deterministic, rule-ranked DecisionCandidate options with auditable rationales.

Architectural Invariants:
- Pure deterministic transformation: same validated inputs produce identical candidate IDs, rationales, and fingerprints.
- Zero LLM generation, zero heuristic guessing, zero random generation.
- Zero mathematical optimization claims: outputs are candidate responses, not optimal solutions.
- Human approval boundary: all candidates default to requires_human_approval = True.
- Zero probability invention: no probability assigned to candidates unless provided by authoritative upstream inputs.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from app.agents.contracts import AgentLimitation, LimitationCategory
from app.agents.decision.contract import (
    DecisionBasis,
    DecisionCandidate,
    DecisionCandidateStatus,
    DecisionConstraint,
    DecisionRationale,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    compute_decision_fingerprint,
    generate_deterministic_decision_id,
)
from app.agents.decision.errors import (
    DecisionTenantIsolationError,
    InvalidDecisionRequestError,
)

RULE_VERSION = "decision_rules_v1.0.0"

# Ordinal priority for deterministic candidate ranking
PRIORITY_RANKS: Dict[str, int] = {
    "LOW": 0,
    "MEDIUM": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}


def _compute_candidate_id(org_id: str, target_ref: str, action_type: str, index: int) -> str:
    token = f"{org_id.strip()}:{target_ref.strip()}:{action_type.strip()}:{index}"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
    return f"cand_{digest}"


class DecisionRuleEngine:
    """Deterministic rule evaluator mapping multi-agent findings to decision candidates."""

    rule_version: str = RULE_VERSION

    def __init__(self, rule_version: Optional[str] = None) -> None:
        self.rule_version = rule_version or RULE_VERSION

    @classmethod
    def evaluate(cls, request: DecisionRequest) -> Tuple[DecisionResult, List[AgentLimitation]]:
        """Evaluate deterministic rules against validated request inputs.

        Returns:
            Tuple of (DecisionResult, List[AgentLimitation])
        """
        org_id = request.organization_id.strip()
        target_ref = (request.target_reference or "default_target").strip()
        limitations: List[AgentLimitation] = []
        evidence_refs: List[str] = list(request.evidence_references)
        upstream_refs: Dict[str, Any] = {}

        # 1. Extract and validate Scenario context
        scen_def = request.scenario_definition
        scen_res = request.scenario_result or request.scenario_reference
        scenario_id = request.scenario_id

        if scen_res and isinstance(scen_res, dict):
            ref_org = scen_res.get("organization_id")
            if ref_org and ref_org.strip() != org_id:
                raise DecisionTenantIsolationError(
                    f"Scenario result tenant '{ref_org}' does not match request tenant '{org_id}'."
                )
            scenario_id = scen_res.get("scenario_id", scenario_id)
            upstream_refs["scenario_id"] = scenario_id
            upstream_refs["scenario_status"] = scen_res.get("status")
            if scen_res.get("fingerprint"):
                upstream_refs["scenario_fingerprint"] = scen_res.get("fingerprint")
            for ev in scen_res.get("evidence_references", []):
                if ev not in evidence_refs:
                    evidence_refs.append(ev)
            if not scen_def and "scenario_definition" in scen_res:
                scen_def = scen_res.get("scenario_definition")

        if scen_def and isinstance(scen_def, dict):
            ref_org = scen_def.get("organization_id")
            if ref_org and ref_org.strip() != org_id:
                raise DecisionTenantIsolationError(
                    f"Scenario definition tenant '{ref_org}' does not match request tenant '{org_id}'."
                )
            scenario_id = scen_def.get("scenario_id", scenario_id)
            upstream_refs["scenario_id"] = scenario_id
            if scen_def.get("target_reference"):
                target_ref = scen_def["target_reference"].strip()

        # Check explicit scenario absence
        if scen_res is None and scen_def is None:
            limitation = AgentLimitation(
                limitation_id=f"lim-no-scen-{target_ref[:8]}",
                category=LimitationCategory.INSUFFICIENT_EVIDENCE,
                description="Scenario context is absent; cannot formulate scenario-grounded decisions.",
                affected_nodes=["decision_agent"],
                mitigation_or_impact="Execute Scenario Agent prior to Decision Agent.",
            )
            limitations.append(limitation)
            decision_id = generate_deterministic_decision_id(
                organization_id=org_id,
                scenario_id=None,
                rule_version=RULE_VERSION,
            )
            return (
                DecisionResult(
                    decision_id=decision_id,
                    organization_id=org_id,
                    decision_type=request.decision_type,
                    status=DecisionStatus.INSUFFICIENT_EVIDENCE.value,
                    candidates=[],
                    preferred_candidate=None,
                    rationales=[],
                    constraints=request.constraints,
                    requires_human_approval=True,
                    upstream_references=upstream_refs,
                    evidence_references=evidence_refs,
                    limitations=limitations,
                    provenance={"status": "INSUFFICIENT_EVIDENCE", "rule_version": RULE_VERSION},
                    fingerprint=None,
                    rule_version=RULE_VERSION,
                ),
                limitations,
            )

        # 2. Extract and validate Risk context
        risk_ref = request.risk_assessment_reference
        risk_id = request.risk_assessment_id
        risk_level = "LOW"
        risk_score: Optional[float] = None

        if risk_ref and isinstance(risk_ref, dict):
            ref_org = risk_ref.get("organization_id")
            if ref_org and ref_org.strip() != org_id:
                raise DecisionTenantIsolationError(
                    f"Risk assessment reference tenant '{ref_org}' does not match request tenant '{org_id}'."
                )
            risk_id = risk_ref.get("assessment_id", risk_id)
            risk_level = str(risk_ref.get("risk_level", "LOW")).upper()
            risk_score = risk_ref.get("risk_score")
            upstream_refs["risk_assessment_id"] = risk_id
            upstream_refs["risk_level"] = risk_level
            if risk_score is not None:
                upstream_refs["risk_score"] = risk_score
            for ev in risk_ref.get("evidence_ids", []):
                if ev not in evidence_refs:
                    evidence_refs.append(ev)

        # 3. Extract and validate Prediction context
        pred_res = request.prediction_result or request.prediction_reference
        pred_id = request.prediction_id
        pred_status = "NOT_AVAILABLE"
        predicted_delay: Optional[float] = None

        if pred_res and isinstance(pred_res, dict):
            ref_org = pred_res.get("organization_id")
            if ref_org and ref_org.strip() != org_id:
                raise DecisionTenantIsolationError(
                    f"Prediction result tenant '{ref_org}' does not match request tenant '{org_id}'."
                )
            pred_id = pred_res.get("prediction_id", pred_id)
            pred_status = pred_res.get("status", "NOT_AVAILABLE")
            upstream_refs["prediction_id"] = pred_id
            upstream_refs["prediction_status"] = pred_status
            if pred_status == "COMPLETED":
                predicted_val = pred_res.get("predicted_value")
                if predicted_val is not None:
                    predicted_delay = float(predicted_val)
                    upstream_refs["predicted_delay_minutes"] = predicted_delay
            for ev in pred_res.get("evidence_references", []):
                if ev not in evidence_refs:
                    evidence_refs.append(ev)
        else:
            limitations.append(
                AgentLimitation(
                    limitation_id=f"lim-no-pred-{target_ref[:8]}",
                    category=LimitationCategory.PREDICTION_MODEL_UNAVAILABLE,
                    description="Prediction result unavailable; decision candidates formulated without quantitative delay forecast.",
                    affected_nodes=["decision_agent"],
                    mitigation_or_impact="Incorporate quantitative prediction when model pipeline becomes available.",
                )
            )

        # 4. Extract constraints from scenario and build authority boundaries
        parsed_constraints: List[DecisionConstraint] = list(request.constraints)
        if scen_def and isinstance(scen_def, dict):
            for sc in scen_def.get("constraints", []):
                if isinstance(sc, dict):
                    parsed_constraints.append(
                        DecisionConstraint(
                            name=sc.get("name", "scenario_constraint"),
                            constraint_type=sc.get("constraint_type", "SCENARIO"),
                            value=sc.get("value", 0),
                            unit=sc.get("unit"),
                        )
                    )
        authority_constraint = DecisionConstraint(
            name="HUMAN_APPROVAL_AUTHORITY",
            constraint_type="AUTHORITY",
            value=True,
        )
        candidate_constraints = parsed_constraints + [authority_constraint]

        # Extract delay from scenario parameters if available
        scenario_delay: Optional[float] = None
        if scen_def and isinstance(scen_def, dict):
            params = scen_def.get("parameters", [])
            for p in params:
                if isinstance(p, dict) and p.get("name") in ("delay_minutes", "expected_delay_minutes"):
                    val = p.get("value")
                    if val is not None:
                        scenario_delay = float(val)
                        break

        effective_delay = scenario_delay if scenario_delay is not None else predicted_delay

        # 5. Evaluate deterministic decision rules
        candidates: List[DecisionCandidate] = []
        rationales: List[DecisionRationale] = []
        candidate_idx = 0

        # Shared base parameters for candidates
        base_params = {
            "target": target_ref,
            "scenario_id": scenario_id,
            "delay_minutes": effective_delay,
            "predicted_delay_minutes": predicted_delay,
            "risk_score": risk_score,
            "risk_level": risk_level,
        }

        # Rule 1: Critical/High Disruption or High Risk -> ESCALATE_FOR_REVIEW
        if (effective_delay is not None and effective_delay >= 120.0) or risk_level in ("HIGH", "CRITICAL"):
            cand_id = _compute_candidate_id(org_id, target_ref, "ESCALATE_FOR_REVIEW", candidate_idx)
            candidate_idx += 1
            escalate_params = dict(base_params)
            escalate_params["escalation_path"] = "EXECUTIVE_OPERATIONS"
            candidates.append(
                DecisionCandidate(
                    candidate_id=cand_id,
                    action_type="ESCALATE_FOR_REVIEW",
                    title="Escalate High Disruption for Operational Review",
                    description=(
                        f"Transit disruption exceeds tolerance (delay: {effective_delay or 'N/A'} mins, "
                        f"risk level: {risk_level}). Recommend immediate executive and logistics escalation."
                    ),
                    priority="CRITICAL",
                    parameters=escalate_params,
                    prerequisites=["validate_corridor_status", "human_review"],
                    constraints=candidate_constraints,
                    expected_effect="Prevents uncoordinated delay propagation and initiates rapid operational review.",
                    evidence_references=evidence_refs,
                    requires_human_approval=True,
                    provenance={"rule_id": "rule_critical_delay_escalate", "rule_version": RULE_VERSION},
                    status=DecisionCandidateStatus.REQUIRES_APPROVAL.value,
                )
            )
            rationales.append(
                DecisionRationale(
                    basis_type=DecisionBasis.SCENARIO if scenario_delay is not None else DecisionBasis.RISK_ASSESSMENT,
                    source_reference=scenario_id or risk_id,
                    evidence_references=evidence_refs,
                    rule_id="rule_critical_delay_escalate",
                    finding_ids=[],
                    explanation_code="CRITICAL_DISRUPTION_EXCEEDS_THRESHOLD",
                )
            )

        # Rule 2: Delay / High Risk -> PREPARE_ALTERNATIVE
        if (effective_delay is not None and effective_delay >= 60.0) or risk_level in ("HIGH", "CRITICAL"):
            cand_id = _compute_candidate_id(org_id, target_ref, "PREPARE_ALTERNATIVE", candidate_idx)
            candidate_idx += 1
            alt_params = dict(base_params)
            alt_params["contingency_mode"] = "SECONDARY_CARRIER_STANDBY"
            candidates.append(
                DecisionCandidate(
                    candidate_id=cand_id,
                    action_type="PREPARE_ALTERNATIVE",
                    title="Prepare Contingency Rerouting & Alternative Carrier Options",
                    description=(
                        f"Significant transit delay projected ({effective_delay or 'N/A'} mins, risk: {risk_level}). "
                        "Prepare alternative transport modes and secondary carriers for review."
                    ),
                    priority="HIGH",
                    parameters=alt_params,
                    prerequisites=["check_carrier_availability", "human_review"],
                    constraints=candidate_constraints,
                    expected_effect="Mitigates SLA penalties by preparing contingency dispatch options.",
                    evidence_references=evidence_refs,
                    requires_human_approval=True,
                    provenance={"rule_id": "rule_high_delay_prepare_alternative", "rule_version": RULE_VERSION},
                    status=DecisionCandidateStatus.REQUIRES_APPROVAL.value,
                )
            )
            rationales.append(
                DecisionRationale(
                    basis_type=DecisionBasis.PREDICTION if predicted_delay is not None else DecisionBasis.SCENARIO,
                    source_reference=pred_id or scenario_id,
                    evidence_references=evidence_refs,
                    rule_id="rule_high_delay_prepare_alternative",
                    finding_ids=[],
                    explanation_code="HIGH_DELAY_CONTINGENCY_PREPARATION",
                )
            )

        # Rule 3: Moderate Delay / Medium Risk -> INVESTIGATE
        if (effective_delay is not None and effective_delay > 0.0) or risk_level in ("MEDIUM", "HIGH"):
            cand_id = _compute_candidate_id(org_id, target_ref, "INVESTIGATE", candidate_idx)
            candidate_idx += 1
            inv_params = dict(base_params)
            inv_params["investigation_scope"] = "CORRIDOR_TELEMETRY"
            candidates.append(
                DecisionCandidate(
                    candidate_id=cand_id,
                    action_type="INVESTIGATE",
                    title="Investigate Transit Corridors & Carrier Telemetry",
                    description=(
                        f"Variance detected ({effective_delay or 'N/A'} mins delay, risk: {risk_level}). "
                        "Investigate sensor telemetry and corridor checkpoints."
                    ),
                    priority="MEDIUM",
                    parameters=inv_params,
                    prerequisites=["query_active_telemetry", "human_review"],
                    constraints=candidate_constraints,
                    expected_effect="Determines if variance is transient or structural without operational disruption.",
                    evidence_references=evidence_refs,
                    requires_human_approval=True,
                    provenance={"rule_id": "rule_moderate_delay_investigate", "rule_version": RULE_VERSION},
                    status=DecisionCandidateStatus.REQUIRES_APPROVAL.value,
                )
            )
            rationales.append(
                DecisionRationale(
                    basis_type=DecisionBasis.RISK_ASSESSMENT if risk_id else DecisionBasis.SCENARIO,
                    source_reference=risk_id or scenario_id,
                    evidence_references=evidence_refs,
                    rule_id="rule_moderate_delay_investigate",
                    finding_ids=[],
                    explanation_code="MODERATE_RISK_INVESTIGATION",
                )
            )

        # Rule 4: Nominal / Baseline -> MONITOR
        if risk_level in ("LOW", "NEGLIGIBLE") or (effective_delay is not None and effective_delay <= 60.0) or not candidates:
            cand_id = _compute_candidate_id(org_id, target_ref, "MONITOR", candidate_idx)
            candidate_idx += 1
            mon_params = dict(base_params)
            mon_params["monitoring_interval_minutes"] = 15
            candidates.append(
                DecisionCandidate(
                    candidate_id=cand_id,
                    action_type="MONITOR",
                    title="Maintain Nominal In-Transit Tracking & Telemetry Monitoring",
                    description="Transit conditions within standard operational tolerance; maintain continuous telemetry tracking.",
                    priority="LOW",
                    parameters=mon_params,
                    prerequisites=["check_telemetry_stream", "human_review"],
                    constraints=candidate_constraints,
                    expected_effect="Preserves real-time situational awareness with zero overhead.",
                    evidence_references=evidence_refs,
                    requires_human_approval=True,
                    provenance={"rule_id": "rule_low_risk_monitor", "rule_version": RULE_VERSION},
                    status=DecisionCandidateStatus.REQUIRES_APPROVAL.value,
                )
            )
            rationales.append(
                DecisionRationale(
                    basis_type=DecisionBasis.EVIDENCE,
                    source_reference=target_ref,
                    evidence_references=evidence_refs,
                    rule_id="rule_low_risk_monitor",
                    finding_ids=[],
                    explanation_code="BASELINE_MONITORING_SUFFICIENT",
                )
            )

        # Ingest Phase 7 recommendations if provided
        for rec in request.available_recommendations:
            if isinstance(rec, dict):
                rec_org = rec.get("organization_id")
                if rec_org and rec_org.strip() != org_id:
                    raise DecisionTenantIsolationError(
                        f"Recommendation tenant '{rec_org}' does not match request organization_id '{org_id}'."
                    )
                rec_id = rec.get("recommendation_id", f"rec_{candidate_idx}")
                rec_title = rec.get("title", "Upstream Operational Recommendation")
                rec_type = rec.get("action_type") or rec.get("recommendation_type", "OPERATIONAL_REVIEW")
                rec_prio = rec.get("priority", "MEDIUM")
                rec_desc = rec.get("description") or rec.get("rationale", "Derived from Phase 7 Risk Recommendation foundation.")
                cand_evidence = rec.get("evidence_references") or rec.get("evidence_ids") or evidence_refs
                rec_requires_approval = rec.get("requires_approval", True)
                cand_id = _compute_candidate_id(org_id, target_ref, str(rec_type), candidate_idx)
                candidate_idx += 1
                rec_params = dict(base_params)
                rec_params["source_recommendation_id"] = rec_id
                candidates.append(
                    DecisionCandidate(
                        candidate_id=cand_id,
                        action_type=str(rec_type),
                        title=f"Review Upstream Recommendation: {rec_title}",
                        description=rec_desc,
                        priority=rec_prio,
                        parameters=rec_params,
                        prerequisites=["validate_recommendation_evidence", "human_review"],
                        constraints=candidate_constraints,
                        expected_effect=rec.get("expected_objective", "Aligns with Phase 7 risk mitigation guidance."),
                        evidence_references=cand_evidence,
                        requires_human_approval=rec_requires_approval,
                        provenance={
                            "source_recommendation_id": rec_id,
                            "recommendation_id": rec_id,
                            "rule_id": "rule_phase7_recommendation",
                            "rule_version": RULE_VERSION,
                        },
                        status=DecisionCandidateStatus.REQUIRES_APPROVAL.value,
                    )
                )
                rationales.append(
                    DecisionRationale(
                        basis_type=DecisionBasis.RECOMMENDATION,
                        source_reference=rec_id,
                        evidence_references=cand_evidence,
                        rule_id="rule_phase7_recommendation",
                        finding_ids=[],
                        explanation_code="UPSTREAM_RECOMMENDATION_MAPPED",
                    )
                )

        # Sort candidates deterministically by priority rank (descending), then candidate_id
        def _rank_candidate(c: DecisionCandidate) -> Tuple[int, str]:
            p = c.priority
            if isinstance(p, int):
                # priority 1 is higher priority than priority 2
                rank = 100 - p
            else:
                rank = PRIORITY_RANKS.get(str(p).upper(), 0)
            return (-rank, str(c.candidate_id))

        candidates.sort(key=_rank_candidate)
        preferred = candidates[0] if candidates else None

        # 6. Compute deterministic identity and fingerprint
        cand_dicts = [c.model_dump(mode="json") for c in candidates]
        constraint_dicts = [con.model_dump(mode="json") for con in candidate_constraints]
        rationale_dicts = [r.model_dump(mode="json") for r in rationales]

        rec_ids = [str(r.get("recommendation_id")) for r in request.available_recommendations if isinstance(r, dict) and r.get("recommendation_id")]

        decision_id = generate_deterministic_decision_id(
            organization_id=org_id,
            scenario_id=scenario_id,
            risk_assessment_id=risk_id,
            prediction_id=pred_id,
            recommendation_ids=rec_ids,
            decision_type=request.decision_type.value,
            target_reference=target_ref,
            rule_version=RULE_VERSION,
        )

        fingerprint = compute_decision_fingerprint(
            organization_id=org_id,
            decision_type=request.decision_type.value,
            target_reference=target_ref,
            candidates=cand_dicts,
            constraints=constraint_dicts,
            rationales=rationale_dicts,
            rule_version=RULE_VERSION,
            scenario_id=scenario_id,
            evidence_references=evidence_refs,
            upstream_references=upstream_refs,
        )

        result = DecisionResult(
            decision_id=decision_id,
            organization_id=org_id,
            decision_type=request.decision_type,
            status=DecisionStatus.REQUIRES_APPROVAL.value,
            candidates=candidates,
            preferred_candidate=preferred,
            preferred_candidate_id=preferred.candidate_id if preferred else None,
            scenario_id=scenario_id,
            scenario_fingerprint=scen_res.get("fingerprint") if isinstance(scen_res, dict) else None,
            risk_assessment_id=risk_id,
            prediction_id=pred_id,
            planning_horizon_hours=request.planning_horizon_hours,
            rationales=rationales,
            constraints=candidate_constraints,
            requires_human_approval=True,
            upstream_references=upstream_refs,
            evidence_references=evidence_refs,
            limitations=limitations,
            provenance={
                "rule_version": RULE_VERSION,
                "candidate_count": len(candidates),
                "decision_id": decision_id,
                "fingerprint": fingerprint,
            },
            fingerprint=fingerprint,
            rule_version=RULE_VERSION,
        )

        return result, limitations
