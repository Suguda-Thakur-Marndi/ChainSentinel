"""Safe database query utilities for tenant isolation, filtering, sorting, search, and pagination."""
from datetime import datetime
from enum import Enum
import re
from typing import Any, Optional
from sqlalchemy import Select, or_
from app.core.errors import AuthorizationError, InvalidFilterFieldError, InvalidSortFieldError


def parse_iso_datetime(val: Any) -> datetime:
    """Parse ISO 8601 string into datetime using standard library."""
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


class ResourceScope(str, Enum):
    """Classification of entity authorization scope."""
    TENANT = "TENANT"      # Scoped directly by org_id (e.g., suppliers, shipments)
    CHILD = "CHILD"        # Scoped hierarchically via parent foreign key (e.g., shipment_events)
    GLOBAL = "GLOBAL"      # Shared global reference catalog (e.g., ports)
    SYSTEM = "SYSTEM"      # System administration root (e.g., organizations)


# Authoritative classification of all 34 database entities from docs/core-api-contract.md
RESOURCE_SCOPES: dict[str, ResourceScope] = {
    # Tenant-owned entities (23 tables)
    "users": ResourceScope.TENANT,
    "suppliers": ResourceScope.TENANT,
    "supplier_sites": ResourceScope.TENANT,
    "factories": ResourceScope.TENANT,
    "warehouses": ResourceScope.TENANT,
    "carriers": ResourceScope.TENANT,
    "products": ResourceScope.TENANT,
    "routes": ResourceScope.TENANT,
    "shipments": ResourceScope.TENANT,
    "inventory": ResourceScope.TENANT,
    "inventory_movements": ResourceScope.TENANT,
    "risks": ResourceScope.TENANT,
    "risk_assessments": ResourceScope.TENANT,
    "incidents": ResourceScope.TENANT,
    "twin_nodes": ResourceScope.TENANT,
    "twin_edges": ResourceScope.TENANT,
    "scenarios": ResourceScope.TENANT,
    "optimization_runs": ResourceScope.TENANT,
    "recommendations": ResourceScope.TENANT,
    "actions": ResourceScope.TENANT,
    "audit_logs": ResourceScope.TENANT,
    "notifications": ResourceScope.TENANT,
    "documents": ResourceScope.TENANT,

    # Hierarchically scoped child entities (8 tables)
    "shipment_events": ResourceScope.CHILD,
    "risk_factors": ResourceScope.CHILD,
    "simulations": ResourceScope.CHILD,
    "approvals": ResourceScope.CHILD,
    "verification_results": ResourceScope.CHILD,
    "agent_runs": ResourceScope.TENANT,
    "agent_tasks": ResourceScope.CHILD,
    "agent_tool_calls": ResourceScope.CHILD,
    "document_chunks": ResourceScope.CHILD,

    # Global reference catalog (1 table)
    "ports": ResourceScope.GLOBAL,

    # System Root (1 table)
    "organizations": ResourceScope.SYSTEM,
}


def get_resource_scope(model: Any) -> ResourceScope:
    """Determine the ResourceScope classification for a given SQLAlchemy model."""
    table_name = getattr(model, "__tablename__", None)
    if table_name and table_name in RESOURCE_SCOPES:
        return RESOURCE_SCOPES[table_name]
    # Default: if model has org_id column, it is TENANT scoped; otherwise GLOBAL
    if hasattr(model, "org_id"):
        return ResourceScope.TENANT
    return ResourceScope.GLOBAL


def apply_tenant_isolation(
    stmt: Select,
    model: Any,
    org_id: Optional[str],
) -> Select:
    """Enforce strict tenant boundary on query statement.

    Rules:
    - Global resources (e.g., ports) are NEVER filtered by org_id.
    - Tenant-scoped resources MUST have a valid org_id context.
    """
    scope = get_resource_scope(model)

    # Global reference data must never be filtered by organization
    if scope == ResourceScope.GLOBAL:
        return stmt

    # Tenant-scoped resources must filter by org_id
    if scope == ResourceScope.TENANT or hasattr(model, "org_id"):
        if not org_id:
            raise AuthorizationError(
                message="Tenant organization context is required to access this resource",
                code="ORGANIZATION_CONTEXT_REQUIRED",
            )
        col = getattr(model, "org_id")
        return stmt.where(col == org_id)

    return stmt


def escape_like_wildcards(term: str) -> str:
    """Escape special SQL LIKE/ILIKE wildcards (%, _, \\) in client search queries."""
    return re.sub(r"([%_\\])", r"\\\1", term)


def apply_search(
    stmt: Select,
    model: Any,
    search_term: Optional[str],
    search_columns: Optional[list[str]],
) -> Select:
    """Apply safe case-insensitive substring search across approved text columns."""
    if not search_term or not search_columns:
        return stmt

    escaped = escape_like_wildcards(search_term.strip())
    if not escaped:
        return stmt

    conditions = []
    for col_name in search_columns:
        if hasattr(model, col_name):
            col = getattr(model, col_name)
            conditions.append(col.ilike(f"%{escaped}%", escape="\\"))

    if conditions:
        return stmt.where(or_(*conditions))
    return stmt


def apply_filters(
    stmt: Select,
    model: Any,
    filters: Optional[dict[str, Any]],
    allowlist: Optional[dict[str, Any]] = None,
) -> Select:
    """Apply safe filtering against an explicit allowlist of model columns.

    Supports:
    - Exact matching: 'status': 'IN_TRANSIT'
    - Date lower bounds: 'created_at_after': '2026-09-01T00:00:00Z' (col >= date)
    - Date upper bounds: 'created_at_before': '2026-09-30T23:59:59Z' (col <= date)
    - Rejects unapproved filter fields when allowlist is provided.
    """
    if not filters:
        return stmt

    for key, val in filters.items():
        if val is None:
            continue

        # If allowlist is enforced, check key
        if allowlist is not None and key not in allowlist:
            raise InvalidFilterFieldError(key, list(allowlist.keys()))

        # Determine column
        if allowlist and key in allowlist:
            col = allowlist[key]
        elif hasattr(model, key):
            col = getattr(model, key)
        else:
            # Check for _after or _before suffix matching a real column
            base_key = None
            if key.endswith("_after"):
                base_key = key[:-6]
            elif key.endswith("_before"):
                base_key = key[:-7]

            if base_key and hasattr(model, base_key):
                col = getattr(model, base_key)
            else:
                continue

        # Handle date ranges
        if key.endswith("_after"):
            date_val = val if isinstance(val, datetime) else parse_iso_datetime(str(val))
            stmt = stmt.where(col >= date_val)
        elif key.endswith("_before"):
            date_val = val if isinstance(val, datetime) else parse_iso_datetime(str(val))
            stmt = stmt.where(col <= date_val)
        else:
            stmt = stmt.where(col == val)

    return stmt


def apply_sorting(
    stmt: Select,
    model: Any,
    sort_param: Optional[str],
    allowlist: Optional[dict[str, Any]] = None,
    default_field: str = "created_at",
    default_desc: bool = True,
) -> Select:
    """Apply safe order_by clause using explicit allowlist.

    Syntax:
    - 'name' -> ascending
    - '+name' -> ascending
    - '-name' -> descending
    """
    if sort_param:
        descending = sort_param.startswith("-")
        field_name = sort_param.lstrip("+-").strip()

        if allowlist is not None:
            if field_name not in allowlist:
                raise InvalidSortFieldError(field_name, list(allowlist.keys()))
            col = allowlist[field_name]
        else:
            if not hasattr(model, field_name):
                raise InvalidSortFieldError(field_name, [])
            col = getattr(model, field_name)

        return stmt.order_by(col.desc() if descending else col.asc())

    # Apply default sorting if column exists on model
    if allowlist and default_field in allowlist:
        col = allowlist[default_field]
        return stmt.order_by(col.desc() if default_desc else col.asc())
    elif hasattr(model, default_field):
        col = getattr(model, default_field)
        return stmt.order_by(col.desc() if default_desc else col.asc())

    return stmt


def apply_pagination(
    stmt: Select,
    page: int = 1,
    limit: int = 20,
) -> Select:
    """Slice query with 1-indexed page and limit bounded to 100."""
    safe_page = max(1, page)
    safe_limit = min(max(1, limit), 100)
    offset = (safe_page - 1) * safe_limit
    return stmt.offset(offset).limit(safe_limit)
