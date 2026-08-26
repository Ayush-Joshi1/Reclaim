"""SQLAlchemy model metadata tests."""

from app.database import Base
from app.models import Customer, Payment, RecoveryAttempt


def test_model_metadata_imports() -> None:
    assert {Customer.__tablename__, Payment.__tablename__, RecoveryAttempt.__tablename__} <= set(
        Base.metadata.tables
    )
    assert "amount" in Payment.__table__.columns
    assert "amount" in RecoveryAttempt.__table__.columns
