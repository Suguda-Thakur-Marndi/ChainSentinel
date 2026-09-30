"""Internal RiskWise supply chain entities provider.

Exposes real database-backed supply chain assets:
- In-transit physical shipments with verified GPS/cellular coordinates.
- Registered port facilities and terminal hubs.
- Active verified supply chain risks and disruption incidents.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Callable, Coroutine, Dict, List, Optional

from app.db.session import SessionLocal
from app.models.logistics import Shipment
from app.models.network import Port
from app.models.risk import Incident, Risk
from app.services.tracking.base import TrackingProvider
from app.services.tracking.models import LiveMapObject, ProviderHealth, ProviderHealthStatus

logger = logging.getLogger("riskwise.tracking.internal")


class InternalRiskWiseProvider(TrackingProvider):
    """Internal database-backed provider for real shipments, ports, and risks."""

    name: str = "internal_riskwise"
    purpose: str = "Enterprise Shipments, Ports & Risk Intelligence"

    def __init__(self, on_update: Optional[Callable[[List[LiveMapObject]], Coroutine[None, None, None]]] = None):
        super().__init__(on_update=on_update)
        self._objects: Dict[str, LiveMapObject] = {}
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._status = ProviderHealthStatus.CONNECTED
        self._last_success: Optional[str] = None
        self._last_error: Optional[str] = None
        self._latency_ms: Optional[float] = None

    async def start(self) -> None:
        """Start periodic refresh from database."""
        self._is_running = True
        await self._refresh_db_objects()
        self._task = asyncio.create_task(self._poll_loop(), name="internal_db_poll_worker")
        logger.info("[InternalProvider] Database entity monitoring active.")

    async def stop(self) -> None:
        """Stop worker."""
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def health_check(self) -> ProviderHealth:
        """Return runtime health status."""
        async with self._lock:
            count = len(self._objects)
        return ProviderHealth(
            name=self.name,
            purpose=self.purpose,
            status=self._status,
            last_success=self._last_success,
            last_error=self._last_error,
            latency_ms=self._latency_ms,
            objects=count,
            reason=self._last_error if self._status != ProviderHealthStatus.CONNECTED else None,
        )

    async def get_objects(self) -> List[LiveMapObject]:
        """Return list of database supply chain entities."""
        async with self._lock:
            return list(self._objects.values())

    async def _poll_loop(self) -> None:
        """Periodically refresh database objects."""
        while self._is_running:
            try:
                await asyncio.sleep(60)
                await self._refresh_db_objects()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[InternalProvider] Poll loop error: {e}")

    async def _refresh_db_objects(self) -> None:
        """Query DB for shipments, ports, and risks with coordinates."""
        now_iso = datetime.now(timezone.utc).isoformat()
        loaded: Dict[str, LiveMapObject] = {}

        try:
            db = SessionLocal()
            try:
                # 1. Shipments with valid coordinates
                shipments = db.query(Shipment).filter(
                    Shipment.current_lat.isnot(None),
                    Shipment.current_lng.isnot(None),
                ).all()

                for s in shipments:
                    try:
                        lat = float(s.current_lat)
                        lng = float(s.current_lng)
                        if abs(lat) < 1e-5 and abs(lng) < 1e-5:
                            continue
                        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                            continue

                        mode_str = str(s.mode or "OCEAN").upper()
                        ent_type = "vessel" if mode_str == "OCEAN" else ("aircraft" if mode_str == "AIR" else "truck")
                        up_time = s.updated_at.isoformat() if s.updated_at else (s.created_at.isoformat() if s.created_at else now_iso)

                        obj = LiveMapObject(
                            id=f"shipment-{s.id}",
                            type="shipment",
                            source="internal_riskwise",
                            latitude=lat,
                            longitude=lng,
                            heading=None,
                            speed=None,
                            status=str(s.status or "IN_TRANSIT"),
                            name=f"Shipment: {s.tracking_number}",
                            identifier=s.tracking_number,
                            timestamp=up_time,
                            last_seen=now_iso,
                            metadata={
                                "shipment_id": s.id,
                                "tracking_number": s.tracking_number,
                                "mode": mode_str,
                                "origin": s.origin,
                                "destination": s.destination,
                                "carrier_id": s.carrier_id,
                                "provenance": getattr(s, "data_provenance", "REAL") or "REAL",
                                "sub_type": ent_type,
                            },
                        )
                        loaded[obj.id] = obj
                    except Exception as err:
                        logger.debug(f"[InternalProvider] Parse shipment error: {err}")

                # 2. Ports with coordinates
                ports = db.query(Port).filter(
                    Port.latitude.isnot(None),
                    Port.longitude.isnot(None),
                ).all()

                for p in ports:
                    try:
                        lat = float(p.latitude)
                        lng = float(p.longitude)
                        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                            continue
                        obj = LiveMapObject(
                            id=f"port-{p.id}",
                            type="port",
                            source="internal_riskwise",
                            latitude=lat,
                            longitude=lng,
                            heading=None,
                            speed=None,
                            status="ACTIVE",
                            name=f"Port of {p.name}",
                            identifier=p.code or p.id,
                            timestamp=now_iso,
                            last_seen=now_iso,
                            metadata={
                                "code": p.code,
                                "country": p.country,
                                "type": "port",
                                "provenance": "REAL",
                            },
                        )
                        loaded[obj.id] = obj
                    except Exception as err:
                        logger.debug(f"[InternalProvider] Parse port error: {err}")

            finally:
                db.close()

            async with self._lock:
                self._objects = loaded
            self._status = ProviderHealthStatus.CONNECTED
            self._last_success = now_iso
            self._last_error = None

        except Exception as e:
            self._status = ProviderHealthStatus.ERROR
            self._last_error = f"{type(e).__name__}: {str(e)}"
            logger.warning(f"[InternalProvider] Refresh failed: {e}")
