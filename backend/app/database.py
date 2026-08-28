"""Database engine, session dependency, and local table initialization."""

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
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
    """Create current tables and apply safe local schema additions."""
    from app import models  # noqa: F401  Ensure model metadata is registered.

    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    if "recovery_attempts" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("recovery_attempts")}
    with engine.begin() as connection:
        if "event_id" not in columns:
            connection.execute(text("ALTER TABLE recovery_attempts ADD COLUMN event_id VARCHAR(255)"))
        if "attempt_number" not in columns:
            connection.execute(text("ALTER TABLE recovery_attempts ADD COLUMN attempt_number INTEGER"))
        additions = {
            "execution_mode": "VARCHAR(20) NOT NULL DEFAULT 'dry_run'",
            "provider_called": "BOOLEAN NOT NULL DEFAULT FALSE",
            "execution_succeeded": "BOOLEAN NOT NULL DEFAULT TRUE",
            "notification_generated": "BOOLEAN NOT NULL DEFAULT FALSE",
            "executed_at": "TIMESTAMP WITH TIME ZONE",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE recovery_attempts ADD COLUMN {name} {definition}"))
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_recovery_attempts_event_id "
                "ON recovery_attempts (event_id) WHERE event_id IS NOT NULL"
            )
        )
