from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Canonical SQLAlchemy metadata root for Alembic-managed tables."""

