"""Candidate Route Generator for RiskWise Optimization Subsystem (TASK-8).

Generates authoritative candidate alternatives from:
1. Digital Twin network topology (edges and nodes)
2. Database master data (Routes and Carriers)
3. Simulation-affected alternatives (filtering or penalizing disrupted corridors)

Guarantees:
- Strict tenant isolation
- Zero fabricated routes in production
- Graceful empty candidate handling
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.digital_twin.contracts import DigitalTwinSnapshot
from app.optimization.contracts import OptimizationAlternative
from app.optimization.errors import OptimizationTenantIsolationError
from app.optimization.integration import (
    DigitalTwinOptimizationIntegration,
    SimulationOptimizationIntegration,
)

logger = logging.getLogger("riskwise.optimization.candidates")


class CandidateRouteGenerator:
    """Extracts, synthesizes, and adapts candidate route alternatives for OR-Tools optimization."""

    @classmethod
    def generate_candidates(
        cls,
        organization_id: str,
        snapshot: Optional[DigitalTwinSnapshot] = None,
        db: Optional[Session] = None,
        simulation_result: Optional[Any] = None,
        origin_node_id: Optional[str] = None,
        destination_node_id: Optional[str] = None,
    ) -> List[OptimizationAlternative]:
        """Generate candidate route alternatives from Digital Twin topology and database master data.
        
        Args:
            organization_id: Mandatory tenant scope.
            snapshot: Active Digital Twin snapshot (authoritative source).
            db: Optional database session for master route and carrier records.
            simulation_result: Optional Phase 13 simulation result to reflect disruptions.
            origin_node_id: Optional filter by origin facility/port.
            destination_node_id: Optional filter by destination facility/port.

        Returns:
            List of strongly typed, validated OptimizationAlternative instances.
        """
        if not organization_id or not str(organization_id).strip():
            raise OptimizationTenantIsolationError("organization_id must be provided to generate candidate routes")

        org_id = organization_id.strip()
        candidates: List[OptimizationAlternative] = []
        seen_ids = set()

        # 1. Primary: Extract routes from Digital Twin snapshot
        if snapshot is not None:
            if snapshot.organization_id != org_id:
                raise OptimizationTenantIsolationError(
                    f"Digital Twin snapshot organization '{snapshot.organization_id}' does not match '{org_id}'"
                )
            twin_candidates = DigitalTwinOptimizationIntegration.extract_candidate_routes(
                snapshot=snapshot,
                organization_id=org_id,
                origin_node_id=origin_node_id,
                destination_node_id=destination_node_id,
            )
            for c in twin_candidates:
                if c.alternative_id not in seen_ids:
                    candidates.append(c)
                    seen_ids.add(c.alternative_id)

        # 2. Secondary / Augmentation: Query database master data if candidates is empty or db provided
        if db is not None and not candidates:
            try:
                from app.models.network import Route, Carrier

                # Query tenant routes
                routes = (
                    db.query(Route)
                    .filter(Route.org_id == org_id)
                    .all()
                )
                for r in routes:
                    if origin_node_id and r.origin_facility_id != origin_node_id:
                        continue
                    if destination_node_id and r.destination_facility_id != destination_node_id:
                        continue

                    alt_id = f"alt_route_{r.id}"
                    if alt_id not in seen_ids:
                        lead_hours = (r.standard_lead_time_days * 24.0) if r.standard_lead_time_days else 48.0
                        candidates.append(
                            OptimizationAlternative(
                                alternative_id=alt_id,
                                entity_type="ROUTE",
                                entity_id=r.id,
                                is_available=True,
                                capacity=100.0,
                                cost=float(r.distance_km * 1.5) if r.distance_km else 500.0,
                                transit_time_hours=lead_hours,
                                risk_score=float(r.risk_score) if r.risk_score is not None else 20.0,
                                properties={
                                    "name": r.name,
                                    "mode": r.mode,
                                    "distance_km": r.distance_km,
                                },
                                provenance_reference=f"db:routes:{r.id}",
                            )
                        )
                        seen_ids.add(alt_id)

                # Query tenant carriers
                carriers = (
                    db.query(Carrier)
                    .filter(Carrier.org_id == org_id)
                    .all()
                )
                for carrier in carriers:
                    alt_id = f"alt_carrier_{carrier.id}"
                    if alt_id not in seen_ids:
                        reliability = float(carrier.on_time_reliability) if carrier.on_time_reliability else 0.95
                        candidates.append(
                            OptimizationAlternative(
                                alternative_id=alt_id,
                                entity_type="CARRIER",
                                entity_id=carrier.id,
                                is_available=True,
                                capacity=250.0,
                                cost=1200.0,
                                transit_time_hours=36.0,
                                risk_score=float(100.0 * (1.0 - reliability)),
                                properties={
                                    "name": carrier.name,
                                    "mode": carrier.mode or "OCEAN",
                                    "on_time_reliability": carrier.on_time_reliability,
                                },
                                provenance_reference=f"db:carriers:{carrier.id}",
                            )
                        )
                        seen_ids.add(alt_id)

            except Exception as e:
                logger.warning(f"Could not query master database routes/carriers for '{org_id}': {e}")

        # 3. Apply simulation effects if simulation_result is provided
        if simulation_result is not None and candidates:
            candidates = SimulationOptimizationIntegration.apply_simulation_effects_to_candidates(
                candidates=candidates,
                simulation_result=simulation_result,
            )

        return candidates
