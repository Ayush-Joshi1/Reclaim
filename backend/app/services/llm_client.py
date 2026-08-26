"""Replaceable LLM clients used by the recovery decision service."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.schemas.recovery_decision import RecoveryContext


class LLMClientError(RuntimeError):
    """Raised when an LLM provider cannot supply a usable response."""


class LLMClient(Protocol):
    """Provider-agnostic interface for a structured recovery recommendation."""

    def generate_recovery_decision(self, context: RecoveryContext) -> dict[str, Any]:
        """Return a JSON-compatible recovery-decision object."""


class OpenAICompatibleLLMClient:
    """Isolated adapter for OpenAI-compatible chat-completions endpoints."""

    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")

    @classmethod
    def from_environment(cls) -> "OpenAICompatibleLLMClient":
        """Create a live client only when all required configuration is present."""
        api_key = os.getenv("RECOVERY_LLM_API_KEY")
        model = os.getenv("RECOVERY_LLM_MODEL")
        base_url = os.getenv("RECOVERY_LLM_BASE_URL", "https://api.openai.com/v1")
        if not api_key or not model:
            raise LLMClientError(
                "RECOVERY_LLM_API_KEY and RECOVERY_LLM_MODEL are required for a live LLM call."
            )
        return cls(api_key=api_key, model=model, base_url=base_url)

    def generate_recovery_decision(self, context: RecoveryContext) -> dict[str, Any]:
        """Request structured JSON without exposing provider credentials in errors."""
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": load_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(context.model_dump(mode="json")),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=20.0,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise LLMClientError("The configured LLM did not return a usable structured decision.") from error

        if not isinstance(parsed, dict):
            raise LLMClientError("The configured LLM returned a non-object decision.")
        return parsed


class FakeLLMClient:
    """Deterministic development/test client that never calls an external provider."""

    def generate_recovery_decision(self, context: RecoveryContext) -> dict[str, Any]:
        """Recommend a conservative action using only supplied deterministic evidence."""
        if not context.risk.recovery_eligible:
            action = "STOP"
            diagnosis = "Deterministic policy does not permit recovery."
            reasoning = "The recovery eligibility result requires a stop."
        elif context.risk.requires_approval:
            action = "ESCALATE"
            diagnosis = "The payment needs merchant review before any recovery action."
            reasoning = "The amount exceeds the merchant's automatic action limit."
        elif context.payment.failure_reason in {"network_error", "timeout", "bank_error"}:
            action = "RETRY"
            diagnosis = "The failure appears transient."
            reasoning = "A low-friction retry is appropriate for a recent transient failure."
        elif context.risk.risk_score >= 70:
            action = "PAYMENT_LINK"
            diagnosis = "The customer has a strong likelihood of completing payment."
            reasoning = "A payment link is a reasonable next step after the failed attempt."
        else:
            action = "REMINDER"
            diagnosis = "The payment may benefit from a non-invasive follow-up."
            reasoning = "A reminder is the least invasive reasonable recovery action."

        return {
            "action": action,
            "diagnosis": diagnosis,
            "reasoning": reasoning,
            "confidence": 0.7,
            "requires_approval": context.risk.requires_approval,
            "priority": context.risk.urgency,
            "policy_constraints": context.risk.eligibility_reasons,
            "expected_outcome": "Provide a safe recovery recommendation for future execution review.",
        }


def load_system_prompt() -> str:
    """Load the versioned system prompt used by the live provider adapter."""
    prompt_path = Path(__file__).resolve().parents[3] / "docs" / "prompts" / "recovery-agent.md"
    return prompt_path.read_text(encoding="utf-8")
