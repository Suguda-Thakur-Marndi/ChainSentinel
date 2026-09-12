"""Golden evaluation test cases for Phase 12 Digital Twin Network Topology (Phase 20)."""
from typing import List
from app.evaluation.contracts import DatasetCategory, EvaluationCase, EvaluationSuiteType


def get_digital_twin_evaluation_cases() -> List[EvaluationCase]:
    """Return golden test cases for topology correctness, deterministic hashing, and SPOF identification."""
    return [
        EvaluationCase(
            case_id="twin-case-001",
            suite_type=EvaluationSuiteType.DIGITAL_TWIN_EVALUATION,
            category=DatasetCategory.NORMAL,
            name="Benchmark Supply Chain Topology Integrity",
            description="Verified 5-node, 4-edge supply chain graph correctly builds nodes and edges matching DB ground truth.",
            tenant_id="org-acme",
            input_data={
                "nodes": [
                    {"node_id": "sup-01", "node_type": "SUPPLIER", "label": "Tokyo Semiconductor Fab"},
                    {"node_id": "port-01", "node_type": "PORT", "label": "Port of Yokohama"},
                    {"node_id": "port-02", "node_type": "PORT", "label": "Port of Long Beach"},
                    {"node_id": "wh-01", "node_type": "WAREHOUSE", "label": "Ontario Distribution Hub"},
                    {"node_id": "fac-01", "node_type": "FACTORY", "label": "Nevada Gigafactory"},
                ],
                "edges": [
                    {"edge_id": "e-1", "from_node_id": "sup-01", "to_node_id": "port-01", "edge_type": "SUPPLIES"},
                    {"edge_id": "e-2", "from_node_id": "port-01", "to_node_id": "port-02", "edge_type": "TRANSPORTS"},
                    {"edge_id": "e-3", "from_node_id": "port-02", "to_node_id": "wh-01", "edge_type": "CONNECTS"},
                    {"edge_id": "e-4", "from_node_id": "wh-01", "to_node_id": "fac-01", "edge_type": "FEEDS"},
                ],
                "tenant_id": "org-acme",
            },
            expected_output={
                "node_count": 5,
                "edge_count": 4,
                "is_connected": True,
                "deterministic_ids_verified": True,
                "single_point_of_failure_ids": ["sup-01", "port-01", "port-02", "wh-01"],
            },
            version="1.0.0",
            tags=["digital_twin", "topology", "spof"],
        ),
        EvaluationCase(
            case_id="twin-case-002",
            suite_type=EvaluationSuiteType.DIGITAL_TWIN_EVALUATION,
            category=DatasetCategory.NORMAL,
            name="Snapshot Immutability and Deterministic Fingerprint",
            description="Snapshot created from identical state produces bit-for-bit identical SHA-256 fingerprint.",
            tenant_id="org-acme",
            input_data={
                "snapshot_version": "1.0",
                "node_ids": ["node-a", "node-b"],
                "edge_ids": ["edge-ab"],
                "tenant_id": "org-acme",
            },
            expected_output={
                "fingerprint_deterministic": True,
                "immutable_status": "CURRENT",
            },
            version="1.0.0",
            tags=["digital_twin", "fingerprint", "immutability"],
        ),
        EvaluationCase(
            case_id="twin-case-003",
            suite_type=EvaluationSuiteType.DIGITAL_TWIN_EVALUATION,
            category=DatasetCategory.SECURITY,
            name="Cross-Tenant Graph Partition Isolation",
            description="Querying topology for Tenant A strictly excludes nodes and edges belonging to Tenant B.",
            tenant_id="tenant-alpha",
            input_data={
                "nodes": [
                    {"node_id": "sup-alpha-1", "node_type": "SUPPLIER", "tenant_id": "tenant-alpha"},
                ],
                "edges": [],
                "tenant_id": "tenant-alpha",
            },
            expected_output={
                "node_count": 1,
                "tenant_isolation_maintained": True,
            },
            version="1.0.0",
            tags=["digital_twin", "tenancy", "security"],
        ),
    ]
