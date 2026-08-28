"""Recovery attempt persistence model."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RecoveryAttempt(Base):
    """A recorded recovery action associated with a payment."""

    __tablename__ = "recovery_attempts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    payment_id: Mapped[UUID] = mapped_column(ForeignKey("payments.id"), nullable=False)
    event_id: Mapped[str | None] = mapped_column(String(255), index=True)
    attempt_number: Mapped[int | None] = mapped_column(Integer)
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="dry_run")
    provider_called: Mapped[bool] = mapped_column(nullable=False, default=False)
    execution_succeeded: Mapped[bool] = mapped_column(nullable=False, default=True)
    notification_generated: Mapped[bool] = mapped_column(nullable=False, default=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    payment: Mapped["Payment"] = relationship(back_populates="recovery_attempts")


Index(
    "uq_recovery_attempts_event_id",
    RecoveryAttempt.event_id,
    unique=True,
    postgresql_where=RecoveryAttempt.event_id.is_not(None),
)
