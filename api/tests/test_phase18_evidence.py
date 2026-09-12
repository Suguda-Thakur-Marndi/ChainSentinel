"""Tests for Phase 18 Evidence Collection layer (read-only, temporal, provenance, tenancy)."""

from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.action.contract import ActionType, TargetEntityType
from app.agents.verification.contract import (
    EvidenceSourcePrecedence,
    ObservedEvidenceItem,
    VerificationCommand,
)
from app.agents.verification.errors import (
    VerificationSecurityViolationError,
    VerificationTenantIsolationError,
)
from app.agents.verification.evidence import EvidenceCollector, MAX_EVIDENCE_ITEMS
from app.db.base import Base
import app.models  # Register all 34 models
from app.models.logistics import Shipment, ShipmentEvent
from app.models.network import Carrier, Factory, Warehouse
from app.models.tenancy import Organization


@pytest.fixture
def sqlite_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = session_factory()

    # Seed tenants
    org_a = Organization(id="org_alpha", name="Alpha Supply Corp")
    org_b = Organization(id="org_beta", name="Beta Global")
    session.add_all([org_a, org_b])

    # Seed shipments
    ship1 = Shipment(
        id="ship_001",
        org_id="org_alpha",
        tracking_number="TRK-ALPHA-01",
        route_id="ROUTE_NORTH",
        carrier_id="CARRIER_OCEAN_1",
        status="IN_TRANSIT",
        mode="OCEAN",
        data_provenance="REAL",
    )
    ship_cross = Shipment(
        id="ship_cross_tenant",
        org_id="org_beta",
        tracking_number="TRK-BETA-99",
        status="IN_TRANSIT",
    )
    session.add_all([ship1, ship_cross])
    session.commit()
    return session


class TestEvidenceCollector:
    """Validate authoritative evidence collection invariants."""

    def test_collect_operational_shipment_state(self, sqlite_db):
        collector = EvidenceCollector(sqlite_db)
        cmd = VerificationCommand(
            action_id="act_reroute_1",
            organization_id="org_alpha",
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_001",
            action_parameters={"new_route_id": "ROUTE_NORTH"},
        )

        evidence = collector.collect(cmd)
        assert len(evidence) >= 1
        item = evidence[0]
        assert item.entity_id == "ship_001"
        assert item.source_precedence == EvidenceSourcePrecedence.REAL
        assert item.observed_attributes["route_id"] == "ROUTE_NORTH"
        assert item.observed_attributes["status"] == "IN_TRANSIT"

    def test_collect_rejects_cross_tenant_shipment(self, sqlite_db):
        collector = EvidenceCollector(sqlite_db)
        cmd = VerificationCommand(
            action_id="act_illegal_cross",
            organization_id="org_alpha",  # Requesting as Alpha
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_cross_tenant",  # Belongs to Beta
        )

        with pytest.raises(VerificationTenantIsolationError, match="belongs to organization 'org_beta'"):
            collector.collect(cmd)

    def test_collect_temporal_filtering_drops_stale_events(self, sqlite_db):
        """Events before action execution must be excluded."""
        now = datetime.now(timezone.utc)
        exec_time = now

        # Add an old historical event (1 hour before execution)
        stale_event = ShipmentEvent(
            id="ev_stale",
            shipment_id="ship_001",
            event_type="HISTORICAL_DEPOT_DEPARTURE",
            timestamp=exec_time - timedelta(hours=1),
            source="REAL",
        )
        # Add a fresh post-action event (10 minutes after execution)
        fresh_event = ShipmentEvent(
            id="ev_fresh",
            shipment_id="ship_001",
            event_type="REROUTE_CONFIRMED",
            timestamp=exec_time + timedelta(minutes=10),
            source="REAL",
        )
        sqlite_db.add_all([stale_event, fresh_event])
        sqlite_db.commit()

        collector = EvidenceCollector(sqlite_db)
        cmd = VerificationCommand(
            action_id="act_timed",
            organization_id="org_alpha",
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_001",
            action_executed_at=exec_time,
            observation_window_seconds=3600,
        )

        evidence = collector.collect(cmd)
        ev_ids = [e.evidence_id for e in evidence]
        assert "event_ev_fresh" in ev_ids
        assert "event_ev_stale" not in ev_ids

    def test_collect_deduplicates_identical_evidence(self, sqlite_db):
        """Events with identical evidence_id or raw_reference_id must be deduplicated."""
        collector = EvidenceCollector(sqlite_db)
        cmd = VerificationCommand(
            action_id="act_dedup",
            organization_id="org_alpha",
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_001",
        )

        ts = datetime.now(timezone.utc)
        duplicate_items = [
            ObservedEvidenceItem(
                evidence_id="ev_dup_1",
                raw_reference_id="ref_telemetry_100",
                source_type="PROVIDER_TELEMETRY",
                source_precedence=EvidenceSourcePrecedence.REAL,
                timestamp=ts,
                entity_type=TargetEntityType.SHIPMENT,
                entity_id="ship_001",
            ),
            ObservedEvidenceItem(
                evidence_id="ev_dup_2",
                raw_reference_id="ref_telemetry_100",  # duplicate reference
                source_type="PROVIDER_TELEMETRY",
                source_precedence=EvidenceSourcePrecedence.REAL,
                timestamp=ts + timedelta(seconds=1),
                entity_type=TargetEntityType.SHIPMENT,
                entity_id="ship_001",
            ),
        ]

        evidence = collector.collect(cmd, extra_evidence=duplicate_items)
        refs = [e.raw_reference_id for e in evidence if e.raw_reference_id]
        assert refs.count("ref_telemetry_100") == 1

    def test_collect_bounds_observation_window_max(self, sqlite_db):
        """Observation window exceeding max allowable seconds must be rejected."""
        from pydantic import ValidationError

        collector = EvidenceCollector(sqlite_db)
        # 1. Pydantic validation rejects at command instantiation
        with pytest.raises(ValidationError, match="Input should be less than or equal to 2592000"):
            VerificationCommand(
                action_id="act_unbounded",
                organization_id="org_alpha",
                action_type=ActionType.SHIPMENT_REROUTE,
                target_entity_type=TargetEntityType.SHIPMENT,
                target_entity_id="ship_001",
                observation_window_seconds=31 * 86400,  # 31 days (max is 30)
            )

        # 2. EvidenceCollector defence-in-depth rejects if bypassed
        cmd = VerificationCommand(
            action_id="act_unbounded",
            organization_id="org_alpha",
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_001",
        )
        object.__setattr__(cmd, "observation_window_seconds", 31 * 86400)
        with pytest.raises(VerificationSecurityViolationError, match="Observation window .* exceeds max limit"):
            collector.collect(cmd)

    def test_read_only_guarantee_no_mutations(self, sqlite_db):
        """Evidence collection must not mutate or alter source records."""
        ship_before = sqlite_db.execute(select(Shipment).where(Shipment.id == "ship_001")).scalars().first()
        status_before = ship_before.status
        updated_at_before = ship_before.updated_at

        collector = EvidenceCollector(sqlite_db)
        cmd = VerificationCommand(
            action_id="act_readonly_test",
            organization_id="org_alpha",
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_001",
        )
        collector.collect(cmd)

        ship_after = sqlite_db.execute(select(Shipment).where(Shipment.id == "ship_001")).scalars().first()
        assert ship_after.status == status_before
        assert ship_after.updated_at == updated_at_before
