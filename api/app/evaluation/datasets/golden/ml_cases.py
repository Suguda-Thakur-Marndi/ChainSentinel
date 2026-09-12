"""Golden evaluation test cases for Phase 11 ML delay prediction and leakage detection (Phase 20)."""
from typing import List
from app.evaluation.contracts import DatasetCategory, EvaluationCase, EvaluationSuiteType


def get_ml_evaluation_cases() -> List[EvaluationCase]:
    """Return golden test cases for ML regression quality, stability, and leakage detection."""
    return [
        EvaluationCase(
            case_id="ml-case-001",
            suite_type=EvaluationSuiteType.ML_EVALUATION,
            category=DatasetCategory.NORMAL,
            name="Shipment Delay Regression Evaluation",
            description="Verified historical shipment feature matrix evaluated against ground truth delay minutes.",
            input_data={
                "features": [
                    {"route_distance_km": 1200.0, "port_congestion_index": 0.8, "carrier_reliability_score": 0.65, "weather_severity": 0.7},
                    {"route_distance_km": 450.0, "port_congestion_index": 0.2, "carrier_reliability_score": 0.90, "weather_severity": 0.1},
                    {"route_distance_km": 2800.0, "port_congestion_index": 0.9, "carrier_reliability_score": 0.50, "weather_severity": 0.85},
                    {"route_distance_km": 900.0, "port_congestion_index": 0.4, "carrier_reliability_score": 0.80, "weather_severity": 0.3},
                    {"route_distance_km": 1600.0, "port_congestion_index": 0.6, "carrier_reliability_score": 0.70, "weather_severity": 0.5},
                ],
                "y_true": [180.0, 15.0, 420.0, 45.0, 120.0],
                "y_pred": [175.0, 20.0, 410.0, 50.0, 130.0],
            },
            expected_output={
                "max_allowed_mae": 15.0,
                "max_allowed_rmse": 20.0,
                "min_allowed_r2": 0.85,
                "sample_count": 5,
            },
            version="1.0.0",
            tags=["ml", "delay_prediction", "mae", "rmse"],
        ),
        EvaluationCase(
            case_id="ml-case-002",
            suite_type=EvaluationSuiteType.ML_EVALUATION,
            category=DatasetCategory.EMPTY_DATA,
            name="Insufficient Samples Returns NOT_AVAILABLE",
            description="Fewer than minimum required samples (n < 5) must emit NOT_AVAILABLE without fabricating score.",
            input_data={
                "y_true": [120.0, 45.0],
                "y_pred": [115.0, 50.0],
                "min_samples": 5,
            },
            expected_output={
                "status": "NOT_AVAILABLE",
                "value": None,
                "is_fabricated": False,
            },
            version="1.0.0",
            tags=["ml", "insufficient_data", "not_available"],
        ),
        EvaluationCase(
            case_id="ml-case-003",
            suite_type=EvaluationSuiteType.ML_EVALUATION,
            category=DatasetCategory.ADVERSARIAL,
            name="Temporal & Target Leakage Detection",
            description="Feature schema containing future timestamp or target proxy ('actual_arrival_time', 'delivered_delay') is flagged and rejected.",
            input_data={
                "candidate_feature_names": [
                    "route_distance_km",
                    "origin_dwell_time",
                    "destination_actual_unloading_time",  # Future event leakage
                    "final_pod_signature_timestamp",      # Target leakage
                ],
            },
            expected_output={
                "leakage_detected": True,
                "leaking_features": ["destination_actual_unloading_time", "final_pod_signature_timestamp"],
                "model_deployable": False,
            },
            version="1.0.0",
            tags=["ml", "leakage", "security"],
        ),
        EvaluationCase(
            case_id="ml-case-004",
            suite_type=EvaluationSuiteType.ML_EVALUATION,
            category=DatasetCategory.SECURITY,
            name="Cross-Tenant Feature Contamination Prevention",
            description="Model trained for Tenant A must not ingest features from Tenant B shipments.",
            input_data={
                "model_tenant": "tenant-alpha",
                "inference_records": [
                    {"shipment_id": "shp-alpha-1", "tenant_id": "tenant-alpha"},
                    {"shipment_id": "shp-beta-9", "tenant_id": "tenant-beta"},
                ],
            },
            expected_output={
                "permitted_shipment_ids": ["shp-alpha-1"],
                "rejected_shipment_ids": ["shp-beta-9"],
                "cross_tenant_violation": False,
            },
            version="1.0.0",
            tags=["ml", "tenancy", "security"],
        ),
    ]
