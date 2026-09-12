"""Decision Agent execution and orchestration layer (Phase 9 & Phase 15).

Coordinates DecisionRequest validation, tenant boundary enforcement,
deterministic policy & rule evaluation, and structured AgentFinding production.
Stops strictly before human approval and operational action execution.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.agents.contracts import AgentFinding, AgentLimitation
from app.agents.decision.contract import (
    DecisionCandidate,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
)
from app.agents.decision.errors import (
    DecisionTenantIsolationError,
    InvalidDecisionRequestError,
)
from app.agents.decision.policy import DecisionPolicy
from app.agents.decision.rules import DecisionRuleEngine


class DecisionAgent:
    """Orchestration agent for deterministic decision candidate formulation."""

    def __init__(
        self,
        rule_engine: Optional[DecisionRuleEngine] = None,
        policy: Optional[DecisionPolicy] = None,
    ) -> None:
        self.rule_engine = rule_engine or DecisionRuleEngine()
        self.policy = policy or DecisionPolicy()

    def execute(self, request: DecisionRequest) -> Tuple[DecisionResult, List[AgentFinding]]:
        """Execute decision evaluation and construct structured agent findings.

        Returns:
            Tuple of (DecisionResult, List[AgentFinding])
        """
        if not request.organization_id or not request.organization_id.strip():
            raise InvalidDecisionRequestError("DecisionRequest organization_id must be non-empty.")

        # 1. Dispatch to Phase 15 DecisionPolicy if optimization, simulation, or Phase 15 fields are present
        has_phase15_signals = (
            request.optimization_result is not None
            or request.optimization_reference is not None
            or request.optimization_id is not None
            or request.simulation_result is not None
            or request.simulation_reference is not None
            or request.simulation_id is not None
            or request.objective_type is not None
            or bool(request.candidate_alternatives)
            or bool(request.shipment_id)
            or bool(request.shipment_ids)
            or bool(request.supplier_id)
            or bool(request.supplier_ids)
        )

        if has_phase15_signals:
            result, limitations = self.policy.evaluate(request)
        else:
            result, limitations = self.rule_engine.evaluate(request)

        # 2. Output tenant validation
        if result.organization_id != request.organization_id:
            raise DecisionTenantIsolationError(
                f"DecisionResult organization '{result.organization_id}' does not match "
                f"request organization '{request.organization_id}'."
            )

        # 3. Produce structured AgentFinding records
        findings: List[AgentFinding] = []

        if result.status in (
            DecisionStatus.READY.value,
            DecisionStatus.REQUIRES_APPROVAL.value,
            DecisionStatus.RECOMMENDED.value,
            DecisionStatus.CONDITIONAL.value,
            DecisionStatus.NO_ACTION_RECOMMENDED.value,
        ) and result.candidates:
            pref = result.preferred_candidate or result.candidates[0]
            cand_types = ", ".join(c.action_type for c in result.candidates)
            sev = (
                "HIGH"
                if pref.priority in ("HIGH", "CRITICAL")
                else ("MEDIUM" if pref.priority == "MEDIUM" else "INFO")
            )

            finding = AgentFinding(
                finding_id=f"find-dec-{result.decision_id[:8]}",
                category="DECISION_CANDIDATE",
                title=f"Decision Candidate: {pref.action_type}",
                summary=(
                    f"Formulated {len(result.candidates)} candidate option(s) [{cand_types}]. "
                    f"Preferred candidate: '{pref.title}' (Priority: {pref.priority}). "
                    "Halting autonomous graph execution for human operational approval."
                ),
                severity=sev,
                confidence=result.confidence if result.confidence is not None else 1.0,
                evidence_ids=result.evidence_references,
                source_references=[f"decision:{result.decision_id}", f"candidate:{pref.candidate_id}"],
                limitations=[lim.description for lim in limitations],
                created_by_node="decision_agent",
            )
            findings.append(finding)

        elif result.status in (
            DecisionStatus.INSUFFICIENT_EVIDENCE.value,
            DecisionStatus.INSUFFICIENT_DATA.value,
        ):
            finding = AgentFinding(
                finding_id=f"find-dec-insuff-{result.decision_id[:8]}",
                category="INSUFFICIENT_EVIDENCE",
                title="Decision Formulation: Insufficient Evidence",
                summary=(
                    "Decision candidates could not be formulated because upstream scenario definitions, "
                    "risk assessments, or prediction results were absent."
                ),
                severity="LOW",
                confidence=1.0,
                evidence_ids=result.evidence_references,
                source_references=[],
                limitations=[lim.description for lim in limitations],
                created_by_node="decision_agent",
            )
            findings.append(finding)

        elif result.status == DecisionStatus.NO_FEASIBLE_OPTION.value:
            finding = AgentFinding(
                finding_id=f"find-dec-nofeas-{result.decision_id[:8]}",
                category="NO_FEASIBLE_OPTION",
                title="Decision Formulation: No Feasible Operational Option",
                summary=(
                    "Mathematical optimization proved infeasible under active network constraints. "
                    "No valid reroute or reallocation candidate can be recommended without constraint relaxation."
                ),
                severity="HIGH",
                confidence=1.0,
                evidence_ids=result.evidence_references,
                source_references=[f"decision:{result.decision_id}"],
                limitations=[lim.description for lim in limitations],
                created_by_node="decision_agent",
            )
            findings.append(finding)

        return result, findings

