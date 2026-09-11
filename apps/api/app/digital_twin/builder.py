"""Authoritative Digital Twin builder for RiskWise.

Constructs a deterministic, tenant-isolated, queryable graph representation of the
current operational supply-chain state without mutating source records or fabricating
unsupported relationships.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from sqlalchemy.orm import Session

from app.digital_twin.contracts import (
    DigitalTwinSnapshot,
    TwinEdgeContract,
    TwinNodeContract,
)
from app.digital_twin.errors import TwinValidationError
from app.digital_twin.fingerprints import (
    compute_edge_fingerprint,
    compute_edge_id,
    compute_node_fingerprint,
    compute_node_id,
    compute_source_fingerprint,
    compute_twin_fingerprint,
)
from app.digital_twin.observability import TwinObservability
from app.digital_twin.validator import TwinGraphValidator
from app.models.logistics import Inventory, Shipment
from app.models.network import (
    Carrier,
    Factory,
    Port,
    Product,
    Route,
    Supplier,
    SupplierSite,
    Warehouse,
)
from app.models.risk import Incident
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType


class DigitalTwinBuilder:
    """Builder responsible for synthesizing validated Digital Twin snapshots."""

    def __init__(self, organization_id: str, twin_id: Optional[str] = None, version: str = "1"):
        if not organization_id or not organization_id.strip():
            raise TwinValidationError("organization_id must be non-empty")
        self.organization_id = organization_id.strip()
        self.twin_id = (twin_id or f"twin-{self.organization_id}").strip()
        self.version = version

    def build_from_database(
        self,
        db: Session,
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        uow: Any = None,
    ) -> DigitalTwinSnapshot:
        """Read authoritative operational entities from DB, build nodes and edges, validate and return snapshot."""
        start_time = time.perf_counter()
        TwinObservability.log_build_started(
            organization_id=self.organization_id,
            twin_id=self.twin_id,
            correlation_id=correlation_id,
            request_id=request_id,
            uow=uow,
        )

        try:
            # 1. Fetch tenant-scoped operational entities
            suppliers: List[Supplier] = (
                db.query(Supplier).filter(Supplier.org_id == self.organization_id).all()
            )
            supplier_sites: List[SupplierSite] = (
                db.query(SupplierSite).filter(SupplierSite.org_id == self.organization_id).all()
            )
            factories: List[Factory] = (
                db.query(Factory).filter(Factory.org_id == self.organization_id).all()
            )
            warehouses: List[Warehouse] = (
                db.query(Warehouse).filter(Warehouse.org_id == self.organization_id).all()
            )
            # Ports are shared reference data; include all available ports scoped to this org
            ports: List[Port] = db.query(Port).all()

            carriers: List[Carrier] = (
                db.query(Carrier).filter(Carrier.org_id == self.organization_id).all()
            )
            routes: List[Route] = (
                db.query(Route).filter(Route.org_id == self.organization_id).all()
            )
            shipments: List[Shipment] = (
                db.query(Shipment).filter(Shipment.org_id == self.organization_id).all()
            )
            products: List[Product] = (
                db.query(Product).filter(Product.org_id == self.organization_id).all()
            )
            inventories: List[Inventory] = (
                db.query(Inventory).filter(Inventory.org_id == self.organization_id).all()
            )
            incidents: List[Incident] = (
                db.query(Incident)
                .filter(Incident.org_id == self.organization_id, Incident.status != "RESOLVED")
                .all()
            )

            # 2. Build graph in-memory
            snapshot = self.build_from_entities(
                suppliers=suppliers,
                supplier_sites=supplier_sites,
                factories=factories,
                warehouses=warehouses,
                ports=ports,
                carriers=carriers,
                routes=routes,
                shipments=shipments,
                products=products,
                inventories=inventories,
                incidents=incidents,
                correlation_id=correlation_id,
                request_id=request_id,
                uow=uow,
            )

            build_duration_ms = (time.perf_counter() - start_time) * 1000
            TwinObservability.log_build_succeeded(
                organization_id=self.organization_id,
                twin_id=self.twin_id,
                node_count=snapshot.node_count,
                edge_count=snapshot.edge_count,
                source_fingerprint=snapshot.source_fingerprint,
                twin_fingerprint=snapshot.twin_fingerprint,
                build_duration_ms=build_duration_ms,
                correlation_id=correlation_id,
                request_id=request_id,
                uow=uow,
            )
            return snapshot

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            TwinObservability.log_build_failed(
                organization_id=self.organization_id,
                twin_id=self.twin_id,
                error_message=str(e),
                failure_category=type(e).__name__,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                request_id=request_id,
                uow=uow,
            )
            raise

    def build_from_entities(
        self,
        suppliers: Sequence[Any] = (),
        supplier_sites: Sequence[Any] = (),
        factories: Sequence[Any] = (),
        warehouses: Sequence[Any] = (),
        ports: Sequence[Any] = (),
        carriers: Sequence[Any] = (),
        routes: Sequence[Any] = (),
        shipments: Sequence[Any] = (),
        products: Sequence[Any] = (),
        inventories: Sequence[Any] = (),
        incidents: Sequence[Any] = (),
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        uow: Any = None,
    ) -> DigitalTwinSnapshot:
        """Construct a validated Digital Twin snapshot from explicit entity collections."""
        nodes: Dict[str, TwinNodeContract] = {}
        edges: Dict[str, TwinEdgeContract] = {}
        source_digests: List[str] = []

        # Facility entity ID to node ID mapping for route and inventory cross-referencing
        facility_id_to_node_id: Dict[str, str] = {}
        supplier_id_to_node_id: Dict[str, str] = {}
        carrier_id_to_node_id: Dict[str, str] = {}
        route_id_to_node_id: Dict[str, str] = {}
        product_id_to_node_id: Dict[str, str] = {}

        # Incident mapping: entity_id -> list of incident summaries
        incident_map: Dict[str, List[Dict[str, Any]]] = {}
        for inc in incidents:
            assets = getattr(inc, "affected_assets", None) or []
            inc_summary = {
                "id": str(getattr(inc, "id", "")),
                "title": str(getattr(inc, "title", "")),
                "severity": str(getattr(inc, "severity", "")),
                "status": str(getattr(inc, "status", "")),
            }
            if isinstance(assets, list):
                for asset in assets:
                    asset_id = str(asset.get("id") if isinstance(asset, dict) else asset)
                    incident_map.setdefault(asset_id, []).append(inc_summary)

        # -------------------------------------------------------------
        # A. BUILD NODES
        # -------------------------------------------------------------

        # 1. Suppliers
        for s in suppliers:
            s_id = str(getattr(s, "id"))
            # Tenant isolation validation on source record
            s_org = getattr(s, "org_id", None)
            if s_org and s_org != self.organization_id:
                continue

            node_id = compute_node_id(self.organization_id, "SUPPLIER", s_id)
            label = str(getattr(s, "name", f"Supplier {s_id}"))
            props: Dict[str, Any] = {
                "tier": getattr(s, "tier", None),
                "country": getattr(s, "country", None),
                "criticality": getattr(s, "criticality", None),
                "financial_exposure": getattr(s, "financial_exposure", None),
            }
            if s_id in incident_map:
                props["active_incidents"] = incident_map[s_id]

            fp = compute_node_fingerprint(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.SUPPLIER.value,
                source_entity_type="SUPPLIER",
                source_entity_id=s_id,
                label=label,
                health_score=getattr(s, "reliability_score", None),
                status=getattr(s, "status", "ACTIVE") if hasattr(s, "status") else "ACTIVE",
                properties=props,
            )
            node = TwinNodeContract(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.SUPPLIER,
                source_entity_type="SUPPLIER",
                source_entity_id=s_id,
                label=label,
                latitude=None,
                longitude=None,
                health_score=getattr(s, "reliability_score", None),
                status=getattr(s, "status", "ACTIVE") if hasattr(s, "status") else "ACTIVE",
                properties=props,
                source_timestamp=getattr(s, "created_at", None),
                fingerprint=fp,
            )
            nodes[node_id] = node
            supplier_id_to_node_id[s_id] = node_id
            source_digests.append(f"SUPPLIER:{s_id}:{fp}")

        # 2. Supplier Sites
        for site in supplier_sites:
            site_id = str(getattr(site, "id"))
            site_org = getattr(site, "org_id", None)
            if site_org and site_org != self.organization_id:
                continue

            node_id = compute_node_id(self.organization_id, "SUPPLIER_SITE", site_id)
            label = str(getattr(site, "name", f"Site {site_id}"))
            props = {
                "supplier_id": str(getattr(site, "supplier_id", "")),
                "site_type": getattr(site, "site_type", None),
                "capacity": getattr(site, "capacity", None),
                "city": getattr(site, "city", None),
                "country": getattr(site, "country", None),
            }
            if site_id in incident_map:
                props["active_incidents"] = incident_map[site_id]

            lat = getattr(site, "latitude", None)
            lon = getattr(site, "longitude", None)
            fp = compute_node_fingerprint(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.SUPPLIER_SITE.value,
                source_entity_type="SUPPLIER_SITE",
                source_entity_id=site_id,
                label=label,
                latitude=lat,
                longitude=lon,
                health_score=None,
                status=getattr(site, "status", "OPERATIONAL"),
                properties=props,
            )
            node = TwinNodeContract(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.SUPPLIER_SITE,
                source_entity_type="SUPPLIER_SITE",
                source_entity_id=site_id,
                label=label,
                latitude=lat,
                longitude=lon,
                health_score=None,
                status=getattr(site, "status", "OPERATIONAL"),
                properties=props,
                source_timestamp=getattr(site, "created_at", None),
                fingerprint=fp,
            )
            nodes[node_id] = node
            facility_id_to_node_id[site_id] = node_id
            source_digests.append(f"SUPPLIER_SITE:{site_id}:{fp}")

        # 3. Factories
        for f in factories:
            f_id = str(getattr(f, "id"))
            f_org = getattr(f, "org_id", None)
            if f_org and f_org != self.organization_id:
                continue

            node_id = compute_node_id(self.organization_id, "FACTORY", f_id)
            label = str(getattr(f, "name", f"Factory {f_id}"))
            props = {
                "code": getattr(f, "code", None),
                "capacity": getattr(f, "capacity", None),
                "utilization": getattr(f, "utilization", None),
                "city": getattr(f, "city", None),
                "country": getattr(f, "country", None),
            }
            if f_id in incident_map:
                props["active_incidents"] = incident_map[f_id]

            lat = getattr(f, "latitude", None)
            lon = getattr(f, "longitude", None)
            fp = compute_node_fingerprint(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.FACTORY.value,
                source_entity_type="FACTORY",
                source_entity_id=f_id,
                label=label,
                latitude=lat,
                longitude=lon,
                status=getattr(f, "status", "OPERATIONAL"),
                properties=props,
            )
            node = TwinNodeContract(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.FACTORY,
                source_entity_type="FACTORY",
                source_entity_id=f_id,
                label=label,
                latitude=lat,
                longitude=lon,
                health_score=None,
                status=getattr(f, "status", "OPERATIONAL"),
                properties=props,
                source_timestamp=getattr(f, "created_at", None),
                fingerprint=fp,
            )
            nodes[node_id] = node
            facility_id_to_node_id[f_id] = node_id
            source_digests.append(f"FACTORY:{f_id}:{fp}")

        # 4. Warehouses
        for w in warehouses:
            w_id = str(getattr(w, "id"))
            w_org = getattr(w, "org_id", None)
            if w_org and w_org != self.organization_id:
                continue

            node_id = compute_node_id(self.organization_id, "WAREHOUSE", w_id)
            label = str(getattr(w, "name", f"Warehouse {w_id}"))
            props = {
                "code": getattr(w, "code", None),
                "total_capacity": getattr(w, "total_capacity", None),
                "current_occupancy": getattr(w, "current_occupancy", None),
                "city": getattr(w, "city", None),
                "country": getattr(w, "country", None),
            }
            if w_id in incident_map:
                props["active_incidents"] = incident_map[w_id]

            lat = getattr(w, "latitude", None)
            lon = getattr(w, "longitude", None)
            fp = compute_node_fingerprint(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.WAREHOUSE.value,
                source_entity_type="WAREHOUSE",
                source_entity_id=w_id,
                label=label,
                latitude=lat,
                longitude=lon,
                status=getattr(w, "status", "OPERATIONAL"),
                properties=props,
            )
            node = TwinNodeContract(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.WAREHOUSE,
                source_entity_type="WAREHOUSE",
                source_entity_id=w_id,
                label=label,
                latitude=lat,
                longitude=lon,
                health_score=None,
                status=getattr(w, "status", "OPERATIONAL"),
                properties=props,
                source_timestamp=getattr(w, "created_at", None),
                fingerprint=fp,
            )
            nodes[node_id] = node
            facility_id_to_node_id[w_id] = node_id
            source_digests.append(f"WAREHOUSE:{w_id}:{fp}")

        # 5. Ports (Shared global reference nodes scoped deterministically to this organization)
        for p in ports:
            p_id = str(getattr(p, "id"))
            node_id = compute_node_id(self.organization_id, "PORT", p_id)
            label = str(getattr(p, "name", f"Port {p_id}"))
            props = {
                "code": getattr(p, "code", None),
                "port_type": getattr(p, "port_type", "SEA"),
                "country": getattr(p, "country", None),
                "congestion_score": getattr(p, "congestion_score", None),
                "average_wait_hours": getattr(p, "average_wait_hours", None),
            }
            lat = getattr(p, "latitude", None)
            lon = getattr(p, "longitude", None)
            fp = compute_node_fingerprint(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.PORT.value,
                source_entity_type="PORT",
                source_entity_id=p_id,
                label=label,
                latitude=lat,
                longitude=lon,
                health_score=None,
                status="OPERATIONAL",
                properties=props,
            )
            node = TwinNodeContract(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.PORT,
                source_entity_type="PORT",
                source_entity_id=p_id,
                label=label,
                latitude=lat,
                longitude=lon,
                health_score=None,
                status="OPERATIONAL",
                properties=props,
                source_timestamp=getattr(p, "created_at", None),
                fingerprint=fp,
            )
            nodes[node_id] = node
            facility_id_to_node_id[p_id] = node_id
            source_digests.append(f"PORT:{p_id}:{fp}")

        # 6. Carriers
        for c in carriers:
            c_id = str(getattr(c, "id"))
            c_org = getattr(c, "org_id", None)
            if c_org and c_org != self.organization_id:
                continue

            node_id = compute_node_id(self.organization_id, "CARRIER", c_id)
            label = str(getattr(c, "name", f"Carrier {c_id}"))
            props = {
                "code": getattr(c, "code", None),
                "mode": getattr(c, "mode", None),
            }
            fp = compute_node_fingerprint(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.CARRIER.value,
                source_entity_type="CARRIER",
                source_entity_id=c_id,
                label=label,
                health_score=getattr(c, "on_time_reliability", None),
                status="ACTIVE",
                properties=props,
            )
            node = TwinNodeContract(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.CARRIER,
                source_entity_type="CARRIER",
                source_entity_id=c_id,
                label=label,
                latitude=None,
                longitude=None,
                health_score=getattr(c, "on_time_reliability", None),
                status="ACTIVE",
                properties=props,
                source_timestamp=getattr(c, "created_at", None),
                fingerprint=fp,
            )
            nodes[node_id] = node
            carrier_id_to_node_id[c_id] = node_id
            source_digests.append(f"CARRIER:{c_id}:{fp}")

        # 7. Products
        for pr in products:
            pr_id = str(getattr(pr, "id"))
            pr_org = getattr(pr, "org_id", None)
            if pr_org and pr_org != self.organization_id:
                continue

            node_id = compute_node_id(self.organization_id, "PRODUCT", pr_id)
            label = str(getattr(pr, "name", f"Product {pr_id}"))
            props = {
                "sku": getattr(pr, "sku", ""),
                "category": getattr(pr, "category", None),
                "unit_cost": getattr(pr, "unit_cost", None),
                "currency": getattr(pr, "currency", "USD"),
            }
            fp = compute_node_fingerprint(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.PRODUCT.value,
                source_entity_type="PRODUCT",
                source_entity_id=pr_id,
                label=label,
                status="ACTIVE",
                properties=props,
            )
            node = TwinNodeContract(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.PRODUCT,
                source_entity_type="PRODUCT",
                source_entity_id=pr_id,
                label=label,
                latitude=None,
                longitude=None,
                health_score=None,
                status="ACTIVE",
                properties=props,
                source_timestamp=getattr(pr, "created_at", None),
                fingerprint=fp,
            )
            nodes[node_id] = node
            product_id_to_node_id[pr_id] = node_id
            source_digests.append(f"PRODUCT:{pr_id}:{fp}")

        # 8. Routes (Nodes representing corridors)
        for r in routes:
            r_id = str(getattr(r, "id"))
            r_org = getattr(r, "org_id", None)
            if r_org and r_org != self.organization_id:
                continue

            node_id = compute_node_id(self.organization_id, "ROUTE", r_id)
            label = str(getattr(r, "name", f"Route {r_id}"))
            props = {
                "mode": getattr(r, "mode", "OCEAN"),
                "distance_km": getattr(r, "distance_km", None),
                "standard_lead_time_days": getattr(r, "standard_lead_time_days", None),
                "origin_facility_id": getattr(r, "origin_facility_id", None),
                "destination_facility_id": getattr(r, "destination_facility_id", None),
            }
            risk_score = getattr(r, "risk_score", None)
            health_score = 100.0 - risk_score if risk_score is not None else None
            fp = compute_node_fingerprint(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.ROUTE.value,
                source_entity_type="ROUTE",
                source_entity_id=r_id,
                label=label,
                health_score=health_score,
                status="OPERATIONAL",
                properties=props,
            )
            node = TwinNodeContract(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.ROUTE,
                source_entity_type="ROUTE",
                source_entity_id=r_id,
                label=label,
                latitude=None,
                longitude=None,
                health_score=health_score,
                status="OPERATIONAL",
                properties=props,
                source_timestamp=getattr(r, "created_at", None),
                fingerprint=fp,
            )
            nodes[node_id] = node
            route_id_to_node_id[r_id] = node_id
            source_digests.append(f"ROUTE:{r_id}:{fp}")

        # 9. Shipments
        for sh in shipments:
            sh_id = str(getattr(sh, "id"))
            sh_org = getattr(sh, "org_id", None)
            if sh_org and sh_org != self.organization_id:
                continue

            node_id = compute_node_id(self.organization_id, "SHIPMENT", sh_id)
            label = f"Shipment {getattr(sh, 'tracking_number', sh_id)}"
            props = {
                "tracking_number": getattr(sh, "tracking_number", ""),
                "route_id": getattr(sh, "route_id", None),
                "carrier_id": getattr(sh, "carrier_id", None),
                "product_id": getattr(sh, "product_id", None),
                "mode": getattr(sh, "mode", "OCEAN"),
                "origin": getattr(sh, "origin", None),
                "destination": getattr(sh, "destination", None),
                "delay_minutes": getattr(sh, "delay_minutes", None),
            }
            lat = getattr(sh, "current_lat", None)
            lon = getattr(sh, "current_lng", None)
            status = getattr(sh, "status", "IN_TRANSIT")
            fp = compute_node_fingerprint(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.SHIPMENT.value,
                source_entity_type="SHIPMENT",
                source_entity_id=sh_id,
                label=label,
                latitude=lat,
                longitude=lon,
                status=status,
                properties=props,
            )
            node = TwinNodeContract(
                node_id=node_id,
                organization_id=self.organization_id,
                node_type=TwinNodeType.SHIPMENT,
                source_entity_type="SHIPMENT",
                source_entity_id=sh_id,
                label=label,
                latitude=lat,
                longitude=lon,
                health_score=None,
                status=status,
                properties=props,
                source_timestamp=getattr(sh, "created_at", None),
                fingerprint=fp,
            )
            nodes[node_id] = node
            source_digests.append(f"SHIPMENT:{sh_id}:{fp}")

        # -------------------------------------------------------------
        # B. BUILD EDGES
        # -------------------------------------------------------------

        # 1. Supplier -> SupplierSite (SUPPLIES)
        for site in supplier_sites:
            site_id = str(getattr(site, "id"))
            sup_id = str(getattr(site, "supplier_id", ""))
            site_node_id = facility_id_to_node_id.get(site_id)
            sup_node_id = supplier_id_to_node_id.get(sup_id)

            if site_node_id and sup_node_id:
                edge_id = compute_edge_id(
                    self.organization_id,
                    sup_node_id,
                    site_node_id,
                    TwinEdgeType.SUPPLIES.value,
                    f"sup_site:{site_id}",
                )
                props = {"relationship": "SUPPLIER_OPERATES_SITE"}
                cap = getattr(site, "capacity", None)
                fp = compute_edge_fingerprint(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=sup_node_id,
                    to_node_id=site_node_id,
                    edge_type=TwinEdgeType.SUPPLIES.value,
                    status="ACTIVE",
                    flow_capacity=cap,
                    properties=props,
                    source_reference=f"supplier_sites:{site_id}",
                )
                edges[edge_id] = TwinEdgeContract(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=sup_node_id,
                    to_node_id=site_node_id,
                    edge_type=TwinEdgeType.SUPPLIES,
                    status="ACTIVE",
                    flow_capacity=cap,
                    current_flow=None,
                    risk_score=None,
                    properties=props,
                    source_reference=f"supplier_sites:{site_id}",
                    fingerprint=fp,
                )

        # 2. Routes (Facility corridor and Route connections)
        for r in routes:
            r_id = str(getattr(r, "id"))
            r_node_id = route_id_to_node_id.get(r_id)
            orig_fac_id = getattr(r, "origin_facility_id", None)
            dest_fac_id = getattr(r, "destination_facility_id", None)

            orig_node_id = facility_id_to_node_id.get(orig_fac_id) if orig_fac_id else None
            dest_node_id = facility_id_to_node_id.get(dest_fac_id) if dest_fac_id else None

            # Corridor edge: origin_node -> destination_node (TRANSPORT)
            if orig_node_id and dest_node_id:
                edge_id = compute_edge_id(
                    self.organization_id,
                    orig_node_id,
                    dest_node_id,
                    TwinEdgeType.TRANSPORT.value,
                    f"route_corridor:{r_id}",
                )
                edge_props = {
                    "mode": getattr(r, "mode", "OCEAN"),
                    "distance_km": getattr(r, "distance_km", None),
                    "standard_lead_time_days": getattr(r, "standard_lead_time_days", None),
                }
                risk_score = getattr(r, "risk_score", None)
                fp = compute_edge_fingerprint(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=orig_node_id,
                    to_node_id=dest_node_id,
                    edge_type=TwinEdgeType.TRANSPORT.value,
                    status="OPERATIONAL",
                    risk_score=risk_score,
                    properties=edge_props,
                    source_reference=f"routes:{r_id}",
                )
                edges[edge_id] = TwinEdgeContract(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=orig_node_id,
                    to_node_id=dest_node_id,
                    edge_type=TwinEdgeType.TRANSPORT,
                    status="OPERATIONAL",
                    flow_capacity=None,
                    current_flow=None,
                    risk_score=risk_score,
                    properties=edge_props,
                    source_reference=f"routes:{r_id}",
                    fingerprint=fp,
                )

            # Route node linkages: orig -> route and route -> dest
            if r_node_id and orig_node_id:
                edge_id = compute_edge_id(
                    self.organization_id,
                    orig_node_id,
                    r_node_id,
                    TwinEdgeType.CONNECTS.value,
                    f"orig_link:{r_id}",
                )
                fp = compute_edge_fingerprint(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=orig_node_id,
                    to_node_id=r_node_id,
                    edge_type=TwinEdgeType.CONNECTS.value,
                    status="OPERATIONAL",
                    source_reference=f"routes:{r_id}:origin",
                )
                edges[edge_id] = TwinEdgeContract(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=orig_node_id,
                    to_node_id=r_node_id,
                    edge_type=TwinEdgeType.CONNECTS,
                    status="OPERATIONAL",
                    source_reference=f"routes:{r_id}:origin",
                    fingerprint=fp,
                )

            if r_node_id and dest_node_id:
                edge_id = compute_edge_id(
                    self.organization_id,
                    r_node_id,
                    dest_node_id,
                    TwinEdgeType.CONNECTS.value,
                    f"dest_link:{r_id}",
                )
                fp = compute_edge_fingerprint(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=r_node_id,
                    to_node_id=dest_node_id,
                    edge_type=TwinEdgeType.CONNECTS.value,
                    status="OPERATIONAL",
                    source_reference=f"routes:{r_id}:destination",
                )
                edges[edge_id] = TwinEdgeContract(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=r_node_id,
                    to_node_id=dest_node_id,
                    edge_type=TwinEdgeType.CONNECTS,
                    status="OPERATIONAL",
                    source_reference=f"routes:{r_id}:destination",
                    fingerprint=fp,
                )

        # 3. Carrier -> Shipment (CARRIES)
        for sh in shipments:
            sh_id = str(getattr(sh, "id"))
            sh_node_id = compute_node_id(self.organization_id, "SHIPMENT", sh_id)
            c_id = getattr(sh, "carrier_id", None)
            c_node_id = carrier_id_to_node_id.get(c_id) if c_id else None

            if sh_node_id in nodes and c_node_id and c_node_id in nodes:
                edge_id = compute_edge_id(
                    self.organization_id,
                    c_node_id,
                    sh_node_id,
                    TwinEdgeType.CARRIES.value,
                    f"carrier_sh:{sh_id}",
                )
                fp = compute_edge_fingerprint(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=c_node_id,
                    to_node_id=sh_node_id,
                    edge_type=TwinEdgeType.CARRIES.value,
                    status="ACTIVE",
                    source_reference=f"shipments:{sh_id}:carrier",
                )
                edges[edge_id] = TwinEdgeContract(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=c_node_id,
                    to_node_id=sh_node_id,
                    edge_type=TwinEdgeType.CARRIES,
                    status="ACTIVE",
                    source_reference=f"shipments:{sh_id}:carrier",
                    fingerprint=fp,
                )

            # Shipment -> Route (CONNECTS)
            r_id = getattr(sh, "route_id", None)
            r_node_id = route_id_to_node_id.get(r_id) if r_id else None
            if sh_node_id in nodes and r_node_id and r_node_id in nodes:
                edge_id = compute_edge_id(
                    self.organization_id,
                    sh_node_id,
                    r_node_id,
                    TwinEdgeType.CONNECTS.value,
                    f"sh_route:{sh_id}",
                )
                fp = compute_edge_fingerprint(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=sh_node_id,
                    to_node_id=r_node_id,
                    edge_type=TwinEdgeType.CONNECTS.value,
                    status="ACTIVE",
                    source_reference=f"shipments:{sh_id}:route",
                )
                edges[edge_id] = TwinEdgeContract(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=sh_node_id,
                    to_node_id=r_node_id,
                    edge_type=TwinEdgeType.CONNECTS,
                    status="ACTIVE",
                    source_reference=f"shipments:{sh_id}:route",
                    fingerprint=fp,
                )

            # Shipment -> Product (FLOW)
            pr_id = getattr(sh, "product_id", None)
            pr_node_id = product_id_to_node_id.get(pr_id) if pr_id else None
            if sh_node_id in nodes and pr_node_id and pr_node_id in nodes:
                edge_id = compute_edge_id(
                    self.organization_id,
                    sh_node_id,
                    pr_node_id,
                    TwinEdgeType.FLOW.value,
                    f"sh_prod:{sh_id}",
                )
                fp = compute_edge_fingerprint(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=sh_node_id,
                    to_node_id=pr_node_id,
                    edge_type=TwinEdgeType.FLOW.value,
                    status="IN_TRANSIT",
                    source_reference=f"shipments:{sh_id}:product",
                )
                edges[edge_id] = TwinEdgeContract(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=sh_node_id,
                    to_node_id=pr_node_id,
                    edge_type=TwinEdgeType.FLOW,
                    status="IN_TRANSIT",
                    source_reference=f"shipments:{sh_id}:product",
                    fingerprint=fp,
                )

        # 4. Inventory: Facility -> Product (LOCATED_AT)
        for inv in inventories:
            inv_id = str(getattr(inv, "id"))
            inv_org = getattr(inv, "org_id", None)
            if inv_org and inv_org != self.organization_id:
                continue

            fac_id = getattr(inv, "facility_id", None)
            pr_id = getattr(inv, "product_id", None)

            fac_node_id = facility_id_to_node_id.get(fac_id) if fac_id else None
            pr_node_id = product_id_to_node_id.get(pr_id) if pr_id else None

            if fac_node_id and pr_node_id:
                edge_id = compute_edge_id(
                    self.organization_id,
                    fac_node_id,
                    pr_node_id,
                    TwinEdgeType.LOCATED_AT.value,
                    f"inv:{inv_id}",
                )
                qty = getattr(inv, "quantity_on_hand", 0.0)
                inv_props = {
                    "safety_stock": getattr(inv, "safety_stock", None),
                    "reorder_point": getattr(inv, "reorder_point", None),
                    "days_of_supply": getattr(inv, "days_of_supply", None),
                }
                fp = compute_edge_fingerprint(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=fac_node_id,
                    to_node_id=pr_node_id,
                    edge_type=TwinEdgeType.LOCATED_AT.value,
                    status="ACTIVE",
                    current_flow=qty,
                    properties=inv_props,
                    source_reference=f"inventory:{inv_id}",
                )
                edges[edge_id] = TwinEdgeContract(
                    edge_id=edge_id,
                    organization_id=self.organization_id,
                    from_node_id=fac_node_id,
                    to_node_id=pr_node_id,
                    edge_type=TwinEdgeType.LOCATED_AT,
                    status="ACTIVE",
                    current_flow=qty,
                    properties=inv_props,
                    source_reference=f"inventory:{inv_id}",
                    fingerprint=fp,
                )

        # -------------------------------------------------------------
        # C. GRAPH VALIDATION
        # -------------------------------------------------------------
        val_start = time.perf_counter()
        validation_result = TwinGraphValidator.validate_graph(
            nodes=nodes,
            edges=edges,
            expected_org_id=self.organization_id,
            verify_fingerprints=True,
        )
        val_duration_ms = (time.perf_counter() - val_start) * 1000

        if not validation_result.is_valid:
            TwinObservability.log_build_failed(
                organization_id=self.organization_id,
                twin_id=self.twin_id,
                error_message="; ".join(validation_result.errors),
                failure_category="TwinValidationError",
                duration_ms=val_duration_ms,
                correlation_id=correlation_id,
                request_id=request_id,
                uow=uow,
            )
            raise TwinValidationError(f"Graph validation failed: {'; '.join(validation_result.errors)}")

        TwinObservability.log_build_validated(
            organization_id=self.organization_id,
            twin_id=self.twin_id,
            node_count=len(nodes),
            edge_count=len(edges),
            validation_duration_ms=val_duration_ms,
            correlation_id=correlation_id,
            request_id=request_id,
            uow=uow,
        )

        # -------------------------------------------------------------
        # D. SNAPSHOT PACKAGING
        # -------------------------------------------------------------
        source_fp = compute_source_fingerprint(source_digests)
        node_fps = [n.fingerprint for n in nodes.values()]
        edge_fps = [e.fingerprint for e in edges.values()]
        twin_fp = compute_twin_fingerprint(
            twin_id=self.twin_id,
            organization_id=self.organization_id,
            version=self.version,
            node_fingerprints=node_fps,
            edge_fingerprints=edge_fps,
        )

        snapshot = DigitalTwinSnapshot(
            twin_id=self.twin_id,
            organization_id=self.organization_id,
            version=self.version,
            node_count=len(nodes),
            edge_count=len(edges),
            nodes=nodes,
            edges=edges,
            source_fingerprint=source_fp,
            twin_fingerprint=twin_fp,
            generated_at=datetime.datetime.now(datetime.timezone.utc),
            status="CURRENT",
        )
        return snapshot
