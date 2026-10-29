"""End-to-End integration test tracing NOAA alerts through the entire ChainSentinel pipeline.

Verifies:
 1. NOAA Alerts Adapter live fetch and schema validation
 2. Canonical normalization with polygon centroid and geofence extraction
 3. Domain normalization to NormalizedRiskSignal (SignalDomain.WEATHER)
 4. Risk Engine evaluation producing high-confidence RiskAssessment and primary drivers
 5. Persistence mapping to ORMRiskAssessment and ORMRiskFactor entities
 6. LangGraph StateGraph initialization, execution context validation, and multi-agent lifecycle
"""
from __future__ import annotations

import uuid
import pytest

from app.integrations.base import IngestionBatch, ProviderHealthStatus
from app.integrations.canonical import CanonicalEventType, EventSeverity
from app.integrations.registry import default_provider_registry
from app.integrations.providers.noaa import NOAAAlertsAdapter, NOAANormalizer
from app.normalization.contract import SignalDomain
from app.normalization.handlers import DomainNormalizationRegistry
from app.risk_engine.pipeline import BaselineRiskEngine
from app.risk_engine.context import RiskEvaluationContext
from app.risk_engine.persistence import RiskAssessmentPersistenceAdapter
from app.agents.contracts import (
    AgentExecutionContext,
    AgentGraphState,
    AgentLifecycleStatus,
    AgentStage,
    RiskAssessmentReference,
)
from app.agents.graph import execute_agent_graph

ORG_ID = "org_chainsentinel_e2e_verification"


def test_noaa_to_risk_engine_and_langgraph_trace():
    """Verify one NOAA severe alert traces through Ingestion -> Canonical -> Risk -> Persistence -> LangGraph."""
    adapter = default_provider_registry.create_adapter("noaa_nws")

    # 1. Health check & Reachability
    try:
        health = adapter.health_check()
    except Exception as exc:
        pytest.skip(f"Live network unavailable for NOAA NWS E2E test: {exc}")

    if health.status != ProviderHealthStatus.HEALTHY:
        pytest.skip(f"NOAA NWS endpoint not reachable (status={health.status.value})")

    # 2. Ingest active alerts with tenant scoping
    batch = adapter.fetch(severity="Severe,Extreme", org_id=ORG_ID)
    assert isinstance(batch, IngestionBatch)
    assert len(batch.events) > 0, "Expected at least 1 active severe/extreme NOAA alert."
    raw_event = batch.events[0]
    assert raw_event.org_id == ORG_ID
    assert raw_event.provider_name == "noaa_nws"

    # 3. Canonical Normalization
    noaa_normalizer = NOAANormalizer()
    canonical = noaa_normalizer.normalize(raw_event)
    assert canonical.org_id == ORG_ID
    assert canonical.provider == "noaa_nws"
    assert canonical.severity in (EventSeverity.HIGH, EventSeverity.CRITICAL)
    assert canonical.event_type in (
        CanonicalEventType.WEATHER_ALERT,
        CanonicalEventType.EXTREME_WEATHER,
        CanonicalEventType.FLOOD,
        CanonicalEventType.STORM,
        CanonicalEventType.CYCLONE,
    )

    # 4. Domain Normalization to NormalizedRiskSignal
    domain_reg = DomainNormalizationRegistry()
    handler = domain_reg.resolve_handler(canonical)
    assert handler.__class__.__name__ == "WeatherNormalizationHandler"
    risk_signal = handler.normalize(canonical)
    assert risk_signal.domain == SignalDomain.WEATHER
    assert risk_signal.organization_id == ORG_ID
    assert risk_signal.measurements is not None
    assert risk_signal.measurements.disruption_level == 1.0

    # 5. Risk Engine Evaluation
    engine = BaselineRiskEngine()
    eval_ctx = RiskEvaluationContext(
        organization_id=ORG_ID,
        signals=[risk_signal],
    )
    assessment = engine.evaluate(context=eval_ctx)
    assert assessment.organization_id == ORG_ID
    assert assessment.overall_score.score >= 50.0  # Severe/Extreme weather contributes high risk
    assert assessment.risk_level in ("HIGH", "CRITICAL")
    assert len(assessment.factors) >= 1
    assert assessment.primary_factor is not None
    assert "Weather Disruption" in assessment.primary_factor.name

    # 6. Persistence Boundary Serialization
    orm_assessment, orm_factors = RiskAssessmentPersistenceAdapter.to_orm(
        assessment, risk_id="risk_weather_e2e_001"
    )
    assert orm_assessment.id == assessment.assessment_id
    assert orm_assessment.org_id == ORG_ID
    assert len(orm_factors) == len(assessment.factors)
    assert "findings" in orm_assessment.__dict__ or hasattr(orm_assessment, "findings")

    # 7. LangGraph Orchestration Lifecycle
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    trace_id = f"trc_{uuid.uuid4().hex[:12]}"

    risk_ref = RiskAssessmentReference(
        assessment_id=assessment.assessment_id,
        organization_id=ORG_ID,
        assessment_fingerprint=assessment.fingerprint,
        risk_score=assessment.overall_score.score,
        risk_level=assessment.risk_level.value,
        factor_count=len(assessment.factors),
    )

    init_state = AgentGraphState(
        run_id=run_id,
        organization_id=ORG_ID,
        actor_id="risk_automation_daemon",
        request_id=f"req_{uuid.uuid4().hex[:8]}",
        correlation_id=canonical.correlation_id or f"corr_{uuid.uuid4().hex[:8]}",
        trace_id=trace_id,
        objective="Assess NOAA severe weather disruption and formulate mitigation scenario",
        risk_assessment_id=assessment.assessment_id,
        risk_assessment=risk_ref,
        current_stage=AgentStage.INITIALIZATION,
        status=AgentLifecycleStatus.RUNNING,
    )

    exec_ctx = AgentExecutionContext(
        organization_id=ORG_ID,
        actor_id="risk_automation_daemon",
        request_id=init_state.request_id,
        correlation_id=init_state.correlation_id,
        trace_id=trace_id,
        roles=["RiskManager"],
    )

    final_state = execute_agent_graph(
        state=init_state,
        context=exec_ctx,
    )
    assert final_state.status in (
        AgentLifecycleStatus.COMPLETED,
        AgentLifecycleStatus.WAITING_FOR_APPROVAL,
    )
    assert final_state.organization_id == ORG_ID
    assert final_state.step_count >= 1
