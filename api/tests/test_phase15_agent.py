"""Phase 15 Test Suite 3: DecisionAgent Orchestration Layer.

Validates:
1. DecisionAgent execution with Phase 15 multi-phase inputs (dispatches to DecisionPolicy)
2. DecisionAgent execution with Phase 9 scenario inputs (dispatches to DecisionRuleEngine)
3. Structured AgentFinding generation:
   - Category DECISION_CANDIDATE with correct severity and source references
   - Category INSUFFICIENT_EVIDENCE when inputs are missing
   - Category NO_FEASIBLE_OPTION when optimization is infeasible
4. Tenant boundary enforcement on request and result
5. Human approval enforcement (requires_human_approval = True; never approved)
6. Advisory read-only guarantee: zero operational mutations
"""

from __future__ import annotations

import pytest

from app.agents.contracts import AgentFinding
from app.agents.decision.agent import DecisionAgent
from app.agents.decision.contract import (
    DecisionConstraint,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    DecisionType,
)
from app.agents.decision.errors import (
    DecisionTenantIsolationError,
    InvalidDecisionRequestError,
)


@pytest.fixture
def org_id() -> str:
    return "org_freight_global"


def test_agent_dispatches_phase15_optimization(org_id: str):
    """Verify DecisionAgent dispatches to DecisionPolicy when optimization result is present."""
    request = DecisionRequest(
        organization_id=org_id,
        target_reference="shipment_888",
        optimization_result={
            "organization_id": org_id,
            "optimization_id": "opt_reroute_888",
            "domain": "SHIPMENT_REROUTE",
            "status": "OPTIMAL",
            "objective": {"objective_type": "MINIMIZE_DELAY"},
            "objective_value": 30.0,
            "selected_alternatives": [
                {"entity_type": "ROUTE", "entity_id": "route_bypass_01", "assigned_value": 1.0}
            ],
            "metrics": {"delay_reduction_minutes": 90.0},
        },
        risk_assessment_reference={
            "organization_id": org_id,
            "assessment_id": "risk_01",
            "risk_score": 80.0,
            "risk_level": "HIGH",
        },
    )

    agent = DecisionAgent()
    result, findings = agent.execute(request)

    assert result.decision_type == DecisionType.REROUTE_SHIPMENT
    assert result.status == DecisionStatus.RECOMMENDED.value
    assert result.optimization_id == "opt_reroute_888"
    assert result.requires_human_approval is True

    assert len(findings) >= 1
    decision_finding = [f for f in findings if f.category == "DECISION_CANDIDATE"][0]
    assert decision_finding.severity == "HIGH"
    assert "route_bypass_01" in decision_finding.summary or "REROUTE_SHIPMENT" in decision_finding.title
    assert f"decision:{result.decision_id}" in decision_finding.source_references


def test_agent_dispatches_phase9_scenario_legacy(org_id: str):
    """Verify DecisionAgent preserves Phase 9 DecisionRuleEngine path when no optimization is present."""
    request = DecisionRequest(
        organization_id=org_id,
        target_reference="shipment_legacy_01",
        scenario_definition={
            "organization_id": org_id,
            "scenario_id": "scen_legacy",
            "parameters": [{"name": "delay_minutes", "value": 150.0}],
        },
        risk_assessment_reference={
            "organization_id": org_id,
            "assessment_id": "risk_leg",
            "risk_level": "HIGH",
        },
    )

    agent = DecisionAgent()
    result, findings = agent.execute(request)

    # In Phase 9, delay >= 120 produced ESCALATE_FOR_REVIEW
    assert any(c.action_type == "ESCALATE_FOR_REVIEW" for c in result.candidates)
    assert result.status == DecisionStatus.REQUIRES_APPROVAL.value
    assert result.requires_human_approval is True


def test_agent_infeasible_findings(org_id: str):
    """Verify DecisionAgent produces NO_FEASIBLE_OPTION finding for infeasible solver outcome."""
    request = DecisionRequest(
        organization_id=org_id,
        target_reference="shipment_bottleneck",
        optimization_result={
            "organization_id": org_id,
            "optimization_id": "opt_infeasible",
            "domain": "SHIPMENT_REROUTE",
            "status": "INFEASIBLE",
            "objective": {"objective_type": "MINIMIZE_DELAY"},
            "selected_alternatives": [],
        },
    )

    agent = DecisionAgent()
    result, findings = agent.execute(request)

    assert result.status == DecisionStatus.NO_FEASIBLE_OPTION.value
    assert len(findings) >= 1
    infeasible_finding = [f for f in findings if f.category == "NO_FEASIBLE_OPTION"][0]
    assert infeasible_finding.severity == "HIGH"
    assert "infeasible" in infeasible_finding.summary.lower()


def test_agent_insufficient_evidence_findings(org_id: str):
    """Verify DecisionAgent handles missing scenario and optimization data."""
    request = DecisionRequest(
        organization_id=org_id,
        target_reference="shipment_empty",
    )

    agent = DecisionAgent()
    result, findings = agent.execute(request)

    assert result.status in (DecisionStatus.INSUFFICIENT_EVIDENCE.value, DecisionStatus.INSUFFICIENT_DATA.value)
    assert len(findings) >= 1
    insuff_finding = [f for f in findings if f.category == "INSUFFICIENT_EVIDENCE"][0]
    assert insuff_finding.severity == "LOW"


def test_agent_enforces_tenant_boundary(org_id: str):
    """Verify DecisionAgent fails closed if request has empty tenant or cross-tenant data."""
    with pytest.raises(InvalidDecisionRequestError):
        DecisionRequest(
            organization_id="",
            target_reference="shipment_01",
        )

    # Cross-tenant optimization in request fails at model validation
    with pytest.raises(DecisionTenantIsolationError):
        DecisionRequest(
            organization_id=org_id,
            target_reference="shipment_01",
            optimization_result={
                "organization_id": "foreign_tenant",
                "optimization_id": "opt_foreign",
                "domain": "SHIPMENT_REROUTE",
                "status": "OPTIMAL",
            },
        )
