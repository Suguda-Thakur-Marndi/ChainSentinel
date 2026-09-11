"""Database connection and session configuration for PostgreSQL."""
from collections.abc import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from app.core.config import settings

engine = None
SessionLocal = None

if settings.DATABASE_URL:
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        connect_args={"connect_timeout": 5},
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for database sessions."""
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is not configured.")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection(timeout: int = 5) -> tuple[bool, str]:
    """Execute SELECT 1 to verify PostgreSQL connectivity.

    Returns:
        tuple[bool, str]: (is_connected, safe_status_message)
    Never exposes passwords, connection strings, or sensitive credentials.
    """
    if engine is None:
        return False, "DATABASE_URL is not configured"

    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).scalar()
            if result == 1:
                return True, "Database connection successful"
            return False, "Unexpected database response"
    except Exception as e:
        error_type = type(e).__name__
        return False, f"Database connection unavailable ({error_type})"
