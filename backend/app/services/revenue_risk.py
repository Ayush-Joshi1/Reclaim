"""Transparent, deterministic payment-recovery risk evaluation."""

from app.schemas.revenue_risk import (
    CustomerRiskContext,
    MerchantPolicy,
    PaymentRiskInput,
    RecoveryHistory,
    RevenueRiskResult,
)


class RevenueRiskEngine:
    """Evaluate recovery likelihood and policy eligibility without machine learning."""

    def evaluate(
        self,
        payment: PaymentRiskInput,
        customer: CustomerRiskContext,
        recovery_history: RecoveryHistory,
        policy: MerchantPolicy,
    ) -> RevenueRiskResult:
        """Apply named scoring and eligibility rules to one payment."""
        score = 50
        factors: list[str] = ["Baseline recovery score: 50."]

        if customer.previous_successful_payments >= 5:
            score += 15
            factors.append("Strong successful payment history: +15.")
        elif customer.previous_successful_payments >= 1:
            score += 8
            factors.append("Previously successful customer: +8.")

        if customer.previous_failed_payments == 0:
            score += 10
            factors.append("First recorded customer failure: +10.")
        elif customer.previous_failed_payments >= 5:
            score -= 20
            factors.append("Repeated customer failures (5 or more): -20.")
        elif customer.previous_failed_payments >= 2:
            score -= 10
            factors.append("Multiple prior customer failures: -10.")

        if payment.time_since_failure_hours <= 6:
            score += 12
            factors.append("Recent failure within 6 hours: +12.")
        elif payment.time_since_failure_hours <= 24:
            score += 7
            factors.append("Recent failure within 24 hours: +7.")
        else:
            score -= 10
            factors.append("Failure is older than 24 hours: -10.")

        if recovery_history.recovery_attempt_count == 0:
            score += 5
            factors.append("No prior recovery attempts for this payment: +5.")
        else:
            score -= 8
            factors.append("Previous recovery attempt exists for this payment: -8.")

        if customer.recent_payment_frequency >= 3:
            score += 5
            factors.append("Active recent payment frequency: +5.")

        if payment.amount >= policy.high_value_threshold:
            score -= 8
            factors.append("High-value payment requires additional caution: -8.")

        recovery_eligible, should_stop, eligibility_reasons = self._evaluate_eligibility(
            payment, recovery_history, policy
        )
        requires_merchant_approval = (
            recovery_eligible and payment.amount > policy.auto_action_amount_limit
        )
        auto_action_eligible = recovery_eligible and not requires_merchant_approval

        if requires_merchant_approval:
            eligibility_reasons.append(
                "Amount exceeds the automatic action limit; merchant approval is required."
            )
        elif recovery_eligible:
            eligibility_reasons.append("Amount is within the automatic action limit.")

        return RevenueRiskResult(
            risk_score=max(0, min(100, score)),
            revenue_at_risk=0 if payment.status.lower() == "successful" else payment.amount,
            recovery_eligible=recovery_eligible,
            auto_action_eligible=auto_action_eligible,
            requires_merchant_approval=requires_merchant_approval,
            should_stop=should_stop,
            urgency=self._urgency(payment.time_since_failure_hours),
            risk_factors=factors,
            eligibility_reasons=eligibility_reasons,
        )

    @staticmethod
    def _urgency(hours_since_failure: int) -> str:
        if hours_since_failure <= 6:
            return "HIGH"
        if hours_since_failure <= 24:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _evaluate_eligibility(
        payment: PaymentRiskInput,
        recovery_history: RecoveryHistory,
        policy: MerchantPolicy,
    ) -> tuple[bool, bool, list[str]]:
        """Apply hard stop rules before any action can be considered."""
        status = payment.status.lower()
        reasons: list[str] = []

        if status == "successful":
            reasons.append("Payment is already successful; recovery must stop.")
        elif status in {"closed", "stopped", "permanently_closed"}:
            reasons.append("Payment is permanently closed or stopped; recovery must stop.")
        elif payment.time_since_failure_hours > policy.recovery_window_hours:
            reasons.append("Recovery window has expired; recovery must stop.")
        elif recovery_history.recovery_attempt_count >= policy.max_recovery_attempts:
            reasons.append("Maximum recovery attempts have been reached; recovery must stop.")

        if reasons:
            return False, True, reasons

        return True, False, ["Payment is within the recovery window and below attempt limits."]
