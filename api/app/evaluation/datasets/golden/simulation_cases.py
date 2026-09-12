"""Golden evaluation test cases for Phase 13 Simulation and Propagation (Phase 20)."""
from typing import List
from app.evaluation.contracts import DatasetCategory, EvaluationCase, EvaluationSuiteType


def get_simulation_evaluation_cases() -> List[EvaluationCase]:
    """Return golden test cases for simulation propagation, scenario application, and non-mutation."""
    return [
        EvaluationCase(
            case_id="sim-case-001",
            suite_type=EvaluationSuiteType.SIMULATION_EVALUATION,
            category=DatasetCategory.NORMAL,
            name="Port Closure Downstream Disruption Propagation",
            description="Injecting 100% capacity reduction on Port of Yokohama propagates delay downstream to warehouse and factory.",
            input_data={
                "disruption_type": "PORT_CLOSURE",
                "target_node_id": "port-01",
                "severity": 1.0,
                "duration_days": 14,
                "network_graph": {
                    "nodes": ["sup-01", "port-01", "port-02", "wh-01", "fac-01"],
                    "edges": [("sup-01", "port-01"), ("port-01", "port-02"), ("port-02", "wh-01"), ("wh-01", "fac-01")],
                },
            },
            expected_output={
                "affected_node_ids": ["port-01", "port-02", "wh-01", "fac-01"],
                "unaffected_node_ids": ["sup-01"],
                "evidence_type_produced": "SIMULATED",
                "production_tables_mutated": False,
            },
            version="1.0.0",
            tags=["simulation", "propagation", "no_mutation"],
        ),
        EvaluationCase(
            case_id="sim-case-002",
            suite_type=EvaluationSuiteType.SIMULATION_EVALUATION,
            category=DatasetCategory.SECURITY,
            name="Simulated Evidence Escalation Prevention",
            description="Simulated impact metrics must never masquerade as REAL ground-truth operational telemetry.",
            input_data={
                "simulated_metrics": {
                    "source_type": "SIMULATED",
                    "projected_cost_increase_usd": 150000.0,
                    "projected_delay_days": 12,
                },
            },
            expected_output={
                "is_escalated_to_real": False,
                "evidence_badge": "SIMULATED",
                "strict_boundary_preserved": True,
            },
            version="1.0.0",
            tags=["simulation", "evidence_boundary", "security"],
        ),
    ]
