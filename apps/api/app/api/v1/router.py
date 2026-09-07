"""Central API v1 router for RiskWise API."""
from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    carriers,
    factories,
    health,
    incidents,
    inventory,
    inventory_movements,
    notifications,
    ports,
    products,
    recommendations,
    risk_assessments,
    risk_factors,
    risks,
    routes,
    shipment_events,
    shipments,
    supplier_sites,
    suppliers,
    verification_results,
    warehouses,
)
from app.api.v1.endpoints import actions, approvals, audit_logs

api_router = APIRouter()

# Mount infrastructure and authentication routers
api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])

# Phase 4 Step 3: Supplier APIs
api_router.include_router(suppliers.router, prefix="/suppliers", tags=["Suppliers"])

# Phase 4 Step 4: Logistics & Network APIs
api_router.include_router(supplier_sites.router, prefix="/supplier-sites", tags=["Supplier Sites"])
api_router.include_router(factories.router, prefix="/factories", tags=["Factories"])
api_router.include_router(warehouses.router, prefix="/warehouses", tags=["Warehouses"])
api_router.include_router(ports.router, prefix="/ports", tags=["Ports"])
api_router.include_router(carriers.router, prefix="/carriers", tags=["Carriers"])
api_router.include_router(products.router, prefix="/products", tags=["Products"])
api_router.include_router(routes.router, prefix="/routes", tags=["Routes"])
api_router.include_router(shipments.router, prefix="/shipments", tags=["Shipments"])
api_router.include_router(shipment_events.router, prefix="/shipment-events", tags=["Shipment Events"])

# Phase 4 Step 5: Inventory APIs
api_router.include_router(inventory.router, prefix="/inventory", tags=["Inventory"])
api_router.include_router(inventory_movements.router, prefix="/inventory-movements", tags=["Inventory Movements"])

# Phase 4 Step 6: Risk APIs
api_router.include_router(risks.router, prefix="/risks", tags=["Risks"])
api_router.include_router(risk_factors.router, prefix="/risk-factors", tags=["Risk Factors"])
api_router.include_router(risk_assessments.router, prefix="/risk-assessments", tags=["Risk Assessments"])
api_router.include_router(incidents.router, prefix="/incidents", tags=["Incidents"])

# Phase 4 Step 7: Decision & Governance APIs
api_router.include_router(recommendations.router, prefix="/recommendations", tags=["Recommendations"])
api_router.include_router(approvals.router, prefix="/approvals", tags=["Approvals"])
api_router.include_router(actions.router, prefix="/actions", tags=["Actions"])
api_router.include_router(verification_results.router, prefix="/verification-results", tags=["Verification Results"])
api_router.include_router(audit_logs.router, prefix="/audit-logs", tags=["Audit Logs"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])



