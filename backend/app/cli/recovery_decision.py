"""Run a validated recovery recommendation from synthetic payment data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.schemas import CustomerRiskContext, MerchantPolicy, PaymentRiskInput, RecoveryHistory
from app.services.llm_client import FakeLLMClient, OpenAICompatibleLLMClient
from app.services.recovery_context import build_recovery_context
from app.services.recovery_decision import RecoveryDecisionService
from app.services.revenue_risk import RevenueRiskEngine


def main() -> None:
    """Load a synthetic record and print a final validated decision."""
    parser = argparse.ArgumentParser(description="Run Reclaim's recovery decision engine.")
    parser.add_argument("--index", type=int, default=0, help="Synthetic record index to evaluate.")
    parser.add_argument("--input", type=Path, default=Path("../data/sample_payments.json"))
    parser.add_argument("--fake", action="store_true", help="Use the deterministic local fake LLM.")
    args = parser.parse_args()

    records = json.loads(args.input.read_text(encoding="utf-8"))
    record = records[args.index]
    payment = PaymentRiskInput(**_select(record, PaymentRiskInput))
    customer = CustomerRiskContext(**_select(record, CustomerRiskContext))
    recovery_history = RecoveryHistory(recovery_attempt_count=record["recovery_attempt_count"])
    policy = MerchantPolicy()
    risk_result = RevenueRiskEngine().evaluate(payment, customer, recovery_history, policy)
    context = build_recovery_context(payment, customer, recovery_history, risk_result, policy)
    client = FakeLLMClient() if args.fake else OpenAICompatibleLLMClient.from_environment()
    decision = RecoveryDecisionService(client).decide(context)
    print(decision.model_dump_json(indent=2))


def _select(record: dict[str, object], schema_type: type) -> dict[str, object]:
    """Select only fields declared by a Pydantic model from dataset records."""
    return {name: record[name] for name in schema_type.model_fields}


if __name__ == "__main__":
    main()
