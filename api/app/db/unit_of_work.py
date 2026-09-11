"""Lightweight Unit of Work pattern coordinating database session, repositories, and atomic transactions."""
from collections.abc import Generator
from types import TracebackType
from typing import Any, Optional, Type, TypeVar
from fastapi import Depends
from sqlalchemy.orm import Session
from app.core.logging import get_logger
from app.db.session import get_db
from app.repositories.audit_log import AuditLogRepository
from app.repositories.base import BaseRepository
from app.repositories.governance_repositories import (
    ActionRepository,
    ApprovalRepository,
    NotificationRepository,
    RecommendationRepository,
    VerificationResultRepository,
)
from app.repositories.inventory import InventoryMovementRepository, InventoryRepository
from app.repositories.network_repositories import (
    CarrierRepository,
    FactoryRepository,
    ProductRepository,
    RouteRepository,
    SupplierSiteRepository,
    WarehouseRepository,
)
from app.repositories.port import PortRepository
from app.repositories.risk_repositories import (
    IncidentRepository,
    RiskAssessmentRepository,
    RiskFactorRepository,
    RiskRepository,
)
from app.repositories.shipment import ShipmentEventRepository, ShipmentRepository
from app.repositories.supplier import SupplierRepository

logger = get_logger("unit_of_work")

T = TypeVar("T")


class UnitOfWork:
    """Coordinates transactions and data access repositories across an atomic business operation."""

    def __init__(self, session: Session):
        self.session = session
        self._repositories: dict[Type[Any], BaseRepository[Any]] = {}

        # Cached standard repositories
        self._suppliers: Optional[SupplierRepository] = None
        self._supplier_sites: Optional[SupplierSiteRepository] = None
        self._factories: Optional[FactoryRepository] = None
        self._warehouses: Optional[WarehouseRepository] = None
        self._carriers: Optional[CarrierRepository] = None
        self._products: Optional[ProductRepository] = None
        self._routes: Optional[RouteRepository] = None
        self._shipments: Optional[ShipmentRepository] = None
        self._shipment_events: Optional[ShipmentEventRepository] = None
        self._ports: Optional[PortRepository] = None
        self._audit_logs: Optional[AuditLogRepository] = None
        self._inventory: Optional[InventoryRepository] = None
        self._inventory_movements: Optional[InventoryMovementRepository] = None
        self._risks: Optional[RiskRepository] = None
        self._risk_factors: Optional[RiskFactorRepository] = None
        self._risk_assessments: Optional[RiskAssessmentRepository] = None
        self._incidents: Optional[IncidentRepository] = None
        self._recommendations: Optional[RecommendationRepository] = None
        self._approvals: Optional[ApprovalRepository] = None
        self._actions: Optional[ActionRepository] = None
        self._verification_results: Optional[VerificationResultRepository] = None
        self._notifications: Optional[NotificationRepository] = None

    @property
    def suppliers(self) -> SupplierRepository:
        """Supplier repository accessor sharing the UoW session."""
        if self._suppliers is None:
            self._suppliers = SupplierRepository(self.session)
        return self._suppliers

    @property
    def supplier_sites(self) -> SupplierSiteRepository:
        """SupplierSite repository accessor sharing the UoW session."""
        if self._supplier_sites is None:
            self._supplier_sites = SupplierSiteRepository(self.session)
        return self._supplier_sites

    @property
    def factories(self) -> FactoryRepository:
        """Factory repository accessor sharing the UoW session."""
        if self._factories is None:
            self._factories = FactoryRepository(self.session)
        return self._factories

    @property
    def warehouses(self) -> WarehouseRepository:
        """Warehouse repository accessor sharing the UoW session."""
        if self._warehouses is None:
            self._warehouses = WarehouseRepository(self.session)
        return self._warehouses

    @property
    def carriers(self) -> CarrierRepository:
        """Carrier repository accessor sharing the UoW session."""
        if self._carriers is None:
            self._carriers = CarrierRepository(self.session)
        return self._carriers

    @property
    def products(self) -> ProductRepository:
        """Product repository accessor sharing the UoW session."""
        if self._products is None:
            self._products = ProductRepository(self.session)
        return self._products

    @property
    def routes(self) -> RouteRepository:
        """Route repository accessor sharing the UoW session."""
        if self._routes is None:
            self._routes = RouteRepository(self.session)
        return self._routes

    @property
    def shipments(self) -> ShipmentRepository:
        """Shipment repository accessor sharing the UoW session."""
        if self._shipments is None:
            self._shipments = ShipmentRepository(self.session)
        return self._shipments

    @property
    def shipment_events(self) -> ShipmentEventRepository:
        """ShipmentEvent repository accessor sharing the UoW session."""
        if self._shipment_events is None:
            self._shipment_events = ShipmentEventRepository(self.session)
        return self._shipment_events

    @property
    def ports(self) -> PortRepository:
        """Port global repository accessor sharing the UoW session."""
        if self._ports is None:
            self._ports = PortRepository(self.session)
        return self._ports

    @property
    def audit_logs(self) -> AuditLogRepository:
        """AuditLog repository accessor sharing the UoW session."""
        if self._audit_logs is None:
            self._audit_logs = AuditLogRepository(self.session)
        return self._audit_logs

    @property
    def inventory(self) -> InventoryRepository:
        """Inventory repository accessor sharing the UoW session."""
        if self._inventory is None:
            self._inventory = InventoryRepository(self.session)
        return self._inventory

    @property
    def inventory_movements(self) -> InventoryMovementRepository:
        """InventoryMovement repository accessor sharing the UoW session."""
        if self._inventory_movements is None:
            self._inventory_movements = InventoryMovementRepository(self.session)
        return self._inventory_movements

    @property
    def risks(self) -> RiskRepository:
        """Risk repository accessor sharing the UoW session."""
        if self._risks is None:
            self._risks = RiskRepository(self.session)
        return self._risks

    @property
    def risk_factors(self) -> RiskFactorRepository:
        """RiskFactor repository accessor sharing the UoW session."""
        if self._risk_factors is None:
            self._risk_factors = RiskFactorRepository(self.session)
        return self._risk_factors

    @property
    def risk_assessments(self) -> RiskAssessmentRepository:
        """RiskAssessment repository accessor sharing the UoW session."""
        if self._risk_assessments is None:
            self._risk_assessments = RiskAssessmentRepository(self.session)
        return self._risk_assessments

    @property
    def incidents(self) -> IncidentRepository:
        """Incident repository accessor sharing the UoW session."""
        if self._incidents is None:
            self._incidents = IncidentRepository(self.session)
        return self._incidents

    @property
    def recommendations(self) -> RecommendationRepository:
        """Recommendation repository accessor sharing the UoW session."""
        if self._recommendations is None:
            self._recommendations = RecommendationRepository(self.session)
        return self._recommendations

    @property
    def approvals(self) -> ApprovalRepository:
        """Approval repository accessor sharing the UoW session."""
        if self._approvals is None:
            self._approvals = ApprovalRepository(self.session)
        return self._approvals

    @property
    def actions(self) -> ActionRepository:
        """Action repository accessor sharing the UoW session."""
        if self._actions is None:
            self._actions = ActionRepository(self.session)
        return self._actions

    @property
    def verification_results(self) -> VerificationResultRepository:
        """VerificationResult repository accessor sharing the UoW session."""
        if self._verification_results is None:
            self._verification_results = VerificationResultRepository(self.session)
        return self._verification_results

    @property
    def notifications(self) -> NotificationRepository:
        """Notification repository accessor sharing the UoW session."""
        if self._notifications is None:
            self._notifications = NotificationRepository(self.session)
        return self._notifications

    def repository(self, model: Type[T]) -> BaseRepository[T]:
        """Dynamically obtain or instantiate a generic BaseRepository for any domain model."""
        if model not in self._repositories:
            self._repositories[model] = BaseRepository(model, self.session)
        return self._repositories[model]

    def commit(self) -> None:
        """Commit all pending database changes within the active transaction."""
        try:
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.error("UnitOfWork commit failed: %s", e)
            raise

    def rollback(self) -> None:
        """Roll back all uncommitted changes in the active transaction."""
        self.session.rollback()

    def flush(self) -> None:
        """Flush pending changes to the database without committing."""
        self.session.flush()

    def __enter__(self) -> "UnitOfWork":
        """Enter context manager block."""
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit context manager, automatically rolling back on exception."""
        if exc_type is not None:
            logger.warning("Rolling back transaction due to exception: %s", exc_val)
            self.rollback()


def get_uow(db: Session = Depends(get_db)) -> Generator[UnitOfWork, None, None]:
    """FastAPI dependency yielding a UnitOfWork bound to the request's database session."""
    uow = UnitOfWork(db)
    try:
        yield uow
    finally:
        # Session cleanup is handled by get_db; ensure uncommitted dirty states are rolled back
        if db.is_active:
            db.rollback()
