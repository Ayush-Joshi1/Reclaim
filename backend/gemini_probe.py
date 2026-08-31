import os
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

import httpx

from app.schemas import CustomerRiskContext, MerchantPolicy, PaymentRiskInput, RecoveryHistory
from app.services.recovery_context import build_recovery_context
from app.services.revenue_risk import RevenueRiskEngine
from app.services.llm_client import OpenAICompatibleLLMClient

NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)
POLICY = MerchantPolicy()
payment = PaymentRiskInput(
    payment_id='pay_gemini_test_006',
    amount=125000,
    currency='INR',
    payment_method='card',
    status='failed',
    failure_reason='card_declined',
    failed_at=NOW - timedelta(hours=2),
    time_since_failure_hours=2,
)
customer = CustomerRiskContext(
    customer_id='cust_gemini_test_006',
    customer_age_days=180,
    previous_successful_payments=12,
    previous_failed_payments=1,
    previous_recovery_attempts=0,
    customer_lifetime_value=1500000,
    average_previous_payment=125000,
    recent_payment_frequency=4,
)
history = RecoveryHistory(recovery_attempt_count=0)
risk = RevenueRiskEngine().evaluate(payment, customer, history, POLICY)
context = build_recovery_context(payment, customer, history, risk, POLICY)
client = OpenAICompatibleLLMClient.from_environment()
body = client._build_payload(context)
print('MODEL', client._model)
print('BASE', client._base_url)
print('PAYLOAD_KEYS', sorted(body.keys()))
print('SYSTEM_PROMPT_LEN', len(body['messages'][0]['content']))
print('USER_PAYLOAD_LEN', len(body['messages'][1]['content']))
resp = httpx.post(f'{client._base_url}/chat/completions', headers=client._headers(), json=body, timeout=60.0)
print('STATUS', resp.status_code)
print('CONTENT_TYPE', resp.headers.get('content-type'))
print(resp.text[:5000])
