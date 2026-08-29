export type RecoveryEventType = "payment_failed" | "recovery_requested";
export type PaymentMethod = "upi" | "card" | "netbanking" | "wallet";
export type RecoveryAction = "RETRY" | "PAYMENT_LINK" | "REMINDER" | "ESCALATE" | "STOP";

export interface RecoveryEvent {
  payment_id: string;
  event_type: RecoveryEventType;
  timestamp: string;
  source: string;
  recovery_attempt_count: number;
  payment: {
    payment_id: string;
    amount: number;
    currency: string;
    payment_method: PaymentMethod;
    status: string;
    failure_reason: string | null;
    failed_at: string;
    time_since_failure_hours: number;
  };
}

export interface RecoveryActionResult {
  payment_id: string;
  action: RecoveryAction;
  mode: "dry_run";
  status: "queued" | "terminal";
  message: string;
}

export interface RecoveryDecision {
  action: RecoveryAction;
  diagnosis: string;
  reasoning: string;
  confidence: number;
  requires_approval: boolean;
  priority: "LOW" | "MEDIUM" | "HIGH";
  policy_constraints: string[];
  expected_outcome: string;
  payment_id: string;
  risk_score: number;
  recovery_eligible: boolean;
  validation_status: "VALID" | "OVERRIDDEN" | "FAILED";
  validation_notes: string[];
  decided_at: string;
}

export interface RecoveryWorkflowResponse {
  event_id: string;
  duplicate: boolean;
  payment_id: string;
  risk_score: number;
  eligible: boolean;
  requires_approval: boolean;
  action: RecoveryAction;
  confidence: number;
  validation_status: "VALID" | "OVERRIDDEN" | "FAILED";
  priority: "LOW" | "MEDIUM" | "HIGH";
  decision: RecoveryDecision;
  result: RecoveryActionResult;
}

export interface RecoveryHistoryRecord {
  event_id: string | null;
  payment_id: string;
  action: RecoveryAction;
  status: string;
  amount: number;
  attempt_number: number | null;
  created_at: string;
  completed_at: string | null;
  execution_mode?: string;
  provider_called?: boolean;
  execution_succeeded?: boolean;
  notification_generated?: boolean;
  executed_at?: string | null;
  recovery_state?: string | null;
  state_reason?: string | null;
  risk_score?: number | null;
  risk_level?: string | null;
  eligibility_result?: boolean | null;
  eligibility_reason?: string | null;
  decision_confidence?: number | null;
  approval_required?: boolean | null;
  validation_status?: string | null;
  policy_override_reason?: string | null;
  decision_diagnosis?: string | null;
  decision_reasoning?: string | null;
  policy_constraints?: string | null;
}

export async function evaluateRecovery(
  event: RecoveryEvent,
): Promise<RecoveryWorkflowResponse> {
  const response = await fetch("/api/recovery", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(event),
  });

  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = isErrorBody(body) ? body.detail : undefined;
    const message = typeof detail === "string" ? detail : detail?.message;
    throw new Error(message ?? `Recovery evaluation failed (${response.status}).`);
  }

  if (!isRecoveryWorkflowResponse(body)) {
    throw new Error("Backend returned an invalid recovery response.");
  }
  return body;
}

function isErrorBody(body: unknown): body is { detail?: string | { message?: string } } {
  return typeof body === "object" && body !== null && "detail" in body;
}

function isRecoveryWorkflowResponse(body: unknown): body is RecoveryWorkflowResponse {
  if (typeof body !== "object" || body === null) return false;
  const response = body as Record<string, unknown>;
  return (
    typeof response.payment_id === "string" &&
    typeof response.risk_score === "number" &&
    typeof response.eligible === "boolean" &&
    typeof response.action === "string" &&
    typeof response.decision === "object" &&
    response.decision !== null &&
    typeof response.result === "object" &&
    response.result !== null
  );
}

export async function fetchRecoveryHistory(
  paymentId?: string,
  limit = 20,
): Promise<RecoveryHistoryRecord[]> {
  const params = new URLSearchParams();
  if (paymentId) params.set("payment_id", paymentId);
  params.set("limit", String(limit));
  const response = await fetch(`/api/recovery?${params.toString()}`, { cache: "no-store" });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = isErrorBody(body) ? body.detail : undefined;
    const message = typeof detail === "string" ? detail : detail?.message;
    throw new Error(message ?? `Recovery history failed (${response.status}).`);
  }
  if (!Array.isArray(body) || !body.every(isRecoveryHistoryRecord)) {
    throw new Error("Backend returned an invalid recovery history response.");
  }
  return body;
}

function isRecoveryHistoryRecord(body: unknown): body is RecoveryHistoryRecord {
  if (typeof body !== "object" || body === null) return false;
  const record = body as Record<string, unknown>;
  return (
    (typeof record.event_id === "string" || record.event_id === null) &&
    typeof record.payment_id === "string" &&
    typeof record.action === "string" &&
    typeof record.status === "string" &&
    typeof record.amount === "number" &&
    (typeof record.attempt_number === "number" || record.attempt_number === null) &&
    typeof record.created_at === "string" &&
    (typeof record.completed_at === "string" || record.completed_at === null)
  );
}

export interface RecoverySummaryActivity {
  event_id: string | null;
  payment_id: string;
  action: RecoveryAction;
  status: string;
  execution_mode: string;
  provider_called: boolean;
  execution_succeeded: boolean;
  notification_generated: boolean;
  executed_at: string | null;
}

export interface RecoverySummary {
  total_evaluations: number;
  total_successful_executions: number;
  total_failed_executions: number;
  total_dry_run_executions: number;
  payments_analyzed: number;
  revenue_at_risk: number;
  total_revenue_at_risk: number;
  revenue_recovered: number | null;
  total_recovered: number;
  recovery_rate: number;
  average_recovered_amount: number;
  interventions: number;
  intervention_rate: number;
  success_rate: number;
  recovered_count: number | null;
  escalation_rate: number;
  stop_rate: number;
  action_counts: Record<string, number>;
  stop_count: number;
  escalate_count: number;
  payment_link_count: number;
  reminder_count: number;
  retry_count: number;
  recent_activity: RecoverySummaryActivity[];
}

export async function fetchRecoverySummary(): Promise<RecoverySummary> {
  const response = await fetch("/api/recovery/summary", { cache: "no-store" });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = isErrorBody(body) ? body.detail : undefined;
    const message = typeof detail === "string" ? detail : detail?.message;
    throw new Error(message ?? `Recovery summary failed (${response.status}).`);
  }
  if (!isRecoverySummary(body)) throw new Error("Backend returned an invalid recovery summary response.");
  return body;
}

function isRecoverySummary(body: unknown): body is RecoverySummary {
  if (typeof body !== "object" || body === null) return false;
  const summary = body as Record<string, unknown>;
  return (
    typeof summary.total_evaluations === "number" &&
    typeof summary.total_successful_executions === "number" &&
    typeof summary.total_failed_executions === "number" &&
    typeof summary.total_dry_run_executions === "number" &&
    typeof summary.payments_analyzed === "number" &&
    typeof summary.revenue_at_risk === "number" &&
    typeof summary.total_revenue_at_risk === "number" &&
    typeof summary.recovery_rate === "number" &&
    typeof summary.average_recovered_amount === "number" &&
    typeof summary.interventions === "number" &&
    typeof summary.intervention_rate === "number" &&
    typeof summary.success_rate === "number" &&
    typeof summary.escalation_rate === "number" &&
    typeof summary.stop_rate === "number" &&
    typeof summary.action_counts === "object" &&
    summary.action_counts !== null &&
    Array.isArray(summary.recent_activity)
  );
}