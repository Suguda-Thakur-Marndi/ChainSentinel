"""Tests for Phase 18 domain verifiers across all supported action types."""

from datetime import datetime, timedelta, timezone
import pytest

from app.agents.action.contract import ActionType, TargetEntityType
from app.agents.verification.contract import (
    EvidenceSourcePrecedence,
    ObservedEvidenceItem,
    VerificationCommand,
    VerificationStatus,
)
from app.agents.verification.verifiers import (
    CarrierReallocationVerifier,
    ExpediteShipmentVerifier,
    FacilityReallocationVerifier,
    HoldShipmentVerifier,
    MonitorVerifier,
    ShipmentRerouteVerifier,
    get_verifier_for_action,
)


class TestDomainVerifiers:
    """Validate deterministic domain verification rules and status semantics."""

    @pytest.fixture
    def base_command(self) -> VerificationCommand:
        return VerificationCommand(
            action_id="act_test_001",
            organization_id="org_retail",
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_123",
            action_parameters={"new_route_id": "ROUTE_NORTH_CORRIDOR"},
            action_executed_at=datetime.now(timezone.utc),
            observation_window_seconds=3600,
        )

    def test_shipment_reroute_verified(self, base_command: VerificationCommand):
        """Authoritative real evidence confirms route update -> VERIFIED."""
        verifier = ShipmentRerouteVerifier()
        intended = verifier.derive_intended_outcome(base_command)

        evidence = [
            ObservedEvidenceItem(
                evidence_id="ev_route_update",
                source_type="OPERATIONAL_DB_SHIPMENT",
                source_precedence=EvidenceSourcePrecedence.REAL,
                entity_type=TargetEntityType.SHIPMENT,
                entity_id="ship_123",
                observed_attributes={"route_id": "ROUTE_NORTH_CORRIDOR", "status": "IN_TRANSIT"},
            )
        ]

        status, verified, outcome, summary = verifier.verify(base_command, intended, evidence)
        assert status == VerificationStatus.VERIFIED
        assert verified is True
        assert outcome.highest_precedence == EvidenceSourcePrecedence.REAL
        assert "route updated" in summary

    def test_shipment_reroute_partially_verified_with_estimated(self, base_command: VerificationCommand):
        """Route matches but evidence is ESTIMATED -> PARTIALLY_VERIFIED."""
        verifier = ShipmentRerouteVerifier()
        intended = verifier.derive_intended_outcome(base_command)

        evidence = [
            ObservedEvidenceItem(
                evidence_id="ev_est_update",
                source_type="PREDICTIVE_MODEL",
                source_precedence=EvidenceSourcePrecedence.ESTIMATED,
                entity_type=TargetEntityType.SHIPMENT,
                entity_id="ship_123",
                observed_attributes={"route_id": "ROUTE_NORTH_CORRIDOR"},
            )
        ]

        status, verified, outcome, _ = verifier.verify(base_command, intended, evidence)
        assert status == VerificationStatus.PARTIALLY_VERIFIED
        assert verified is False
        assert outcome.highest_precedence == EvidenceSourcePrecedence.ESTIMATED

    def test_shipment_reroute_insufficient_with_simulated_only(self, base_command: VerificationCommand):
        """SIMULATED evidence alone can NEVER prove real-world action outcome."""
        verifier = ShipmentRerouteVerifier()
        intended = verifier.derive_intended_outcome(base_command)

        evidence = [
            ObservedEvidenceItem(
                evidence_id="ev_sim_update",
                source_type="MONTE_CARLO_SIMULATION",
                source_precedence=EvidenceSourcePrecedence.SIMULATED,
                entity_type=TargetEntityType.SHIPMENT,
                entity_id="ship_123",
                observed_attributes={"route_id": "ROUTE_NORTH_CORRIDOR"},
            )
        ]

        status, verified, outcome, summary = verifier.verify(base_command, intended, evidence)
        assert status == VerificationStatus.INSUFFICIENT_EVIDENCE
        assert verified is False
        assert "Simulated evidence cannot establish" in summary

    def test_shipment_reroute_conflict_detection(self, base_command: VerificationCommand):
        """Contradictory evidence (reroute confirmed vs rejected) -> CONFLICT."""
        verifier = ShipmentRerouteVerifier()
        intended = verifier.derive_intended_outcome(base_command)

        evidence = [
            ObservedEvidenceItem(
                evidence_id="ev_ok",
                source_type="SHIPMENT_EVENT",
                source_precedence=EvidenceSourcePrecedence.REAL,
                entity_type=TargetEntityType.SHIPMENT,
                entity_id="ship_123",
                observed_attributes={"event_type": "REROUTE_CONFIRMED"},
            ),
            ObservedEvidenceItem(
                evidence_id="ev_err",
                source_type="SHIPMENT_EVENT",
                source_precedence=EvidenceSourcePrecedence.REAL,
                entity_type=TargetEntityType.SHIPMENT,
                entity_id="ship_123",
                observed_attributes={"event_type": "REROUTE_FAILED"},
            ),
        ]

        status, verified, outcome, summary = verifier.verify(base_command, intended, evidence)
        assert status == VerificationStatus.CONFLICT
        assert verified is False
        assert outcome.conflict_detected is True
        assert "Conflict" in summary

    def test_shipment_reroute_failed_outcome(self, base_command: VerificationCommand):
        """Operational state shows old route after observation -> FAILED."""
        verifier = ShipmentRerouteVerifier()
        intended = verifier.derive_intended_outcome(base_command)

        evidence = [
            ObservedEvidenceItem(
                evidence_id="ev_old_route",
                source_type="OPERATIONAL_DB_SHIPMENT",
                source_precedence=EvidenceSourcePrecedence.REAL,
                entity_type=TargetEntityType.SHIPMENT,
                entity_id="ship_123",
                observed_attributes={"route_id": "ROUTE_OLD_CONGESTED"},
            )
        ]

        status, verified, outcome, _ = verifier.verify(base_command, intended, evidence)
        assert status == VerificationStatus.FAILED
        assert verified is False

    def test_carrier_reallocation_verified(self):
        """Carrier reallocation matching expected carrier -> VERIFIED."""
        cmd = VerificationCommand(
            action_id="act_carrier_01",
            organization_id="org_test",
            action_type=ActionType.CARRIER_REALLOCATION,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_456",
            action_parameters={"new_carrier_id": "CARRIER_MAERSK_EXPRESS"},
        )
        verifier = CarrierReallocationVerifier()
        intended = verifier.derive_intended_outcome(cmd)

        evidence = [
            ObservedEvidenceItem(
                evidence_id="ev_c1",
                source_type="OPERATIONAL_DB_SHIPMENT",
                source_precedence=EvidenceSourcePrecedence.REAL,
                entity_type=TargetEntityType.SHIPMENT,
                entity_id="ship_456",
                observed_attributes={"carrier_id": "CARRIER_MAERSK_EXPRESS"},
            )
        ]

        status, verified, _, _ = verifier.verify(cmd, intended, evidence)
        assert status == VerificationStatus.VERIFIED
        assert verified is True

    def test_hold_shipment_verified(self):
        """Hold action followed by status=HELD -> VERIFIED."""
        cmd = VerificationCommand(
            action_id="act_hold_01",
            organization_id="org_test",
            action_type=ActionType.HOLD_SHIPMENT,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_789",
        )
        verifier = HoldShipmentVerifier()
        intended = verifier.derive_intended_outcome(cmd)

        evidence = [
            ObservedEvidenceItem(
                evidence_id="ev_hold",
                source_type="SHIPMENT_EVENT",
                source_precedence=EvidenceSourcePrecedence.REAL,
                entity_type=TargetEntityType.SHIPMENT,
                entity_id="ship_789",
                observed_attributes={"status": "HELD", "event_type": "CUSTOMS_HOLD"},
            )
        ]

        status, verified, _, _ = verifier.verify(cmd, intended, evidence)
        assert status == VerificationStatus.VERIFIED
        assert verified is True

    def test_hold_shipment_conflict(self):
        """Hold action with contradictory DELIVERED event -> CONFLICT."""
        cmd = VerificationCommand(
            action_id="act_hold_02",
            organization_id="org_test",
            action_type=ActionType.HOLD_SHIPMENT,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_789",
        )
        verifier = HoldShipmentVerifier()
        intended = verifier.derive_intended_outcome(cmd)

        evidence = [
            ObservedEvidenceItem(
                evidence_id="ev_h",
                source_type="SHIPMENT_EVENT",
                source_precedence=EvidenceSourcePrecedence.REAL,
                entity_type=TargetEntityType.SHIPMENT,
                entity_id="ship_789",
                observed_attributes={"status": "HELD", "event_type": "HOLD"},
            ),
            ObservedEvidenceItem(
                evidence_id="ev_d",
                source_type="SHIPMENT_EVENT",
                source_precedence=EvidenceSourcePrecedence.REAL,
                entity_type=TargetEntityType.SHIPMENT,
                entity_id="ship_789",
                observed_attributes={"status": "DELIVERED", "event_type": "DELIVERED"},
            ),
        ]

        status, verified, outcome, _ = verifier.verify(cmd, intended, evidence)
        assert status == VerificationStatus.CONFLICT
        assert verified is False
        assert outcome.conflict_detected is True

    def test_expedite_shipment_verified(self):
        """Expedite action shifting mode to AIR -> VERIFIED."""
        cmd = VerificationCommand(
            action_id="act_exp_01",
            organization_id="org_test",
            action_type=ActionType.EXPEDITE_SHIPMENT,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_exp",
            action_parameters={"mode": "AIR"},
        )
        verifier = ExpediteShipmentVerifier()
        intended = verifier.derive_intended_outcome(cmd)

        evidence = [
            ObservedEvidenceItem(
                evidence_id="ev_air",
                source_type="SHIPMENT_EVENT",
                source_precedence=EvidenceSourcePrecedence.REAL,
                entity_type=TargetEntityType.SHIPMENT,
                entity_id="ship_exp",
                observed_attributes={"mode": "AIR", "event_type": "AIR_FREIGHT_BOOKED"},
            )
        ]

        status, verified, _, _ = verifier.verify(cmd, intended, evidence)
        assert status == VerificationStatus.VERIFIED
        assert verified is True

    def test_passive_monitor_action_not_applicable(self):
        """Passive monitor action returns NOT_APPLICABLE outcome."""
        cmd = VerificationCommand(
            action_id="act_mon_01",
            organization_id="org_test",
            action_type=ActionType.MONITOR,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_mon",
        )
        verifier = MonitorVerifier()
        intended = verifier.derive_intended_outcome(cmd)

        status, verified, _, summary = verifier.verify(cmd, intended, [])
        assert status == VerificationStatus.NOT_APPLICABLE
        assert verified is True
        assert "Passive monitoring action" in summary
