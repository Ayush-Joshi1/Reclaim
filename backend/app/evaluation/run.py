"""Deterministic synthetic evaluation for Day 7 business and agent metrics."""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.schemas.revenue_risk import CustomerRiskContext, MerchantPolicy, PaymentRiskInput, RecoveryHistory
from app.services.recovery_context import build_recovery_context
from app.services.recovery_decision import RecoveryDecisionService
from app.services.revenue_risk import RevenueRiskEngine
from app.services.llm_client import FakeLLMClient

DEFAULT_SAMPLE_SIZE = 500
DEFAULT_SEED = 42


@dataclass(frozen=True)
class BusinessMetrics:
    total_revenue_at_risk: int
    total_recovered: int
    recovery_rate: float
    average_recovered_amount: float
    successful_recovery_count: int


@dataclass(frozen=True)
class AgentMetrics:
    intervention_count: int
    successful_recovery_count: int
    escalation_count: int
    stop_count: int
    intervention_rate: float
    success_rate: float
    escalation_rate: float
    stop_rate: float


@dataclass(frozen=True)
class EvaluationResult:
    sample_size: int
    seed: int
    business_metrics: BusinessMetrics
    agent_metrics: AgentMetrics

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_size": self.sample_size,
            "seed": self.seed,
            "business_metrics": {
                "total_revenue_at_risk": self.business_metrics.total_revenue_at_risk,
                "total_recovered": self.business_metrics.total_recovered,
                "recovery_rate": self.business_metrics.recovery_rate,
                "average_recovered_amount": self.business_metrics.average_recovered_amount,
                "successful_recovery_count": self.business_metrics.successful_recovery_count,
            },
            "agent_metrics": {
                "intervention_count": self.agent_metrics.intervention_count,
                "successful_recovery_count": self.agent_metrics.successful_recovery_count,
                "escalation_count": self.agent_metrics.escalation_count,
                "stop_count": self.agent_metrics.stop_count,
                "intervention_rate": self.agent_metrics.intervention_rate,
                "success_rate": self.agent_metrics.success_rate,
                "escalation_rate": self.agent_metrics.escalation_rate,
                "stop_rate": self.agent_metrics.stop_rate,
            },
        }


def generate_evaluation_dataset(*, seed: int = DEFAULT_SEED, count: int = DEFAULT_SAMPLE_SIZE) -> list[dict[str, Any]]:
    """Generate a deterministic synthetic set of failed-payment evaluation records."""
    if count < 1:
        raise ValueError("count must be at least 1")

    rng = random.Random(seed)
    scenario_names = (
        "high_recovery_likelihood",
        "medium_recovery_likelihood",
        "low_recovery_likelihood",
        "high_value_requires_approval",
        "repeated_failure_stop",
        "strong_success_history",
        "repeated_customer_failures",
        "previous_recovery_attempts",
        "recent_failure",
        "expired_recovery_window",
    )
    weights = (18, 16, 8, 6, 6, 12, 10, 8, 10, 6)
    entries: list[dict[str, Any]] = []

    for index in range(count):
        scenario_type = rng.choices(scenario_names, weights=weights, k=1)[0]
        entry = _build_scenario(index=index, rng=rng, scenario_type=scenario_type)
        entries.append(entry)

    return entries


def _build_scenario(*, index: int, rng: random.Random, scenario_type: str) -> dict[str, Any]:
    amount = rng.choice((49_900, 99_900, 199_900, 499_900, 799_900, 1_299_900))
    successful = rng.randint(1, 5)
    failed = rng.randint(0, 2)
    recovery_attempts = 0
    hours = rng.randint(2, 30)

    if scenario_type == "high_recovery_likelihood":
        successful, failed, recovery_attempts, hours = rng.randint(6, 12), 0, 0, rng.randint(1, 6)
    elif scenario_type == "medium_recovery_likelihood":
        successful, failed, recovery_attempts, hours = rng.randint(1, 4), 1, 0, rng.randint(8, 24)
    elif scenario_type == "low_recovery_likelihood":
        successful, failed, recovery_attempts, hours = 0, rng.randint(4, 7), 1, rng.randint(25, 47)
    elif scenario_type == "high_value_requires_approval":
        amount, successful, failed, hours = rng.choice((2_500_000, 3_999_900, 5_000_000)), 8, 0, 3
    elif scenario_type == "repeated_failure_stop":
        successful, failed, recovery_attempts, hours = 1, 7, 2, 5
    elif scenario_type == "strong_success_history":
        successful, failed, recovery_attempts, hours = rng.randint(10, 20), 1, 0, 12
    elif scenario_type == "repeated_customer_failures":
        successful, failed, recovery_attempts, hours = 1, rng.randint(5, 10), 0, 14
    elif scenario_type == "previous_recovery_attempts":
        successful, failed, recovery_attempts, hours = 3, 2, 1, 10
    elif scenario_type == "recent_failure":
        successful, failed, recovery_attempts, hours = 2, 0, 0, rng.randint(0, 3)
    elif scenario_type == "expired_recovery_window":
        successful, failed, recovery_attempts, hours = 2, 1, 0, rng.randint(49, 120)

    customer_id = str(uuid5(NAMESPACE_URL, f"reclaim-customer-{index}"))
    payment_id = str(uuid5(NAMESPACE_URL, f"reclaim-payment-{index}"))
    failure_reason = rng.choice((
        "card_declined",
        "insufficient_funds",
        "authentication_failed",
        "network_error",
        "bank_error",
        "timeout",
        "unknown",
    ))
    failed_at = datetime(2026, 8, 25, 12, tzinfo=UTC) - timedelta(hours=hours)

    return {
        "scenario_type": scenario_type,
        "customer_id": customer_id,
        "customer_age_days": rng.randint(30, 1_500),
        "previous_successful_payments": successful,
        "previous_failed_payments": failed,
        "previous_recovery_attempts": recovery_attempts,
        "customer_lifetime_value": max(amount, successful * rng.randint(80_000, 300_000)),
        "average_previous_payment": rng.choice((49_900, 99_900, 199_900, 499_900)),
        "recent_payment_frequency": rng.randint(0, 6),
        "payment_id": payment_id,
        "amount": amount,
        "currency": "INR",
        "payment_method": rng.choices(("upi", "card", "netbanking", "wallet"), weights=(45, 35, 12, 8), k=1)[0],
        "status": "failed",
        "failure_reason": failure_reason,
        "failed_at": failed_at.isoformat(),
        "time_since_failure_hours": hours,
        "recovery_attempt_count": recovery_attempts,
    }


def calculate_metrics(records: list[dict[str, Any]], *, sample_size: int) -> EvaluationResult:
    """Compute business and agent metrics from a list of evaluated transaction records."""
    total_revenue_at_risk = sum(int(record["revenue_at_risk"]) for record in records)
    total_recovered = sum(int(record["recovered_amount"]) for record in records)
    successful_recovery_count = sum(1 for record in records if bool(record.get("successful_recovery")))
    recovery_rate = (total_recovered / total_revenue_at_risk * 100.0) if total_revenue_at_risk else 0.0
    average_recovered_amount = (total_recovered / successful_recovery_count) if successful_recovery_count else 0.0

    intervention_count = sum(1 for record in records if bool(record.get("intervention")))
    escalation_count = sum(1 for record in records if bool(record.get("escalation")))
    stop_count = sum(1 for record in records if bool(record.get("stop")))
    success_count = sum(1 for record in records if bool(record.get("successful_recovery")))
    intervention_rate = (intervention_count / sample_size * 100.0) if sample_size else 0.0
    success_rate = (success_count / intervention_count * 100.0) if intervention_count else 0.0
    escalation_rate = (escalation_count / sample_size * 100.0) if sample_size else 0.0
    stop_rate = (stop_count / sample_size * 100.0) if sample_size else 0.0

    return EvaluationResult(
        sample_size=sample_size,
        seed=records[0].get("seed", DEFAULT_SEED) if records else DEFAULT_SEED,
        business_metrics=BusinessMetrics(
            total_revenue_at_risk=total_revenue_at_risk,
            total_recovered=total_recovered,
            recovery_rate=round(recovery_rate, 2),
            average_recovered_amount=round(average_recovered_amount, 2),
            successful_recovery_count=successful_recovery_count,
        ),
        agent_metrics=AgentMetrics(
            intervention_count=intervention_count,
            successful_recovery_count=success_count,
            escalation_count=escalation_count,
            stop_count=stop_count,
            intervention_rate=round(intervention_rate, 2),
            success_rate=round(success_rate, 2),
            escalation_rate=round(escalation_rate, 2),
            stop_rate=round(stop_rate, 2),
        ),
    )


def evaluate_transactions(*, seed: int = DEFAULT_SEED, sample_size: int = DEFAULT_SAMPLE_SIZE) -> EvaluationResult:
    """Apply the real risk and decision logic to a deterministic synthetic dataset."""
    policy = MerchantPolicy()
    dataset = generate_evaluation_dataset(seed=seed, count=sample_size)
    evaluated: list[dict[str, Any]] = []

    for index, record in enumerate(dataset):
        payment = PaymentRiskInput(
            payment_id=record["payment_id"],
            amount=int(record["amount"]),
            currency=str(record["currency"]),
            payment_method=str(record["payment_method"]),
            status=str(record["status"]),
            failure_reason=str(record["failure_reason"]),
            failed_at=datetime.fromisoformat(record["failed_at"]),
            time_since_failure_hours=int(record["time_since_failure_hours"]),
        )
        customer = CustomerRiskContext(
            customer_id=str(record["customer_id"]),
            customer_age_days=int(record["customer_age_days"]),
            previous_successful_payments=int(record["previous_successful_payments"]),
            previous_failed_payments=int(record["previous_failed_payments"]),
            previous_recovery_attempts=int(record["previous_recovery_attempts"]),
            customer_lifetime_value=int(record["customer_lifetime_value"]),
            average_previous_payment=int(record["average_previous_payment"]),
            recent_payment_frequency=int(record["recent_payment_frequency"]),
        )
        recovery_history = RecoveryHistory(recovery_attempt_count=int(record["recovery_attempt_count"]))
        risk = RevenueRiskEngine().evaluate(payment, customer, recovery_history, policy)
        context = build_recovery_context(payment, customer, recovery_history, risk, policy)
        decision = RecoveryDecisionService(FakeLLMClient()).decide(context)

        action = decision.action
        escalation = action == "ESCALATE"
        stop = action == "STOP"
        intervention = action in {"RETRY", "PAYMENT_LINK", "REMINDER"} and risk.recovery_eligible and not risk.requires_merchant_approval
        successful_recovery = bool(intervention and action in {"RETRY", "PAYMENT_LINK"} and risk.risk_score >= 60)
        recovered_amount = int(payment.amount) if successful_recovery else 0

        evaluated.append(
            {
                "seed": seed,
                "payment_id": payment.payment_id,
                "revenue_at_risk": risk.revenue_at_risk,
                "recovered_amount": recovered_amount,
                "intervention": intervention,
                "successful_recovery": successful_recovery,
                "escalation": escalation,
                "stop": stop,
                "action": action,
                "risk_score": risk.risk_score,
                "requires_approval": risk.requires_merchant_approval,
                "index": index,
            }
        )

    return calculate_metrics(evaluated, sample_size=sample_size)


def render_results(result: EvaluationResult) -> str:
    """Return a plain-text summary of the Day 7 evaluation."""
    business = result.business_metrics
    agent = result.agent_metrics
    lines = [
        "========================================",
        "RECLAIM DAY 7 EVALUATION",
        "========================================",
        f"Sample size: {result.sample_size}",
        f"Seed: {result.seed}",
        "",
        "BUSINESS METRICS",
        f"Revenue at risk: {business.total_revenue_at_risk}",
        f"Simulated recovered revenue: {business.total_recovered}",
        f"Recovery rate: {business.recovery_rate:.2f}%",
        f"Average recovered amount: {business.average_recovered_amount:.2f}",
        "",
        "AGENT METRICS",
        f"Intervention rate: {agent.intervention_rate:.2f}%",
        f"Success rate: {agent.success_rate:.2f}%",
        f"Escalation rate: {agent.escalation_rate:.2f}%",
        f"Stop rate: {agent.stop_rate:.2f}%",
        "",
        "COUNTS",
        f"Successful recoveries: {business.successful_recovery_count}",
        f"Interventions: {agent.intervention_count}",
        f"Escalations: {agent.escalation_count}",
        f"Stops: {agent.stop_count}",
        "========================================",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Reclaim Day 7 synthetic evaluation.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--json", action="store_true", help="Print structured JSON instead of a human-readable summary.")
    args = parser.parse_args()

    result = evaluate_transactions(seed=args.seed, sample_size=args.sample_size)
    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        print(render_results(result))


if __name__ == "__main__":
    main()
