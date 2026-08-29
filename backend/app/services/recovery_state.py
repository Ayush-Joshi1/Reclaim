"""Deterministic recovery lifecycle state transitions for failed-payment recovery."""

from __future__ import annotations

from typing import Literal

RecoveryState = Literal[
    "detected",
    "evaluating",
    "eligible",
    "approval_required",
    "action_pending",
    "executing",
    "recovered",
    "failed",
    "stopped",
    "duplicate",
    "ignored",
]


class RecoveryStateMachine:
    """Validate the supported recovery lifecycle and guard stale or invalid transitions."""

    VALID_STATES: set[RecoveryState] = {
        "detected",
        "evaluating",
        "eligible",
        "approval_required",
        "action_pending",
        "executing",
        "recovered",
        "failed",
        "stopped",
        "duplicate",
        "ignored",
    }

    TRANSITIONS: dict[RecoveryState, set[RecoveryState]] = {
        "detected": {"evaluating", "ignored", "duplicate", "stopped"},
        "evaluating": {"eligible", "approval_required", "ignored", "duplicate", "stopped", "failed"},
        "eligible": {"action_pending", "ignored", "duplicate", "stopped", "failed"},
        "approval_required": {"stopped", "duplicate", "failed"},
        "action_pending": {"executing", "recovered", "stopped", "duplicate", "failed"},
        "executing": {"recovered", "failed", "stopped", "duplicate"},
        "recovered": {"stopped", "duplicate"},
        "failed": {"evaluating", "stopped", "duplicate", "ignored"},
        "stopped": set(),
        "duplicate": {"duplicate", "stopped", "ignored"},
        "ignored": {"stopped", "duplicate"},
    }

    TERMINAL_STATES: set[RecoveryState] = {"recovered", "failed", "stopped", "duplicate", "ignored"}

    @classmethod
    def transition(cls, from_state: str, to_state: str) -> RecoveryState:
        """Move from one valid lifecycle state to another while blocking unsafe transitions."""
        if from_state not in cls.VALID_STATES:
            raise ValueError(f"Unknown recovery state: {from_state}")
        if to_state not in cls.VALID_STATES:
            raise ValueError(f"Unknown recovery state: {to_state}")
        if to_state == from_state:
            return to_state  # type: ignore[return-value]
        if to_state not in cls.TRANSITIONS.get(from_state, set()):
            raise ValueError(f"Invalid recovery transition: {from_state} -> {to_state}")
        return to_state  # type: ignore[return-value]

    @classmethod
    def ensure_execution_allowed(cls, state: str) -> None:
        """Reject execution when the payment or recovery is already terminal, duplicate, or blocked."""
        if state == "stopped":
            return
        if state in {"approval_required"}:
            raise ValueError("Recovery requires approval and cannot execute automatically.")
        if state in {"duplicate", "ignored", "failed", "recovered"}:
            if state == "ignored":
                raise ValueError("Recovery is ineligible and cannot execute.")
            raise ValueError(f"Recovery state does not allow execution: {state}")

    @classmethod
    def is_terminal(cls, state: str) -> bool:
        """Return true when the recovery state cannot continue into a new action."""
        return state in cls.TERMINAL_STATES

    @classmethod
    def is_active(cls, state: str) -> bool:
        """Return true for states that can still progress into execution or recovery completion."""
        return state not in cls.TERMINAL_STATES and state not in {"ignored", "duplicate"}

    @classmethod
    def for_payment_status(cls, status: str) -> RecoveryState:
        """Map a payment state to the safest recovery state, preventing stale recovery actions."""
        normalized = (status or "").lower()
        if normalized in {"authorized", "captured", "successful", "closed", "stopped", "permanently_closed"}:
            return "stopped"
        if normalized in {"failed", "payment_failed", "declined"}:
            return "detected"
        return "ignored"
