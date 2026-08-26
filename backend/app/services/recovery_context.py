"""Build LLM-safe recovery context from deterministic risk results."""

from app.schemas.recovery_decision import RecoveryContext, RecoveryRiskContext
from app.schemas.revenue_risk import (
    CustomerRiskContext,
    MerchantPolicy,
    PaymentRiskInput,
    RecoveryHistory,
    RevenueRiskResult,
)


def build_recovery_context(
    payment: PaymentRiskInput,
    customer: CustomerRiskContext,
    recovery_history: RecoveryHistory,
    risk_result: RevenueRiskResult,
    merchant_policy: MerchantPolicy,
) -> RecoveryContext:
    """Package immutable evidence for an LLM recovery recommendation."""
    return RecoveryContext(
        payment=payment,
        customer=customer,
        recovery_history=recovery_history,
        risk=RecoveryRiskContext(
            risk_score=risk_result.risk_score,
            revenue_at_risk=risk_result.revenue_at_risk,
            recovery_eligible=risk_result.recovery_eligible,
            auto_action_eligible=risk_result.auto_action_eligible,
            requires_approval=risk_result.requires_merchant_approval,
            urgency=risk_result.urgency,
            risk_factors=risk_result.risk_factors,
            eligibility_reasons=risk_result.eligibility_reasons,
        ),
        merchant_policy=merchant_policy,
    )
