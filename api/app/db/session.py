"""Database connection and session configuration for PostgreSQL."""
from collections.abc import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from app.core.config import settings

import logging
from app.core.logging import get_logger

logger = get_logger("db")

engine = None
SessionLocal = None

def ensure_tables_exist(bind_engine=None):
    global engine
    target = bind_engine or engine
    if target is not None:
        import app.models as models
        models.Base.metadata.create_all(bind=target)

def init_db_engine():
    global engine, SessionLocal
    if not settings.DATABASE_URL:
        return

    url = settings.DATABASE_URL
    is_sqlite = url.startswith("sqlite")

    if is_sqlite:
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
        )
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        logger.info("Initialized local SQLite database.")
    else:
        try:
            temp_engine = create_engine(
                url,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
                connect_args={"connect_timeout": 3},
            )
            # In dev mode, test reachability quickly
            if settings.APP_ENV == "development":
                with temp_engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            engine = temp_engine
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        except Exception as exc:
            if settings.APP_ENV == "development":
                logger.warning(
                    f"Remote database unreachable ({type(exc).__name__}). Falling back to local SQLite for development."
                )
                local_url = "sqlite:///./riskwise_local.db"
                engine = create_engine(
                    local_url,
                    connect_args={"check_same_thread": False},
                )
                SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            else:
                raise

init_db_engine()


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
