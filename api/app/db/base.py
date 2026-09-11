"""SQLAlchemy Declarative Base for RiskWise 2.0."""
import uuid
from sqlalchemy.orm import DeclarativeBase


def generate_uuid() -> str:
    """Generate a standard string UUID4 for primary keys."""
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models in RiskWise 2.0."""
    pass

