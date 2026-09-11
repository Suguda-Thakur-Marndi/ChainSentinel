"""Repository for Shipment and ShipmentEvent entity data access and lifecycle operations."""
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from app.core.errors import NotFoundError
from app.models.logistics import Shipment, ShipmentEvent
from app.repositories.base import BaseRepository
from app.repositories.query_utils import (
    apply_filters,
    apply_pagination,
    apply_search,
    apply_sorting,
)

# ==============================================================================
# SHIPMENT ALLOWLISTS
# ==============================================================================
SHIPMENT_SEARCH_COLUMNS = ["tracking_number", "origin", "destination"]

SHIPMENT_SORT_ALLOWLIST = {
    "tracking_number": Shipment.tracking_number,
    "eta": Shipment.eta,
    "delay_minutes": Shipment.delay_minutes,
    "status": Shipment.status,
    "created_at": Shipment.created_at,
    "updated_at": Shipment.updated_at,
}

SHIPMENT_FILTER_ALLOWLIST = {
    "status": Shipment.status,
    "mode": Shipment.mode,
    "carrier_id": Shipment.carrier_id,
    "product_id": Shipment.product_id,
    "data_provenance": Shipment.data_provenance,
    "created_at_after": Shipment.created_at,
    "created_at_before": Shipment.created_at,
}

# ==============================================================================
# SHIPMENT EVENT ALLOWLISTS
# ==============================================================================
EVENT_SEARCH_COLUMNS = ["event_type", "source_type", "status"]

EVENT_SORT_ALLOWLIST = {
    "timestamp": ShipmentEvent.timestamp,
    "created_at": ShipmentEvent.created_at,
}

EVENT_FILTER_ALLOWLIST = {
    "shipment_id": ShipmentEvent.shipment_id,
    "event_type": ShipmentEvent.event_type,
    "source_type": ShipmentEvent.source_type,
    "created_at_after": ShipmentEvent.created_at,
    "created_at_before": ShipmentEvent.created_at,
}


class ShipmentRepository(BaseRepository[Shipment]):
    """Data access repository for Shipment entities."""

    def __init__(self, session: Session):
        super().__init__(Shipment, session)

    def get_with_events(self, shipment_id: str, org_id: Optional[str] = None) -> Optional[Shipment]:
        """Retrieve a shipment eagerly loading its chronological event telemetry."""
        stmt = (
            select(Shipment)
            .where(Shipment.id == shipment_id)
            .options(selectinload(Shipment.events))
        )
        if org_id:
            stmt = stmt.where(Shipment.org_id == org_id)
        return self.session.scalars(stmt).first()

    def get_by_tracking_number(
        self, tracking_number: str, org_id: Optional[str] = None
    ) -> Optional[Shipment]:
        """Look up a shipment by its tracking number within tenant scope."""
        stmt = select(Shipment).where(Shipment.tracking_number == tracking_number)
        if org_id:
            stmt = stmt.where(Shipment.org_id == org_id)
        return self.session.scalars(stmt).first()

    def create_shipment(
        self,
        tracking_number: str,
        origin: Optional[str] = None,
        destination: Optional[str] = None,
        status: str = "IN_TRANSIT",
        mode: str = "OCEAN",
        org_id: Optional[str] = None,
        route_id: Optional[str] = None,
        product_id: Optional[str] = None,
        carrier_id: Optional[str] = None,
        current_lat: Optional[float] = None,
        current_lng: Optional[float] = None,
        eta: Optional[datetime] = None,
        eta_confidence: Optional[float] = None,
        delay_minutes: Optional[float] = None,
        data_provenance: str = "REAL",
        risk_id: Optional[str] = None,
        auto_commit: bool = True,
    ) -> Shipment:
        """Create and persist a new Shipment entity."""
        shipment = Shipment(
            tracking_number=tracking_number,
            origin=origin,
            destination=destination,
            status=status,
            mode=mode,
            org_id=org_id,
            route_id=route_id,
            product_id=product_id,
            carrier_id=carrier_id,
            current_lat=current_lat,
            current_lng=current_lng,
            eta=eta,
            eta_confidence=eta_confidence,
            delay_minutes=delay_minutes or 0.0,
            data_provenance=data_provenance,
            risk_id=risk_id,
        )
        return self.create(shipment, auto_commit=auto_commit)

    def update_status(
        self,
        shipment_id: str,
        new_status: str,
        delay_minutes: Optional[float] = None,
        current_lat: Optional[float] = None,
        current_lng: Optional[float] = None,
        auto_commit: bool = True,
    ) -> Optional[Shipment]:
        """Update operational status and delay metrics for a shipment."""
        shipment = self.get(shipment_id)
        if not shipment:
            return None
        shipment.status = new_status
        if delay_minutes is not None:
            shipment.delay_minutes = delay_minutes
        if current_lat is not None:
            shipment.current_lat = current_lat
        if current_lng is not None:
            shipment.current_lng = current_lng
        return self.update(shipment, auto_commit=auto_commit)

    def add_event(
        self,
        shipment_id: str,
        event_type: Optional[str] = None,
        mode: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        status: Optional[str] = None,
        delay_minutes: Optional[float] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        eta: Optional[datetime] = None,
        source: str = "REAL",
        source_type: Optional[str] = None,
        confidence: Optional[float] = None,
        raw_event_id: Optional[str] = None,
        metadata_json: Optional[dict[str, Any]] = None,
        auto_commit: bool = True,
    ) -> ShipmentEvent:
        """Append an immutable telemetry event to a shipment."""
        event = ShipmentEvent(
            shipment_id=shipment_id,
            event_type=event_type,
            mode=mode,
            timestamp=timestamp or datetime.now(timezone.utc),
            status=status,
            delay_minutes=delay_minutes or 0.0,
            latitude=latitude,
            longitude=longitude,
            eta=eta,
            source=source,
            source_type=source_type,
            confidence=confidence or 1.0,
            raw_event_id=raw_event_id,
            metadata_json=metadata_json or {},
        )
        try:
            self.session.add(event)
            if auto_commit:
                self.session.commit()
                self.session.refresh(event)
            else:
                self.session.flush()
            return event
        except Exception:
            if auto_commit:
                self.session.rollback()
            raise

    def get_events(self, shipment_id: str) -> list[ShipmentEvent]:
        """Retrieve all events associated with a shipment ordered chronologically."""
        stmt = (
            select(ShipmentEvent)
            .where(ShipmentEvent.shipment_id == shipment_id)
            .order_by(ShipmentEvent.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())


class ShipmentEventRepository(BaseRepository[ShipmentEvent]):
    """Data access repository for ShipmentEvent append-only telemetry records."""

    def __init__(self, session: Session):
        super().__init__(ShipmentEvent, session)

    def get_event_in_org(self, event_id: str, org_id: str) -> Optional[ShipmentEvent]:
        """Retrieve an individual shipment event ensuring parent shipment belongs to org_id."""
        stmt = (
            select(ShipmentEvent)
            .join(Shipment, Shipment.id == ShipmentEvent.shipment_id)
            .where(ShipmentEvent.id == event_id, Shipment.org_id == org_id)
        )
        return self.session.scalars(stmt).first()

    def list_events_for_org(
        self,
        org_id: str,
        shipment_id: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        filters: Optional[dict[str, Any]] = None,
        sort_param: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[ShipmentEvent], int]:
        """List shipment events with parent shipment tenant isolation and query protections."""
        base_stmt = (
            select(ShipmentEvent)
            .join(Shipment, Shipment.id == ShipmentEvent.shipment_id)
            .where(Shipment.org_id == org_id)
        )
        count_stmt = (
            select(func.count())
            .select_from(ShipmentEvent)
            .join(Shipment, Shipment.id == ShipmentEvent.shipment_id)
            .where(Shipment.org_id == org_id)
        )

        if shipment_id:
            base_stmt = base_stmt.where(ShipmentEvent.shipment_id == shipment_id)
            count_stmt = count_stmt.where(ShipmentEvent.shipment_id == shipment_id)

        # Apply safe filters, search, sorting
        base_stmt = apply_filters(base_stmt, ShipmentEvent, filters, EVENT_FILTER_ALLOWLIST)
        count_stmt = apply_filters(count_stmt, ShipmentEvent, filters, EVENT_FILTER_ALLOWLIST)

        base_stmt = apply_search(base_stmt, ShipmentEvent, search, EVENT_SEARCH_COLUMNS)
        count_stmt = apply_search(count_stmt, ShipmentEvent, search, EVENT_SEARCH_COLUMNS)

        base_stmt = apply_sorting(
            base_stmt,
            ShipmentEvent,
            sort_param,
            EVENT_SORT_ALLOWLIST,
            default_field="created_at",
            default_desc=True,
        )
        base_stmt = apply_pagination(base_stmt, page, limit)

        total = self.session.scalar(count_stmt) or 0
        items = list(self.session.scalars(base_stmt).all())
        return items, total

    def add_event(
        self,
        shipment_id: str,
        event_type: Optional[str] = None,
        mode: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        status: Optional[str] = None,
        delay_minutes: Optional[float] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        eta: Optional[datetime] = None,
        source: str = "REAL",
        source_type: Optional[str] = None,
        confidence: Optional[float] = None,
        raw_event_id: Optional[str] = None,
        metadata_json: Optional[dict[str, Any]] = None,
        auto_commit: bool = True,
    ) -> ShipmentEvent:
        """Append an immutable telemetry event to a shipment."""
        event = ShipmentEvent(
            shipment_id=shipment_id,
            event_type=event_type,
            mode=mode,
            timestamp=timestamp or datetime.now(timezone.utc),
            status=status,
            delay_minutes=delay_minutes or 0.0,
            latitude=latitude,
            longitude=longitude,
            eta=eta,
            source=source,
            source_type=source_type,
            confidence=confidence or 1.0,
            raw_event_id=raw_event_id,
            metadata_json=metadata_json or {},
        )
        return self.create(event, auto_commit=auto_commit)
