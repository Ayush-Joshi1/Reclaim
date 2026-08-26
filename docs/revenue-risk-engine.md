# Revenue Risk Engine

## Purpose

The Revenue Risk Engine provides a transparent, deterministic assessment of a failed payment before any future recovery agent reasons about it. It does not perform recovery actions or call external services.

## Inputs and outputs

Inputs are a failed payment, customer/payment history, recovery history, and a merchant policy. Amounts are integers in the smallest currency unit (paise for INR), and failure timestamps must be timezone-aware.

The engine returns a 0–100 `risk_score`, `revenue_at_risk`, urgency, explanatory risk factors, eligibility reasons, and distinct booleans for recovery eligibility, automatic action eligibility, merchant approval, and whether recovery should stop.

## Scoring philosophy

The score starts at 50 and applies small, named adjustments:

- Strong successful history: +15; any prior success: +8.
- First customer failure: +10; two or more prior failures: -10; five or more: -20.
- Failure within 6 hours: +12; within 24 hours: +7; older than 24 hours: -10.
- No previous attempt for the payment: +5; an existing attempt: -8.
- Active recent payment frequency: +5.
- Payment at or above the high-value threshold: -8.

The result is clamped to 0–100. These are explainable recovery-likelihood signals, not a machine-learning prediction.

## Eligibility and policy rules

`MerchantPolicy` supplies the maximum recovery attempts, recovery window, automatic-action amount limit, high-value threshold, and maximum customer notifications. The engine does not hardcode these values.

Recovery stops when a payment is successful, permanently closed/stopped, outside the recovery window, or at its attempt limit. An otherwise eligible payment above the automatic-action amount limit requires merchant approval; it is not marked for automatic action.

## Example scenarios

- A first failure from a customer with six successful payments, no prior attempt, and a two-hour-old failure scores highly and has HIGH urgency.
- A payment with six prior customer failures loses score for the repeated-failure pattern.
- A 49-hour-old failure is outside the default 48-hour recovery window and must stop.
- A ₹25,000 payment (`2_500_000` paise) can be recoverable, but requires merchant approval under the default limit.

## Determinism and future AI use

Given identical inputs and policy, the engine always returns identical output. The synthetic generator is also seed-based and uses a fixed reference timestamp. A future AI agent can consume the score, factors, eligibility state, and policy decision as context; it must not replace these hard safety constraints.
