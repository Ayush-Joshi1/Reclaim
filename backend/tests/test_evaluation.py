"""Tests for the deterministic Day 7 evaluation runner and metric computation."""

from app.evaluation.run import calculate_metrics, evaluate_transactions, generate_evaluation_dataset


def test_evaluation_dataset_is_deterministic_and_has_500_records() -> None:
    first = generate_evaluation_dataset(seed=42, count=500)
    second = generate_evaluation_dataset(seed=42, count=500)

    assert len(first) == 500
    assert first == second
    assert {"payment_id", "amount", "customer_id", "failure_reason"}.issubset(first[0].keys())


def test_evaluate_transactions_returns_business_and_agent_metrics() -> None:
    result = evaluate_transactions(seed=42, sample_size=500)

    assert result.sample_size == 500
    assert result.seed == 42
    assert result.business_metrics.total_revenue_at_risk >= 0
    assert result.business_metrics.total_recovered >= 0
    assert result.business_metrics.recovery_rate >= 0.0
    assert result.business_metrics.average_recovered_amount >= 0.0
    assert result.agent_metrics.intervention_rate >= 0.0
    assert result.agent_metrics.success_rate >= 0.0
    assert result.agent_metrics.escalation_rate >= 0.0
    assert result.agent_metrics.stop_rate >= 0.0


def test_zero_recovery_and_zero_intervention_metrics_are_safe() -> None:
    result = calculate_metrics(
        [
            {
                "revenue_at_risk": 1000,
                "recovered_amount": 0,
                "intervention": False,
                "successful_recovery": False,
                "escalation": False,
                "stop": False,
            }
        ],
        sample_size=1,
    )

    assert result.business_metrics.total_recovered == 0
    assert result.business_metrics.recovery_rate == 0.0
    assert result.business_metrics.average_recovered_amount == 0.0
    assert result.agent_metrics.intervention_count == 0
    assert result.agent_metrics.intervention_rate == 0.0
    assert result.agent_metrics.success_rate == 0.0


def test_duplicate_and_blocked_actions_do_not_inflate_metrics() -> None:
    result = calculate_metrics(
        [
            {
                "revenue_at_risk": 1000,
                "recovered_amount": 0,
                "intervention": False,
                "successful_recovery": False,
                "escalation": False,
                "stop": True,
            },
            {
                "revenue_at_risk": 1000,
                "recovered_amount": 0,
                "intervention": False,
                "successful_recovery": False,
                "escalation": False,
                "stop": False,
            },
            {
                "revenue_at_risk": 1000,
                "recovered_amount": 300,
                "intervention": True,
                "successful_recovery": True,
                "escalation": False,
                "stop": False,
            },
            {
                "revenue_at_risk": 1000,
                "recovered_amount": 0,
                "intervention": False,
                "successful_recovery": False,
                "escalation": True,
                "stop": False,
            },
        ],
        sample_size=4,
    )

    assert result.agent_metrics.intervention_count == 1
    assert result.agent_metrics.success_rate == 100.0
    assert result.agent_metrics.escalation_count == 1
    assert result.agent_metrics.stop_count == 1
    assert result.business_metrics.total_recovered == 300
    assert result.business_metrics.recovery_rate == 7.5
    assert result.business_metrics.average_recovered_amount == 300.0
