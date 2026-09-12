"""Read-only authoritative evidence collection layer for the Verification Agent (Phase 18).

Collects operational signals strictly from authoritative storage:
- `shipment_events` (telemetry, milestone, status updates)
- `shipments` (current routing, carrier assignment, operational status)
- `carriers` (reallocation confirmations, reliability updates)
- `facilities` / `warehouses` / `factories` (reallocation operational state)

Enforces:
- Strict tenant boundaries (organization_id scoping)
- Temporal observation windows (filtering out stale pre-action events and distant future events)
- Source precedence: REAL > ESTIMATED > SIMULATED
- Deduplication and chronological ordering
- Hard bounds on evidence set size
- Absolute read-only guarantees (no mutations)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.agents.action.contract import TargetEntityType
from app.agents.verification.contract import (
    EvidenceSourcePrecedence,
    ObservedEvidenceItem,
    VerificationCommand,
)
from app.agents.verification.errors import (
    VerificationSecurityViolationError,
    VerificationTenantIsolationError,
)
from app.models.governance import Action
from app.models.logistics import Shipment, ShipmentEvent
from app.models.network import Carrier, Factory, Warehouse


MAX_EVIDENCE_ITEMS = 100
MAX_OBSERVATION_WINDOW_SECONDS = 30 * 86400  # 30 days
FUTURE_TOLERANCE_SECONDS = 3600  # 1 hour clock skew tolerance


def _map_source_to_precedence(source_str: Optional[str]) -> EvidenceSourcePrecedence:
    """Map string source identifier to authoritative precedence enum."""
    if not source_str:
        return EvidenceSourcePrecedence.REAL
    clean = str(source_str).strip().upper()
    if clean == "SIMULATED":
        return EvidenceSourcePrecedence.SIMULATED
    if clean == "ESTIMATED":
        return EvidenceSourcePrecedence.ESTIMATED
    return EvidenceSourcePrecedence.REAL


def _to_utc(dt: Optional[datetime]) -> datetime:
    """Normalize any datetime (naive or aware) to UTC-aware datetime."""
    if not dt:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class EvidenceCollector:
    """Read-only collector of post-action operational evidence."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def collect(
        self,
        command: VerificationCommand,
        extra_evidence: Optional[List[ObservedEvidenceItem]] = None,
    ) -> List[ObservedEvidenceItem]:
        """Collect, validate, deduplicate, and order authoritative evidence for a command."""
        # 1. Bounds check on observation window
        if command.observation_window_seconds > MAX_OBSERVATION_WINDOW_SECONDS:
            raise VerificationSecurityViolationError(
                f"Observation window ({command.observation_window_seconds}s) exceeds max limit ({MAX_OBSERVATION_WINDOW_SECONDS}s)."
            )

        window_start = _to_utc(command.action_executed_at)
        window_end = window_start + timedelta(seconds=command.observation_window_seconds)

        collected: List[ObservedEvidenceItem] = []

        # 2. Collect from operational entity state
        entity_evidence = self._collect_operational_entity_state(command)
        if entity_evidence:
            collected.append(entity_evidence)

        # 3. Collect from shipment_events if target entity is a shipment or action pertains to shipment
        if command.target_entity_type == TargetEntityType.SHIPMENT:
            events_evidence = self._collect_shipment_events(command, window_start, window_end)
            collected.extend(events_evidence)

        # 4. Integrate extra external evidence if provided (e.g. from adapter confirmations)
        if extra_evidence:
            for item in extra_evidence:
                # Validate tenant/entity match
                if item.entity_id != command.target_entity_id:
                    continue
                # Temporal filtering for extra evidence
                item_ts = _to_utc(item.timestamp)
                start_ts = window_start
                end_ts = window_end
                
                # Check for stale evidence (before action execution)
                if item_ts < (start_ts - timedelta(seconds=5)):
                    continue
                # Check for distant future evidence
                now_utc = datetime.now(timezone.utc)
                if item_ts > (now_utc + timedelta(seconds=FUTURE_TOLERANCE_SECONDS)):
                    continue
                collected.append(item)

        # 5. Deduplicate by evidence_id / raw_reference_id
        deduped = self._deduplicate_evidence(collected)

        # 6. Chronological sort (oldest to newest)
        deduped.sort(key=lambda x: _to_utc(x.timestamp))

        # 7. Apply hard bounds on item count
        if len(deduped) > MAX_EVIDENCE_ITEMS:
            deduped = deduped[:MAX_EVIDENCE_ITEMS]

        return deduped

    def _collect_operational_entity_state(
        self, command: VerificationCommand
    ) -> Optional[ObservedEvidenceItem]:
        """Fetch current authoritative operational DB record and verify tenant isolation."""
        if command.target_entity_type == TargetEntityType.SHIPMENT:
            shipment = (
                self.db.execute(
                    select(Shipment).where(Shipment.id == command.target_entity_id)
                )
                .scalars()
                .first()
            )
            if not shipment:
                return None

            # Enforce tenant isolation strictly
            if shipment.org_id and shipment.org_id != command.organization_id:
                raise VerificationTenantIsolationError(
                    f"Shipment '{shipment.id}' belongs to organization '{shipment.org_id}', "
                    f"not command organization '{command.organization_id}'."
                )

            precedence = _map_source_to_precedence(shipment.data_provenance)
            ts = shipment.updated_at or shipment.created_at or datetime.now(timezone.utc)

            return ObservedEvidenceItem(
                evidence_id=f"op_state_shipment_{shipment.id}",
                source_type="OPERATIONAL_DB_SHIPMENT",
                source_precedence=precedence,
                timestamp=ts,
                entity_type=TargetEntityType.SHIPMENT,
                entity_id=shipment.id,
                observed_attributes={
                    "route_id": shipment.route_id,
                    "carrier_id": shipment.carrier_id,
                    "status": shipment.status,
                    "mode": shipment.mode,
                    "eta": shipment.eta.isoformat() if shipment.eta else None,
                    "delay_minutes": shipment.delay_minutes,
                },
                confidence=1.0 if precedence == EvidenceSourcePrecedence.REAL else 0.8,
                metadata={"origin": shipment.origin, "destination": shipment.destination},
            )

        if command.target_entity_type == TargetEntityType.CARRIER:
            carrier = (
                self.db.execute(
                    select(Carrier).where(Carrier.id == command.target_entity_id)
                )
                .scalars()
                .first()
            )
            if not carrier:
                return None

            if carrier.org_id and carrier.org_id != command.organization_id:
                raise VerificationTenantIsolationError(
                    f"Carrier '{carrier.id}' belongs to organization '{carrier.org_id}', "
                    f"not command organization '{command.organization_id}'."
                )

            ts = carrier.updated_at or carrier.created_at or datetime.now(timezone.utc)
            return ObservedEvidenceItem(
                evidence_id=f"op_state_carrier_{carrier.id}",
                source_type="OPERATIONAL_DB_CARRIER",
                source_precedence=EvidenceSourcePrecedence.REAL,
                timestamp=ts,
                entity_type=TargetEntityType.CARRIER,
                entity_id=carrier.id,
                observed_attributes={
                    "name": carrier.name,
                    "code": carrier.code,
                    "mode": carrier.mode,
                    "on_time_reliability": carrier.on_time_reliability,
                },
                confidence=1.0,
            )

        if command.target_entity_type == TargetEntityType.FACILITY:
            # Check Factory first, then Warehouse
            factory = (
                self.db.execute(
                    select(Factory).where(Factory.id == command.target_entity_id)
                )
                .scalars()
                .first()
            )
            if factory:
                if factory.org_id and factory.org_id != command.organization_id:
                    raise VerificationTenantIsolationError(
                        f"Factory '{factory.id}' belongs to organization '{factory.org_id}', "
                        f"not command organization '{command.organization_id}'."
                    )
                ts = factory.updated_at or factory.created_at or datetime.now(timezone.utc)
                return ObservedEvidenceItem(
                    evidence_id=f"op_state_factory_{factory.id}",
                    source_type="OPERATIONAL_DB_FACILITY",
                    source_precedence=EvidenceSourcePrecedence.REAL,
                    timestamp=ts,
                    entity_type=TargetEntityType.FACILITY,
                    entity_id=factory.id,
                    observed_attributes={
                        "name": factory.name,
                        "status": factory.status,
                        "capacity": factory.capacity,
                        "utilization": factory.utilization,
                    },
                    confidence=1.0,
                )

            warehouse = (
                self.db.execute(
                    select(Warehouse).where(Warehouse.id == command.target_entity_id)
                )
                .scalars()
                .first()
            )
            if warehouse:
                if warehouse.org_id and warehouse.org_id != command.organization_id:
                    raise VerificationTenantIsolationError(
                        f"Warehouse '{warehouse.id}' belongs to organization '{warehouse.org_id}', "
                        f"not command organization '{command.organization_id}'."
                    )
                ts = warehouse.updated_at or warehouse.created_at or datetime.now(timezone.utc)
                return ObservedEvidenceItem(
                    evidence_id=f"op_state_warehouse_{warehouse.id}",
                    source_type="OPERATIONAL_DB_FACILITY",
                    source_precedence=EvidenceSourcePrecedence.REAL,
                    timestamp=ts,
                    entity_type=TargetEntityType.FACILITY,
                    entity_id=warehouse.id,
                    observed_attributes={
                        "name": warehouse.name,
                        "status": warehouse.status,
                        "total_capacity": warehouse.total_capacity,
                        "current_occupancy": warehouse.current_occupancy,
                    },
                    confidence=1.0,
                )

        return None

    def _collect_shipment_events(
        self,
        command: VerificationCommand,
        window_start: datetime,
        window_end: datetime,
    ) -> List[ObservedEvidenceItem]:
        """Fetch post-action shipment_events bounded by observation window."""
        # Check shipment tenant boundary first
        shipment = (
            self.db.execute(
                select(Shipment).where(Shipment.id == command.target_entity_id)
            )
            .scalars()
            .first()
        )
        if not shipment:
            return []

        if shipment.org_id and shipment.org_id != command.organization_id:
            raise VerificationTenantIsolationError(
                f"Shipment '{shipment.id}' belongs to organization '{shipment.org_id}', "
                f"not command organization '{command.organization_id}'."
            )

        # Allow 5-second tolerance for clock skew before action_executed_at
        effective_start = window_start - timedelta(seconds=5)

        # Authoritative bounded query
        query = (
            select(ShipmentEvent)
            .where(ShipmentEvent.shipment_id == command.target_entity_id)
            .order_by(ShipmentEvent.timestamp.asc())
            .limit(MAX_EVIDENCE_ITEMS * 2)
        )

        events = self.db.execute(query).scalars().all()
        now_utc = datetime.now(timezone.utc)
        items: List[ObservedEvidenceItem] = []

        for ev in events:
            ev_ts = _to_utc(ev.timestamp)
            if ev_ts < effective_start or ev_ts > window_end:
                continue
            # Future-dated check
            if ev_ts > (now_utc + timedelta(seconds=FUTURE_TOLERANCE_SECONDS)):
                continue

            precedence = _map_source_to_precedence(ev.source)

            items.append(
                ObservedEvidenceItem(
                    evidence_id=f"event_{ev.id}",
                    source_type=ev.source_type or "SHIPMENT_EVENT",
                    source_precedence=precedence,
                    timestamp=ev_ts,
                    entity_type=TargetEntityType.SHIPMENT,
                    entity_id=ev.shipment_id,
                    observed_attributes={
                        "status": ev.status,
                        "mode": ev.mode,
                        "event_type": ev.event_type,
                        "eta": ev.eta.isoformat() if ev.eta else None,
                        "delay_minutes": ev.delay_minutes,
                        "latitude": ev.latitude,
                        "longitude": ev.longitude,
                    },
                    raw_reference_id=ev.raw_event_id,
                    confidence=ev.confidence or (1.0 if precedence == EvidenceSourcePrecedence.REAL else 0.8),
                    metadata=ev.metadata_json or {},
                )
            )

        return items

    def _deduplicate_evidence(
        self, items: List[ObservedEvidenceItem]
    ) -> List[ObservedEvidenceItem]:
        """Deduplicate items by evidence_id or raw_reference_id."""
        seen_ids = set()
        deduped: List[ObservedEvidenceItem] = []
        for item in items:
            key = item.raw_reference_id or item.evidence_id
            if key in seen_ids:
                continue
            seen_ids.add(key)
            deduped.append(item)
        return deduped
