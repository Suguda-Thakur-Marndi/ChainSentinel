"""Repository for Port global reference entity data access."""
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.network import Port
from app.repositories.base import BaseRepository

PORT_SEARCH_COLUMNS = ["name", "code", "country"]

PORT_SORT_ALLOWLIST = {
    "name": Port.name,
    "code": Port.code,
    "country": Port.country,
    "congestion_score": Port.congestion_score,
    "average_wait_hours": Port.average_wait_hours,
    "created_at": Port.created_at,
}

PORT_FILTER_ALLOWLIST = {
    "country": Port.country,
    "port_type": Port.port_type,
}


class PortRepository(BaseRepository[Port]):
    """Data access repository for Port reference entities (Global scope)."""

    def __init__(self, session: Session):
        super().__init__(Port, session)

    def get_by_code(self, code: str) -> Optional[Port]:
        """Look up a global transit port by its UN/LOCODE."""
        stmt = select(Port).where(Port.code == code)
        return self.session.scalars(stmt).first()

    def list_ports(
        self,
        page: int = 1,
        limit: int = 20,
        country: Optional[str] = None,
        port_type: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> list[Port]:
        """List global ports with optional search, filtering, and sorting."""
        filters = {}
        if country:
            filters["country"] = country
        if port_type:
            filters["port_type"] = port_type

        return self.list(
            org_id=None,  # Ports are global; org_id is always None
            page=page,
            limit=limit,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=PORT_FILTER_ALLOWLIST,
            sort_allowlist=PORT_SORT_ALLOWLIST,
            search_columns=PORT_SEARCH_COLUMNS,
            default_sort_field="name",
            default_sort_desc=False,
        )
