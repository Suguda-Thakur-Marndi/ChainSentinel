"""Golden evaluation cases for End-to-End Workflow evaluation.

Evaluates:
- Complete operational lifecycle transitions:
  Disruption -> Research -> Risk -> ML -> Digital Twin -> Simulation -> Optimization -> Decision -> Approval -> Action -> Verification
- Semantic consistency across transitions (no dropped context, no state mutation leaks)
- Strict boundary checks (e.g. Action Submitted != Verified, Simulation != Real)
"""

from typing import List
from app.evaluation.contracts import EvaluationCase, EvaluationDomain, DatasetCategory

GOLDEN_E2E_CASES: List[EvaluationCase] = [
    EvaluationCase(
        case_id="case-e2e-001-full-disruption-lifecycle",
        name="Full End-to-End Port Disruption to Verified Action",
        domain=EvaluationDomain.END_TO_END,
        category=DatasetCategory.NORMAL,
        description=(
            "Complete workflow from port strike detection, research corroboration, risk recalculation, "
            "delay ML inference, digital twin graph lookup, impact simulation, reroute optimization, "
            "decision recommendation, human approval gate, execution dispatch, and sensory verification."
        ),
        tenant_id="tenant-gold-001",
        input_data={
            "stages": [
                {"stage": "DISRUPTION_SIGNAL", "payload": {"event": "Hamburg Port Strike", "severity": "HIGH", "port": "PORT-HAM"}},
                {"stage": "RESEARCH_AGENT", "payload": {"query": "Hamburg port terminal strike duration", "verified_sources": 2}},
                {"stage": "RISK_ENGINE", "payload": {"shipment_id": "SHP-E2E-100", "base_score": 45, "event_factor": 40}},
                {"stage": "ML_PREDICTION", "payload": {"features": {"delay_history_days": 1.2, "carrier_tier": 1, "port_congestion_index": 0.85}}},
                {"stage": "DIGITAL_TWIN", "payload": {"node_id": "PORT-HAM", "affected_downstream_nodes": ["DC-BERLIN", "MFG-MUNICH"]}},
                {"stage": "SIMULATION", "payload": {"scenario": "REROUTE_VIA_ROTTERDAM", "duration_days": 5}},
                {"stage": "OPTIMIZATION", "payload": {"candidates": ["OPT_ROTTERDAM", "OPT_ANTWERP"], "budget_cap": 25000.0}},
                {"stage": "DECISION_ENGINE", "payload": {"top_candidate": "OPT_ROTTERDAM", "cost_delta": 4200.0, "time_saved_days": 4}},
                {"stage": "APPROVAL_GATE", "payload": {"approver_role": "SUPPLY_CHAIN_VP", "approved": True, "notes": "Approved reroute"}},
                {"stage": "ACTION_EXECUTOR", "payload": {"action_type": "NOTIFY_CARRIER_AND_REROUTE", "carrier": "MAERSK", "target_port": "PORT-RTM"}},
                {"stage": "VERIFICATION_AGENT", "payload": {"verification_target": "PORT-RTM", "evidence_type": "REAL", "ais_confirmed": True}},
            ]
        },
        expected_output={
            "all_stages_completed": True,
            "stage_transitions_valid": [
                "DISRUPTION_TO_RESEARCH",
                "RESEARCH_TO_RISK",
                "RISK_TO_ML",
                "ML_TO_DIGITAL_TWIN",
                "DIGITAL_TWIN_TO_SIMULATION",
                "SIMULATION_TO_OPTIMIZATION",
                "OPTIMIZATION_TO_DECISION",
                "DECISION_TO_APPROVAL",
                "APPROVAL_TO_ACTION",
                "ACTION_TO_VERIFICATION",
            ],
            "final_status": "VERIFIED_SUCCESS",
            "semantic_consistency": True,
            "no_production_mutation_in_eval": True,
        },
        assertions={
            "transitions_intact": True,
            "risk_score_monotonic": True,
            "approval_fingerprint_matches_decision": True,
            "action_matches_approved_candidate": True,
            "verification_uses_real_evidence": True,
        },
        tags=["e2e", "workflow", "lifecycle", "port_disruption"],
    ),
    EvaluationCase(
        case_id="case-e2e-002-approval-rejected-flow",
        name="End-to-End Workflow with Human Rejection Halting Execution",
        domain=EvaluationDomain.END_TO_END,
        category=DatasetCategory.EDGE_CASE,
        description="Verify pipeline stops at Human Approval stage when rejected; Action executor MUST NOT trigger.",
        tenant_id="tenant-gold-001",
        input_data={
            "stages": [
                {"stage": "DISRUPTION_SIGNAL", "payload": {"event": "Rail Congestion", "severity": "MEDIUM"}},
                {"stage": "DECISION_ENGINE", "payload": {"top_candidate": "EXPENSIVE_AIR_FREIGHT", "cost_delta": 55000.0}},
                {"stage": "APPROVAL_GATE", "payload": {"approver_role": "LOGISTICS_MGR", "approved": False, "rejection_reason": "Air freight cost exceeds threshold"}},
            ]
        },
        expected_output={
            "final_stage_reached": "APPROVAL_GATE",
            "action_executed": False,
            "status": "HALTED_BY_GOVERNANCE",
        },
        assertions={
            "action_blocked_after_rejection": True,
            "verification_bypassed": True,
        },
        tags=["e2e", "governance", "rejection"],
    ),
    EvaluationCase(
        case_id="case-e2e-003-navigation-journey",
        name="Control Tower Portal Navigation Journey",
        domain=EvaluationDomain.END_TO_END,
        category=DatasetCategory.NORMAL,
        description="Verify semantic flow: Login -> Dashboard -> Supplier -> Shipment -> Event -> Risk assessment view.",
        tenant_id="tenant-gold-001",
        input_data={
            "navigation_sequence": [
                "/auth/login",
                "/dashboard",
                "/suppliers/SUP-101",
                "/shipments/SHP-502",
                "/events/EVT-900",
                "/risk-assessment/SHP-502",
            ]
        },
        expected_output={
            "valid_breadcrumbs": True,
            "context_preserved": ["SUP-101", "SHP-502", "EVT-900"],
            "all_routes_resolvable": True,
        },
        assertions={
            "route_continuity": True,
        },
        tags=["e2e", "navigation", "frontend_journey"],
    ),
]
