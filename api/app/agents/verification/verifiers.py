"""Specialized domain verifiers for the Verification Agent (Phase 18).

Implements deterministic evaluation for each supported ActionType:
1. SHIPMENT_REROUTE
2. CARRIER_REALLOCATION
3. FACILITY_REALLOCATION
4. EXPEDITE_SHIPMENT
5. HOLD_SHIPMENT
6. MONITOR

Rules:
- Strictly deterministic logic (no LLM, no probabilistic override)
- Conservative fail-closed semantics
- Respects source hierarchy: REAL > ESTIMATED > SIMULATED
- SIMULATED evidence can NEVER prove real-world success
- Detects contradictory / conflicting evidence
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.agents.action.contract import ActionType, TargetEntityType
from app.agents.verification.contract import (
    EvidenceSourcePrecedence,
    IntendedOutcome,
    ObservedEvidenceItem,
    ObservedOutcome,
    VerificationCommand,
    VerificationStatus,
)


class BaseActionVerifier:
    """Base class for action-specific verification evaluation."""

    action_type: ActionType

    def derive_intended_outcome(self, command: VerificationCommand) -> IntendedOutcome:
        """Derive the expected real-world operational state from approved action parameters."""
        raise NotImplementedError

    def verify(
        self,
        command: VerificationCommand,
        intended: IntendedOutcome,
        evidence_items: List[ObservedEvidenceItem],
    ) -> Tuple[VerificationStatus, bool, ObservedOutcome, str]:
        """Evaluate evidence against intended outcome.
        
        Returns:
            (VerificationStatus, verified_bool, ObservedOutcome, summary_message)
        """
        raise NotImplementedError


class ShipmentRerouteVerifier(BaseActionVerifier):
    """Verifier for SHIPMENT_REROUTE actions."""

    action_type = ActionType.SHIPMENT_REROUTE

    def derive_intended_outcome(self, command: VerificationCommand) -> IntendedOutcome:
        params = command.action_parameters or {}
        expected_route = (
            params.get("new_route_id")
            or params.get("route_id")
            or params.get("target_route_id")
            or params.get("destination")
        )
        return IntendedOutcome(
            action_type=self.action_type,
            target_entity_type=command.target_entity_type,
            target_entity_id=command.target_entity_id,
            expected_attributes={
                "route_id": expected_route,
                "mode": params.get("mode"),
            },
            observation_window_seconds=command.observation_window_seconds,
            required_precedence=EvidenceSourcePrecedence.REAL,
        )

    def verify(
        self,
        command: VerificationCommand,
        intended: IntendedOutcome,
        evidence_items: List[ObservedEvidenceItem],
    ) -> Tuple[VerificationStatus, bool, ObservedOutcome, str]:
        if not evidence_items:
            # Check window expiry
            now = datetime.now(timezone.utc)
            window_end = command.action_executed_at.astimezone(timezone.utc) + (
                intended.observation_window_seconds * (datetime.now(timezone.utc) - datetime.now(timezone.utc) + 1)
                if hasattr(intended, "_fake") else
                datetime.fromtimestamp(command.action_executed_at.timestamp() + command.observation_window_seconds, tz=timezone.utc)
            )
            if now > window_end:
                status = VerificationStatus.EXPIRED
                msg = "Observation window expired with no post-action evidence."
            else:
                status = VerificationStatus.PENDING
                msg = "Action within observation window; awaiting authoritative evidence."
            return (
                status,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    evidence_count=0,
                ),
                msg,
            )

        # Assess precedence
        has_real = any(e.source_precedence == EvidenceSourcePrecedence.REAL for e in evidence_items)
        has_simulated_only = all(e.source_precedence == EvidenceSourcePrecedence.SIMULATED for e in evidence_items)

        if has_simulated_only:
            return (
                VerificationStatus.INSUFFICIENT_EVIDENCE,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.SIMULATED,
                    evidence_items=evidence_items,
                ),
                "Simulated evidence cannot establish real-world operational outcome.",
            )

        expected_route = intended.expected_attributes.get("route_id")
        observed_route = None
        reroute_event_found = False
        rejection_found = False

        # Scan evidence
        for item in evidence_items:
            attrs = item.observed_attributes
            if "route_id" in attrs and attrs["route_id"]:
                observed_route = attrs["route_id"]

            ev_type = str(attrs.get("event_type", "")).upper()
            status_val = str(attrs.get("status", "")).upper()

            if any(k in ev_type for k in ("REROUTE_CONFIRMED", "REROUTED", "COURSE_CORRECTION")):
                reroute_event_found = True
            if "REJECT" in ev_type or "FAILED" in status_val or "REROUTE_FAILED" in ev_type:
                rejection_found = True

        # Check for conflict
        if reroute_event_found and rejection_found:
            return (
                VerificationStatus.CONFLICT,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"route_id": observed_route},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL if has_real else EvidenceSourcePrecedence.ESTIMATED,
                    evidence_items=evidence_items,
                    conflict_detected=True,
                    conflict_details="Contradictory evidence: reroute event observed alongside rejection/failure event.",
                ),
                "Conflict detected between reroute confirmation and failure signals.",
            )

        if rejection_found:
            return (
                VerificationStatus.FAILED,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"route_id": observed_route},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL if has_real else EvidenceSourcePrecedence.ESTIMATED,
                    evidence_items=evidence_items,
                ),
                "Authoritative evidence confirms reroute execution failed or was rejected.",
            )

        # Match check
        route_matched = (expected_route is not None and observed_route == expected_route)

        if route_matched and has_real:
            return (
                VerificationStatus.VERIFIED,
                True,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"route_id": observed_route},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL,
                    evidence_items=evidence_items,
                ),
                f"Authoritative real-world evidence confirms route updated to '{observed_route}'.",
            )
        elif route_matched and not has_real:
            return (
                VerificationStatus.PARTIALLY_VERIFIED,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"route_id": observed_route},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.ESTIMATED,
                    evidence_items=evidence_items,
                ),
                f"Route matches '{observed_route}' but evidence is ESTIMATED, not confirmed REAL.",
            )
        elif reroute_event_found:
            return (
                VerificationStatus.PARTIALLY_VERIFIED,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"route_id": observed_route},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL if has_real else EvidenceSourcePrecedence.ESTIMATED,
                    evidence_items=evidence_items,
                ),
                "Reroute telemetry event observed but route assignment not yet finalized in operational state.",
            )
        else:
            return (
                VerificationStatus.FAILED,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"route_id": observed_route},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL if has_real else EvidenceSourcePrecedence.ESTIMATED,
                    evidence_items=evidence_items,
                ),
                f"Authoritative state shows route is '{observed_route}', expected '{expected_route}'.",
            )


class CarrierReallocationVerifier(BaseActionVerifier):
    """Verifier for CARRIER_REALLOCATION actions."""

    action_type = ActionType.CARRIER_REALLOCATION

    def derive_intended_outcome(self, command: VerificationCommand) -> IntendedOutcome:
        params = command.action_parameters or {}
        expected_carrier = (
            params.get("new_carrier_id")
            or params.get("carrier_id")
            or params.get("target_carrier_id")
        )
        return IntendedOutcome(
            action_type=self.action_type,
            target_entity_type=command.target_entity_type,
            target_entity_id=command.target_entity_id,
            expected_attributes={"carrier_id": expected_carrier},
            observation_window_seconds=command.observation_window_seconds,
            required_precedence=EvidenceSourcePrecedence.REAL,
        )

    def verify(
        self,
        command: VerificationCommand,
        intended: IntendedOutcome,
        evidence_items: List[ObservedEvidenceItem],
    ) -> Tuple[VerificationStatus, bool, ObservedOutcome, str]:
        if not evidence_items:
            now = datetime.now(timezone.utc)
            window_end = datetime.fromtimestamp(
                command.action_executed_at.timestamp() + command.observation_window_seconds, tz=timezone.utc
            )
            if now > window_end:
                return (
                    VerificationStatus.EXPIRED,
                    False,
                    ObservedOutcome(target_entity_type=command.target_entity_type, target_entity_id=command.target_entity_id),
                    "Observation window expired with no post-action evidence.",
                )
            return (
                VerificationStatus.PENDING,
                False,
                ObservedOutcome(target_entity_type=command.target_entity_type, target_entity_id=command.target_entity_id),
                "Awaiting post-action carrier reallocation evidence.",
            )

        has_real = any(e.source_precedence == EvidenceSourcePrecedence.REAL for e in evidence_items)
        has_simulated_only = all(e.source_precedence == EvidenceSourcePrecedence.SIMULATED for e in evidence_items)

        if has_simulated_only:
            return (
                VerificationStatus.INSUFFICIENT_EVIDENCE,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.SIMULATED,
                    evidence_items=evidence_items,
                ),
                "Simulated evidence cannot prove real carrier reallocation.",
            )

        expected_carrier = intended.expected_attributes.get("carrier_id")
        observed_carrier = None
        carrier_event_found = False
        rejection_found = False

        for item in evidence_items:
            attrs = item.observed_attributes
            if "carrier_id" in attrs and attrs["carrier_id"]:
                observed_carrier = attrs["carrier_id"]

            ev_type = str(attrs.get("event_type", "")).upper()
            if any(k in ev_type for k in ("CARRIER_REALLOCATED", "CARRIER_ACCEPTED", "CARRIER_ASSIGNED")):
                carrier_event_found = True
            if "REJECT" in ev_type or "CARRIER_UNAVAILABLE" in ev_type:
                rejection_found = True

        if carrier_event_found and rejection_found:
            return (
                VerificationStatus.CONFLICT,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"carrier_id": observed_carrier},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL if has_real else EvidenceSourcePrecedence.ESTIMATED,
                    conflict_detected=True,
                    conflict_details="Contradictory carrier assignment and rejection telemetry.",
                    evidence_items=evidence_items,
                ),
                "Conflict detected between carrier assignment and rejection.",
            )

        if rejection_found:
            return (
                VerificationStatus.FAILED,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"carrier_id": observed_carrier},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL if has_real else EvidenceSourcePrecedence.ESTIMATED,
                    evidence_items=evidence_items,
                ),
                "Carrier reallocation was rejected or failed.",
            )

        carrier_matched = (expected_carrier is not None and observed_carrier == expected_carrier)

        if carrier_matched and has_real:
            return (
                VerificationStatus.VERIFIED,
                True,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"carrier_id": observed_carrier},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL,
                    evidence_items=evidence_items,
                ),
                f"Authoritative real-world evidence confirms carrier reallocated to '{observed_carrier}'.",
            )
        elif carrier_matched and not has_real:
            return (
                VerificationStatus.PARTIALLY_VERIFIED,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"carrier_id": observed_carrier},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.ESTIMATED,
                    evidence_items=evidence_items,
                ),
                f"Carrier matches '{observed_carrier}' with ESTIMATED provenance.",
            )
        elif carrier_event_found:
            return (
                VerificationStatus.PARTIALLY_VERIFIED,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"carrier_id": observed_carrier},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL if has_real else EvidenceSourcePrecedence.ESTIMATED,
                    evidence_items=evidence_items,
                ),
                "Carrier assignment telemetry event observed; pending operational sync.",
            )
        else:
            return (
                VerificationStatus.FAILED,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"carrier_id": observed_carrier},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL if has_real else EvidenceSourcePrecedence.ESTIMATED,
                    evidence_items=evidence_items,
                ),
                f"Operational carrier '{observed_carrier}' does not match expected '{expected_carrier}'.",
            )


class FacilityReallocationVerifier(BaseActionVerifier):
    """Verifier for FACILITY_REALLOCATION actions."""

    action_type = ActionType.FACILITY_REALLOCATION

    def derive_intended_outcome(self, command: VerificationCommand) -> IntendedOutcome:
        params = command.action_parameters or {}
        expected_facility = (
            params.get("new_facility_id")
            or params.get("facility_id")
            or params.get("target_facility_id")
        )
        return IntendedOutcome(
            action_type=self.action_type,
            target_entity_type=command.target_entity_type,
            target_entity_id=command.target_entity_id,
            expected_attributes={"facility_id": expected_facility},
            observation_window_seconds=command.observation_window_seconds,
            required_precedence=EvidenceSourcePrecedence.REAL,
        )

    def verify(
        self,
        command: VerificationCommand,
        intended: IntendedOutcome,
        evidence_items: List[ObservedEvidenceItem],
    ) -> Tuple[VerificationStatus, bool, ObservedOutcome, str]:
        if not evidence_items:
            now = datetime.now(timezone.utc)
            window_end = datetime.fromtimestamp(
                command.action_executed_at.timestamp() + command.observation_window_seconds, tz=timezone.utc
            )
            if now > window_end:
                return (
                    VerificationStatus.EXPIRED,
                    False,
                    ObservedOutcome(target_entity_type=command.target_entity_type, target_entity_id=command.target_entity_id),
                    "Observation window expired with no facility reallocation evidence.",
                )
            return (
                VerificationStatus.PENDING,
                False,
                ObservedOutcome(target_entity_type=command.target_entity_type, target_entity_id=command.target_entity_id),
                "Awaiting facility reallocation evidence.",
            )

        has_real = any(e.source_precedence == EvidenceSourcePrecedence.REAL for e in evidence_items)
        has_simulated_only = all(e.source_precedence == EvidenceSourcePrecedence.SIMULATED for e in evidence_items)

        if has_simulated_only:
            return (
                VerificationStatus.INSUFFICIENT_EVIDENCE,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.SIMULATED,
                    evidence_items=evidence_items,
                ),
                "Simulated evidence cannot prove facility reallocation.",
            )

        # Operational status check
        operational_state = next(
            (e for e in evidence_items if "OPERATIONAL_DB" in e.source_type), None
        )
        if operational_state and has_real:
            status_val = operational_state.observed_attributes.get("status", "")
            if status_val in ("OPERATIONAL", "ACTIVE", "REALLOCATED"):
                return (
                    VerificationStatus.VERIFIED,
                    True,
                    ObservedOutcome(
                        target_entity_type=command.target_entity_type,
                        target_entity_id=command.target_entity_id,
                        observed_attributes=operational_state.observed_attributes,
                        evidence_count=len(evidence_items),
                        highest_precedence=EvidenceSourcePrecedence.REAL,
                        evidence_items=evidence_items,
                    ),
                    f"Authoritative facility operational state verified as '{status_val}'.",
                )

        return (
            VerificationStatus.PARTIALLY_VERIFIED,
            False,
            ObservedOutcome(
                target_entity_type=command.target_entity_type,
                target_entity_id=command.target_entity_id,
                evidence_count=len(evidence_items),
                highest_precedence=EvidenceSourcePrecedence.REAL if has_real else EvidenceSourcePrecedence.ESTIMATED,
                evidence_items=evidence_items,
            ),
            "Facility reallocation acknowledged but operational load rebalancing in progress.",
        )


class ExpediteShipmentVerifier(BaseActionVerifier):
    """Verifier for EXPEDITE_SHIPMENT actions."""

    action_type = ActionType.EXPEDITE_SHIPMENT

    def derive_intended_outcome(self, command: VerificationCommand) -> IntendedOutcome:
        params = command.action_parameters or {}
        return IntendedOutcome(
            action_type=self.action_type,
            target_entity_type=command.target_entity_type,
            target_entity_id=command.target_entity_id,
            expected_attributes={
                "mode": params.get("mode", "AIR"),
                "expedited": True,
            },
            observation_window_seconds=command.observation_window_seconds,
            required_precedence=EvidenceSourcePrecedence.REAL,
        )

    def verify(
        self,
        command: VerificationCommand,
        intended: IntendedOutcome,
        evidence_items: List[ObservedEvidenceItem],
    ) -> Tuple[VerificationStatus, bool, ObservedOutcome, str]:
        if not evidence_items:
            now = datetime.now(timezone.utc)
            window_end = datetime.fromtimestamp(
                command.action_executed_at.timestamp() + command.observation_window_seconds, tz=timezone.utc
            )
            if now > window_end:
                return (
                    VerificationStatus.EXPIRED,
                    False,
                    ObservedOutcome(target_entity_type=command.target_entity_type, target_entity_id=command.target_entity_id),
                    "Observation window expired with no expedited transit evidence.",
                )
            return (
                VerificationStatus.PENDING,
                False,
                ObservedOutcome(target_entity_type=command.target_entity_type, target_entity_id=command.target_entity_id),
                "Awaiting expedited transit evidence.",
            )

        has_real = any(e.source_precedence == EvidenceSourcePrecedence.REAL for e in evidence_items)
        has_simulated_only = all(e.source_precedence == EvidenceSourcePrecedence.SIMULATED for e in evidence_items)

        if has_simulated_only:
            return (
                VerificationStatus.INSUFFICIENT_EVIDENCE,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.SIMULATED,
                    evidence_items=evidence_items,
                ),
                "Simulated telemetry cannot prove expedited transit execution.",
            )

        expected_mode = intended.expected_attributes.get("mode", "AIR").upper()
        observed_mode = None
        expedite_event_found = False

        for item in evidence_items:
            attrs = item.observed_attributes
            if "mode" in attrs and attrs["mode"]:
                observed_mode = str(attrs["mode"]).upper()
            ev_type = str(attrs.get("event_type", "")).upper()
            if any(k in ev_type for k in ("EXPEDITE", "AIR_FREIGHT", "EXPRESS_TRANSIT")):
                expedite_event_found = True

        mode_matched = (observed_mode == expected_mode)

        if (mode_matched or expedite_event_found) and has_real:
            return (
                VerificationStatus.VERIFIED,
                True,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"mode": observed_mode, "expedite_confirmed": True},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL,
                    evidence_items=evidence_items,
                ),
                f"Authoritative evidence confirms shipment expedited via mode '{observed_mode or expected_mode}'.",
            )
        elif (mode_matched or expedite_event_found) and not has_real:
            return (
                VerificationStatus.PARTIALLY_VERIFIED,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"mode": observed_mode},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.ESTIMATED,
                    evidence_items=evidence_items,
                ),
                "Expedited transit signal observed but evidence source is ESTIMATED.",
            )
        else:
            return (
                VerificationStatus.FAILED,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"mode": observed_mode},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL if has_real else EvidenceSourcePrecedence.ESTIMATED,
                    evidence_items=evidence_items,
                ),
                f"Shipment transit mode remained '{observed_mode}', expected expedited '{expected_mode}'.",
            )


class HoldShipmentVerifier(BaseActionVerifier):
    """Verifier for HOLD_SHIPMENT actions."""

    action_type = ActionType.HOLD_SHIPMENT

    def derive_intended_outcome(self, command: VerificationCommand) -> IntendedOutcome:
        return IntendedOutcome(
            action_type=self.action_type,
            target_entity_type=command.target_entity_type,
            target_entity_id=command.target_entity_id,
            expected_attributes={"status": "HELD"},
            observation_window_seconds=command.observation_window_seconds,
            required_precedence=EvidenceSourcePrecedence.REAL,
        )

    def verify(
        self,
        command: VerificationCommand,
        intended: IntendedOutcome,
        evidence_items: List[ObservedEvidenceItem],
    ) -> Tuple[VerificationStatus, bool, ObservedOutcome, str]:
        if not evidence_items:
            now = datetime.now(timezone.utc)
            window_end = datetime.fromtimestamp(
                command.action_executed_at.timestamp() + command.observation_window_seconds, tz=timezone.utc
            )
            if now > window_end:
                return (
                    VerificationStatus.EXPIRED,
                    False,
                    ObservedOutcome(target_entity_type=command.target_entity_type, target_entity_id=command.target_entity_id),
                    "Observation window expired without hold confirmation.",
                )
            return (
                VerificationStatus.PENDING,
                False,
                ObservedOutcome(target_entity_type=command.target_entity_type, target_entity_id=command.target_entity_id),
                "Awaiting hold confirmation evidence.",
            )

        has_real = any(e.source_precedence == EvidenceSourcePrecedence.REAL for e in evidence_items)
        has_simulated_only = all(e.source_precedence == EvidenceSourcePrecedence.SIMULATED for e in evidence_items)

        if has_simulated_only:
            return (
                VerificationStatus.INSUFFICIENT_EVIDENCE,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.SIMULATED,
                    evidence_items=evidence_items,
                ),
                "Simulated telemetry cannot establish a legally binding shipment hold.",
            )

        observed_status = None
        hold_event_found = False
        release_or_delivered = False

        for item in evidence_items:
            attrs = item.observed_attributes
            if "status" in attrs and attrs["status"]:
                observed_status = str(attrs["status"]).upper()
            ev_type = str(attrs.get("event_type", "")).upper()
            if any(k in ev_type for k in ("HOLD", "CUSTOMS_HOLD", "QUARANTINE", "SHIPMENT_HELD")):
                hold_event_found = True
            if any(k in ev_type for k in ("RELEASED", "DELIVERED")):
                release_or_delivered = True

        # Conflict check
        if (hold_event_found or observed_status == "HELD") and release_or_delivered:
            return (
                VerificationStatus.CONFLICT,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"status": observed_status},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL if has_real else EvidenceSourcePrecedence.ESTIMATED,
                    conflict_detected=True,
                    conflict_details="Contradictory evidence: hold signal detected alongside delivery/release signal.",
                    evidence_items=evidence_items,
                ),
                "Conflict: hold signal contradicted by release/delivery telemetry.",
            )

        status_is_held = (observed_status in ("HELD", "ON_HOLD", "CUSTOMS_HOLD"))

        if (status_is_held or hold_event_found) and has_real:
            return (
                VerificationStatus.VERIFIED,
                True,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"status": "HELD"},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL,
                    evidence_items=evidence_items,
                ),
                "Authoritative evidence confirms shipment is in HELD state.",
            )
        elif (status_is_held or hold_event_found) and not has_real:
            return (
                VerificationStatus.PARTIALLY_VERIFIED,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"status": observed_status},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.ESTIMATED,
                    evidence_items=evidence_items,
                ),
                "Hold signal observed with ESTIMATED provenance.",
            )
        else:
            return (
                VerificationStatus.FAILED,
                False,
                ObservedOutcome(
                    target_entity_type=command.target_entity_type,
                    target_entity_id=command.target_entity_id,
                    observed_attributes={"status": observed_status},
                    evidence_count=len(evidence_items),
                    highest_precedence=EvidenceSourcePrecedence.REAL if has_real else EvidenceSourcePrecedence.ESTIMATED,
                    evidence_items=evidence_items,
                ),
                f"Shipment status is '{observed_status}', expected 'HELD'.",
            )


class MonitorVerifier(BaseActionVerifier):
    """Verifier for passive MONITOR actions."""

    action_type = ActionType.MONITOR

    def derive_intended_outcome(self, command: VerificationCommand) -> IntendedOutcome:
        return IntendedOutcome(
            action_type=self.action_type,
            target_entity_type=command.target_entity_type,
            target_entity_id=command.target_entity_id,
            expected_attributes={"passive_monitoring": True},
            observation_window_seconds=command.observation_window_seconds,
            required_precedence=EvidenceSourcePrecedence.REAL,
        )

    def verify(
        self,
        command: VerificationCommand,
        intended: IntendedOutcome,
        evidence_items: List[ObservedEvidenceItem],
    ) -> Tuple[VerificationStatus, bool, ObservedOutcome, str]:
        # Passive monitoring does not alter operational state
        return (
            VerificationStatus.NOT_APPLICABLE,
            True,
            ObservedOutcome(
                target_entity_type=command.target_entity_type,
                target_entity_id=command.target_entity_id,
                observed_attributes={"monitoring_active": True},
                evidence_count=len(evidence_items),
                evidence_items=evidence_items,
            ),
            "Passive monitoring action does not mandate operational state mutation.",
        )


VERIFIER_REGISTRY: Dict[ActionType, BaseActionVerifier] = {
    ActionType.SHIPMENT_REROUTE: ShipmentRerouteVerifier(),
    ActionType.CARRIER_REALLOCATION: CarrierReallocationVerifier(),
    ActionType.FACILITY_REALLOCATION: FacilityReallocationVerifier(),
    ActionType.EXPEDITE_SHIPMENT: ExpediteShipmentVerifier(),
    ActionType.HOLD_SHIPMENT: HoldShipmentVerifier(),
    ActionType.MONITOR: MonitorVerifier(),
}


def get_verifier_for_action(action_type: ActionType) -> BaseActionVerifier:
    """Retrieve the authoritative domain verifier for an action type."""
    if action_type not in VERIFIER_REGISTRY:
        # Fallback to general verifier or raise
        raise ValueError(f"No verifier registered for ActionType '{action_type}'.")
    return VERIFIER_REGISTRY[action_type]
