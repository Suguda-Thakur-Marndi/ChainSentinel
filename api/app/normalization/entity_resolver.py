"""Entity Normalization and Resolution Engine for Phase 6 Step 3.

Provides conservative, namespace-isolated entity resolution across heterogeneous sources
while aggressively preventing false correlations and enforcing strict multi-tenant isolation.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set, Tuple

from app.normalization.contract import (
    CorrelationConfidence,
    CorrelationMethod,
    CorrelationStatus,
    EntityReference,
    EntityType,
    NormalizedRiskSignal,
    SignalEntityReferences,
)
from app.normalization.identifiers import IdentifierNormalizer, NormalizedIdentifier

logger = logging.getLogger("riskwise.normalization.entity_resolver")


# =============================================================================
# Entity Lookup Provider Interface
# =============================================================================
class EntityLookupProvider(ABC):
    """Abstract interface for tenant-scoped master data entity lookups."""

    @abstractmethod
    def get_shipment(self, org_id: Optional[str], internal_id: str) -> Optional[Dict[str, Any]]:
        """Look up internal shipment by ID within tenant boundary."""
        pass

    @abstractmethod
    def get_shipment_by_tracking(
        self, org_id: Optional[str], tracking_number: str, carrier_namespace: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Look up shipment by tracking number and carrier namespace within tenant boundary."""
        pass

    @abstractmethod
    def get_supplier(self, org_id: Optional[str], internal_id: str) -> Optional[Dict[str, Any]]:
        """Look up supplier by ID within tenant boundary."""
        pass

    @abstractmethod
    def get_supplier_by_code(self, org_id: Optional[str], code: str) -> Optional[Dict[str, Any]]:
        """Look up supplier by explicit code within tenant boundary."""
        pass

    @abstractmethod
    def get_supplier_site(self, org_id: Optional[str], internal_id: str) -> Optional[Dict[str, Any]]:
        """Look up supplier site by ID within tenant boundary."""
        pass

    @abstractmethod
    def get_factory(self, org_id: Optional[str], internal_id: str) -> Optional[Dict[str, Any]]:
        """Look up factory plant by ID within tenant boundary."""
        pass

    @abstractmethod
    def get_warehouse(self, org_id: Optional[str], internal_id: str) -> Optional[Dict[str, Any]]:
        """Look up warehouse facility by ID within tenant boundary."""
        pass

    @abstractmethod
    def get_warehouse_by_code(self, org_id: Optional[str], code: str) -> Optional[Dict[str, Any]]:
        """Look up warehouse by explicit code within tenant boundary."""
        pass

    @abstractmethod
    def get_port(self, internal_id: str) -> Optional[Dict[str, Any]]:
        """Look up global reference port by internal ID."""
        pass

    @abstractmethod
    def get_port_by_unlocode(self, unlocode: str) -> Optional[Dict[str, Any]]:
        """Look up global reference port by UN/LOCODE."""
        pass

    @abstractmethod
    def get_carrier(self, org_id: Optional[str], internal_id: str) -> Optional[Dict[str, Any]]:
        """Look up carrier by ID within tenant boundary."""
        pass

    @abstractmethod
    def get_carrier_by_code(self, org_id: Optional[str], code: str, namespace: str) -> Optional[Dict[str, Any]]:
        """Look up carrier by namespace-qualified carrier code."""
        pass

    @abstractmethod
    def get_route(self, org_id: Optional[str], internal_id: str) -> Optional[Dict[str, Any]]:
        """Look up shipping route by ID within tenant boundary."""
        pass

    @abstractmethod
    def get_vessel_by_imo(self, imo: str) -> Optional[Dict[str, Any]]:
        """Look up registered vessel by IMO number."""
        pass

    @abstractmethod
    def get_vessel_by_mmsi(self, mmsi: str) -> Optional[Dict[str, Any]]:
        """Look up registered vessel by MMSI number."""
        pass

    @abstractmethod
    def get_aircraft_by_icao24(self, icao24: str) -> Optional[Dict[str, Any]]:
        """Look up registered aircraft by ICAO24 transponder hex code."""
        pass


# =============================================================================
# In-Memory Entity Lookup Provider (Thread-safe, testable, fast)
# =============================================================================
class InMemoryEntityLookupProvider(EntityLookupProvider):
    """High-performance in-memory entity lookup provider for deterministic resolution."""

    def __init__(self) -> None:
        # Tenanted indexes: Dict[org_id, Dict[id/code, record]]
        self._shipments_by_id: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._shipments_by_tracking: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._suppliers_by_id: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._suppliers_by_code: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._supplier_sites_by_id: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._factories_by_id: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._warehouses_by_id: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._warehouses_by_code: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._carriers_by_id: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._carriers_by_code: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._routes_by_id: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # Global shared reference indexes (Ports, Vessels, Aircraft)
        self._ports_by_id: Dict[str, Dict[str, Any]] = {}
        self._ports_by_unlocode: Dict[str, Dict[str, Any]] = {}
        self._vessels_by_imo: Dict[str, Dict[str, Any]] = {}
        self._vessels_by_mmsi: Dict[str, Dict[str, Any]] = {}
        self._aircraft_by_icao24: Dict[str, Dict[str, Any]] = {}

    # Registration helpers for testing and runtime setup
    def register_shipment(self, org_id: str, shipment_id: str, tracking_number: str, carrier_namespace: str = "LOGISTICS", **kwargs: Any) -> None:
        rec = {"id": shipment_id, "org_id": org_id, "tracking_number": tracking_number, "carrier_namespace": carrier_namespace, **kwargs}
        self._shipments_by_id.setdefault(org_id, {})[shipment_id] = rec
        tracking_key = f"{carrier_namespace.upper()}:{tracking_number.strip()}"
        self._shipments_by_tracking.setdefault(org_id, {})[tracking_key] = rec

    def register_supplier(self, org_id: str, supplier_id: str, code: Optional[str] = None, name: str = "", **kwargs: Any) -> None:
        rec = {"id": supplier_id, "org_id": org_id, "code": code, "name": name, **kwargs}
        self._suppliers_by_id.setdefault(org_id, {})[supplier_id] = rec
        if code:
            self._suppliers_by_code.setdefault(org_id, {})[code.strip().upper()] = rec

    def register_supplier_site(self, org_id: str, site_id: str, supplier_id: str, name: str = "", **kwargs: Any) -> None:
        rec = {"id": site_id, "org_id": org_id, "supplier_id": supplier_id, "name": name, **kwargs}
        self._supplier_sites_by_id.setdefault(org_id, {})[site_id] = rec

    def register_factory(self, org_id: str, factory_id: str, name: str = "", **kwargs: Any) -> None:
        rec = {"id": factory_id, "org_id": org_id, "name": name, **kwargs}
        self._factories_by_id.setdefault(org_id, {})[factory_id] = rec

    def register_warehouse(self, org_id: str, warehouse_id: str, code: Optional[str] = None, name: str = "", **kwargs: Any) -> None:
        rec = {"id": warehouse_id, "org_id": org_id, "code": code, "name": name, **kwargs}
        self._warehouses_by_id.setdefault(org_id, {})[warehouse_id] = rec
        if code:
            self._warehouses_by_code.setdefault(org_id, {})[code.strip().upper()] = rec

    def register_port(self, port_id: str, code: str, name: str, unlocode: Optional[str] = None, **kwargs: Any) -> None:
        rec = {"id": port_id, "code": code, "name": name, "unlocode": unlocode, **kwargs}
        self._ports_by_id[port_id] = rec
        if unlocode:
            self._ports_by_unlocode[unlocode.strip().upper()] = rec

    def register_carrier(self, org_id: str, carrier_id: str, code: str, namespace: str = "LOGISTICS", name: str = "", **kwargs: Any) -> None:
        rec = {"id": carrier_id, "org_id": org_id, "code": code, "namespace": namespace, "name": name, **kwargs}
        self._carriers_by_id.setdefault(org_id, {})[carrier_id] = rec
        code_key = f"{namespace.upper()}:{code.strip().upper()}"
        self._carriers_by_code.setdefault(org_id, {})[code_key] = rec

    def register_route(self, org_id: str, route_id: str, name: str = "", **kwargs: Any) -> None:
        rec = {"id": route_id, "org_id": org_id, "name": name, **kwargs}
        self._routes_by_id.setdefault(org_id, {})[route_id] = rec

    def register_vessel(self, imo: Optional[str], mmsi: Optional[str], name: str, vessel_id: str = "", **kwargs: Any) -> None:
        vid = vessel_id or (imo or mmsi or name)
        rec = {"id": vid, "imo": imo, "mmsi": mmsi, "name": name, **kwargs}
        if imo:
            self._vessels_by_imo[str(imo).strip()] = rec
        if mmsi:
            self._vessels_by_mmsi[str(mmsi).strip()] = rec

    def register_aircraft(self, icao24: str, callsign: Optional[str] = None, aircraft_id: str = "", **kwargs: Any) -> None:
        aid = aircraft_id or icao24
        rec = {"id": aid, "icao24": icao24.lower().strip(), "callsign": callsign, **kwargs}
        self._aircraft_by_icao24[icao24.lower().strip()] = rec

    # Implementations of EntityLookupProvider
    def get_shipment(self, org_id: Optional[str], internal_id: str) -> Optional[Dict[str, Any]]:
        if not org_id or not internal_id:
            return None
        return self._shipments_by_id.get(org_id, {}).get(internal_id)

    def get_shipment_by_tracking(
        self, org_id: Optional[str], tracking_number: str, carrier_namespace: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        if not org_id or not tracking_number:
            return None
        ns = (carrier_namespace or "LOGISTICS").upper()
        tracking_key = f"{ns}:{tracking_number.strip()}"
        return self._shipments_by_tracking.get(org_id, {}).get(tracking_key)

    def get_supplier(self, org_id: Optional[str], internal_id: str) -> Optional[Dict[str, Any]]:
        if not org_id or not internal_id:
            return None
        return self._suppliers_by_id.get(org_id, {}).get(internal_id)

    def get_supplier_by_code(self, org_id: Optional[str], code: str) -> Optional[Dict[str, Any]]:
        if not org_id or not code:
            return None
        return self._suppliers_by_code.get(org_id, {}).get(code.strip().upper())

    def get_supplier_site(self, org_id: Optional[str], internal_id: str) -> Optional[Dict[str, Any]]:
        if not org_id or not internal_id:
            return None
        return self._supplier_sites_by_id.get(org_id, {}).get(internal_id)

    def get_factory(self, org_id: Optional[str], internal_id: str) -> Optional[Dict[str, Any]]:
        if not org_id or not internal_id:
            return None
        return self._factories_by_id.get(org_id, {}).get(internal_id)

    def get_warehouse(self, org_id: Optional[str], internal_id: str) -> Optional[Dict[str, Any]]:
        if not org_id or not internal_id:
            return None
        return self._warehouses_by_id.get(org_id, {}).get(internal_id)

    def get_warehouse_by_code(self, org_id: Optional[str], code: str) -> Optional[Dict[str, Any]]:
        if not org_id or not code:
            return None
        return self._warehouses_by_code.get(org_id, {}).get(code.strip().upper())

    def get_port(self, internal_id: str) -> Optional[Dict[str, Any]]:
        if not internal_id:
            return None
        return self._ports_by_id.get(internal_id)

    def get_port_by_unlocode(self, unlocode: str) -> Optional[Dict[str, Any]]:
        if not unlocode:
            return None
        return self._ports_by_unlocode.get(unlocode.strip().upper())

    def get_carrier(self, org_id: Optional[str], internal_id: str) -> Optional[Dict[str, Any]]:
        if not org_id or not internal_id:
            return None
        return self._carriers_by_id.get(org_id, {}).get(internal_id)

    def get_carrier_by_code(self, org_id: Optional[str], code: str, namespace: str) -> Optional[Dict[str, Any]]:
        if not org_id or not code:
            return None
        code_key = f"{namespace.upper()}:{code.strip().upper()}"
        return self._carriers_by_code.get(org_id, {}).get(code_key)

    def get_route(self, org_id: Optional[str], internal_id: str) -> Optional[Dict[str, Any]]:
        if not org_id or not internal_id:
            return None
        return self._routes_by_id.get(org_id, {}).get(internal_id)

    def get_vessel_by_imo(self, imo: str) -> Optional[Dict[str, Any]]:
        if not imo:
            return None
        return self._vessels_by_imo.get(str(imo).strip())

    def get_vessel_by_mmsi(self, mmsi: str) -> Optional[Dict[str, Any]]:
        if not mmsi:
            return None
        return self._vessels_by_mmsi.get(str(mmsi).strip())

    def get_aircraft_by_icao24(self, icao24: str) -> Optional[Dict[str, Any]]:
        if not icao24:
            return None
        return self._aircraft_by_icao24.get(icao24.lower().strip())


# =============================================================================
# Entity Normalizer Engine
# =============================================================================
class EntityNormalizer:
    """Conservative, namespace-isolated entity normalizer.

    Resolves raw and canonical entity identifiers into strongly typed EntityReference objects
    and enforces strict multi-tenant isolation, conflict detection, and false-positive prevention.
    """

    def __init__(self, lookup_provider: Optional[EntityLookupProvider] = None) -> None:
        self.lookup_provider = lookup_provider or InMemoryEntityLookupProvider()

    def normalize_entities(self, signal: NormalizedRiskSignal) -> NormalizedRiskSignal:
        """Enrich a NormalizedRiskSignal with verified and unresolved EntityReferences."""
        org_id = signal.organization_id
        entities = signal.entities
        attrs = signal.normalized_attributes
        unresolved = dict(entities.unresolved_identifiers)

        # 1. Resolve Shipment
        self._resolve_shipment(org_id, entities, attrs, unresolved)

        # 2. Resolve Supplier
        self._resolve_supplier(org_id, entities, attrs, unresolved)

        # 3. Resolve Supplier Site vs Factory
        self._resolve_facilities(org_id, entities, attrs, unresolved)

        # 4. Resolve Warehouse
        self._resolve_warehouse(org_id, entities, attrs, unresolved)

        # 5. Resolve Port (Single Authoritative Path)
        self._resolve_port(entities, attrs, unresolved)

        # 6. Resolve Route
        self._resolve_route(org_id, entities, attrs, unresolved)

        # 7. Resolve Carrier
        self._resolve_carrier(org_id, entities, attrs, unresolved)

        # 8. Resolve Vessel (with IMO > MMSI > callsign hierarchy & conflict detection)
        self._resolve_vessel(entities, attrs, unresolved)

        # 9. Resolve Aircraft (with ICAO24 / callsign conflict detection)
        self._resolve_aircraft(entities, attrs, unresolved)

        # 10. Resolve Vehicle / Tracking Object
        self._resolve_vehicle(entities, attrs, unresolved)

        # Update unresolved identifiers dict on entities
        entities.unresolved_identifiers = unresolved

        # Assess overall correlation status
        if entities.has_conflict:
            entities.correlation_status = CorrelationStatus.AMBIGUOUS
        elif entities.shipment_id or entities.supplier_id:
            entities.correlation_status = CorrelationStatus.RESOLVED
        elif (
            entities.port_id
            or entities.route_id
            or entities.carrier_id
            or entities.supplier_site_id
            or entities.factory_id
            or entities.warehouse_id
            or entities.vessel_mmsi
            or entities.aircraft_icao24
            or any(r.correlation_confidence in (CorrelationConfidence.EXACT, CorrelationConfidence.VERIFIED, CorrelationConfidence.STRONG) for r in entities.references)
        ):
            entities.correlation_status = CorrelationStatus.PARTIAL
        else:
            entities.correlation_status = CorrelationStatus.NONE

        return signal

    # -------------------------------------------------------------------------
    # 1. Shipment Resolution
    # -------------------------------------------------------------------------
    def _resolve_shipment(
        self,
        org_id: Optional[str],
        entities: SignalEntityReferences,
        attrs: Dict[str, Any],
        unresolved: Dict[str, str],
    ) -> None:
        # Check internal shipment ID
        raw_shipment_id = entities.shipment_id or attrs.get("shipment_id")
        if raw_shipment_id:
            clean_id = str(raw_shipment_id).strip()
            # Must be scoped by org_id
            found = self.lookup_provider.get_shipment(org_id, clean_id) if org_id else None
            if found:
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.SHIPMENT,
                        internal_id=found["id"],
                        external_id=clean_id,
                        identifier_namespace="INTERNAL",
                        identifier_type="SHIPMENT_ID",
                        correlation_confidence=CorrelationConfidence.EXACT,
                        correlation_method=CorrelationMethod.INTERNAL_ID,
                        evidence={"matched_by": "internal_id", "record": found},
                        raw_identifier=str(raw_shipment_id),
                    )
                )
                return
            else:
                # Unresolved internal ID (or cross-tenant attempt)
                unresolved["shipment_id"] = clean_id
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.SHIPMENT,
                        internal_id=None,
                        external_id=clean_id,
                        identifier_namespace="INTERNAL",
                        identifier_type="SHIPMENT_ID",
                        correlation_confidence=CorrelationConfidence.UNRESOLVED,
                        correlation_method=CorrelationMethod.UNRESOLVED,
                        evidence={"reason": "Shipment ID not found within tenant scope", "org_id": org_id},
                        raw_identifier=str(raw_shipment_id),
                    )
                )

        # Check tracking number + carrier namespace
        raw_tracking = attrs.get("tracking_number") or unresolved.get("tracking_number") or unresolved.get("tracking_id")
        carrier_ns = attrs.get("carrier_code") or attrs.get("carrier") or "LOGISTICS"
        if raw_tracking:
            norm_tracking = IdentifierNormalizer.normalize_tracking_number(str(raw_tracking), carrier_ns)
            found_tracking = (
                self.lookup_provider.get_shipment_by_tracking(org_id, norm_tracking.normalized_value, norm_tracking.namespace)
                if org_id
                else None
            )
            if found_tracking:
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.SHIPMENT,
                        internal_id=found_tracking["id"],
                        external_id=norm_tracking.normalized_value,
                        identifier_namespace=norm_tracking.namespace,
                        identifier_type="TRACKING_NUMBER",
                        correlation_confidence=CorrelationConfidence.VERIFIED,
                        correlation_method=CorrelationMethod.VERIFIED_MAPPING,
                        evidence={"matched_by": "tracking_number", "record": found_tracking},
                        raw_identifier=str(raw_tracking),
                    )
                )
            else:
                unresolved["tracking_number"] = norm_tracking.normalized_value
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.SHIPMENT,
                        internal_id=None,
                        external_id=norm_tracking.normalized_value,
                        identifier_namespace=norm_tracking.namespace,
                        identifier_type="TRACKING_NUMBER",
                        correlation_confidence=CorrelationConfidence.UNRESOLVED,
                        correlation_method=CorrelationMethod.UNRESOLVED,
                        evidence={"reason": "Tracking number not mapped to internal shipment", "org_id": org_id},
                        raw_identifier=str(raw_tracking),
                    )
                )

    # -------------------------------------------------------------------------
    # 2. Supplier Resolution
    # -------------------------------------------------------------------------
    def _resolve_supplier(
        self,
        org_id: Optional[str],
        entities: SignalEntityReferences,
        attrs: Dict[str, Any],
        unresolved: Dict[str, str],
    ) -> None:
        raw_supplier_id = entities.supplier_id or attrs.get("supplier_id")
        if raw_supplier_id:
            clean_id = str(raw_supplier_id).strip()
            found = self.lookup_provider.get_supplier(org_id, clean_id) if org_id else None
            if found:
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.SUPPLIER,
                        internal_id=found["id"],
                        external_id=clean_id,
                        identifier_namespace="INTERNAL",
                        identifier_type="SUPPLIER_ID",
                        correlation_confidence=CorrelationConfidence.EXACT,
                        correlation_method=CorrelationMethod.INTERNAL_ID,
                        evidence={"matched_by": "internal_id", "record": found},
                        raw_identifier=str(raw_supplier_id),
                    )
                )
                return
            else:
                unresolved["supplier_id"] = clean_id
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.SUPPLIER,
                        internal_id=None,
                        external_id=clean_id,
                        identifier_namespace="INTERNAL",
                        identifier_type="SUPPLIER_ID",
                        correlation_confidence=CorrelationConfidence.UNRESOLVED,
                        correlation_method=CorrelationMethod.UNRESOLVED,
                        evidence={"reason": "Supplier ID not found in tenant", "org_id": org_id},
                        raw_identifier=str(raw_supplier_id),
                    )
                )

        raw_code = attrs.get("supplier_code")
        if raw_code and org_id:
            clean_code = str(raw_code).strip()
            found_code = self.lookup_provider.get_supplier_by_code(org_id, clean_code)
            if found_code:
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.SUPPLIER,
                        internal_id=found_code["id"],
                        external_id=clean_code,
                        identifier_namespace="INTERNAL",
                        identifier_type="SUPPLIER_CODE",
                        correlation_confidence=CorrelationConfidence.VERIFIED,
                        correlation_method=CorrelationMethod.VERIFIED_MAPPING,
                        evidence={"matched_by": "supplier_code", "record": found_code},
                        raw_identifier=str(raw_code),
                    )
                )
                return

        # Explicitly preserve supplier_name without fuzzy matching
        if "supplier_name" in attrs and not entities.supplier_id:
            unresolved["supplier_name"] = str(attrs["supplier_name"]).strip()

    # -------------------------------------------------------------------------
    # 3. Facilities: Supplier Site vs Factory
    # -------------------------------------------------------------------------
    def _resolve_facilities(
        self,
        org_id: Optional[str],
        entities: SignalEntityReferences,
        attrs: Dict[str, Any],
        unresolved: Dict[str, str],
    ) -> None:
        # Supplier Site
        raw_site_id = entities.supplier_site_id or attrs.get("supplier_site_id") or attrs.get("site_id")
        if raw_site_id:
            clean_id = str(raw_site_id).strip()
            found = self.lookup_provider.get_supplier_site(org_id, clean_id) if org_id else None
            if found:
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.SUPPLIER_SITE,
                        internal_id=found["id"],
                        external_id=clean_id,
                        identifier_namespace="INTERNAL",
                        identifier_type="SITE_ID",
                        correlation_confidence=CorrelationConfidence.EXACT,
                        correlation_method=CorrelationMethod.INTERNAL_ID,
                        evidence={"matched_by": "supplier_site_id", "record": found},
                        raw_identifier=str(raw_site_id),
                    )
                )
            else:
                unresolved["supplier_site_id"] = clean_id
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.SUPPLIER_SITE,
                        internal_id=None,
                        external_id=clean_id,
                        identifier_namespace="INTERNAL",
                        identifier_type="SITE_ID",
                        correlation_confidence=CorrelationConfidence.UNRESOLVED,
                        correlation_method=CorrelationMethod.UNRESOLVED,
                        evidence={"reason": "Supplier site not found in tenant", "org_id": org_id},
                        raw_identifier=str(raw_site_id),
                    )
                )

        # Factory
        raw_factory_id = entities.factory_id or attrs.get("factory_id")
        if raw_factory_id:
            clean_id = str(raw_factory_id).strip()
            found = self.lookup_provider.get_factory(org_id, clean_id) if org_id else None
            if found:
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.FACTORY,
                        internal_id=found["id"],
                        external_id=clean_id,
                        identifier_namespace="INTERNAL",
                        identifier_type="FACTORY_ID",
                        correlation_confidence=CorrelationConfidence.EXACT,
                        correlation_method=CorrelationMethod.INTERNAL_ID,
                        evidence={"matched_by": "factory_id", "record": found},
                        raw_identifier=str(raw_factory_id),
                    )
                )
            else:
                unresolved["factory_id"] = clean_id
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.FACTORY,
                        internal_id=None,
                        external_id=clean_id,
                        identifier_namespace="INTERNAL",
                        identifier_type="FACTORY_ID",
                        correlation_confidence=CorrelationConfidence.UNRESOLVED,
                        correlation_method=CorrelationMethod.UNRESOLVED,
                        evidence={"reason": "Factory not found in tenant", "org_id": org_id},
                        raw_identifier=str(raw_factory_id),
                    )
                )

    # -------------------------------------------------------------------------
    # 4. Warehouse Resolution
    # -------------------------------------------------------------------------
    def _resolve_warehouse(
        self,
        org_id: Optional[str],
        entities: SignalEntityReferences,
        attrs: Dict[str, Any],
        unresolved: Dict[str, str],
    ) -> None:
        raw_wh_id = entities.warehouse_id or attrs.get("warehouse_id")
        if raw_wh_id:
            clean_id = str(raw_wh_id).strip()
            found = self.lookup_provider.get_warehouse(org_id, clean_id) if org_id else None
            if found:
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.WAREHOUSE,
                        internal_id=found["id"],
                        external_id=clean_id,
                        identifier_namespace="INTERNAL",
                        identifier_type="WAREHOUSE_ID",
                        correlation_confidence=CorrelationConfidence.EXACT,
                        correlation_method=CorrelationMethod.INTERNAL_ID,
                        evidence={"matched_by": "warehouse_id", "record": found},
                        raw_identifier=str(raw_wh_id),
                    )
                )
                return
            else:
                unresolved["warehouse_id"] = clean_id
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.WAREHOUSE,
                        internal_id=None,
                        external_id=clean_id,
                        identifier_namespace="INTERNAL",
                        identifier_type="WAREHOUSE_ID",
                        correlation_confidence=CorrelationConfidence.UNRESOLVED,
                        correlation_method=CorrelationMethod.UNRESOLVED,
                        evidence={"reason": "Warehouse ID not found in tenant", "org_id": org_id},
                        raw_identifier=str(raw_wh_id),
                    )
                )

        raw_code = attrs.get("warehouse_code")
        if raw_code and org_id:
            clean_code = str(raw_code).strip()
            found_code = self.lookup_provider.get_warehouse_by_code(org_id, clean_code)
            if found_code:
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.WAREHOUSE,
                        internal_id=found_code["id"],
                        external_id=clean_code,
                        identifier_namespace="INTERNAL",
                        identifier_type="WAREHOUSE_CODE",
                        correlation_confidence=CorrelationConfidence.VERIFIED,
                        correlation_method=CorrelationMethod.VERIFIED_MAPPING,
                        evidence={"matched_by": "warehouse_code", "record": found_code},
                        raw_identifier=str(raw_code),
                    )
                )

    # -------------------------------------------------------------------------
    # 5. Port Resolution (Single Authoritative Route)
    # -------------------------------------------------------------------------
    def _resolve_port(
        self,
        entities: SignalEntityReferences,
        attrs: Dict[str, Any],
        unresolved: Dict[str, str],
    ) -> None:
        # Check internal port ID
        raw_port_id = entities.port_id or attrs.get("port_id")
        if raw_port_id:
            clean_id = str(raw_port_id).strip()
            found = self.lookup_provider.get_port(clean_id)
            if found:
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.PORT,
                        internal_id=found["id"],
                        external_id=clean_id,
                        identifier_namespace="PORT",
                        identifier_type="PORT_ID",
                        correlation_confidence=CorrelationConfidence.EXACT,
                        correlation_method=CorrelationMethod.INTERNAL_ID,
                        evidence={"matched_by": "internal_port_id", "record": found},
                        raw_identifier=str(raw_port_id),
                    )
                )
                return

        # Check UN/LOCODE
        raw_unlocode = attrs.get("unlocode") or attrs.get("port_code") or unresolved.get("unlocode")
        if raw_unlocode:
            norm_loc = IdentifierNormalizer.normalize_unlocode(str(raw_unlocode))
            if norm_loc.is_valid:
                found_port = self.lookup_provider.get_port_by_unlocode(norm_loc.normalized_value)
                if found_port:
                    entities.add_reference(
                        EntityReference(
                            entity_type=EntityType.PORT,
                            internal_id=found_port["id"],
                            external_id=norm_loc.normalized_value,
                            identifier_namespace="PORT",
                            identifier_type="UNLOCODE",
                            correlation_confidence=CorrelationConfidence.VERIFIED,
                            correlation_method=CorrelationMethod.VERIFIED_MAPPING,
                            evidence={"matched_by": "unlocode", "record": found_port},
                            raw_identifier=str(raw_unlocode),
                        )
                    )
                    return
                else:
                    unresolved["unlocode"] = norm_loc.normalized_value
                    entities.add_reference(
                        EntityReference(
                            entity_type=EntityType.PORT,
                            internal_id=None,
                            external_id=norm_loc.normalized_value,
                            identifier_namespace="PORT",
                            identifier_type="UNLOCODE",
                            correlation_confidence=CorrelationConfidence.UNRESOLVED,
                            correlation_method=CorrelationMethod.UNRESOLVED,
                            evidence={"reason": "UN/LOCODE not found in master port registry"},
                            raw_identifier=str(raw_unlocode),
                        )
                    )

    # -------------------------------------------------------------------------
    # 6. Route Resolution
    # -------------------------------------------------------------------------
    def _resolve_route(
        self,
        org_id: Optional[str],
        entities: SignalEntityReferences,
        attrs: Dict[str, Any],
        unresolved: Dict[str, str],
    ) -> None:
        raw_route_id = entities.route_id or attrs.get("route_id")
        if raw_route_id:
            clean_id = str(raw_route_id).strip()
            found = self.lookup_provider.get_route(org_id, clean_id) if org_id else None
            if found:
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.ROUTE,
                        internal_id=found["id"],
                        external_id=clean_id,
                        identifier_namespace="INTERNAL",
                        identifier_type="ROUTE_ID",
                        correlation_confidence=CorrelationConfidence.EXACT,
                        correlation_method=CorrelationMethod.INTERNAL_ID,
                        evidence={"matched_by": "route_id", "record": found},
                        raw_identifier=str(raw_route_id),
                    )
                )
            else:
                unresolved["route_id"] = clean_id
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.ROUTE,
                        internal_id=None,
                        external_id=clean_id,
                        identifier_namespace="INTERNAL",
                        identifier_type="ROUTE_ID",
                        correlation_confidence=CorrelationConfidence.UNRESOLVED,
                        correlation_method=CorrelationMethod.UNRESOLVED,
                        evidence={"reason": "Route ID not found in tenant", "org_id": org_id},
                        raw_identifier=str(raw_route_id),
                    )
                )

    # -------------------------------------------------------------------------
    # 7. Carrier Resolution
    # -------------------------------------------------------------------------
    def _resolve_carrier(
        self,
        org_id: Optional[str],
        entities: SignalEntityReferences,
        attrs: Dict[str, Any],
        unresolved: Dict[str, str],
    ) -> None:
        raw_carrier_id = entities.carrier_id or attrs.get("carrier_id")
        if raw_carrier_id:
            clean_id = str(raw_carrier_id).strip()
            found = self.lookup_provider.get_carrier(org_id, clean_id) if org_id else None
            if found:
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.CARRIER,
                        internal_id=found["id"],
                        external_id=clean_id,
                        identifier_namespace="INTERNAL",
                        identifier_type="CARRIER_ID",
                        correlation_confidence=CorrelationConfidence.EXACT,
                        correlation_method=CorrelationMethod.INTERNAL_ID,
                        evidence={"matched_by": "carrier_id", "record": found},
                        raw_identifier=str(raw_carrier_id),
                    )
                )
                return
            else:
                unresolved["carrier_id"] = clean_id

        raw_carrier_code = attrs.get("carrier_code")
        carrier_ns = attrs.get("carrier_namespace") or "LOGISTICS"
        if raw_carrier_code and org_id:
            clean_code = str(raw_carrier_code).strip()
            found_carrier = self.lookup_provider.get_carrier_by_code(org_id, clean_code, carrier_ns)
            if found_carrier:
                entities.add_reference(
                    EntityReference(
                        entity_type=EntityType.CARRIER,
                        internal_id=found_carrier["id"],
                        external_id=clean_code,
                        identifier_namespace=carrier_ns.upper(),
                        identifier_type="CARRIER_CODE",
                        correlation_confidence=CorrelationConfidence.VERIFIED,
                        correlation_method=CorrelationMethod.VERIFIED_MAPPING,
                        evidence={"matched_by": "carrier_code", "record": found_carrier},
                        raw_identifier=str(raw_carrier_code),
                    )
                )
            else:
                unresolved["carrier_code"] = f"{carrier_ns.upper()}:{clean_code}"

    # -------------------------------------------------------------------------
    # 8. Vessel Resolution (IMO > MMSI > callsign > name & Conflict Detection)
    # -------------------------------------------------------------------------
    def _resolve_vessel(
        self,
        entities: SignalEntityReferences,
        attrs: Dict[str, Any],
        unresolved: Dict[str, str],
    ) -> None:
        raw_imo = attrs.get("imo") or attrs.get("vessel_imo")
        raw_mmsi = entities.vessel_mmsi or attrs.get("mmsi") or attrs.get("vessel_mmsi")
        raw_callsign = attrs.get("callsign") or attrs.get("vessel_callsign")
        raw_name = attrs.get("vessel_name") or attrs.get("ship_name")

        vessel_by_imo = None
        vessel_by_mmsi = None

        norm_imo = IdentifierNormalizer.normalize_imo(str(raw_imo)) if raw_imo else None
        norm_mmsi = IdentifierNormalizer.normalize_mmsi(str(raw_mmsi)) if raw_mmsi else None

        if norm_imo and norm_imo.is_valid:
            vessel_by_imo = self.lookup_provider.get_vessel_by_imo(norm_imo.normalized_value)
        if norm_mmsi and norm_mmsi.is_valid:
            vessel_by_mmsi = self.lookup_provider.get_vessel_by_mmsi(norm_mmsi.normalized_value)

        # Conflict check: IMO and MMSI resolve to conflicting vessels
        if vessel_by_imo and vessel_by_mmsi and vessel_by_imo.get("id") != vessel_by_mmsi.get("id"):
            conflict_msg = (
                f"Vessel conflict: IMO {norm_imo.normalized_value} resolves to '{vessel_by_imo.get('name')}' "
                f"({vessel_by_imo.get('id')}) but MMSI {norm_mmsi.normalized_value} resolves to '{vessel_by_mmsi.get('name')}' "
                f"({vessel_by_mmsi.get('id')})"
            )
            entities.add_reference(
                EntityReference(
                    entity_type=EntityType.VESSEL,
                    internal_id=None,
                    external_id=norm_imo.normalized_value,
                    identifier_namespace="MARITIME",
                    identifier_type="IMO",
                    correlation_confidence=CorrelationConfidence.UNRESOLVED,
                    correlation_method=CorrelationMethod.UNRESOLVED,
                    evidence={"imo_vessel": vessel_by_imo, "mmsi_vessel": vessel_by_mmsi},
                    raw_identifier=str(raw_imo),
                    is_conflict=True,
                    conflict_details=conflict_msg,
                )
            )
            unresolved["vessel_conflict"] = conflict_msg
            return

        # 1. Prefer IMO (strongest maritime identifier)
        if vessel_by_imo:
            entities.add_reference(
                EntityReference(
                    entity_type=EntityType.VESSEL,
                    internal_id=vessel_by_imo.get("id"),
                    external_id=norm_imo.normalized_value,
                    identifier_namespace="MARITIME",
                    identifier_type="IMO",
                    correlation_confidence=CorrelationConfidence.EXACT,
                    correlation_method=CorrelationMethod.EXACT_IDENTIFIER,
                    evidence={"vessel": vessel_by_imo},
                    raw_identifier=str(raw_imo),
                )
            )
            return
        elif norm_imo and norm_imo.is_valid:
            unresolved["imo"] = norm_imo.normalized_value
            entities.add_reference(
                EntityReference(
                    entity_type=EntityType.VESSEL,
                    internal_id=None,
                    external_id=norm_imo.normalized_value,
                    identifier_namespace="MARITIME",
                    identifier_type="IMO",
                    correlation_confidence=CorrelationConfidence.STRONG,
                    correlation_method=CorrelationMethod.NAMESPACE_IDENTIFIER,
                    evidence={"status": "Valid IMO but vessel not registered in local master"},
                    raw_identifier=str(raw_imo),
                )
            )

        # 2. MMSI (secondary maritime identifier)
        if vessel_by_mmsi:
            entities.add_reference(
                EntityReference(
                    entity_type=EntityType.VESSEL,
                    internal_id=vessel_by_mmsi.get("id"),
                    external_id=norm_mmsi.normalized_value,
                    identifier_namespace="MARITIME",
                    identifier_type="MMSI",
                    correlation_confidence=CorrelationConfidence.VERIFIED,
                    correlation_method=CorrelationMethod.EXACT_IDENTIFIER,
                    evidence={"vessel": vessel_by_mmsi},
                    raw_identifier=str(raw_mmsi),
                )
            )
            return
        elif norm_mmsi and norm_mmsi.is_valid:
            unresolved["mmsi"] = norm_mmsi.normalized_value
            entities.add_reference(
                EntityReference(
                    entity_type=EntityType.VESSEL,
                    internal_id=None,
                    external_id=norm_mmsi.normalized_value,
                    identifier_namespace="MARITIME",
                    identifier_type="MMSI",
                    correlation_confidence=CorrelationConfidence.STRONG,
                    correlation_method=CorrelationMethod.NAMESPACE_IDENTIFIER,
                    evidence={"status": "Valid MMSI but vessel not registered"},
                    raw_identifier=str(raw_mmsi),
                )
            )

        # 3. Radio Callsign / Name fallback
        if raw_callsign:
            norm_cs = IdentifierNormalizer.normalize_callsign(str(raw_callsign), namespace="MARITIME")
            unresolved["vessel_callsign"] = norm_cs.normalized_value
        if raw_name:
            unresolved["vessel_name"] = str(raw_name).strip()

    # -------------------------------------------------------------------------
    # 9. Aircraft Resolution (ICAO24 vs Callsign & Conflict Detection)
    # -------------------------------------------------------------------------
    def _resolve_aircraft(
        self,
        entities: SignalEntityReferences,
        attrs: Dict[str, Any],
        unresolved: Dict[str, str],
    ) -> None:
        raw_icao = entities.aircraft_icao24 or attrs.get("icao24") or attrs.get("aircraft_icao24")
        raw_callsign = entities.flight_number or attrs.get("callsign") or attrs.get("flight_number")

        norm_icao = IdentifierNormalizer.normalize_icao24(str(raw_icao)) if raw_icao else None
        norm_callsign = IdentifierNormalizer.normalize_callsign(str(raw_callsign), namespace="AVIATION") if raw_callsign else None

        found_aircraft = None
        if norm_icao and norm_icao.is_valid:
            found_aircraft = self.lookup_provider.get_aircraft_by_icao24(norm_icao.normalized_value)

        # Conflict check: registered aircraft has known permanent callsign that conflicts with reported callsign
        if (
            found_aircraft
            and found_aircraft.get("callsign")
            and norm_callsign
            and norm_callsign.is_valid
            and found_aircraft.get("callsign").upper() != norm_callsign.normalized_value
        ):
            conflict_msg = (
                f"Aircraft identity ambiguity: ICAO24 {norm_icao.normalized_value} registered as callsign "
                f"'{found_aircraft.get('callsign')}' but active transmission reports callsign '{norm_callsign.normalized_value}'"
            )
            entities.add_reference(
                EntityReference(
                    entity_type=EntityType.AIRCRAFT,
                    internal_id=found_aircraft.get("id"),
                    external_id=norm_icao.normalized_value,
                    identifier_namespace="AVIATION",
                    identifier_type="ICAO24",
                    correlation_confidence=CorrelationConfidence.UNRESOLVED,
                    correlation_method=CorrelationMethod.UNRESOLVED,
                    evidence={"registered_aircraft": found_aircraft, "reported_callsign": norm_callsign.normalized_value},
                    raw_identifier=str(raw_icao),
                    is_conflict=True,
                    conflict_details=conflict_msg,
                )
            )
            unresolved["aircraft_conflict"] = conflict_msg
            return

        if found_aircraft:
            entities.add_reference(
                EntityReference(
                    entity_type=EntityType.AIRCRAFT,
                    internal_id=found_aircraft.get("id"),
                    external_id=norm_icao.normalized_value,
                    identifier_namespace="AVIATION",
                    identifier_type="ICAO24",
                    correlation_confidence=CorrelationConfidence.EXACT,
                    correlation_method=CorrelationMethod.EXACT_IDENTIFIER,
                    evidence={"aircraft": found_aircraft},
                    raw_identifier=str(raw_icao),
                )
            )
        elif norm_icao and norm_icao.is_valid:
            unresolved["icao24"] = norm_icao.normalized_value
            entities.add_reference(
                EntityReference(
                    entity_type=EntityType.AIRCRAFT,
                    internal_id=None,
                    external_id=norm_icao.normalized_value,
                    identifier_namespace="AVIATION",
                    identifier_type="ICAO24",
                    correlation_confidence=CorrelationConfidence.STRONG,
                    correlation_method=CorrelationMethod.NAMESPACE_IDENTIFIER,
                    evidence={"status": "Valid ICAO24 hex address but aircraft not in master"},
                    raw_identifier=str(raw_icao),
                )
            )

        if norm_callsign and norm_callsign.is_valid and not found_aircraft:
            unresolved["callsign"] = norm_callsign.normalized_value
            entities.add_reference(
                EntityReference(
                    entity_type=EntityType.AIRCRAFT,
                    internal_id=None,
                    external_id=norm_callsign.normalized_value,
                    identifier_namespace="AVIATION",
                    identifier_type="CALLSIGN",
                    correlation_confidence=CorrelationConfidence.WEAK,
                    correlation_method=CorrelationMethod.EXTERNAL_REFERENCE,
                    evidence={"status": "Radio callsign (non-permanent identity)"},
                    raw_identifier=str(raw_callsign),
                )
            )

    # -------------------------------------------------------------------------
    # 10. Vehicle / Tracking Object Resolution
    # -------------------------------------------------------------------------
    def _resolve_vehicle(
        self,
        entities: SignalEntityReferences,
        attrs: Dict[str, Any],
        unresolved: Dict[str, str],
    ) -> None:
        raw_veh = entities.vehicle_id or attrs.get("vehicle_id") or attrs.get("asset_id")
        if raw_veh:
            norm_veh = IdentifierNormalizer.normalize_generic(str(raw_veh), namespace="FLEET", identifier_type="VEHICLE_ID")
            entities.add_reference(
                EntityReference(
                    entity_type=EntityType.VEHICLE,
                    internal_id=None,
                    external_id=norm_veh.normalized_value,
                    identifier_namespace=norm_veh.namespace,
                    identifier_type=norm_veh.identifier_type,
                    correlation_confidence=CorrelationConfidence.STRONG,
                    correlation_method=CorrelationMethod.NAMESPACE_IDENTIFIER,
                    raw_identifier=str(raw_veh),
                )
            )
            entities.vehicle_id = norm_veh.normalized_value

        raw_obj = attrs.get("container_id") or attrs.get("pallet_id") or attrs.get("tracking_object_id")
        if raw_obj:
            norm_obj = IdentifierNormalizer.normalize_generic(str(raw_obj), namespace="LOGISTICS", identifier_type="TRACKING_OBJECT")
            entities.add_reference(
                EntityReference(
                    entity_type=EntityType.TRACKING_OBJECT,
                    internal_id=None,
                    external_id=norm_obj.normalized_value,
                    identifier_namespace=norm_obj.namespace,
                    identifier_type=norm_obj.identifier_type,
                    correlation_confidence=CorrelationConfidence.STRONG,
                    correlation_method=CorrelationMethod.NAMESPACE_IDENTIFIER,
                    raw_identifier=str(raw_obj),
                )
            )
            unresolved["tracking_object_id"] = norm_obj.normalized_value
