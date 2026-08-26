"""Database engine, session dependency, and local table initialization."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


def normalize_database_url(database_url: str) -> str:
    """Use psycopg 3 for conventional PostgreSQL URLs."""
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


engine: Engine = create_engine(
    normalize_database_url(settings.database_url),
    pool_pre_ping=True,
    connect_args={"connect_timeout": 5},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Provide a request-scoped database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_tables() -> None:
    """Create the current model tables for local development."""
    from app import models  # noqa: F401  Ensure model metadata is registered.

    Base.metadata.create_all(bind=engine)
