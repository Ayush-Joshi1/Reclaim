"""Reproducible synthetic failed-payment dataset generation."""

from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

PAYMENT_METHODS = ("upi", "card", "netbanking", "wallet")
FAILURE_REASONS = (
    "card_declined",
    "insufficient_funds",
    "authentication_failed",
    "network_error",
    "bank_error",
    "timeout",
    "unknown",
)
REFERENCE_TIME = datetime(2026, 8, 25, 12, tzinfo=UTC)


def generate_dataset(count: int = 500, seed: int = 42) -> list[dict[str, object]]:
    """Generate reproducible, varied payment-recovery scenarios."""
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

    selected_scenarios = list(scenario_names[:count])
    selected_scenarios.extend(
        rng.choices(scenario_names, weights=weights, k=count - len(selected_scenarios))
    )
    return [
        _build_scenario(index, rng, scenario_type)
        for index, scenario_type in enumerate(selected_scenarios)
    ]


def write_dataset(output_path: Path, count: int = 500, seed: int = 42) -> Path:
    """Generate and write a JSON dataset, returning its path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(generate_dataset(count=count, seed=seed), indent=2), encoding="utf-8"
    )
    return output_path


def _build_scenario(index: int, rng: random.Random, scenario_type: str) -> dict[str, object]:
    """Create one representative recovery situation with slight variation."""
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
        "payment_method": rng.choices(PAYMENT_METHODS, weights=(45, 35, 12, 8), k=1)[0],
        "status": "failed",
        "failure_reason": rng.choices(
            FAILURE_REASONS, weights=(25, 20, 12, 15, 12, 10, 6), k=1
        )[0],
        "failed_at": (REFERENCE_TIME - timedelta(hours=hours)).isoformat(),
        "time_since_failure_hours": hours,
        "recovery_attempt_count": recovery_attempts,
    }


def main() -> None:
    """Generate a dataset from the command line."""
    parser = argparse.ArgumentParser(description="Generate synthetic Reclaim payment data.")
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("../data/sample_payments.json"))
    args = parser.parse_args()
    write_dataset(args.output, count=args.count, seed=args.seed)


if __name__ == "__main__":
    main()
