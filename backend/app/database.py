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

    # Ensure the additive schema updates exist before the app begins serving requests.
    # This keeps the development database compatible with the stateful recovery model.

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
            "recovery_state": "VARCHAR(50)",
            "state_reason": "VARCHAR(500)",
            "provider_payment_id": "VARCHAR(255)",
            "provider_payment_link_id": "VARCHAR(255)",
            "provider_payment_link_url": "VARCHAR(2048)",
            "provider_reference_id": "VARCHAR(255)",
            "risk_score": "INTEGER",
            "risk_level": "VARCHAR(20)",
            "eligibility_result": "BOOLEAN",
            "eligibility_reason": "VARCHAR(1000)",
            "decision_confidence": "DOUBLE PRECISION",
            "approval_required": "BOOLEAN",
            "validation_status": "VARCHAR(20)",
            "policy_override_reason": "VARCHAR(1000)",
            "decision_diagnosis": "VARCHAR(400)",
            "decision_reasoning": "VARCHAR(800)",
            "policy_constraints": "VARCHAR(4000)",
            "reconciliation_status": "VARCHAR(50)",
            "reconciliation_previous_state": "VARCHAR(50)",
            "reconciliation_provider_state": "VARCHAR(50)",
            "reconciliation_resulting_state": "VARCHAR(50)",
            "reconciliation_reason": "VARCHAR(500)",
            "reconciled_at": "TIMESTAMP WITH TIME ZONE",
            "reconciliation_attempts": "INTEGER NOT NULL DEFAULT 0",
            "follow_up_status": "VARCHAR(50)",
            "follow_up_last_reason": "VARCHAR(500)",
            "follow_up_last_run_at": "TIMESTAMP WITH TIME ZONE",
            "follow_up_next_at": "TIMESTAMP WITH TIME ZONE",
            "follow_up_claimed_until": "TIMESTAMP WITH TIME ZONE",
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

    if "payments" not in inspector.get_table_names():
        return

    payment_columns = {column["name"] for column in inspector.get_columns("payments")}
    with engine.begin() as connection:
        payment_additions = {
            "recovery_state": "VARCHAR(50)",
            "state_updated_at": "TIMESTAMP WITH TIME ZONE",
        }
        for name, definition in payment_additions.items():
            if name not in payment_columns:
                connection.execute(text(f"ALTER TABLE payments ADD COLUMN {name} {definition}"))


create_tables()
