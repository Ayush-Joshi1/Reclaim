"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  evaluateRecovery,
  fetchRecoveryHistory,
  fetchRecoverySummary,
  type PaymentMethod,
  type RecoveryEvent,
  type RecoveryHistoryRecord,
  type RecoverySummary,
  type RecoveryWorkflowResponse,
} from "@/lib/recovery";

const initialTimestamp = new Date().toISOString().slice(0, 16);

const initialForm = {
  paymentId: "",
  amount: "",
  currency: "INR",
  paymentMethod: "card" as PaymentMethod,
  failureReason: "",
  failedAt: initialTimestamp,
  timeSinceFailureHours: "",
  recoveryAttemptCount: "0",
};

export default function Home() {
  const [form, setForm] = useState(initialForm);
  const [result, setResult] = useState<RecoveryWorkflowResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [history, setHistory] = useState<RecoveryHistoryRecord[]>([]);
  const [historyFilter, setHistoryFilter] = useState("");
  const [historyLimit, setHistoryLimit] = useState(10);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [selectedHistoryRecord, setSelectedHistoryRecord] = useState<RecoveryHistoryRecord | null>(null);
  const [summary, setSummary] = useState<RecoverySummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const loadHistory = useCallback(async (paymentId = historyFilter, limit = historyLimit) => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const nextHistory = await fetchRecoveryHistory(paymentId || undefined, limit);
      setHistory(nextHistory);
      setSelectedHistoryRecord((current) => {
        if (!nextHistory.length) return null;
        if (current) {
          const currentKey = `${current.payment_id}-${current.event_id ?? current.created_at}`;
          const exists = nextHistory.some((record) => `${record.payment_id}-${record.event_id ?? record.created_at}` === currentKey);
          if (exists) return current;
        }
        return nextHistory[0];
      });
    } catch (historyFetchError) {
      setHistoryError(historyFetchError instanceof Error ? historyFetchError.message : "Recovery history failed.");
    } finally {
      setHistoryLoading(false);
    }
  }, [historyFilter, historyLimit]);

  const loadSummary = useCallback(async () => {
    setSummaryError(null);
    try {
      setSummary(await fetchRecoverySummary());
    } catch (summaryFetchError) {
      setSummaryError(summaryFetchError instanceof Error ? summaryFetchError.message : "Recovery summary failed.");
    }
  }, []);

  useEffect(() => {
    const initializeDashboard = async () => {
      await Promise.all([loadSummary(), loadHistory()]);
    };
    void initializeDashboard();
  }, [loadHistory, loadSummary]);

  function updateField(field: keyof typeof initialForm, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoading(true);
    setError(null);
    setResult(null);

    const recoveryEvent: RecoveryEvent = {
      payment_id: form.paymentId,
      event_type: "payment_failed",
      timestamp: new Date().toISOString(),
      source: "reclaim-dashboard",
      recovery_attempt_count: Number(form.recoveryAttemptCount),
      payment: {
        payment_id: form.paymentId,
        amount: Number(form.amount),
        currency: form.currency,
        payment_method: form.paymentMethod,
        status: "failed",
        failure_reason: form.failureReason || null,
        failed_at: new Date(`${form.failedAt}:00Z`).toISOString(),
        time_since_failure_hours: Number(form.timeSinceFailureHours),
      },
    };

    try {
      setResult(await evaluateRecovery(recoveryEvent));
      void loadHistory();
      void loadSummary();
    } catch (evaluationError) {
      setError(evaluationError instanceof Error ? evaluationError.message : "Recovery evaluation failed.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="min-h-screen px-6 py-10 text-slate-900 sm:px-10 lg:px-12">
      <section className="mx-auto max-w-7xl">
        <header className="mb-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Autonomous payment recovery</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-900 sm:text-4xl">Reclaim</h1>
            </div>
            <div className="flex flex-wrap gap-2 text-xs font-medium text-slate-600">
              <StatusPill label="Backend live" tone="neutral" />
              <StatusPill label="Recovery flow" tone="info" />
              <StatusPill label="Dry-run by default" tone="warning" />
            </div>
          </div>
          <div className="mt-6 grid gap-3 md:grid-cols-5">
            {[
              "Failed payment",
              "Risk / eligibility",
              "Recovery decision",
              "Action execution",
              "Outcome tracking",
            ].map((step, index) => (
              <div key={step} className="flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white">{index + 1}</span>
                <span className="text-sm font-medium text-slate-700">{step}</span>
              </div>
            ))}
          </div>
        </header>

        <div className="grid gap-6 lg:grid-cols-[minmax(280px,0.8fr)_minmax(0,1.2fr)]">
          <form onSubmit={handleSubmit} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm ring-1 ring-slate-100">
            <div className="mb-6">
              <h2 className="text-lg font-semibold text-slate-900">Evaluate a payment</h2>
              <p className="mt-1 text-sm text-slate-500">Run the projectÃ¢â‚¬â„¢s backend decision flow for a failed payment event.</p>
            </div>
            <div className="space-y-4">
              <label className="block text-sm font-medium text-slate-700">Payment ID<input required value={form.paymentId} onChange={(event) => updateField("paymentId", event.target.value)} className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 font-mono text-sm text-slate-900 shadow-sm transition focus:border-slate-400 focus:outline-none" /></label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm font-medium text-slate-700">Amount<input required min="0" type="number" value={form.amount} onChange={(event) => updateField("amount", event.target.value)} className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 shadow-sm transition focus:border-slate-400 focus:outline-none" /></label>
                <label className="block text-sm font-medium text-slate-700">Currency<input required minLength={3} maxLength={3} value={form.currency} onChange={(event) => updateField("currency", event.target.value.toUpperCase())} className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm uppercase text-slate-900 shadow-sm transition focus:border-slate-400 focus:outline-none" /></label>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm font-medium text-slate-700">Payment method<select value={form.paymentMethod} onChange={(event) => updateField("paymentMethod", event.target.value)} className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 shadow-sm transition focus:border-slate-400 focus:outline-none"><option value="card">Card</option><option value="upi">UPI</option><option value="netbanking">Netbanking</option><option value="wallet">Wallet</option></select></label>
                <label className="block text-sm font-medium text-slate-700">Attempts<input required min="0" type="number" value={form.recoveryAttemptCount} onChange={(event) => updateField("recoveryAttemptCount", event.target.value)} className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 shadow-sm transition focus:border-slate-400 focus:outline-none" /></label>
              </div>
              <label className="block text-sm font-medium text-slate-700">Failed at (UTC)<input required type="datetime-local" value={form.failedAt} onChange={(event) => updateField("failedAt", event.target.value)} className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 shadow-sm transition focus:border-slate-400 focus:outline-none" /></label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm font-medium text-slate-700">Hours since failure<input required min="0" type="number" value={form.timeSinceFailureHours} onChange={(event) => updateField("timeSinceFailureHours", event.target.value)} className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 shadow-sm transition focus:border-slate-400 focus:outline-none" /></label>
                <label className="block text-sm font-medium text-slate-700">Failure reason<input value={form.failureReason} onChange={(event) => updateField("failureReason", event.target.value)} className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 shadow-sm transition focus:border-slate-400 focus:outline-none" /></label>
              </div>
            </div>
            <button disabled={isLoading} type="submit" className="mt-6 w-full rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400">{isLoading ? "Evaluating..." : "Evaluate recovery"}</button>
          </form>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm ring-1 ring-slate-100" aria-live="polite">
            {!result && !error && <div className="flex min-h-64 items-center justify-center text-center text-sm text-slate-500">Submit an event to see the validated recovery decision.</div>}
            {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"><p className="font-semibold">Evaluation failed</p><p className="mt-1">{error}</p></div>}
            {result && <DecisionResult result={result} />}
          </section>
        </div>

        <section className="mt-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm ring-1 ring-slate-100">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-4">
            <div>
              <p className="text-sm text-slate-500">Merchant summary</p>
              <h2 className="mt-1 text-lg font-semibold text-slate-900">Recovery performance</h2>
            </div>
            <button type="button" onClick={() => { void loadSummary(); void loadHistory(); }} className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50">Refresh data</button>
          </div>
          {summaryError && <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{summaryError}</div>}
          {!summaryError && !summary && <p className="py-8 text-center text-sm text-slate-500">Loading merchant KPIs...</p>}
          {summary && (
            <>
              <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <KpiCard label="Revenue at Risk" value={formatCurrency(summary.revenue_at_risk)} helper="Persisted failed-payment totals" tone="slate" />
                <KpiCard label="Revenue Recovered" value={summary.revenue_recovered == null ? "Unavailable" : formatCurrency(summary.revenue_recovered)} helper={summary.revenue_recovered == null ? "No successful recovery amount recorded" : "Persisted recovered amount"} tone="emerald" />
                <KpiCard label="Recovery Rate" value={summary.recovery_rate == null ? "Unavailable" : `${summary.recovery_rate.toFixed(1)}%`} helper="Recovered outcomes / total evaluations" tone="amber" />
                <KpiCard label="Payments Analyzed" value={String(summary.payments_analyzed ?? 0)} helper="Unique payments in persisted history" tone="sky" />
                <KpiCard label="Interventions" value={String(summary.interventions ?? 0)} helper="Persisted recovery attempts" tone="indigo" />
                <KpiCard label="Recovered" value={summary.recovered_count == null ? "Unavailable" : String(summary.recovered_count)} helper={summary.recovered_count == null ? "No successful recovery outcome recorded" : "Persisted successful recoveries"} tone="emerald" />
                <KpiCard label="Escalated" value={String(summary.escalate_count ?? 0)} helper="Escalation actions recorded" tone="violet" />
                <KpiCard label="Stopped" value={String(summary.stop_count ?? 0)} helper="Stop actions recorded" tone="rose" />
              </div>
              <div className="mt-6 flex flex-wrap gap-2 text-sm text-slate-600">
                <Badge label="RETRY" value={summary.retry_count} />
                <Badge label="PAYMENT_LINK" value={summary.payment_link_count} />
                <Badge label="REMINDER" value={summary.reminder_count} />
                <Badge label="ESCALATE" value={summary.escalate_count} />
                <Badge label="STOP" value={summary.stop_count} />
              </div>
            </>
          )}
        </section>

        <section className="mt-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm ring-1 ring-slate-100">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-4">
            <div>
              <p className="text-sm text-slate-500">Persisted activity</p>
              <h2 className="mt-1 text-lg font-semibold text-slate-900">Recovery history</h2>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <input value={historyFilter} onChange={(event) => setHistoryFilter(event.target.value)} placeholder="Filter by payment ID" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm transition focus:border-slate-400 focus:outline-none" />
              <select value={historyLimit} onChange={(event) => setHistoryLimit(Number(event.target.value))} className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm transition focus:border-slate-400 focus:outline-none">
                <option value={5}>5 rows</option>
                <option value={10}>10 rows</option>
                <option value={20}>20 rows</option>
              </select>
              <button type="button" onClick={() => void loadHistory(historyFilter, historyLimit)} disabled={historyLoading} className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50">{historyLoading ? "Loading..." : "Refresh"}</button>
            </div>
          </div>
          {historyError && <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{historyError}</div>}
          {!historyLoading && !historyError && history.length === 0 && <p className="py-8 text-center text-sm text-slate-500">No persisted recovery activity yet.</p>}
          {!historyLoading && !historyError && history.length > 0 && (
            <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(260px,0.8fr)]">
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="w-full min-w-[980px] text-left text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-3 py-3">Payment ID</th>
                      <th className="px-3 py-3">Event ID</th>
                      <th className="px-3 py-3">Action</th>
                      <th className="px-3 py-3">Status</th>
                      <th className="px-3 py-3">Recovery state</th>
                      <th className="px-3 py-3">Amount</th>
                      <th className="px-3 py-3">Attempt</th>
                      <th className="px-3 py-3">Execution mode</th>
                      <th className="px-3 py-3">Provider called</th>
                      <th className="px-3 py-3">Execution success</th>
                      <th className="px-3 py-3">Notification</th>
                      <th className="px-3 py-3">Timestamp</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((record) => {
                      const isSelected = selectedHistoryRecord && `${record.payment_id}-${record.event_id ?? record.created_at}` === `${selectedHistoryRecord.payment_id}-${selectedHistoryRecord.event_id ?? selectedHistoryRecord.created_at}`;
                      return (
                        <tr key={record.event_id ?? `${record.payment_id}-${record.created_at}`} onClick={() => setSelectedHistoryRecord(record)} className={`cursor-pointer border-b border-slate-100 last:border-0 transition-colors ${isSelected ? "bg-slate-100 hover:bg-slate-100" : "hover:bg-slate-50"}`}>
                          <td className="px-3 py-3 font-mono text-xs">{record.payment_id}</td>
                          <td className="px-3 py-3 font-mono text-xs">{record.event_id ?? "-"}</td>
                          <td className="px-3 py-3 font-semibold">{record.action}</td>
                          <td className="px-3 py-3"><span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium">{record.status}</span></td>
                          <td className="px-3 py-3">{record.recovery_state ?? "Not recorded"}</td>
                          <td className="px-3 py-3">{formatCurrency(record.amount)}</td>
                          <td className="px-3 py-3">{record.attempt_number ?? "-"}</td>
                          <td className="px-3 py-3">{record.execution_mode ?? "dry_run"}</td>
                          <td className="px-3 py-3">{record.provider_called ? "Yes" : "No"}</td>
                          <td className="px-3 py-3">{record.execution_succeeded === undefined ? "Unrecorded" : record.execution_succeeded ? "Yes" : "No"}</td>
                          <td className="px-3 py-3">{record.notification_generated ? "Yes" : "No"}</td>
                          <td className="px-3 py-3 whitespace-nowrap">{formatTimestamp(record.executed_at ?? record.created_at)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <aside className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                {selectedHistoryRecord ? <AuditPanel record={selectedHistoryRecord} /> : <p className="text-sm text-slate-500">Select a recovery event to inspect its audit trail.</p>}
              </aside>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}

function KpiCard({ label, value, helper, tone = "slate" }: { label: string; value: string; helper: string; tone?: "slate" | "emerald" | "amber" | "sky" | "indigo" | "violet" | "rose" }) {
  const toneClasses: Record<string, string> = {
    slate: "border-slate-200 bg-slate-50",
    emerald: "border-emerald-200 bg-emerald-50",
    amber: "border-amber-200 bg-amber-50",
    sky: "border-sky-200 bg-sky-50",
    indigo: "border-indigo-200 bg-indigo-50",
    violet: "border-violet-200 bg-violet-50",
    rose: "border-rose-200 bg-rose-50",
  };

  return (
    <div className={`rounded-xl border p-4 ${toneClasses[tone]}`}>
      <p className="text-xs font-medium uppercase tracking-[0.08em] text-slate-500">{label}</p>
      <p className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">{value}</p>
      <p className="mt-2 text-xs text-slate-500">{helper}</p>
    </div>
  );
}

function StatusPill({ label, tone }: { label: string; tone: "neutral" | "info" | "warning" }) {
  const toneClasses: Record<string, string> = {
    neutral: "border-slate-200 bg-slate-100 text-slate-700",
    info: "border-sky-200 bg-sky-100 text-sky-700",
    warning: "border-amber-200 bg-amber-100 text-amber-700",
  };

  return <span className={`rounded-full border px-2.5 py-1 ${toneClasses[tone]}`}>{label}</span>;
}

function Badge({ label, value }: { label: string; value: number }) {
  return <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-700">{label} {value}</span>;
}

function AuditPanel({ record }: { record: RecoveryHistoryRecord }) {
  const policyConstraints = parsePolicyConstraints(record.policy_constraints);
  const timeline = [
    { title: "Event received", timestamp: formatTimestamp(record.created_at), detail: "Persisted record created for payment activity." },
    { title: "Risk evaluated", timestamp: formatTimestamp(record.created_at), detail: record.risk_score == null ? "Risk score not recorded." : `Risk score: ${record.risk_score}/100 (${record.risk_level ?? "unclassified"}).` },
    { title: "Policy / eligibility checked", timestamp: formatTimestamp(record.created_at), detail: record.eligibility_result == null ? "Eligibility result not recorded." : `${record.eligibility_result ? "Eligible" : "Not eligible"}. ${record.eligibility_reason ?? ""}` },
    { title: "Action selected", timestamp: formatTimestamp(record.created_at), detail: `${record.action} was selected as the persisted action for this event.` },
    { title: "Execution attempted", timestamp: record.executed_at ? formatTimestamp(record.executed_at) : "No execution timestamp recorded", detail: record.execution_mode ? `Execution mode: ${record.execution_mode}` : "Execution mode unavailable." },
    { title: "Notification / provider result", timestamp: record.executed_at ? formatTimestamp(record.executed_at) : "No execution timestamp recorded", detail: record.provider_called ? "Provider was marked as called." : "Provider call marker is false or unrecorded." },
    { title: "Final status", timestamp: record.completed_at ? formatTimestamp(record.completed_at) : record.executed_at ? formatTimestamp(record.executed_at) : formatTimestamp(record.created_at), detail: `Status: ${record.status}` },
  ];

  return (
    <div>
      <div className="flex items-start justify-between gap-3 border-b border-slate-200 pb-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.08em] text-slate-500">Audit record</p>
          <h3 className="mt-1 text-xl font-semibold">{record.action}</h3>
        </div>
        <span className="rounded-full bg-slate-900 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-white">{record.status}</span>
      </div>

      <div className="mt-4 grid gap-3 text-sm">
        <DetailRow label="Payment ID" value={record.payment_id} />
        <DetailRow label="Event ID" value={record.event_id ?? "Unavailable"} />
        <DetailRow label="Amount" value={formatCurrency(record.amount)} />
        <DetailRow label="Attempt" value={record.attempt_number ?? "Unavailable"} />
        <DetailRow label="Action" value={record.action} />
        <DetailRow label="Status" value={record.status} />
        <DetailRow label="Recovery state" value={record.recovery_state ?? "Not recorded"} />
        <DetailRow label="Risk score" value={record.risk_score == null ? "Not recorded" : `${record.risk_score}/100 (${record.risk_level ?? "unclassified"})`} />
        <DetailRow label="Eligibility" value={record.eligibility_result == null ? "Not recorded" : record.eligibility_result ? "Eligible" : "Not eligible"} />
        <DetailRow label="Confidence" value={record.decision_confidence == null ? "Not recorded" : `${Math.round(record.decision_confidence * 100)}%`} />
        <DetailRow label="Approval required" value={record.approval_required == null ? "Not recorded" : record.approval_required ? "Yes" : "No"} />
        <DetailRow label="Validation" value={record.validation_status ?? "Not recorded"} />
        <DetailRow label="Execution mode" value={record.execution_mode ?? "dry_run"} />
        <DetailRow label="Provider called" value={record.provider_called === undefined ? "Unrecorded" : record.provider_called ? "Yes" : "No"} />
        <DetailRow label="Execution succeeded" value={record.execution_succeeded === undefined ? "Unrecorded" : record.execution_succeeded ? "Yes" : "No"} />
        <DetailRow label="Notification generated" value={record.notification_generated ? "Yes" : "No"} />
        <DetailRow label="Created" value={formatTimestamp(record.created_at)} />
        <DetailRow label="Executed" value={record.executed_at ? formatTimestamp(record.executed_at) : "Not recorded"} />
        <DetailRow label="Completed" value={record.completed_at ? formatTimestamp(record.completed_at) : "Not recorded"} />
      </div>

      <div className="mt-6 rounded-md border border-slate-200 bg-white p-3">
        <p className="text-sm font-semibold">Decision / reasoning</p>
        <TextBlock label="Diagnosis" value={record.decision_diagnosis ?? "Not recorded"} />
        <TextBlock label="Reasoning" value={record.decision_reasoning ?? "Not recorded"} />
        <TextBlock label="State reason" value={record.state_reason ?? "Not recorded"} />
        <TextBlock label="Policy override / stop reason" value={record.policy_override_reason ?? "None recorded"} />
        <ListBlock label="Policy constraints" items={policyConstraints} />
      </div>

      <div className="mt-6">
        <p className="text-sm font-semibold">Lifecycle timeline</p>
        <ol className="mt-3 space-y-3 border-l border-slate-200 pl-4">
          {timeline.map((step) => (
            <li key={step.title} className="relative">
              <span className="absolute -left-[1.1rem] top-1.5 h-2.5 w-2.5 rounded-full border border-slate-300 bg-white" />
              <div className="ml-1">
                <p className="text-sm font-medium">{step.title}</p>
                <p className="text-xs text-slate-500">{step.timestamp}</p>
                <p className="mt-1 text-xs leading-5 text-slate-600">{step.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-slate-200 bg-white px-3 py-2">
      <span className="text-xs font-medium uppercase tracking-[0.08em] text-slate-500">{label}</span>
      <span className="text-right text-sm font-medium text-slate-800">{String(value)}</span>
    </div>
  );
}

function parsePolicyConstraints(value: string | null | undefined): string[] {
  if (!value) return [];
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) && parsed.every((item) => typeof item === "string") ? parsed : [value];
  } catch {
    return [value];
  }
}

function DecisionResult({ result }: { result: RecoveryWorkflowResponse }) {
  const decision = result.decision;
  const paymentLink = result.result.payment_link;
  const isPaymentLinkAction = result.action === "PAYMENT_LINK" && paymentLink;

  const details = [
    ["Payment ID", result.payment_id],
    ["Risk score", `${result.risk_score}/100`],
    ["Recovery eligibility", result.eligible ? "Eligible" : "Not eligible"],
    ["Urgency", result.priority],
    ["Recommended action", result.action],
    ["Confidence", `${Math.round(result.confidence * 100)}%`],
    ["Priority", result.priority],
    ["Requires approval", result.requires_approval ? "Yes" : "No"],
    ["Duplicate", result.duplicate ? "Yes" : "No"],
    ["Validation status", result.validation_status],
  ];

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 pb-5">
        <div>
          <p className="text-sm text-slate-500">Validated recovery decision</p>
          <h2 className="mt-1 text-2xl font-semibold">{result.action}</h2>
        </div>
        <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">DRY RUN</span>
      </div>

      {/* Prominent Payment Link Section */}
      {isPaymentLinkAction && (
        <div className="mt-6 rounded-lg border-2 border-green-200 bg-green-50 p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="inline-block h-3 w-3 rounded-full bg-green-600"></span>
            <h3 className="text-lg font-semibold text-green-900">PAYMENT LINK READY</h3>
          </div>
          <p className="text-sm text-green-700 mb-4">Click below to open the payment link in a new tab.</p>
          <a
            href={paymentLink}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-lg bg-green-600 px-6 py-3 font-semibold text-white hover:bg-green-700 transition-colors"
          >
            Open Payment Link Ã¢â€ â€™
          </a>
          <p className="mt-4 text-sm text-green-700">
            <span className="font-semibold">Provider:</span> Razorpay Test Mode
          </p>
        </div>
      )}

      <dl className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {details.map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
            <dd className="mt-1 text-sm font-semibold">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-6 space-y-5 text-sm">
        <TextBlock label="Diagnosis" value={decision.diagnosis} />
        <TextBlock label="Reasoning" value={decision.reasoning} />
        <TextBlock label="Expected outcome" value={decision.expected_outcome} />
        <ListBlock label="Risk factors" items={decision.validation_notes} />
        <ListBlock label="Policy constraints" items={decision.policy_constraints} />
        <div className="rounded-md bg-slate-50 p-4">
          <p className="font-semibold">Dry-run result</p>
          <p className="mt-1 text-slate-600">{result.result.message}</p>
          <p className="mt-2 text-xs font-medium uppercase text-slate-500">Status: {result.result.status}</p>
        </div>
      </div>
    </div>
  );
}

function TextBlock({ label, value }: { label: string; value: string }) { return <div><p className="font-semibold">{label}</p><p className="mt-1 leading-6 text-slate-600">{value}</p></div>; }
function ListBlock({ label, items }: { label: string; items: string[] }) { return <div><p className="font-semibold">{label}</p><ul className="mt-1 list-disc space-y-1 pl-5 text-slate-600">{items.map((item) => <li key={item}>{item}</li>)}</ul></div>; }
function formatCurrency(value: number) { return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value); }
function formatTimestamp(value: string | null | undefined) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not recorded";
  return date.toLocaleString();
}
