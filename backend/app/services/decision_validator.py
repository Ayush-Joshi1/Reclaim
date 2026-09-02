"""Final deterministic policy validation for LLM recovery recommendations."""

from datetime import UTC, datetime

from app.schemas.recovery_decision import (
    RecoveryContext,
    RecoveryDecision,
    ValidatedRecoveryDecision,
)


class DecisionValidator:
    """Prevent an LLM recommendation from weakening deterministic policy."""

    def validate(
        self, candidate: RecoveryDecision, context: RecoveryContext
    ) -> ValidatedRecoveryDecision:
        """Return a constrained decision, forcing STOP when a hard rule applies."""
        hard_stop_reasons = self._hard_stop_reasons(context)
        if hard_stop_reasons:
            return self._forced_stop(context, hard_stop_reasons)

        canonical_action = self._canonical_action(context)
        notes: list[str] = ["Deterministic recovery policy selected the final action."]
        if candidate.action != canonical_action:
            notes.append(
                f"LLM action {candidate.action} was replaced by the canonical policy action {canonical_action}."
            )
        requires_approval = context.risk.requires_approval
        if candidate.requires_approval != requires_approval:
            notes.append("Approval requirement was reset to the deterministic policy result.")

        if candidate.priority != context.risk.urgency:
            notes.append("Priority was reset to the deterministic risk-engine urgency.")

        return ValidatedRecoveryDecision(
            **candidate.model_copy(
                update={
                    "action": canonical_action,
                    "requires_approval": requires_approval,
                    "priority": context.risk.urgency,
                    "policy_constraints": self._policy_constraints(context),
                }
            ).model_dump(),
            payment_id=context.payment.payment_id,
            risk_score=context.risk.risk_score,
            recovery_eligible=context.risk.recovery_eligible,
            validation_status="OVERRIDDEN" if len(notes) > 1 else "VALID",
            validation_notes=notes,
            decided_at=datetime.now(UTC),
        )

    def safe_failure(self, context: RecoveryContext, reason: str) -> ValidatedRecoveryDecision:
        """Return a deterministic action when the LLM cannot provide a decision."""
        if self._hard_stop_reasons(context):
            return self._forced_stop(context, ["LLM output was unusable; deterministic policy requires STOP."])

        return ValidatedRecoveryDecision(
            action=self._canonical_action(context),
            diagnosis="AI recovery recommendation could not be validated.",
            reasoning="The deterministic recovery policy selected the action because the AI result was unavailable or malformed.",
            confidence=0.0,
            requires_approval=context.risk.requires_approval,
            priority=context.risk.urgency,
            policy_constraints=self._policy_constraints(context),
            expected_outcome="Merchant review is required before any future recovery execution.",
            payment_id=context.payment.payment_id,
            risk_score=context.risk.risk_score,
            recovery_eligible=context.risk.recovery_eligible,
            validation_status="FAILED",
            validation_notes=[f"LLM decision failed validation: {reason}"],
            decided_at=datetime.now(UTC),
        )

    @staticmethod
    def _canonical_action(context: RecoveryContext) -> str:
        """Apply the same deterministic action order used by the fallback client."""
        if not context.risk.recovery_eligible:
            return "STOP"
        if context.risk.requires_approval:
            return "ESCALATE"
        if context.payment.failure_reason in {"network_error", "timeout", "bank_error"}:
            return "RETRY"
        if context.risk.risk_score >= 70:
            return "PAYMENT_LINK"
        return "REMINDER"

    @staticmethod
    def _hard_stop_reasons(context: RecoveryContext) -> list[str]:
        reasons: list[str] = []
        status = context.payment.status.lower()
        if not context.risk.recovery_eligible:
            reasons.append("Deterministic risk engine marked recovery ineligible.")
        if status == "successful":
            reasons.append("Payment is already successful.")
        if status in {"closed", "stopped", "permanently_closed"}:
            reasons.append("Payment is closed or stopped.")
        if context.payment.time_since_failure_hours > context.merchant_policy.recovery_window_hours:
            reasons.append("Recovery window has expired.")
        if (
            context.recovery_history.recovery_attempt_count
            >= context.merchant_policy.max_recovery_attempts
        ):
            reasons.append("Maximum recovery attempts have been reached.")
        return reasons

    @staticmethod
    def _policy_constraints(context: RecoveryContext) -> list[str]:
        constraints = list(context.risk.eligibility_reasons)
        policy = context.merchant_policy
        constraints.extend(
            [
                f"Maximum recovery attempts: {policy.max_recovery_attempts}.",
                f"Recovery window: {policy.recovery_window_hours} hours.",
                f"Automatic action amount limit: {policy.auto_action_amount_limit}.",
                f"High-value threshold: {policy.high_value_threshold}.",
                f"Maximum customer notifications: {policy.max_customer_notifications}.",
            ]
        )
        if context.risk.requires_approval:
            constraints.append("Merchant approval is required; this is not auto-executable.")
        return constraints

    def _forced_stop(
        self, context: RecoveryContext, reasons: list[str]
    ) -> ValidatedRecoveryDecision:
        return ValidatedRecoveryDecision(
            action="STOP",
            diagnosis="Deterministic policy does not permit recovery.",
            reasoning="The final validator enforced a policy stop after evaluating immutable payment and policy facts.",
            confidence=1.0,
            requires_approval=context.risk.requires_approval,
            priority=context.risk.urgency,
            policy_constraints=self._policy_constraints(context),
            expected_outcome="No recovery action should be sent for this payment.",
            payment_id=context.payment.payment_id,
            risk_score=context.risk.risk_score,
            recovery_eligible=False,
            validation_status="OVERRIDDEN",
            validation_notes=reasons,
            decided_at=datetime.now(UTC),
        )
