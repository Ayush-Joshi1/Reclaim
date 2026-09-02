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
    recovery_state: Mapped[str | None] = mapped_column(String(50), index=True, default="detected")
    state_reason: Mapped[str | None] = mapped_column(String(500))
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_payment_link_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_payment_link_url: Mapped[str | None] = mapped_column(String(2048))
    provider_reference_id: Mapped[str | None] = mapped_column(String(255), index=True)
    risk_score: Mapped[int | None] = mapped_column(Integer)
    risk_level: Mapped[str | None] = mapped_column(String(20))
    eligibility_result: Mapped[bool | None] = mapped_column()
    eligibility_reason: Mapped[str | None] = mapped_column(String(1000))
    decision_confidence: Mapped[float | None] = mapped_column()
    approval_required: Mapped[bool | None] = mapped_column()
    validation_status: Mapped[str | None] = mapped_column(String(20))
    policy_override_reason: Mapped[str | None] = mapped_column(String(1000))
    decision_diagnosis: Mapped[str | None] = mapped_column(String(400))
    decision_reasoning: Mapped[str | None] = mapped_column(String(800))
    policy_constraints: Mapped[str | None] = mapped_column(String(4000))
    reconciliation_status: Mapped[str | None] = mapped_column(String(50))
    reconciliation_previous_state: Mapped[str | None] = mapped_column(String(50))
    reconciliation_provider_state: Mapped[str | None] = mapped_column(String(50))
    reconciliation_resulting_state: Mapped[str | None] = mapped_column(String(50))
    reconciliation_reason: Mapped[str | None] = mapped_column(String(500))
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconciliation_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    follow_up_status: Mapped[str | None] = mapped_column(String(50), index=True)
    follow_up_last_reason: Mapped[str | None] = mapped_column(String(500))
    follow_up_last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    follow_up_next_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    follow_up_claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
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
