"""Core database module exporting session and engine primitives for consistency."""
from app.db.session import (
    engine,
    SessionLocal,
    get_db,
    init_db_engine,
    dispose_db_engine,
    check_db_connection,
    ensure_tables_exist,
)

__all__ = [
    "engine",
    "SessionLocal",
    "get_db",
    "init_db_engine",
    "dispose_db_engine",
    "check_db_connection",
    "ensure_tables_exist",
]
