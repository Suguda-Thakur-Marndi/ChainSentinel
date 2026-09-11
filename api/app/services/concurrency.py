"""Concurrency utilities for row locking, atomic arithmetic, and idempotent state transitions."""
from typing import Any, Optional, Type, TypeVar
from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session
from app.core.errors import ConflictError, LifecycleStateError
from app.repositories.query_utils import apply_tenant_isolation

ModelType = TypeVar("ModelType")


def get_with_for_update(
    session: Session,
    model: Type[ModelType],
    id: str,
    org_id: Optional[str] = None,
) -> Optional[ModelType]:
    """Retrieve an entity with an exclusive database row lock (SELECT ... FOR UPDATE).

    Prevents concurrent modifications during critical state transitions (e.g. recommendation sign-offs).
    """
    stmt: Select = select(model).where(getattr(model, "id") == id).with_for_update()
    stmt = apply_tenant_isolation(stmt, model, org_id)
    return session.scalars(stmt).first()


def atomic_adjust_numeric(
    session: Session,
    model: Type[ModelType],
    id: str,
    field_name: str,
    delta: float,
    org_id: Optional[str] = None,
    allow_negative: bool = False,
) -> int:
    """Execute an atomic in-database numeric adjustment without read-modify-write race conditions.

    Example: stock reconciliation `quantity_on_hand = quantity_on_hand + delta`.
    Returns the number of affected rows (0 or 1).
    """
    if not hasattr(model, field_name):
        raise AttributeError(f"Model {model.__name__} has no column {field_name}")

    col = getattr(model, field_name)
    stmt = update(model).where(getattr(model, "id") == id)

    if org_id and hasattr(model, "org_id"):
        stmt = stmt.where(getattr(model, "org_id") == org_id)

    if not allow_negative:
        stmt = stmt.where((col + delta) >= 0)

    stmt = stmt.values({col: col + delta})
    result = session.execute(stmt)
    return result.rowcount


def validate_state_transition(
    current_status: str,
    target_status: str,
    allowed_transitions: dict[str, list[str]],
) -> None:
    """Validate that a requested status transition adheres to the domain state machine.

    Raises:
        LifecycleStateError: If the transition is illegal or invalid.
    """
    normalized_curr = current_status.strip().upper()
    normalized_target = target_status.strip().upper()

    valid_targets = [s.upper() for s in allowed_transitions.get(normalized_curr, [])]
    if normalized_target not in valid_targets:
        raise LifecycleStateError(
            message=(
                f"Illegal state transition from '{current_status}' to '{target_status}'. "
                f"Allowed transitions: {', '.join(valid_targets) if valid_targets else 'None (Terminal state)'}"
            ),
            code="INVALID_STATE_TRANSITION",
            details={
                "current_status": current_status,
                "target_status": target_status,
                "allowed_transitions": valid_targets,
            },
        )
