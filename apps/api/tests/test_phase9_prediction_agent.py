"""Comprehensive test suite for RiskWise 2.0 Phase 9 Step 6: Prediction Agent Integration.

Verifies:
1. PredictionRequest contracts, Pydantic validation, extra="forbid", and forbidden client values.
2. PredictionFeature contracts, bounds, units, NaN/inf rejection, and tenant validation.
3. ModelMetadata and explicit PredictionUncertainty semantics (never probability without calibration).
4. PredictionResult contract, non-negative delay, units, and status consistency.
5. BasePredictionService abstraction, UnavailablePredictionService (production default), and DeterministicMockPredictionService.
6. Deterministic feature extraction from authoritative RiskAssessment and structured findings.
7. PredictionAgent orchestration and structured AgentFinding generation.
8. State ownership and write boundaries (PREDICTION stage only).
9. LangGraph node registration, telemetry emission, and StateGraph pipeline execution.
10. Multi-tenant isolation and fail-closed security invariants.
11. Read-only safety, zero operational mutations, and Risk Engine immutability.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.agents.contracts import (
    AgentExecutionContext,
    AgentGraphState,
    AgentGraphStateDict,
    AgentLimitation,
    AgentNodeContract,
    AgentStage,
    LimitationCategory,
    ToolSideEffectType,
    apply_state_update,
    validate_state_update,
)
from app.agents.errors import (
    AgentStateOwnershipViolationError,
    AgentTenantIsolationError,
    AgentValidationError,
)
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.agents.prediction import (
    BasePredictionService,
    DeterministicMockPredictionService,
    FeatureValidationError,
    InvalidModelOutputError,
    InvalidPredictionRequestError,
    ModelExecutionError,
    ModelMetadata,
    ModelTimeoutError,
    ModelUnavailableError,
    PREDICTION_NODE_CONTRACT,
    PredictionAgent,
    PredictionAgentError,
    PredictionAuthorizationError,
    PredictionFeature,
    PredictionFeatureExtractor,
    PredictionRequest,
    PredictionResult,
    PredictionStatus,
    PredictionTenantIsolationError,
    PredictionType,
    PredictionUncertainty,
    UnavailablePredictionService,
    generate_deterministic_prediction_id,
    prediction_node,
)
from app.agents.registry import NodeRegistry
from app.agents.research.contract import ResearchFinding, ResearchResult
from app.agents.risk.contract import RiskAgentResult


# ==============================================================================
# FIXTURES AND FACTORIES
# ==============================================================================

@pytest.fixture
def sample_context() -> AgentExecutionContext:
    return AgentExecutionContext(
        organization_id="org_test_123",
        actor_id="usr_test_456",
        request_id="req_test_789",
        correlation_id="corr_test_001",
        trace_id="trace_test_002",
        role="ANALYST",
        roles=["analyst"],
        permissions=["read", "prediction_evaluate"],
    )


@pytest.fixture
def sample_feature() -> PredictionFeature:
    return PredictionFeature(
        feature_name="risk_composite_score",
        value=65.5,
        unit="score",
        source="RiskAssessment:ra_001",
        source_type="RISK_ENGINE",
        timestamp=datetime.now(timezone.utc),
        evidence_references=["ev_001", "ev_002"],
        organization_id="org_test_123",
        provenance={"rule": "direct_composite_score"},
    )


@pytest.fixture
def sample_request(sample_feature: PredictionFeature) -> PredictionRequest:
    return PredictionRequest(
        prediction_id="pred_test_001",
        organization_id="org_test_123",
        prediction_type=PredictionType.SHIPMENT_DELAY,
        target="delay_minutes",
        shipment_id="ship_999",
        risk_assessment_id="ra_001",
        risk_assessment_reference={"assessment_id": "ra_001", "organization_id": "org_test_123", "risk_score": 65.5},
        features=[sample_feature],
        prediction_horizon_hours=24.0,
        model_name="deterministic_mock_shipment_delay",
        model_version="1.0.0-mock",
        correlation_id="corr_test_001",
        trace_id="trace_test_002",
    )


@pytest.fixture
def sample_graph_state() -> AgentGraphStateDict:
    return {
        "run_id": "run_test_001",
        "organization_id": "org_test_123",
        "actor_id": "usr_test_456",
        "request_id": "req_test_789",
        "correlation_id": "corr_test_001",
        "trace_id": "trace_test_002",
        "objective": "Predict shipment delay for Rotterdam consignment",
        "input_reference": "ship_999",
        "input_references": {"scheduled_transit_hours": 48.0},
        "current_stage": AgentStage.RISK_ASSESSMENT.value,
        "current_node": "risk_agent",
        "status": "RUNNING",
        "step_count": 3,
        "evidence_bundle_id": "bundle_test_001",
        "evidence_references": ["ev_001", "ev_002"],
        "citation_references": ["cit_001"],
        "risk_assessment_id": "ra_001",
        "risk_assessment_reference": {
            "assessment_id": "ra_001",
            "organization_id": "org_test_123",
            "assessment_fingerprint": "fp_assessment_001",
            "risk_score": 65.5,
            "risk_level": "HIGH",
            "factor_count": 3,
        },
        "structured_findings": [
            {
                "finding_id": "find_001",
                "category": "PORT_CONGESTION",
                "title": "Severe Berth Congestion",
                "summary": "Port of Rotterdam reports 48-hour delay.",
                "severity": "HIGH",
                "confidence": 0.9,
                "evidence_ids": ["ev_001"],
                "source_references": [],
                "limitations": [],
                "created_by_node": "research_agent",
            }
        ],
        "findings": {},
        "warnings": [],
        "limitations": [],
        "conflicts": [],
        "route_history": [],
        "retry_count": 0,
        "errors": [],
        "metadata": {},
        "state_schema_version": "1.0.0",
    }


# ==============================================================================
# GROUP 1: PREDICTION REQUEST CONTRACT & FORBIDDEN INJECTIONS (10 tests)
# ==============================================================================

class TestPredictionRequestContracts:
    def test_valid_prediction_request(self, sample_request: PredictionRequest):
        assert sample_request.prediction_id == "pred_test_001"
        assert sample_request.organization_id == "org_test_123"
        assert sample_request.prediction_type == PredictionType.SHIPMENT_DELAY
        assert sample_request.target == "delay_minutes"
        assert len(sample_request.features) == 1

    def test_missing_organization_id_rejected(self, sample_feature: PredictionFeature):
        with pytest.raises(InvalidPredictionRequestError):
            PredictionRequest(
                prediction_id="pred_test_001",
                organization_id="",
                features=[sample_feature],
            )

    def test_whitespace_organization_id_rejected(self, sample_feature: PredictionFeature):
        with pytest.raises(InvalidPredictionRequestError):
            PredictionRequest(
                prediction_id="pred_test_001",
                organization_id="   ",
                features=[sample_feature],
            )

    def test_extra_forbidden_client_predicted_value_rejected(self, sample_feature: PredictionFeature):
        with pytest.raises(ValidationError):
            PredictionRequest(
                prediction_id="pred_test_001",
                organization_id="org_test_123",
                features=[sample_feature],
                predicted_value=120.0,  # Prohibited client injection
            )

    def test_extra_forbidden_client_probability_rejected(self, sample_feature: PredictionFeature):
        with pytest.raises(ValidationError):
            PredictionRequest(
                prediction_id="pred_test_001",
                organization_id="org_test_123",
                features=[sample_feature],
                probability=0.95,  # Prohibited client injection
            )

    def test_extra_forbidden_client_arbitrary_risk_score_rejected(self, sample_feature: PredictionFeature):
        with pytest.raises(ValidationError):
            PredictionRequest(
                prediction_id="pred_test_001",
                organization_id="org_test_123",
                features=[sample_feature],
                risk_score=99.0,  # Prohibited client injection
            )

    def test_cross_tenant_feature_rejected(self, sample_feature: PredictionFeature):
        rogue_feature = PredictionFeature(
            feature_name="rogue_score",
            value=10.0,
            source="test",
            source_type="test",
            organization_id="org_other_999",  # Mismatch
        )
        with pytest.raises(PredictionTenantIsolationError):
            PredictionRequest(
                prediction_id="pred_test_001",
                organization_id="org_test_123",
                features=[sample_feature, rogue_feature],
            )

    def test_cross_tenant_risk_assessment_reference_rejected(self, sample_feature: PredictionFeature):
        with pytest.raises(PredictionTenantIsolationError):
            PredictionRequest(
                prediction_id="pred_test_001",
                organization_id="org_test_123",
                risk_assessment_reference={"assessment_id": "ra_1", "organization_id": "org_different_888"},
                features=[sample_feature],
            )

    def test_nan_prediction_horizon_rejected(self, sample_feature: PredictionFeature):
        with pytest.raises(InvalidPredictionRequestError):
            PredictionRequest(
                prediction_id="pred_test_001",
                organization_id="org_test_123",
                features=[sample_feature],
                prediction_horizon_hours=float("nan"),
            )

    def test_serialization_round_trip(self, sample_request: PredictionRequest):
        serialized = sample_request.model_dump(mode="json")
        deserialized = PredictionRequest.model_validate(serialized)
        assert deserialized.prediction_id == sample_request.prediction_id
        assert deserialized.features[0].feature_name == "risk_composite_score"


# ==============================================================================
# GROUP 2: PREDICTION FEATURE CONTRACTS & VALIDATION (12 tests)
# ==============================================================================

class TestPredictionFeatureContracts:
    def test_valid_float_feature(self):
        f = PredictionFeature(
            feature_name="transit_hours",
            value=72.5,
            unit="hours",
            source="TMS",
            source_type="OPERATIONAL",
            organization_id="org_test_123",
        )
        assert f.value == 72.5
        assert f.unit == "hours"

    def test_valid_int_and_bool_features(self):
        f_int = PredictionFeature(
            feature_name="stops_count",
            value=3,
            unit="count",
            source="TMS",
            source_type="OPERATIONAL",
            organization_id="org_test_123",
        )
        f_bool = PredictionFeature(
            feature_name="has_refrigeration",
            value=True,
            source="TMS",
            source_type="OPERATIONAL",
            organization_id="org_test_123",
        )
        assert f_int.value == 3
        assert f_bool.value is True

    def test_nan_feature_value_rejected(self):
        with pytest.raises(FeatureValidationError):
            PredictionFeature(
                feature_name="invalid_nan",
                value=float("nan"),
                source="test",
                source_type="test",
                organization_id="org_test_123",
            )

    def test_positive_infinity_feature_value_rejected(self):
        with pytest.raises(FeatureValidationError):
            PredictionFeature(
                feature_name="invalid_pos_inf",
                value=float("inf"),
                source="test",
                source_type="test",
                organization_id="org_test_123",
            )

    def test_negative_infinity_feature_value_rejected(self):
        with pytest.raises(FeatureValidationError):
            PredictionFeature(
                feature_name="invalid_neg_inf",
                value=float("-inf"),
                source="test",
                source_type="test",
                organization_id="org_test_123",
            )

    def test_empty_organization_id_rejected(self):
        with pytest.raises(FeatureValidationError):
            PredictionFeature(
                feature_name="score",
                value=50.0,
                source="test",
                source_type="test",
                organization_id="",
            )

    def test_whitespace_organization_id_rejected(self):
        with pytest.raises(FeatureValidationError):
            PredictionFeature(
                feature_name="score",
                value=50.0,
                source="test",
                source_type="test",
                organization_id="   ",
            )

    def test_secret_key_in_provenance_rejected(self):
        with pytest.raises((AgentValidationError, ValidationError)):
            PredictionFeature(
                feature_name="score",
                value=50.0,
                source="test",
                source_type="test",
                organization_id="org_test_123",
                provenance={"api_key": "secret_abc_123"},
            )

    def test_bearer_token_in_provenance_rejected(self):
        with pytest.raises((AgentValidationError, ValidationError)):
            PredictionFeature(
                feature_name="score",
                value=50.0,
                source="test",
                source_type="test",
                organization_id="org_test_123",
                provenance={"authorization": "Bearer token_xyz_999"},
            )

    def test_timestamp_preservation(self):
        ts = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
        f = PredictionFeature(
            feature_name="event_timestamp",
            value="2026-09-10T12:00:00Z",
            source="test",
            source_type="test",
            timestamp=ts,
            organization_id="org_test_123",
        )
        assert f.timestamp == ts

    def test_evidence_references_preservation(self):
        f = PredictionFeature(
            feature_name="linked_score",
            value=42.0,
            source="test",
            source_type="test",
            evidence_references=["ev_101", "ev_102"],
            organization_id="org_test_123",
        )
        assert f.evidence_references == ["ev_101", "ev_102"]

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            PredictionFeature(
                feature_name="test",
                value=1.0,
                source="test",
                source_type="test",
                organization_id="org_test_123",
                unexpected_extra_field=123,
            )


# ==============================================================================
# GROUP 3: MODEL METADATA & UNCERTAINTY SEMANTICS (10 tests)
# ==============================================================================

class TestModelMetadataAndUncertainty:
    def test_model_metadata_production_flag(self):
        meta = ModelMetadata(
            model_name="production_delay_net",
            model_version="2.1.0",
            model_type="GRADIENT_BOOSTED_TREES",
            is_production=True,
        )
        assert meta.is_production is True
        assert meta.model_name == "production_delay_net"

    def test_model_metadata_mock_flag(self):
        meta = ModelMetadata(
            model_name="deterministic_mock_shipment_delay",
            model_version="1.0.0-mock",
            is_production=False,
        )
        assert meta.is_production is False

    def test_model_metadata_secret_scrubbing(self):
        with pytest.raises((AgentValidationError, ValidationError)):
            ModelMetadata(
                model_name="test_model",
                model_version="1.0.0",
                metadata={"api_token": "secret_key_000"},
            )

    def test_valid_uncertainty(self):
        unc = PredictionUncertainty(
            prediction_interval=(10.0, 30.0),
            confidence_interval=(12.0, 28.0),
            standard_error=2.5,
            confidence_score=0.90,
            method="BOOTSTRAP_INTERVALS",
        )
        assert unc.prediction_interval == (10.0, 30.0)
        assert unc.confidence_score == 0.90
        assert unc.method == "BOOTSTRAP_INTERVALS"

    def test_uncertainty_interval_with_nan_rejected(self):
        with pytest.raises(InvalidModelOutputError):
            PredictionUncertainty(
                prediction_interval=(float("nan"), 30.0),
            )

    def test_uncertainty_interval_with_infinity_rejected(self):
        with pytest.raises(InvalidModelOutputError):
            PredictionUncertainty(
                prediction_interval=(10.0, float("inf")),
            )

    def test_uncertainty_lower_exceeds_upper_rejected(self):
        with pytest.raises(InvalidModelOutputError):
            PredictionUncertainty(
                prediction_interval=(50.0, 20.0),
            )

    def test_uncertainty_standard_error_nan_rejected(self):
        with pytest.raises(InvalidModelOutputError):
            PredictionUncertainty(
                standard_error=float("nan"),
            )

    def test_uncertainty_confidence_score_bounds(self):
        with pytest.raises(ValidationError):
            PredictionUncertainty(confidence_score=1.5)  # Must be <= 1.0

        with pytest.raises(ValidationError):
            PredictionUncertainty(confidence_score=-0.1)  # Must be >= 0.0

    def test_uncertainty_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            PredictionUncertainty(
                confidence_score=0.8,
                probability_score=0.8,  # Forbidden field
            )


# ==============================================================================
# GROUP 4: PREDICTION RESULT CONTRACT & VALIDATION (10 tests)
# ==============================================================================

class TestPredictionResultContracts:
    def test_valid_completed_result(self):
        res = PredictionResult(
            prediction_id="pred_001",
            organization_id="org_test_123",
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="delay_minutes",
            predicted_value=45.0,
            unit="minutes",
            model_metadata=ModelMetadata(model_name="mock", model_version="1.0"),
            status=PredictionStatus.COMPLETED.value,
        )
        assert res.status == "COMPLETED"
        assert res.predicted_value == 45.0
        assert res.unit == "minutes"

    def test_completed_status_requires_predicted_value(self):
        with pytest.raises(InvalidModelOutputError):
            PredictionResult(
                prediction_id="pred_001",
                organization_id="org_test_123",
                prediction_type=PredictionType.SHIPMENT_DELAY,
                target="delay_minutes",
                predicted_value=None,  # Forbidden for COMPLETED
                model_metadata=ModelMetadata(model_name="mock", model_version="1.0"),
                status=PredictionStatus.COMPLETED.value,
            )

    def test_predicted_value_nan_rejected(self):
        with pytest.raises(InvalidModelOutputError):
            PredictionResult(
                prediction_id="pred_001",
                organization_id="org_test_123",
                prediction_type=PredictionType.SHIPMENT_DELAY,
                target="delay_minutes",
                predicted_value=float("nan"),
                model_metadata=ModelMetadata(model_name="mock", model_version="1.0"),
                status=PredictionStatus.COMPLETED.value,
            )

    def test_predicted_value_infinity_rejected(self):
        with pytest.raises(InvalidModelOutputError):
            PredictionResult(
                prediction_id="pred_001",
                organization_id="org_test_123",
                prediction_type=PredictionType.SHIPMENT_DELAY,
                target="delay_minutes",
                predicted_value=float("inf"),
                model_metadata=ModelMetadata(model_name="mock", model_version="1.0"),
                status=PredictionStatus.COMPLETED.value,
            )

    def test_negative_predicted_delay_rejected(self):
        with pytest.raises(InvalidModelOutputError):
            PredictionResult(
                prediction_id="pred_001",
                organization_id="org_test_123",
                prediction_type=PredictionType.SHIPMENT_DELAY,
                target="delay_minutes",
                predicted_value=-15.0,  # Negative delay is impossible
                model_metadata=ModelMetadata(model_name="mock", model_version="1.0"),
                status=PredictionStatus.COMPLETED.value,
            )

    def test_empty_organization_id_rejected(self):
        with pytest.raises(InvalidModelOutputError):
            PredictionResult(
                prediction_id="pred_001",
                organization_id="",
                prediction_type=PredictionType.SHIPMENT_DELAY,
                target="delay_minutes",
                predicted_value=30.0,
                model_metadata=ModelMetadata(model_name="mock", model_version="1.0"),
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            PredictionResult(
                prediction_id="pred_001",
                organization_id="org_test_123",
                prediction_type=PredictionType.SHIPMENT_DELAY,
                target="delay_minutes",
                predicted_value=30.0,
                model_metadata=ModelMetadata(model_name="mock", model_version="1.0"),
                arbitrary_field="not_allowed",
            )

    def test_secret_in_provenance_rejected(self):
        with pytest.raises((AgentValidationError, ValidationError)):
            PredictionResult(
                prediction_id="pred_001",
                organization_id="org_test_123",
                prediction_type=PredictionType.SHIPMENT_DELAY,
                target="delay_minutes",
                predicted_value=30.0,
                model_metadata=ModelMetadata(model_name="mock", model_version="1.0"),
                provenance={"api_key": "rsa_secret_123"},
            )

    def test_not_available_status_allows_none_predicted_value(self):
        res = PredictionResult(
            prediction_id="pred_001",
            organization_id="org_test_123",
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="delay_minutes",
            predicted_value=None,
            model_metadata=ModelMetadata(model_name="prod", model_version="0.0", is_production=True),
            status=PredictionStatus.NOT_AVAILABLE.value,
        )
        assert res.status == "NOT_AVAILABLE"
        assert res.predicted_value is None

    def test_created_by_node_defaults_to_prediction_agent(self):
        res = PredictionResult(
            prediction_id="pred_001",
            organization_id="org_test_123",
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="delay_minutes",
            predicted_value=10.0,
            model_metadata=ModelMetadata(model_name="mock", model_version="1.0"),
        )
        assert res.created_by_node == "prediction_agent"


# ==============================================================================
# GROUP 5: PREDICTION SERVICES & UNAVAILABLE DEFAULT (10 tests)
# ==============================================================================

class TestPredictionServices:
    def test_base_service_abstract_enforcement(self):
        class IncompleteService(BasePredictionService):
            pass

        with pytest.raises(TypeError):
            IncompleteService()  # Cannot instantiate without abstract methods

    def test_unavailable_service_is_not_available(self):
        svc = UnavailablePredictionService()
        assert svc.is_available() is False

    def test_unavailable_service_metadata(self):
        svc = UnavailablePredictionService()
        meta = svc.get_model_metadata()
        assert meta.is_production is True
        assert meta.metadata.get("status") == "UNAVAILABLE"

    def test_unavailable_service_returns_not_available_status(self, sample_request: PredictionRequest):
        svc = UnavailablePredictionService()
        res = svc.predict(sample_request)
        assert res.status == PredictionStatus.NOT_AVAILABLE.value
        assert res.predicted_value is None

    def test_unavailable_service_returns_limitation(self, sample_request: PredictionRequest):
        svc = UnavailablePredictionService()
        res = svc.predict(sample_request)
        assert len(res.limitations) == 1
        assert res.limitations[0].category == LimitationCategory.PREDICTION_MODEL_UNAVAILABLE

    def test_unavailable_service_never_fabricates_delay(self, sample_request: PredictionRequest):
        svc = UnavailablePredictionService()
        res = svc.predict(sample_request)
        assert res.predicted_value is None
        assert res.uncertainty is None

    def test_mock_service_is_available(self):
        svc = DeterministicMockPredictionService()
        assert svc.is_available() is True

    def test_mock_service_metadata_explicitly_not_production(self):
        svc = DeterministicMockPredictionService()
        meta = svc.get_model_metadata()
        assert meta.is_production is False
        assert meta.model_type == "DETERMINISTIC_TEST_MOCK"
        assert meta.metadata.get("disclaimer") == "NOT_FOR_PRODUCTION_USE"

    def test_mock_service_computes_delay_from_risk_score(self, sample_request: PredictionRequest):
        svc = DeterministicMockPredictionService(base_delay_minutes=15.0)
        # sample_request has risk_composite_score = 65.5
        # Expected: 15.0 + 65.5 * 1.5 = 113.25
        res = svc.predict(sample_request)
        assert res.status == PredictionStatus.COMPLETED.value
        assert res.predicted_value == 113.25
        assert res.uncertainty is not None
        assert res.uncertainty.prediction_interval == (90.6, 141.56)

    def test_mock_service_computes_delay_from_disruption_flags(self):
        svc = DeterministicMockPredictionService(base_delay_minutes=15.0)
        feat_port = PredictionFeature(
            feature_name="port_disruption_detected",
            value=1.0,
            source="test",
            source_type="test",
            organization_id="org_test_123",
        )
        feat_weather = PredictionFeature(
            feature_name="weather_disruption_detected",
            value=1.0,
            source="test",
            source_type="test",
            organization_id="org_test_123",
        )
        req = PredictionRequest(
            prediction_id="pred_test_flags",
            organization_id="org_test_123",
            features=[feat_port, feat_weather],
        )
        # 15.0 (base) + 120.0 (port) + 90.0 (weather) = 225.0
        res = svc.predict(req)
        assert res.predicted_value == 225.0


# ==============================================================================
# GROUP 6: FEATURE EXTRACTION & RISK INTEGRATION (10 tests)
# ==============================================================================

class TestFeatureExtraction:
    def test_extract_risk_composite_score(self, sample_graph_state: AgentGraphStateDict):
        features, limitations = PredictionFeatureExtractor.extract_features(sample_graph_state, "org_test_123")
        score_feat = next((f for f in features if f.feature_name == "risk_composite_score"), None)
        assert score_feat is not None
        assert score_feat.value == 65.5
        assert score_feat.unit == "score"
        assert score_feat.source_type == "RISK_ENGINE"

    def test_extract_risk_level_severity(self, sample_graph_state: AgentGraphStateDict):
        features, _ = PredictionFeatureExtractor.extract_features(sample_graph_state, "org_test_123")
        sev_feat = next((f for f in features if f.feature_name == "risk_level_severity"), None)
        assert sev_feat is not None
        assert sev_feat.value == 3  # HIGH maps to 3

    def test_extract_risk_factor_count(self, sample_graph_state: AgentGraphStateDict):
        features, _ = PredictionFeatureExtractor.extract_features(sample_graph_state, "org_test_123")
        count_feat = next((f for f in features if f.feature_name == "risk_factor_count"), None)
        assert count_feat is not None
        assert count_feat.value == 3

    def test_preserves_evidence_ids_from_risk_assessment(self, sample_graph_state: AgentGraphStateDict):
        features, _ = PredictionFeatureExtractor.extract_features(sample_graph_state, "org_test_123")
        score_feat = next((f for f in features if f.feature_name == "risk_composite_score"), None)
        assert score_feat is not None
        assert score_feat.evidence_references == ["ev_001", "ev_002"]

    def test_extract_port_disruption_detected(self, sample_graph_state: AgentGraphStateDict):
        features, _ = PredictionFeatureExtractor.extract_features(sample_graph_state, "org_test_123")
        port_feat = next((f for f in features if f.feature_name == "port_disruption_detected"), None)
        assert port_feat is not None
        assert port_feat.value == 1.0

    def test_extract_logistics_delay_detected(self, sample_graph_state: AgentGraphStateDict):
        sample_graph_state["structured_findings"].append({
            "finding_id": "find_002",
            "category": "TRANSIT_DELAY",
            "title": "Customs clearance delay",
            "summary": "Delay at border",
            "severity": "MEDIUM",
            "confidence": 0.8,
            "evidence_ids": ["ev_003"],
            "created_by_node": "research_agent",
        })
        features, _ = PredictionFeatureExtractor.extract_features(sample_graph_state, "org_test_123")
        delay_feat = next((f for f in features if f.feature_name == "logistics_delay_detected"), None)
        assert delay_feat is not None
        assert delay_feat.value == 1.0

    def test_extract_weather_disruption_detected(self, sample_graph_state: AgentGraphStateDict):
        sample_graph_state["structured_findings"].append({
            "finding_id": "find_003",
            "category": "WEATHER_STORM",
            "title": "North Sea Gale",
            "summary": "High wind advisory",
            "severity": "HIGH",
            "confidence": 0.95,
            "evidence_ids": ["ev_004"],
            "created_by_node": "research_agent",
        })
        features, _ = PredictionFeatureExtractor.extract_features(sample_graph_state, "org_test_123")
        weather_feat = next((f for f in features if f.feature_name == "weather_disruption_detected"), None)
        assert weather_feat is not None
        assert weather_feat.value == 1.0

    def test_extract_scheduled_transit_hours(self, sample_graph_state: AgentGraphStateDict):
        features, _ = PredictionFeatureExtractor.extract_features(sample_graph_state, "org_test_123")
        transit_feat = next((f for f in features if f.feature_name == "scheduled_transit_hours"), None)
        assert transit_feat is not None
        assert transit_feat.value == 48.0

    def test_insufficient_features_limitation_when_empty(self):
        empty_state: AgentGraphStateDict = {
            "organization_id": "org_test_123",
            "structured_findings": [],
            "risk_assessment_reference": None,
        }
        features, limitations = PredictionFeatureExtractor.extract_features(empty_state, "org_test_123")
        assert len(features) == 0
        assert len(limitations) == 1
        assert limitations[0].category == LimitationCategory.INSUFFICIENT_FEATURES

    def test_cross_tenant_risk_assessment_raises_tenant_error(self, sample_graph_state: AgentGraphStateDict):
        sample_graph_state["risk_assessment_reference"]["organization_id"] = "org_malicious_999"
        with pytest.raises(PredictionTenantIsolationError):
            PredictionFeatureExtractor.extract_features(sample_graph_state, "org_test_123")


# ==============================================================================
# GROUP 7: PREDICTION AGENT ORCHESTRATION & FINDINGS (10 tests)
# ==============================================================================

class TestPredictionAgentExecution:
    def test_agent_with_unavailable_service(self, sample_request: PredictionRequest):
        agent = PredictionAgent(service=UnavailablePredictionService())
        result, findings = agent.execute(sample_request)
        assert result.status == PredictionStatus.NOT_AVAILABLE.value
        assert result.predicted_value is None
        assert len(findings) == 1
        assert findings[0].category == "PREDICTION_UNAVAILABLE"

    def test_agent_with_mock_service(self, sample_request: PredictionRequest):
        agent = PredictionAgent(service=DeterministicMockPredictionService())
        result, findings = agent.execute(sample_request)
        assert result.status == PredictionStatus.COMPLETED.value
        assert result.predicted_value is not None
        assert len(findings) == 1
        assert findings[0].category == "PREDICTED_DELAY"
        assert "Predicted Shipment Delay" in findings[0].title

    def test_agent_with_no_features_returns_insufficient_features(self):
        agent = PredictionAgent(service=DeterministicMockPredictionService())
        req = PredictionRequest(
            prediction_id="pred_empty",
            organization_id="org_test_123",
            features=[],
        )
        result, findings = agent.execute(req)
        assert result.status == PredictionStatus.INSUFFICIENT_FEATURES.value
        assert result.predicted_value is None
        assert len(findings) == 1
        assert findings[0].category == "INSUFFICIENT_FEATURES"

    def test_agent_high_uncertainty_limitation(self, sample_request: PredictionRequest):
        mock_svc = MagicMock(spec=BasePredictionService)
        meta = ModelMetadata(model_name="mock", model_version="1.0")
        mock_svc.get_model_metadata.return_value = meta
        mock_svc.is_available.return_value = True
        mock_svc.predict.return_value = PredictionResult(
            prediction_id=sample_request.prediction_id,
            organization_id=sample_request.organization_id,
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="delay_minutes",
            predicted_value=100.0,
            unit="minutes",
            uncertainty=PredictionUncertainty(
                prediction_interval=(10.0, 200.0),  # Range = 190 > 100 * 1.5
                confidence_score=0.7,
            ),
            model_metadata=meta,
            status=PredictionStatus.COMPLETED.value,
        )
        agent = PredictionAgent(service=mock_svc)
        result, _ = agent.execute(sample_request)
        assert any(lim.category == LimitationCategory.HIGH_UNCERTAINTY for lim in result.limitations)

    def test_agent_empty_org_id_rejected(self):
        agent = PredictionAgent()
        with pytest.raises(InvalidPredictionRequestError):
            agent.execute(MagicMock(organization_id=""))

    def test_agent_cross_tenant_result_raises_tenant_error(self, sample_request: PredictionRequest):
        mock_svc = MagicMock(spec=BasePredictionService)
        mock_svc.get_model_metadata.return_value = ModelMetadata(model_name="m", model_version="v")
        mock_svc.predict.return_value = PredictionResult(
            prediction_id="pred_1",
            organization_id="org_different_777",  # Cross-tenant output
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="delay_minutes",
            predicted_value=50.0,
            model_metadata=ModelMetadata(model_name="m", model_version="v"),
            status=PredictionStatus.COMPLETED.value,
        )
        agent = PredictionAgent(service=mock_svc)
        with pytest.raises(PredictionTenantIsolationError):
            agent.execute(sample_request)

    def test_deterministic_id_generation_consistency(self):
        id_1 = generate_deterministic_prediction_id(
            organization_id="org_test_123",
            prediction_type="SHIPMENT_DELAY",
            target_reference="ship_999",
            feature_fingerprint="feat_count_2:risk_score:transit_hours",
            model_name="deterministic_mock_shipment_delay",
            model_version="1.0.0-mock",
        )
        id_2 = generate_deterministic_prediction_id(
            organization_id="org_test_123",
            prediction_type="SHIPMENT_DELAY",
            target_reference="ship_999",
            feature_fingerprint="feat_count_2:risk_score:transit_hours",
            model_name="deterministic_mock_shipment_delay",
            model_version="1.0.0-mock",
        )
        assert id_1 == id_2
        assert uuid.UUID(id_1).version == 5

    def test_deterministic_id_varies_by_model_version(self):
        id_v1 = generate_deterministic_prediction_id(
            "org_123", "SHIPMENT_DELAY", "ship_1", "fp_1", "model_x", "1.0.0"
        )
        id_v2 = generate_deterministic_prediction_id(
            "org_123", "SHIPMENT_DELAY", "ship_1", "fp_1", "model_x", "2.0.0"
        )
        assert id_v1 != id_v2

    def test_deterministic_id_varies_by_tenant(self):
        id_org1 = generate_deterministic_prediction_id(
            "org_1", "SHIPMENT_DELAY", "ship_1", "fp_1", "model_x", "1.0.0"
        )
        id_org2 = generate_deterministic_prediction_id(
            "org_2", "SHIPMENT_DELAY", "ship_1", "fp_1", "model_x", "1.0.0"
        )
        assert id_org1 != id_org2

    def test_repeated_agent_execution_produces_identical_output(self, sample_request: PredictionRequest):
        agent = PredictionAgent(service=DeterministicMockPredictionService())
        res1, find1 = agent.execute(sample_request)
        res2, find2 = agent.execute(sample_request)
        assert res1.predicted_value == res2.predicted_value
        assert find1[0].summary == find2[0].summary


# ==============================================================================
# GROUP 8: STATE OWNERSHIP & WRITE BOUNDARIES (10 tests)
# ==============================================================================

class TestStateOwnershipAndValidation:
    def test_prediction_stage_can_write_prediction_id(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        validate_state_update(
            current_state=state_obj,
            update_payload={"prediction_id": "pred_001"},
            writer_node_id="prediction_agent",
            writer_stage=AgentStage.PREDICTION,
        )

    def test_prediction_stage_can_write_prediction_reference(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        validate_state_update(
            current_state=state_obj,
            update_payload={"prediction_reference": {"prediction_id": "pred_001", "status": "COMPLETED"}},
            writer_node_id="prediction_agent",
            writer_stage=AgentStage.PREDICTION,
        )

    def test_prediction_stage_can_write_prediction_result(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        validate_state_update(
            current_state=state_obj,
            update_payload={"prediction_result": {"prediction_id": "pred_001", "predicted_value": 30.0}},
            writer_node_id="prediction_agent",
            writer_stage=AgentStage.PREDICTION,
        )

    def test_research_stage_cannot_write_prediction_id(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"prediction_id": "pred_001"},
                writer_node_id="research_agent",
                writer_stage=AgentStage.RESEARCH,
            )

    def test_risk_stage_cannot_write_prediction_reference(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"prediction_reference": {"prediction_id": "pred_001"}},
                writer_node_id="risk_agent",
                writer_stage=AgentStage.RISK_ASSESSMENT,
            )

    def test_initialization_stage_cannot_write_prediction_result(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"prediction_result": {"prediction_id": "pred_001"}},
                writer_node_id="initialization",
                writer_stage=AgentStage.INITIALIZATION,
            )

    def test_prediction_stage_cannot_mutate_organization_id(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentTenantIsolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"organization_id": "org_tampered_666"},
                writer_node_id="prediction_agent",
                writer_stage=AgentStage.PREDICTION,
            )

    def test_prediction_stage_cannot_overwrite_evidence_bundle(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"evidence_bundle_id": "bundle_tampered_777"},
                writer_node_id="prediction_agent",
                writer_stage=AgentStage.PREDICTION,
            )

    def test_prediction_stage_cannot_overwrite_risk_assessment(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"risk_assessment_id": "ra_tampered_888"},
                writer_node_id="prediction_agent",
                writer_stage=AgentStage.PREDICTION,
            )

    def test_prediction_stage_cannot_overwrite_approval_reference(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"approval_reference": "appr_tampered_999"},
                writer_node_id="prediction_agent",
                writer_stage=AgentStage.PREDICTION,
            )


# ==============================================================================
# GROUP 9: LANGGRAPH NODE CONTRACT & EXECUTION (10 tests)
# ==============================================================================

class TestLangGraphNodeAndExecution:
    def test_prediction_node_contract_properties(self):
        assert PREDICTION_NODE_CONTRACT.node_id == "prediction_agent"
        assert PREDICTION_NODE_CONTRACT.stage == AgentStage.PREDICTION
        assert PREDICTION_NODE_CONTRACT.is_side_effecting is False
        assert "prediction_id" in PREDICTION_NODE_CONTRACT.output_keys
        assert "prediction_result" in PREDICTION_NODE_CONTRACT.output_keys
        assert PREDICTION_NODE_CONTRACT.requires_evidence is True

    def test_prediction_node_default_unavailable_service(self, sample_graph_state: AgentGraphStateDict):
        updates = prediction_node(sample_graph_state)
        assert updates["prediction_id"] is not None
        assert updates["prediction_reference"]["status"] == "NOT_AVAILABLE"
        assert updates["prediction_result"]["predicted_value"] is None
        assert updates["current_stage"] == AgentStage.PREDICTION.value
        assert updates["current_node"] == "prediction_agent"

    def test_prediction_node_with_mock_service(self, sample_graph_state: AgentGraphStateDict):
        mock_svc = DeterministicMockPredictionService()
        updates = prediction_node(sample_graph_state, service=mock_svc)
        assert updates["prediction_reference"]["status"] == "COMPLETED"
        assert updates["prediction_reference"]["predicted_value"] is not None
        assert updates["prediction_reference"]["predicted_value"] > 0.0

    def test_prediction_node_increments_step_count(self, sample_graph_state: AgentGraphStateDict):
        init_step = sample_graph_state["step_count"]
        updates = prediction_node(sample_graph_state)
        assert updates["step_count"] == init_step + 1

    def test_prediction_node_missing_organization_id_raises_tenant_error(self, sample_graph_state: AgentGraphStateDict):
        sample_graph_state["organization_id"] = ""
        with pytest.raises(PredictionTenantIsolationError):
            prediction_node(sample_graph_state)

    def test_prediction_node_emits_telemetry_on_success(self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch):
        telemetry_records: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: telemetry_records.append(t))
        prediction_node(sample_graph_state)
        assert len(telemetry_records) == 1
        telemetry = telemetry_records[0]
        assert telemetry.node_name == "prediction_agent"
        assert telemetry.status == "SUCCESS"
        assert telemetry.organization_id == "org_test_123"

    def test_prediction_node_emits_telemetry_on_failure(self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch):
        telemetry_records: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: telemetry_records.append(t))
        sample_graph_state["organization_id"] = ""
        with pytest.raises(PredictionTenantIsolationError):
            prediction_node(sample_graph_state)
        assert len(telemetry_records) == 1
        telemetry = telemetry_records[0]
        assert telemetry.node_name == "prediction_agent"
        assert telemetry.status == "FAILED"
        assert telemetry.error_code == "PredictionTenantIsolationError"

    def test_prediction_node_registry_registration(self):
        reg = NodeRegistry()
        reg.register_node(PREDICTION_NODE_CONTRACT, prediction_node)
        assert reg.has_node("prediction_agent")
        entry = reg.get_node("prediction_agent")
        assert entry.contract.node_id == "prediction_agent"
        assert entry.contract.stage == AgentStage.PREDICTION

    def test_apply_state_update_with_prediction_updates(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        updates = prediction_node(sample_graph_state, service=DeterministicMockPredictionService())
        new_state = apply_state_update(
            current_state=state_obj,
            update_payload=updates,
            writer_node_id="prediction_agent",
            writer_stage=AgentStage.PREDICTION,
        )
        assert new_state.prediction_id == updates["prediction_id"]
        assert new_state.prediction_reference == updates["prediction_reference"]
        assert new_state.current_stage == AgentStage.PREDICTION
        assert new_state.current_node == "prediction_agent"

    def test_full_pipeline_to_prediction_termination(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        # 1. Run prediction node
        pred_updates = prediction_node(sample_graph_state, service=DeterministicMockPredictionService())
        post_pred_state = apply_state_update(
            current_state=state_obj,
            update_payload=pred_updates,
            writer_node_id="prediction_agent",
            writer_stage=AgentStage.PREDICTION,
        )
        # 2. Transition safely to TERMINATION
        term_updates = {
            "current_stage": AgentStage.TERMINATION.value,
            "current_node": "termination",
            "status": "COMPLETED",
            "completed_at": datetime.now(timezone.utc),
            "termination_reason": "Prediction pipeline complete.",
        }
        final_state = apply_state_update(
            current_state=post_pred_state,
            update_payload=term_updates,
            writer_node_id="termination",
            writer_stage=AgentStage.TERMINATION,
        )
        assert final_state.current_stage == AgentStage.TERMINATION
        assert final_state.prediction_id == pred_updates["prediction_id"]
        assert final_state.status.value == "COMPLETED"


# ==============================================================================
# GROUP 10: SECURITY & MULTI-TENANT ISOLATION (8 tests)
# ==============================================================================

class TestSecurityAndTenantIsolation:
    def test_cross_tenant_request_isolation(self, sample_request: PredictionRequest):
        req_dict = sample_request.model_dump()
        req_dict["features"][0]["organization_id"] = "org_infiltrator_007"
        with pytest.raises((ValidationError, PredictionTenantIsolationError)):
            PredictionRequest.model_validate(req_dict)

    def test_cross_tenant_risk_reference_isolation(self, sample_request: PredictionRequest):
        req_dict = sample_request.model_dump()
        req_dict["risk_assessment_reference"]["organization_id"] = "org_other_999"
        with pytest.raises((ValidationError, PredictionTenantIsolationError)):
            PredictionRequest.model_validate(req_dict)

    def test_secret_scrubbing_bearer_token_in_prediction_feature(self):
        with pytest.raises((AgentValidationError, ValidationError)):
            PredictionFeature(
                feature_name="test",
                value=1.0,
                source="test",
                source_type="test",
                organization_id="org_test_123",
                provenance={"auth_header": "Bearer secret_jwt_token_12345"},
            )

    def test_secret_scrubbing_password_in_prediction_feature(self):
        with pytest.raises((AgentValidationError, ValidationError)):
            PredictionFeature(
                feature_name="test",
                value=1.0,
                source="test",
                source_type="test",
                organization_id="org_test_123",
                provenance={"db_password": "super_secret_password_1"},
            )

    def test_secret_scrubbing_bearer_in_prediction_result(self):
        with pytest.raises((AgentValidationError, ValidationError)):
            PredictionResult(
                prediction_id="pred_1",
                organization_id="org_test_123",
                prediction_type=PredictionType.SHIPMENT_DELAY,
                target="delay_minutes",
                predicted_value=15.0,
                model_metadata=ModelMetadata(model_name="m", model_version="v"),
                provenance={"auth": "bearer token_123"},
            )

    def test_sensitive_value_in_state_update_rejected(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentValidationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"findings": {"secret": "Bearer abc_secret_token"}},
                writer_node_id="prediction_agent",
                writer_stage=AgentStage.PREDICTION,
            )

    def test_cross_tenant_extraction_rejected(self, sample_graph_state: AgentGraphStateDict):
        with pytest.raises(PredictionTenantIsolationError):
            PredictionFeatureExtractor.extract_features(sample_graph_state, "org_impostor_999")

    def test_empty_tenant_in_deterministic_id_rejected(self):
        with pytest.raises(PredictionTenantIsolationError):
            generate_deterministic_prediction_id(
                organization_id="",
                prediction_type="SHIPMENT_DELAY",
                target_reference="ref",
                feature_fingerprint="fp",
                model_name="model",
                model_version="1.0",
            )


# ==============================================================================
# GROUP 11: NON-ACTION SAFETY & RISK ENGINE IMMUTABILITY (8 tests)
# ==============================================================================

class TestNonActionAndRiskPreservation:
    def test_risk_score_in_state_is_unchanged_after_prediction(self, sample_graph_state: AgentGraphStateDict):
        orig_score = sample_graph_state["risk_assessment_reference"]["risk_score"]
        updates = prediction_node(sample_graph_state, service=DeterministicMockPredictionService())
        assert "risk_score" not in updates
        assert "risk_assessment_reference" not in updates
        assert sample_graph_state["risk_assessment_reference"]["risk_score"] == orig_score

    def test_risk_level_in_state_is_unchanged_after_prediction(self, sample_graph_state: AgentGraphStateDict):
        orig_level = sample_graph_state["risk_assessment_reference"]["risk_level"]
        updates = prediction_node(sample_graph_state, service=DeterministicMockPredictionService())
        assert "risk_level" not in updates
        assert sample_graph_state["risk_assessment_reference"]["risk_level"] == orig_level

    def test_risk_factor_count_in_state_is_unchanged_after_prediction(self, sample_graph_state: AgentGraphStateDict):
        orig_factors = sample_graph_state["risk_assessment_reference"]["factor_count"]
        updates = prediction_node(sample_graph_state, service=DeterministicMockPredictionService())
        assert "factor_count" not in updates
        assert sample_graph_state["risk_assessment_reference"]["factor_count"] == orig_factors

    def test_risk_assessment_id_in_state_is_unchanged(self, sample_graph_state: AgentGraphStateDict):
        orig_id = sample_graph_state["risk_assessment_id"]
        updates = prediction_node(sample_graph_state, service=DeterministicMockPredictionService())
        assert "risk_assessment_id" not in updates
        assert sample_graph_state["risk_assessment_id"] == orig_id

    def test_research_findings_preserved_in_state(self, sample_graph_state: AgentGraphStateDict):
        orig_finding_id = sample_graph_state["structured_findings"][0]["finding_id"]
        updates = prediction_node(sample_graph_state, service=DeterministicMockPredictionService())
        updated_finding_ids = [f["finding_id"] for f in updates["structured_findings"]]
        assert orig_finding_id in updated_finding_ids

    def test_no_shipment_mutation(self, sample_graph_state: AgentGraphStateDict):
        updates = prediction_node(sample_graph_state, service=DeterministicMockPredictionService())
        for prohibited in ("shipment_status", "reroute", "new_route", "carrier_instructions"):
            assert prohibited not in updates

    def test_no_inventory_mutation(self, sample_graph_state: AgentGraphStateDict):
        updates = prediction_node(sample_graph_state, service=DeterministicMockPredictionService())
        for prohibited in ("inventory_allocated", "stock_adjusted", "warehouse_order"):
            assert prohibited not in updates

    def test_no_external_carrier_or_supplier_communication(self, sample_graph_state: AgentGraphStateDict):
        updates = prediction_node(sample_graph_state, service=DeterministicMockPredictionService())
        for prohibited in ("carrier_dispatched", "supplier_alert_sent", "email_sent", "webhook_triggered"):
            assert prohibited not in updates
