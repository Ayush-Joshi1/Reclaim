"""Replaceable LLM clients used by the recovery decision service."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.schemas.recovery_decision import RecoveryContext

logger = logging.getLogger(__name__)


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
        self._uses_google_gemini = "generativelanguage.googleapis.com" in self._base_url.lower()

    @classmethod
    def from_environment(cls) -> "OpenAICompatibleLLMClient":
        """Create a live client only when all required configuration is present."""
        api_key = os.getenv("RECOVERY_LLM_API_KEY")
        model = os.getenv("RECOVERY_LLM_MODEL")
        base_url = os.getenv(
            "RECOVERY_LLM_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        if not api_key or not model:
            raise LLMClientError(
                "RECOVERY_LLM_API_KEY and RECOVERY_LLM_MODEL are required for a live LLM call."
            )
        return cls(api_key=api_key, model=model, base_url=base_url)

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    def _build_payload(self, context: RecoveryContext) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": load_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(context.model_dump(mode="json")),
                },
            ],
            "temperature": 0,
        }
        if not self._uses_google_gemini:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _safe_response_body(self, response: httpx.Response) -> str:
        response_body = getattr(response, "text", None)
        if not isinstance(response_body, str):
            try:
                response_body = json.dumps(response.json())
            except (AttributeError, TypeError, ValueError):
                response_body = "[response body unavailable]"
        if self._api_key:
            response_body = response_body.replace(self._api_key, "[REDACTED]")
        return response_body[:500]

    @staticmethod
    def _decode_json_text(content: str) -> Any:
        text = content.strip()
        if not text:
            raise ValueError("The provider returned empty JSON content.")

        candidates = [text]

        if "```" in text:
            fenced_parts = [part.strip() for part in text.split("```") if part.strip()]
            candidates.extend(fenced_parts)

        for candidate in candidates:
            if not candidate:
                continue
            if candidate.lower().startswith("json"):
                candidate = candidate[4:].strip()
            candidate = candidate.strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

            for start_char, end_char in (("{", "}"), ("[", "]")):
                start = candidate.find(start_char)
                end = candidate.rfind(end_char)
                if start != -1 and end > start:
                    json_candidate = candidate[start : end + 1]
                    try:
                        return json.loads(json_candidate)
                    except json.JSONDecodeError:
                        continue

        return json.loads(text)

    @staticmethod
    def _parse_json_content(content: Any) -> Any:
        if isinstance(content, (dict, list)):
            return content
        if not isinstance(content, str):
            raise TypeError("Provider content is neither JSON nor a string.")
        return OpenAICompatibleLLMClient._decode_json_text(content)

    @staticmethod
    def _collect_text_values(node: Any) -> list[str]:
        values: list[str] = []
        if isinstance(node, str):
            values.append(node)
            return values
        if isinstance(node, list):
            for item in node:
                values.extend(OpenAICompatibleLLMClient._collect_text_values(item))
            return values
        if isinstance(node, dict):
            for key in ("text", "content", "value"):
                if key in node:
                    values.extend(OpenAICompatibleLLMClient._collect_text_values(node[key]))
            if not values and "parts" in node:
                values.extend(OpenAICompatibleLLMClient._collect_text_values(node["parts"]))
        return values

    @staticmethod
    def _extract_content(payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict):
                    text_values = OpenAICompatibleLLMClient._collect_text_values(message.get("content"))
                    if text_values:
                        return "".join(text_values)

        candidates = payload.get("candidates")
        if isinstance(candidates, list) and candidates:
            first_candidate = candidates[0]
            if isinstance(first_candidate, dict):
                text_values = OpenAICompatibleLLMClient._collect_text_values(first_candidate.get("content"))
                if text_values:
                    return "".join(text_values)

        if isinstance(payload.get("content"), str):
            return payload["content"]

        if isinstance(payload.get("output_text"), str):
            return payload["output_text"]

        raise LLMClientError("The configured LLM did not return a usable structured decision.")

    def _log_safe_provider_failure(self, response: Any, error: Exception) -> None:
        host = urlparse(self._base_url).netloc or "unknown-host"
        status_code = getattr(response, "status_code", "unknown")
        content_type = getattr(response, "headers", {}).get("content-type", "unknown")
        preview = self._safe_response_body(response) if response is not None else "[no response body]"
        logger.warning(
            "LLM provider failure: host=%s model=%s status=%s content_type=%s body_preview=%s error=%s:%s",
            host,
            self._model,
            status_code,
            content_type,
            preview,
            type(error).__name__,
            str(error)[:200],
        )

    def generate_recovery_decision(self, context: RecoveryContext) -> dict[str, Any]:
        """Request structured JSON without exposing provider credentials in errors."""
        response: Any = None
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=self._build_payload(context),
                timeout=20.0,
            )
            response.raise_for_status()
            parsed = self._parse_json_content(self._extract_content(response.json()))
        except httpx.HTTPStatusError as error:
            if error.response is None:
                self._log_safe_provider_failure(response, error)
                raise LLMClientError(
                    "The configured LLM did not return a usable structured decision."
                ) from error
            self._log_safe_provider_failure(error.response, error)
            raise LLMClientError(
                f"LLM provider returned HTTP {getattr(error.response, 'status_code', 'unknown')}: "
                f"{self._safe_response_body(error.response)}"
            ) from error
        except LLMClientError as error:
            self._log_safe_provider_failure(response, error)
            raise LLMClientError(
                f"LLM provider returned HTTP {getattr(response, 'status_code', 'unknown')} "
                f"with an unusable response: "
                f"{self._safe_response_body(response)}"
            ) from error
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            self._log_safe_provider_failure(response, error)
            if response is None:
                raise LLMClientError(
                    "The configured LLM did not return a usable structured decision."
                ) from error
            raise LLMClientError(
                f"LLM provider returned HTTP {getattr(response, 'status_code', 'unknown')} "
                f"with an unusable response: "
                f"{self._safe_response_body(response)}"
            ) from error

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
