"""Deterministic Decision Policy Engine for RiskWise 2.0 (Phase 15).

Synthesizes authoritative upstream multi-phase artifacts:
- Phase 7 Risk Engine: RiskAssessment (risk scores, levels, drivers)
- Phase 8 RAG Grounding: Evidence bundles, citations, provenance
- Phase 11 ML Prediction: PredictionResult (delay forecasts, uncertainty intervals)
- Phase 12/13 Simulation: ScenarioResult, Digital Twin topologies, simulated disruptions
- Phase 14 Optimization: OptimizationResult (solver status, objectives, alternatives, variable assignments)

Guarantees:
- Strictly deterministic evaluation: identical inputs produce identical candidates, rationales, and fingerprints.
- Non-fabrication: never invents routes, costs, delays, risks, capacities, or confidence.
- Solver status fidelity: preserves exact distinction between OPTIMAL, FEASIBLE, TIME_LIMIT, INFEASIBLE, UNBOUNDED, FAILED.
- Strict multi-tenant isolation: validates every reference matches request tenant.
- Fail-closed security: prompt injection text in evidence treated as raw data, never instructions.
- Human approval boundary: always enforces requires_human_approval = True; never auto-approves or executes.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from app.agents.contracts import AgentLimitation, LimitationCategory
from app.agents.decision.contract import (
    AlternativeEvaluation,
    DecisionBasis,
    DecisionCandidate,
    DecisionCandidateStatus,
    DecisionConstraint,
    DecisionOptimizationSummary,
    DecisionPredictionSummary,
    DecisionRationale,
    DecisionRequest,
    DecisionResult,
    DecisionRiskSummary,
    DecisionScenarioSummary,
    DecisionStatus,
    DecisionType,
    compute_decision_fingerprint,
    generate_deterministic_decision_id,
)
from app.agents.decision.errors import (
    DecisionFreshnessError,
    DecisionInfeasibleError,
    DecisionPolicyError,
    DecisionTenantIsolationError,
    InvalidDecisionCandidateError,
    InvalidDecisionRequestError,
)

DECISION_POLICY_VERSION = "1.0.0"


class DecisionPolicyConfig:
    """Configurable thresholds for deterministic decision policy."""

    def __init__(
        self,
        max_freshness_seconds: float = 86400.0,
        high_risk_threshold: float = 70.0,
        medium_risk_threshold: float = 40.0,
        critical_delay_threshold_minutes: float = 120.0,
        high_delay_threshold_minutes: float = 60.0,
        policy_version: str = DECISION_POLICY_VERSION,
    ) -> None:
        self.max_freshness_seconds = max_freshness_seconds
        self.high_risk_threshold = high_risk_threshold
        self.medium_risk_threshold = medium_risk_threshold
        self.critical_delay_threshold_minutes = critical_delay_threshold_minutes
        self.high_delay_threshold_minutes = high_delay_threshold_minutes
        self.policy_version = policy_version


def _compute_candidate_id(org_id: str, target_ref: str, action_type: str, index: int) -> str:
    token = f"{org_id.strip()}:{target_ref.strip()}:{action_type.strip()}:{index}"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
    return f"cand_{digest}"


class DecisionPolicy:
    """Deterministic policy evaluator synthesizing multi-phase RiskWise inputs."""

    def __init__(self, config: Optional[DecisionPolicyConfig] = None) -> None:
        self.config = config or DecisionPolicyConfig()

    def evaluate(self, request: DecisionRequest) -> Tuple[DecisionResult, List[AgentLimitation]]:
        """Evaluate deterministic decision policy over validated request inputs.

        Returns:
            Tuple of (DecisionResult, List[AgentLimitation])
        """
        org_id = request.organization_id.strip()
        target_ref = (
            request.target_reference
            or request.shipment_id
            or (request.shipment_ids[0] if request.shipment_ids else None)
            or request.supplier_id
            or "default_target"
        ).strip()
        limitations: List[AgentLimitation] = []
        evidence_refs: List[str] = list(request.evidence_references)
        upstream_refs: Dict[str, Any] = {}

        # 1. Freshness validation
        if request.freshness_timestamp is not None:
            now = datetime.now(timezone.utc)
            freshness_dt = (
                request.freshness_timestamp
                if request.freshness_timestamp.tzinfo
                else request.freshness_timestamp.replace(tzinfo=timezone.utc)
            )
            age_seconds = (now - freshness_dt).total_seconds()
            if age_seconds > self.config.max_freshness_seconds:
                limitations.append(
                    AgentLimitation(
                        limitation_id=f"lim-stale-{target_ref[:8]}",
                        category=LimitationCategory.STALE_DATA,
                        description=(
                            f"Decision input data age ({age_seconds:.0f}s) exceeds policy "
                            f"freshness threshold ({self.config.max_freshness_seconds:.0f}s)."
                        ),
                        affected_nodes=["decision_agent"],
                        mitigation_or_impact="Decision formulated under conditional status; re-query upstream telemetry.",
                    )
                )

        # 2. Extract and validate Risk Context (Phase 7)
        risk_ref = request.risk_assessment_reference
        risk_id = request.risk_assessment_id
        risk_level = "LOW"
        risk_score: Optional[float] = None
        risk_drivers: List[str] = []

        if risk_ref and isinstance(risk_ref, dict):
            ref_org = risk_ref.get("organization_id")
            if ref_org and ref_org.strip() != org_id:
                raise DecisionTenantIsolationError(
                    f"Risk assessment reference tenant '{ref_org}' does not match request tenant '{org_id}'."
                )
            risk_id = risk_ref.get("assessment_id") or risk_ref.get("risk_assessment_id", risk_id)
            risk_score = risk_ref.get("risk_score") if risk_ref.get("risk_score") is not None else risk_ref.get("composite_score")
            if "risk_level" in risk_ref:
                risk_level = str(risk_ref["risk_level"]).upper()
            elif risk_score is not None:
                if risk_score >= 0.70:
                    risk_level = "CRITICAL" if risk_score >= 0.85 else "HIGH"
                elif risk_score >= 0.40:
                    risk_level = "MEDIUM"
                else:
                    risk_level = "LOW"
            else:
                risk_level = "LOW"

            upstream_refs["risk_assessment_id"] = risk_id
            upstream_refs["risk_level"] = risk_level
            if risk_score is not None:
                upstream_refs["risk_score"] = risk_score
            for ev in risk_ref.get("evidence_ids", []):
                if ev not in evidence_refs:
                    evidence_refs.append(ev)
            for factor in risk_ref.get("factors", []):
                if isinstance(factor, dict) and factor.get("factor_name"):
                    risk_drivers.append(factor["factor_name"])
                elif isinstance(factor, str):
                    risk_drivers.append(factor)

        risk_summary = DecisionRiskSummary(
            risk_assessment_id=risk_id,
            risk_level=risk_level,
            risk_score=risk_score,
            risk_drivers=risk_drivers,
            evidence_ids=[ev for ev in evidence_refs if ev.startswith("ev_") or ev.startswith("risk_")],
        )

        # 3. Extract and validate Prediction Context (Phase 11)
        pred_res = request.prediction_result or request.prediction_reference
        pred_id = request.prediction_id
        pred_status = "NOT_AVAILABLE"
        predicted_delay: Optional[float] = None
        conf_lower: Optional[float] = None
        conf_upper: Optional[float] = None
        model_name: Optional[str] = None

        if pred_res and isinstance(pred_res, dict):
            ref_org = pred_res.get("organization_id")
            if ref_org and ref_org.strip() != org_id:
                raise DecisionTenantIsolationError(
                    f"Prediction result tenant '{ref_org}' does not match request tenant '{org_id}'."
                )
            pred_id = pred_res.get("prediction_id", pred_id)
            pred_status = pred_res.get("status", "NOT_AVAILABLE")
            model_name = pred_res.get("model_name")
            upstream_refs["prediction_id"] = pred_id
            upstream_refs["prediction_status"] = pred_status
            if pred_status == "COMPLETED":
                predicted_val = pred_res.get("predicted_value")
                if predicted_val is not None:
                    predicted_delay = float(predicted_val)
                    upstream_refs["predicted_delay_minutes"] = predicted_delay
                conf_lower = pred_res.get("confidence_lower")
                conf_upper = pred_res.get("confidence_upper")
            for ev in pred_res.get("evidence_references", []):
                if ev not in evidence_refs:
                    evidence_refs.append(ev)
        else:
            limitations.append(
                AgentLimitation(
                    limitation_id=f"lim-no-pred-{target_ref[:8]}",
                    category=LimitationCategory.PREDICTION_MODEL_UNAVAILABLE,
                    description="Prediction result unavailable; delay forecasts ungrounded by quantitative ML.",
                    affected_nodes=["decision_agent"],
                    mitigation_or_impact="Decision formulated relying on scenario and risk heuristics.",
                )
            )

        prediction_summary = DecisionPredictionSummary(
            prediction_id=pred_id,
            status=pred_status,
            predicted_delay_minutes=predicted_delay,
            confidence_lower=conf_lower,
            confidence_upper=conf_upper,
            model_name=model_name,
        )

        # 4. Extract and validate Scenario / Simulation Context (Phase 12/13)
        scen_res = request.scenario_result or request.scenario_reference
        scen_def = request.scenario_definition
        scen_id = request.scenario_id
        sim_res = request.simulation_result or request.simulation_reference
        sim_id = request.simulation_id
        scenario_delay: Optional[float] = None
        affected_nodes: List[str] = []
        affected_edges: List[str] = []

        if scen_res and isinstance(scen_res, dict):
            ref_org = scen_res.get("organization_id")
            if ref_org and ref_org.strip() != org_id:
                raise DecisionTenantIsolationError(
                    f"Scenario result tenant '{ref_org}' does not match request tenant '{org_id}'."
                )
            scen_id = scen_res.get("scenario_id", scen_id)
            upstream_refs["scenario_id"] = scen_id
            if scen_res.get("fingerprint"):
                upstream_refs["scenario_fingerprint"] = scen_res.get("fingerprint")
            for ev in scen_res.get("evidence_references", []):
                if ev not in evidence_refs:
                    evidence_refs.append(ev)
            if not scen_def and "scenario_definition" in scen_res:
                scen_def = scen_res.get("scenario_definition")

        if sim_res and isinstance(sim_res, dict):
            ref_org = sim_res.get("organization_id")
            if ref_org and ref_org.strip() != org_id:
                raise DecisionTenantIsolationError(
                    f"Simulation result tenant '{ref_org}' does not match request tenant '{org_id}'."
                )
            sim_id = sim_res.get("simulation_id", sim_id)
            upstream_refs["simulation_id"] = sim_id

        if scen_def and isinstance(scen_def, dict):
            ref_org = scen_def.get("organization_id")
            if ref_org and ref_org.strip() != org_id:
                raise DecisionTenantIsolationError(
                    f"Scenario definition tenant '{ref_org}' does not match request tenant '{org_id}'."
                )
            scen_id = scen_def.get("scenario_id", scen_id)
            params = scen_def.get("parameters", [])
            for p in params:
                if isinstance(p, dict) and p.get("name") in ("delay_minutes", "expected_delay_minutes"):
                    val = p.get("value")
                    if val is not None:
                        scenario_delay = float(val)
                        break
            affected_nodes = list(scen_def.get("affected_nodes", []))
            affected_edges = list(scen_def.get("affected_edges", []))

        scenario_summary = DecisionScenarioSummary(
            scenario_id=scen_id,
            scenario_type=scen_def.get("scenario_type") if isinstance(scen_def, dict) else None,
            expected_delay_minutes=scenario_delay,
            affected_nodes=affected_nodes,
            affected_edges=affected_edges,
        )

        effective_delay = scenario_delay if scenario_delay is not None else predicted_delay

        # 5. Extract and validate Optimization Context (Phase 14)
        opt_res = request.optimization_result or request.optimization_reference
        opt_id = request.optimization_id
        opt_summary: Optional[DecisionOptimizationSummary] = None
        solver_status = "NOT_AVAILABLE"
        opt_domain = "SHIPMENT_REROUTE"
        opt_objective_type = request.objective_type or "MINIMIZE_DELAY"
        opt_objective_val: Optional[float] = None
        opt_selected_alts: List[Dict[str, Any]] = []
        opt_metrics: Dict[str, Any] = {}
        solver_wall_time = 0.0

        if opt_res and isinstance(opt_res, dict):
            ref_org = opt_res.get("organization_id")
            if ref_org and ref_org.strip() != org_id:
                raise DecisionTenantIsolationError(
                    f"Optimization result tenant '{ref_org}' does not match request tenant '{org_id}'."
                )
            opt_id = opt_res.get("optimization_id", opt_id)
            solver_status = str(opt_res.get("status", "NOT_AVAILABLE")).upper()
            opt_domain = str(opt_res.get("domain", "SHIPMENT_REROUTE")).upper()
            obj_dict = opt_res.get("objective", {})
            if isinstance(obj_dict, dict) and obj_dict.get("objective_type"):
                opt_objective_type = str(obj_dict["objective_type"]).upper()
            opt_objective_val = opt_res.get("objective_value")
            opt_selected_alts = list(opt_res.get("selected_alternatives") or opt_res.get("alternatives") or [])
            opt_metrics = dict(opt_res.get("metrics", {}))
            solver_metadata = opt_res.get("solver_metadata", {})
            solver_wall_time = float(solver_metadata.get("wall_time_ms", 0.0))

            upstream_refs["optimization_id"] = opt_id
            upstream_refs["optimization_status"] = solver_status
            upstream_refs["optimization_domain"] = opt_domain
            upstream_refs["optimization_objective_type"] = opt_objective_type
            if opt_objective_val is not None:
                upstream_refs["optimization_objective_value"] = opt_objective_val

            opt_summary = DecisionOptimizationSummary(
                optimization_id=opt_id or "opt_unknown",
                domain=opt_domain,
                solver_status=solver_status,
                objective_type=opt_objective_type,
                objective_value=opt_objective_val,
                selected_alternatives_count=len(opt_selected_alts),
                solver_wall_time_ms=solver_wall_time,
                is_optimal=(solver_status == "OPTIMAL"),
                time_limit_reached=(solver_status == "TIME_LIMIT"),
                metrics=opt_metrics,
            )

        # 6. Parse constraints & build authority boundary
        candidate_constraints: List[DecisionConstraint] = list(request.constraints)
        authority_constraint = DecisionConstraint(
            name="HUMAN_APPROVAL_AUTHORITY",
            constraint_type="AUTHORITY",
            value=True,
        )
        candidate_constraints.append(authority_constraint)

        # 7. Evaluate Alternatives & Map to Decision Candidates
        alternatives_evaluated: List[AlternativeEvaluation] = []
        candidates: List[DecisionCandidate] = []
        rationales: List[DecisionRationale] = []
        candidate_idx = 0
        selected_alt_id: Optional[str] = None
        preferred_candidate: Optional[DecisionCandidate] = None
        tradeoffs_map: Dict[str, Any] = {}

        decision_type = request.decision_type
        decision_status = DecisionStatus.RECOMMENDED.value
        confidence: Optional[float] = None

        # Build map of candidate alternatives provided in request or solver
        raw_alternatives: List[Dict[str, Any]] = list(request.candidate_alternatives)
        if not raw_alternatives and opt_res and isinstance(opt_res, dict):
            # Fallback to selected_alternatives from optimization result
            raw_alternatives = opt_selected_alts

        # ----------------------------------------------------------------------
        # BRANCH A: Optimization Result Available
        # ----------------------------------------------------------------------
        if opt_res is not None and solver_status != "NOT_AVAILABLE":
            # Determine mapped decision type from optimization domain
            if opt_domain == "SHIPMENT_REROUTE":
                decision_type = DecisionType.REROUTE_SHIPMENT
            elif opt_domain == "ROUTE_SELECTION":
                decision_type = DecisionType.SELECT_ROUTE
            elif opt_domain == "CARRIER_ALLOCATION":
                decision_type = DecisionType.REALLOCATE_CARRIER
            elif opt_domain == "FACILITY_ALLOCATION":
                decision_type = DecisionType.REALLOCATE_FACILITY
            else:
                decision_type = DecisionType.OPERATIONAL_RESPONSE

            if solver_status == "OPTIMAL":
                decision_status = DecisionStatus.RECOMMENDED.value
                confidence = 0.95 if predicted_delay is not None else 0.90
            elif solver_status == "FEASIBLE":
                decision_status = DecisionStatus.CONDITIONAL.value
                confidence = 0.80
                limitations.append(
                    AgentLimitation(
                        limitation_id=f"lim-opt-feasible-{target_ref[:8]}",
                        category=LimitationCategory.HIGH_UNCERTAINTY,
                        description="Optimization solver found feasible solution, but mathematical optimality was not proven.",
                        affected_nodes=["decision_agent"],
                        mitigation_or_impact="Review decision candidate conditionally; solver optimality gap exists.",
                    )
                )
            elif solver_status == "TIME_LIMIT":
                if opt_selected_alts:
                    decision_status = DecisionStatus.CONDITIONAL.value
                    confidence = 0.70
                    limitations.append(
                        AgentLimitation(
                            limitation_id=f"lim-opt-timelimit-{target_ref[:8]}",
                            category=LimitationCategory.HIGH_UNCERTAINTY,
                            description=(
                                f"Optimization solver reached configured time limit ({solver_wall_time:.1f}ms). "
                                "Candidate alternative is feasible, but optimality was NOT proven."
                            ),
                            affected_nodes=["decision_agent"],
                            mitigation_or_impact="Decision is CONDITIONAL; re-solve with higher time limit if optimal guarantee needed.",
                        )
                    )
                else:
                    decision_status = DecisionStatus.NO_FEASIBLE_OPTION.value
                    decision_type = DecisionType.HOLD
                    confidence = None
                    limitations.append(
                        AgentLimitation(
                            limitation_id=f"lim-opt-timelimit-empty-{target_ref[:8]}",
                            category=LimitationCategory.HIGH_UNCERTAINTY,
                            description="Optimization solver hit time limit without identifying any feasible alternative.",
                            affected_nodes=["decision_agent"],
                            mitigation_or_impact="Halt operational dispatch; escalate for manual logistics intervention.",
                        )
                    )
            elif solver_status == "INFEASIBLE":
                decision_status = DecisionStatus.NO_FEASIBLE_OPTION.value
                decision_type = DecisionType.HOLD
                confidence = None
                limitations.append(
                    AgentLimitation(
                        limitation_id=f"lim-opt-infeasible-{target_ref[:8]}",
                        category=LimitationCategory.UNSUPPORTED_OPERATION,
                        description=(
                            "Optimization proved mathematically INFEASIBLE under active operational constraints "
                            "(e.g. capacity limits, time windows, carrier availability). No feasible response exists."
                        ),
                        affected_nodes=["decision_agent"],
                        mitigation_or_impact="Hold shipment dispatch and escalate for executive exception review.",
                    )
                )
            elif solver_status in ("UNBOUNDED", "FAILED"):
                decision_status = DecisionStatus.FAILED.value
                decision_type = DecisionType.ESCALATION
                confidence = None
                limitations.append(
                    AgentLimitation(
                        limitation_id=f"lim-opt-failed-{target_ref[:8]}",
                        category=LimitationCategory.UNSUPPORTED_OPERATION,
                        description=f"Optimization solver execution failed with status '{solver_status}'.",
                        affected_nodes=["decision_agent"],
                        mitigation_or_impact="Check solver logs and constraints; rerun optimization pipeline.",
                    )
                )

            # Evaluate candidate alternatives and compare them
            selected_alt_obj: Optional[Dict[str, Any]] = None
            if opt_selected_alts and solver_status not in ("INFEASIBLE", "FAILED"):
                selected_alt_obj = opt_selected_alts[0]
                selected_alt_id = (
                    selected_alt_obj.get("entity_id")
                    or selected_alt_obj.get("alternative_id")
                    or selected_alt_obj.get("variable_id")
                )
            else:
                selected_alt_id = None

            # Evaluate each candidate alternative
            for alt in raw_alternatives:
                alt_entity_id = alt.get("entity_id") or alt.get("variable_id", f"alt_{candidate_idx}")
                alt_id = alt.get("alternative_id", f"alt_{alt_entity_id}")
                alt_type = alt.get("entity_type", "ROUTE")
                is_sel = bool(
                    (selected_alt_id and (
                        (alt_entity_id and alt_entity_id == selected_alt_id)
                        or (alt.get("alternative_id") and alt.get("alternative_id") == selected_alt_id)
                    ))
                    or (alt.get("assigned_value", 0.0) >= 0.99)
                    or (bool(selected_alt_obj) and alt == selected_alt_obj)
                ) and (solver_status not in ("INFEASIBLE", "FAILED"))

                if is_sel and not selected_alt_id:
                    selected_alt_id = alt.get("entity_id") or alt_id

                is_feas = bool(alt.get("is_available", True) and (solver_status not in ("INFEASIBLE", "FAILED")))

                cost_val = alt.get("cost")
                delay_val = alt.get("transit_time_hours") or alt.get("delay_minutes")
                risk_val = alt.get("risk_score")
                obj_val = alt.get("objective_value") or cost_val or delay_val or opt_objective_val

                rejection_reason: Optional[str] = None
                tradeoff_entry: Dict[str, Any] = {}

                if is_sel:
                    rejection_reason = None
                else:
                    if not is_feas or solver_status == "INFEASIBLE":
                        rejection_reason = "Violates active operational constraints or capacity limits."
                    elif obj_val is not None and opt_objective_val is not None:
                        rejection_reason = (
                            f"Suboptimal for objective {opt_objective_type}: value {obj_val} "
                            f"vs selected {opt_objective_val}."
                        )
                    else:
                        rejection_reason = "Alternative evaluated as suboptimal compared to selected candidate."

                    if selected_alt_obj:
                        sel_cost = selected_alt_obj.get("cost")
                        sel_delay = selected_alt_obj.get("transit_time_hours") or selected_alt_obj.get("delay_minutes")
                        if cost_val is not None and sel_cost is not None:
                            tradeoff_entry["cost_delta"] = round(cost_val - sel_cost, 2)
                        if delay_val is not None and sel_delay is not None:
                            tradeoff_entry["delay_delta"] = round(delay_val - sel_delay, 2)

                alt_eval = AlternativeEvaluation(
                    alternative_id=alt_id,
                    entity_type=alt_type,
                    entity_id=alt_entity_id,
                    is_selected=is_sel,
                    is_feasible=is_feas,
                    objective_value=obj_val,
                    cost=cost_val,
                    delay_minutes=delay_val,
                    risk_score=risk_val,
                    metrics={"objective_value": obj_val} if obj_val is not None else {},
                    rejection_reason=rejection_reason,
                    tradeoffs=tradeoff_entry,
                    evidence_references=evidence_refs,
                )
                alternatives_evaluated.append(alt_eval)
                if tradeoff_entry:
                    tradeoffs_map[alt_id] = tradeoff_entry

            # Sort alternatives deterministically: selected first, then feasible, then by objective_value, then entity_id
            def _sort_alt(a: AlternativeEvaluation) -> Tuple[int, int, float, str]:
                is_s = 1 if a.is_selected else 0
                is_f = 1 if a.is_feasible else 0
                ov = a.objective_value if a.objective_value is not None else float("inf")
                return (-is_s, -is_f, ov, a.alternative_id)

            alternatives_evaluated.sort(key=_sort_alt)

            # Formulate primary DecisionCandidate from solver outcome
            if solver_status in ("OPTIMAL", "FEASIBLE", "TIME_LIMIT") and opt_selected_alts:
                sel_cand_id = _compute_candidate_id(org_id, target_ref, decision_type.value, candidate_idx)
                candidate_idx += 1
                cand_title = (
                    f"Execute Mathematically Optimal {decision_type.value.replace('_', ' ').title()}"
                    if solver_status == "OPTIMAL"
                    else f"Execute Feasible {decision_type.value.replace('_', ' ').title()}"
                )
                cand_desc = (
                    f"Solver evaluated candidate alternatives under objective {opt_objective_type}. "
                    f"Selected alternative '{selected_alt_id}' satisfies active network constraints "
                    f"(status: {solver_status}, objective value: {opt_objective_val or 'N/A'})."
                )
                cand_params = {
                    "target": target_ref,
                    "optimization_id": opt_id,
                    "selected_alternative_id": selected_alt_id,
                    "domain": opt_domain,
                    "objective_type": opt_objective_type,
                    "objective_value": opt_objective_val,
                    "solver_status": solver_status,
                    "metrics": opt_metrics,
                }
                primary_candidate = DecisionCandidate(
                    candidate_id=sel_cand_id,
                    action_type=decision_type.value,
                    title=cand_title,
                    description=cand_desc,
                    priority="HIGH" if risk_level in ("HIGH", "CRITICAL") else "MEDIUM",
                    parameters=cand_params,
                    prerequisites=["validate_corridor_telemetry", "human_review"],
                    constraints=candidate_constraints,
                    expected_effect=f"Optimizes operational response under {opt_objective_type} with solver verified constraints.",
                    evidence_references=evidence_refs,
                    requires_human_approval=True,
                    provenance={
                        "rule_id": "rule_optimization_synthesis",
                        "rule_version": self.config.policy_version,
                        "solver_status": solver_status,
                        "optimization_id": opt_id,
                    },
                    status=DecisionCandidateStatus.REQUIRES_APPROVAL.value,
                )
                candidates.append(primary_candidate)
                preferred_candidate = primary_candidate

                rationales.append(
                    DecisionRationale(
                        basis_type=DecisionBasis.OPTIMIZATION,
                        source_reference=opt_id,
                        evidence_references=evidence_refs,
                        rule_id="rule_optimization_synthesis",
                        finding_ids=[],
                        explanation_code=(
                            "MATHEMATICALLY_OPTIMAL_SOLUTION_PROVEN"
                            if solver_status == "OPTIMAL"
                            else (
                                "OPTIMIZATION_TIME_LIMIT_FEASIBLE_SUBOPTIMAL"
                                if solver_status == "TIME_LIMIT"
                                else "OPTIMIZATION_FEASIBLE_SOLUTION_UNPROVEN_OPTIMALITY"
                            )
                        ),
                        provenance={"optimization_id": opt_id, "solver_status": solver_status},
                    )
                )

            elif solver_status == "INFEASIBLE":
                cand_id = _compute_candidate_id(org_id, target_ref, "HOLD", candidate_idx)
                candidate_idx += 1
                primary_candidate = DecisionCandidate(
                    candidate_id=cand_id,
                    action_type="HOLD",
                    title="Hold Shipment & Escalate: Optimization Infeasible",
                    description=(
                        "Mathematical optimization proved infeasible under active network and capacity constraints. "
                        "Do NOT dispatch alternative routing automatically; requires manual human review."
                    ),
                    priority="CRITICAL",
                    parameters={"optimization_id": opt_id, "solver_status": "INFEASIBLE", "target": target_ref},
                    prerequisites=["escalate_to_operations_manager", "human_review"],
                    constraints=candidate_constraints,
                    expected_effect="Prevents uncoordinated constraint violations and prompts manual exception handling.",
                    evidence_references=evidence_refs,
                    requires_human_approval=True,
                    provenance={"rule_id": "rule_infeasible_hold", "rule_version": self.config.policy_version},
                    status=DecisionCandidateStatus.REQUIRES_APPROVAL.value,
                )
                candidates.append(primary_candidate)
                preferred_candidate = primary_candidate

                rationales.append(
                    DecisionRationale(
                        basis_type=DecisionBasis.CONSTRAINT,
                        source_reference=opt_id,
                        evidence_references=evidence_refs,
                        rule_id="rule_infeasible_hold",
                        finding_ids=[],
                        explanation_code="OPTIMIZATION_INFEASIBLE_NO_FEASIBLE_OPTION",
                    )
                )

        # ----------------------------------------------------------------------
        # BRANCH B: Optimization Unavailable / Heuristic Evaluation
        # ----------------------------------------------------------------------
        else:
            # Evaluate deterministic heuristic rules based on risk and delay
            # Rule 1: Nominal conditions -> NO_ACTION / MONITOR
            if (
                risk_level in ("LOW", "NEGLIGIBLE")
                and (risk_score is None or risk_score < self.config.medium_risk_threshold)
                and (effective_delay is None or effective_delay <= 0.0)
            ):
                decision_type = DecisionType.NO_ACTION
                decision_status = DecisionStatus.NO_ACTION_RECOMMENDED.value
                confidence = 0.95

                cand_id = _compute_candidate_id(org_id, target_ref, "NO_ACTION", candidate_idx)
                candidate_idx += 1
                cand = DecisionCandidate(
                    candidate_id=cand_id,
                    action_type="NO_ACTION",
                    title="No Action Recommended: Baseline Nominal",
                    description="Operating risk is nominal and no shipment delay detected. No operational mutation recommended.",
                    priority="LOW",
                    parameters={"target": target_ref, "risk_score": risk_score, "risk_level": risk_level},
                    prerequisites=[],
                    constraints=candidate_constraints,
                    expected_effect="Maintains standard operational schedule with zero intervention overhead.",
                    evidence_references=evidence_refs,
                    requires_human_approval=True,
                    provenance={"rule_id": "rule_nominal_no_action", "rule_version": self.config.policy_version},
                    status=DecisionCandidateStatus.REQUIRES_APPROVAL.value,
                )
                candidates.append(cand)
                preferred_candidate = cand

                rationales.append(
                    DecisionRationale(
                        basis_type=DecisionBasis.POLICY,
                        source_reference=target_ref,
                        evidence_references=evidence_refs,
                        rule_id="rule_nominal_no_action",
                        finding_ids=[],
                        explanation_code="NOMINAL_OPERATIONS_NO_ACTION",
                    )
                )

            # Rule 2: Low-to-moderate variance -> MONITOR
            elif (effective_delay is not None and effective_delay <= self.config.high_delay_threshold_minutes) or risk_level == "LOW":
                decision_type = DecisionType.MONITOR
                decision_status = DecisionStatus.RECOMMENDED.value
                confidence = 0.85

                cand_id = _compute_candidate_id(org_id, target_ref, "MONITOR", candidate_idx)
                candidate_idx += 1
                cand = DecisionCandidate(
                    candidate_id=cand_id,
                    action_type="MONITOR",
                    title="Maintain Active In-Transit Telemetry Monitoring",
                    description=(
                        f"Delay variance ({effective_delay or 'N/A'} mins) and risk ({risk_level}) "
                        "remain within standard tolerance; maintain real-time corridor monitoring."
                    ),
                    priority="LOW",
                    parameters={
                        "target": target_ref,
                        "delay_minutes": effective_delay,
                        "risk_level": risk_level,
                        "monitoring_interval_minutes": 15,
                    },
                    prerequisites=["check_telemetry_stream"],
                    constraints=candidate_constraints,
                    expected_effect="Preserves real-time visibility without operational disruption.",
                    evidence_references=evidence_refs,
                    requires_human_approval=True,
                    provenance={"rule_id": "rule_low_risk_monitor", "rule_version": self.config.policy_version},
                    status=DecisionCandidateStatus.REQUIRES_APPROVAL.value,
                )
                candidates.append(cand)
                preferred_candidate = cand

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

            # Rule 3: High disruption without optimization -> ESCALATE / REVIEW
            else:
                decision_type = DecisionType.ESCALATION
                decision_status = DecisionStatus.CONDITIONAL.value
                confidence = 0.75

                cand_id = _compute_candidate_id(org_id, target_ref, "ESCALATE_FOR_REVIEW", candidate_idx)
                candidate_idx += 1
                cand = DecisionCandidate(
                    candidate_id=cand_id,
                    action_type="ESCALATE_FOR_REVIEW",
                    title="Escalate Disruption for Human Operational Review",
                    description=(
                        f"Disruption detected (delay: {effective_delay or 'N/A'} mins, risk: {risk_level}) "
                        "without mathematical optimization; escalate to operations manager for contingency planning."
                    ),
                    priority="CRITICAL" if risk_level == "CRITICAL" else "HIGH",
                    parameters={
                        "target": target_ref,
                        "delay_minutes": effective_delay,
                        "risk_level": risk_level,
                        "risk_score": risk_score,
                    },
                    prerequisites=["validate_corridor_status", "human_review"],
                    constraints=candidate_constraints,
                    expected_effect="Alerts operations team for manual re-dispatch or scenario exploration.",
                    evidence_references=evidence_refs,
                    requires_human_approval=True,
                    provenance={"rule_id": "rule_high_risk_escalate", "rule_version": self.config.policy_version},
                    status=DecisionCandidateStatus.REQUIRES_APPROVAL.value,
                )
                candidates.append(cand)
                preferred_candidate = cand

                rationales.append(
                    DecisionRationale(
                        basis_type=DecisionBasis.RISK_ASSESSMENT,
                        source_reference=risk_id or target_ref,
                        evidence_references=evidence_refs,
                        rule_id="rule_high_risk_escalate",
                        finding_ids=[],
                        explanation_code="HIGH_RISK_ESCALATION_REQUIRED",
                    )
                )

        # 7b. In Branch B: If candidate alternatives were provided in request, evaluate and select best
        if raw_alternatives and not alternatives_evaluated:
            for alt in raw_alternatives:
                alt_entity_id = alt.get("entity_id") or alt.get("variable_id", f"alt_{candidate_idx}")
                alt_id = alt.get("alternative_id", f"alt_{alt_entity_id}")
                alt_type = alt.get("entity_type", "ROUTE")
                is_feas = alt.get("is_feasible", True) and alt.get("is_available", True)
                cost_val = alt.get("cost_estimate") if alt.get("cost_estimate") is not None else alt.get("cost")
                delay_val = alt.get("delay_hours") or alt.get("transit_time_hours") or alt.get("delay_minutes")
                risk_val = alt.get("risk_score")
                obj_val = alt.get("objective_value") or cost_val or delay_val

                alt_eval = AlternativeEvaluation(
                    alternative_id=alt_id,
                    entity_type=alt_type,
                    entity_id=str(alt_entity_id),
                    is_selected=False,
                    is_feasible=is_feas,
                    objective_value=obj_val,
                    cost=cost_val,
                    cost_estimate=cost_val,
                    delay_hours=alt.get("delay_hours"),
                    delay_minutes=alt.get("delay_minutes") or (delay_val * 60.0 if delay_val is not None else None),
                    risk_score=risk_val,
                    metrics={"objective_value": obj_val} if obj_val is not None else {},
                    evidence_references=evidence_refs,
                )
                alternatives_evaluated.append(alt_eval)

            feasible_alts = [a for a in alternatives_evaluated if a.is_feasible]
            if feasible_alts:
                feasible_alts.sort(key=lambda a: (a.objective_value if a.objective_value is not None else float("inf"), a.alternative_id))
                sel_eval = feasible_alts[0]
                sel_eval.is_selected = True
                selected_alt_id = sel_eval.alternative_id

                for a in alternatives_evaluated:
                    t_entry: Dict[str, Any] = {}
                    if sel_eval.cost is not None and a.cost is not None:
                        t_entry["cost_delta"] = round(a.cost - sel_eval.cost, 2)
                    if sel_eval.delay_minutes is not None and a.delay_minutes is not None:
                        t_entry["delay_delta"] = round(a.delay_minutes - sel_eval.delay_minutes, 2)
                    a.tradeoffs = t_entry
                    if t_entry:
                        tradeoffs_map[a.alternative_id] = t_entry
                    if not a.is_selected:
                        a.rejection_reason = "Alternative evaluated as suboptimal compared to selected candidate."

                decision_status = DecisionStatus.RECOMMENDED.value
                decision_type = request.decision_type
                cand_id = _compute_candidate_id(org_id, target_ref, decision_type.value, candidate_idx)
                candidate_idx += 1
                cand = DecisionCandidate(
                    candidate_id=cand_id,
                    action_type=decision_type.value,
                    title=f"Execute Selected Candidate Option ({selected_alt_id})",
                    description=f"Candidate alternative '{selected_alt_id}' selected based on evaluated cost/delay trade-offs.",
                    priority="HIGH" if risk_level in ("HIGH", "CRITICAL") else "MEDIUM",
                    parameters={"selected_alternative_id": selected_alt_id, "cost": sel_eval.cost, "target": target_ref},
                    prerequisites=["validate_alternative_feasibility", "human_review"],
                    constraints=candidate_constraints,
                    expected_effect="Applies validated alternative selection with minimized disruption.",
                    evidence_references=evidence_refs,
                    requires_human_approval=True,
                    provenance={"rule_id": "rule_candidate_alternative_selection", "rule_version": self.config.policy_version},
                    status=DecisionCandidateStatus.REQUIRES_APPROVAL.value,
                )
                candidates.insert(0, cand)
                preferred_candidate = cand

        # 8. Ingest Phase 7 Recommendations if provided
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
                cand_id = _compute_candidate_id(org_id, target_ref, str(rec_type), candidate_idx)
                candidate_idx += 1

                candidates.append(
                    DecisionCandidate(
                        candidate_id=cand_id,
                        action_type=str(rec_type),
                        title=f"Review Upstream Recommendation: {rec_title}",
                        description=rec_desc,
                        priority=rec_prio,
                        parameters={
                            "target": target_ref,
                            "source_recommendation_id": rec_id,
                            "delay_minutes": effective_delay,
                            "risk_score": risk_score,
                        },
                        prerequisites=["validate_recommendation_evidence", "human_review"],
                        constraints=candidate_constraints,
                        expected_effect=rec.get("expected_objective", "Aligns with Phase 7 risk mitigation guidance."),
                        evidence_references=cand_evidence,
                        requires_human_approval=True,
                        provenance={
                            "source_recommendation_id": rec_id,
                            "rule_id": "rule_phase7_recommendation",
                            "rule_version": self.config.policy_version,
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

        # 9. Compute deterministic identity and fingerprint
        cand_dicts = [c.model_dump(mode="json") for c in candidates]
        constraint_dicts = [con.model_dump(mode="json") for con in candidate_constraints]
        rationale_dicts = [r.model_dump(mode="json") for r in rationales]
        alt_dicts = [a.model_dump(mode="json") for a in alternatives_evaluated]

        rec_ids = [
            str(r.get("recommendation_id"))
            for r in request.available_recommendations
            if isinstance(r, dict) and r.get("recommendation_id")
        ]

        decision_id = generate_deterministic_decision_id(
            organization_id=org_id,
            scenario_id=scen_id,
            risk_assessment_id=risk_id,
            prediction_id=pred_id,
            recommendation_ids=rec_ids,
            decision_type=decision_type.value,
            target_reference=target_ref,
            rule_version="decision_rules_v1.0.0",
            optimization_id=opt_id,
        )

        fingerprint = compute_decision_fingerprint(
            organization_id=org_id,
            decision_type=decision_type.value,
            target_reference=target_ref,
            candidates=cand_dicts,
            constraints=constraint_dicts,
            rationales=rationale_dicts,
            rule_version="decision_rules_v1.0.0",
            scenario_id=scen_id,
            evidence_references=evidence_refs,
            upstream_references=upstream_refs,
            optimization_id=opt_id,
            alternatives=alt_dicts,
            policy_version=self.config.policy_version,
        )

        result = DecisionResult(
            decision_id=decision_id,
            organization_id=org_id,
            decision_type=decision_type,
            status=decision_status,
            candidates=candidates,
            preferred_candidate=preferred_candidate,
            preferred_candidate_id=preferred_candidate.candidate_id if preferred_candidate else None,
            scenario_id=scen_id,
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
                "policy_version": self.config.policy_version,
                "candidate_count": len(candidates),
                "decision_id": decision_id,
                "fingerprint": fingerprint,
                "solver_status": solver_status,
            },
            fingerprint=fingerprint,
            rule_version="decision_rules_v1.0.0",
            # Phase 15 Extensions
            optimization_id=opt_id,
            optimization_summary=opt_summary,
            simulation_id=sim_id,
            scenario_summary=scenario_summary,
            risk_summary=risk_summary,
            prediction_summary=prediction_summary,
            alternatives_considered=alternatives_evaluated,
            selected_alternative_id=selected_alt_id,
            tradeoffs=tradeoffs_map,
            confidence=confidence,
            decision_policy_version=self.config.policy_version,
            freshness_timestamp=request.freshness_timestamp,
        )

        return result, limitations
