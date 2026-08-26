"""Tests for reproducible synthetic dataset generation."""

from app.services.synthetic_data import generate_dataset, write_dataset


def test_dataset_is_reproducible_and_contains_required_scenarios() -> None:
    first = generate_dataset(count=100, seed=42)
    second = generate_dataset(count=100, seed=42)

    assert first == second
    assert len(first) == 100
    assert {
        "high_recovery_likelihood",
        "high_value_requires_approval",
        "repeated_failure_stop",
        "expired_recovery_window",
    } <= {record["scenario_type"] for record in first}
    assert {"customer_id", "payment_id", "amount", "failed_at"} <= set(first[0])


def test_write_dataset_creates_json_file(tmp_path) -> None:
    output = write_dataset(tmp_path / "payments.json", count=3, seed=9)

    assert output.exists()
    assert '"payment_id"' in output.read_text(encoding="utf-8")
