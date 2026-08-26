"""Orchestrate context building, LLM recommendation, and policy validation."""

from typing import Any

from pydantic import ValidationError

from app.schemas.recovery_decision import RecoveryContext, RecoveryDecision, ValidatedRecoveryDecision
from app.services.decision_validator import DecisionValidator
from app.services.llm_client import LLMClient, LLMClientError


class RecoveryDecisionService:
    """Produce a validated LLM recommendation without executing any action."""

    def __init__(self, llm_client: LLMClient, validator: DecisionValidator | None = None) -> None:
        self._llm_client = llm_client
        self._validator = validator or DecisionValidator()

    def decide(self, context: RecoveryContext) -> ValidatedRecoveryDecision:
        """Call the provider, validate its JSON, then enforce deterministic policy."""
        try:
            raw_decision: dict[str, Any] = self._llm_client.generate_recovery_decision(context)
            candidate = RecoveryDecision.model_validate(raw_decision)
        except (LLMClientError, ValidationError, TypeError, ValueError) as error:
            return self._validator.safe_failure(context, error.__class__.__name__)

        return self._validator.validate(candidate, context)
