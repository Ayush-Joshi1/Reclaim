"""Focused tests for the recovery lifecycle and stale-action guardrails."""

from datetime import UTC, datetime

import pytest

from app.services.recovery_state import RecoveryStateMachine


def test_valid_transition() -> None:
    assert RecoveryStateMachine.transition("detected", "evaluating") == "evaluating"


def test_invalid_transition_is_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid recovery transition"):
        RecoveryStateMachine.transition("stopped", "executing")


def test_stop_is_terminal() -> None:
    assert RecoveryStateMachine.is_terminal("stopped") is True
    assert RecoveryStateMachine.is_active("stopped") is False


def test_approval_required_state_cannot_execute() -> None:
    with pytest.raises(ValueError, match="approval"):
        RecoveryStateMachine.ensure_execution_allowed("approval_required")


def test_ineligible_state_cannot_execute() -> None:
    with pytest.raises(ValueError, match="ineligible"):
        RecoveryStateMachine.ensure_execution_allowed("ignored")


def test_successful_recovery_transition() -> None:
    assert RecoveryStateMachine.transition("executing", "recovered") == "recovered"


def test_failed_execution_transition() -> None:
    assert RecoveryStateMachine.transition("executing", "failed") == "failed"


def test_payment_success_stops_stale_recovery() -> None:
    assert RecoveryStateMachine.for_payment_status("captured") == "stopped"
    assert RecoveryStateMachine.for_payment_status("authorized") == "stopped"


def test_state_machine_rejects_malformed_state() -> None:
    with pytest.raises(ValueError, match="Unknown recovery state"):
        RecoveryStateMachine.transition("unknown", "executing")
