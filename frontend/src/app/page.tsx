"use client";

import { FormEvent, useEffect, useState } from "react";
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
  paymentId: "pay_demo_001",
  amount: "125000",
  currency: "INR",
  paymentMethod: "card" as PaymentMethod,
  failureReason: "insufficient_funds",
  failedAt: initialTimestamp,
  timeSinceFailureHours: "2",
  recoveryAttemptCount: "0",
};

export default function Home() {
  const [form, setForm] = useState(initialForm);
  const [result, setResult] = useState<RecoveryWorkflowResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [history, setHistory] = useState<RecoveryHistoryRecord[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [summary, setSummary] = useState<RecoverySummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  async function loadHistory() {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      setHistory(await fetchRecoveryHistory());
    } catch (historyFetchError) {
      setHistoryError(historyFetchError instanceof Error ? historyFetchError.message : "Recovery history failed.");
    } finally {
      setHistoryLoading(false);
    }
  }

  async function loadSummary() {
    setSummaryError(null);
    try {
      setSummary(await fetchRecoverySummary());
    } catch (summaryFetchError) {
      setSummaryError(summaryFetchError instanceof Error ? summaryFetchError.message : "Recovery summary failed.");
    }
  }

  useEffect(() => {
    void fetchRecoveryHistory()
      .then((records) => {
        setHistory(records);
      })
      .catch((historyFetchError: unknown) => {
        setHistoryError(historyFetchError instanceof Error ? historyFetchError.message : "Recovery history failed.");
      })
      .finally(() => {
        setHistoryLoading(false);
      });
  }, []);

  useEffect(() => {
    void fetchRecoverySummary()
      .then((loadedSummary) => {
        setSummary(loadedSummary);
      })
      .catch((summaryFetchError: unknown) => {
        setSummaryError(summaryFetchError instanceof Error ? summaryFetchError.message : "Recovery summary failed.");
      });
  }, []);

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
    <main className="min-h-screen bg-slate-50 px-6 py-12 text-slate-900 sm:px-10">
      <section className="mx-auto max-w-6xl">
        <header className="mb-10">
          <p className="text-sm font-medium text-slate-500">Revenue recovery dashboard</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">Reclaim</h1>
        </header>

        <div className="grid gap-6 lg:grid-cols-[minmax(280px,0.8fr)_minmax(0,1.2fr)]">
          <form onSubmit={handleSubmit} className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
            <div className="mb-6">
              <h2 className="text-lg font-semibold">Evaluate a payment</h2>
              <p className="mt-1 text-sm text-slate-500">Run a dry-run recovery decision using backend policy.</p>
            </div>
            <div className="space-y-4">
              <label className="block text-sm font-medium">Payment ID<input required value={form.paymentId} onChange={(event) => updateField("paymentId", event.target.value)} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm" /></label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm font-medium">Amount<input required min="0" type="number" value={form.amount} onChange={(event) => updateField("amount", event.target.value)} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm" /></label>
                <label className="block text-sm font-medium">Currency<input required minLength={3} maxLength={3} value={form.currency} onChange={(event) => updateField("currency", event.target.value.toUpperCase())} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm uppercase" /></label>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm font-medium">Payment method<select value={form.paymentMethod} onChange={(event) => updateField("paymentMethod", event.target.value)} className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"><option value="card">Card</option><option value="upi">UPI</option><option value="netbanking">Netbanking</option><option value="wallet">Wallet</option></select></label>
                <label className="block text-sm font-medium">Attempts<input required min="0" type="number" value={form.recoveryAttemptCount} onChange={(event) => updateField("recoveryAttemptCount", event.target.value)} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm" /></label>
              </div>
              <label className="block text-sm font-medium">Failed at (UTC)<input required type="datetime-local" value={form.failedAt} onChange={(event) => updateField("failedAt", event.target.value)} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm" /></label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm font-medium">Hours since failure<input required min="0" type="number" value={form.timeSinceFailureHours} onChange={(event) => updateField("timeSinceFailureHours", event.target.value)} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm" /></label>
                <label className="block text-sm font-medium">Failure reason<input value={form.failureReason} onChange={(event) => updateField("failureReason", event.target.value)} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm" /></label>
              </div>
            </div>
            <button disabled={isLoading} type="submit" className="mt-6 w-full rounded-md bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-400">{isLoading ? "Evaluating..." : "Evaluate recovery"}</button>
          </form>

          <section className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm" aria-live="polite">
            {!result && !error && <div className="flex min-h-64 items-center justify-center text-center text-sm text-slate-500">Submit an event to see the validated recovery decision.</div>}
            {error && <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"><p className="font-semibold">Evaluation failed</p><p className="mt-1">{error}</p></div>}
            {result && <DecisionResult result={result} />}
          </section>
        </div>
        <section className="mt-8 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-4">
            <div><p className="text-sm text-slate-500">Operational view</p><h2 className="mt-1 text-lg font-semibold">Recovery summary</h2></div>
            <button type="button" onClick={() => { void loadSummary(); void loadHistory(); }} disabled={historyLoading} className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-50">Refresh data</button>
          </div>
          {summaryError && <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800">{summaryError}</div>}
          {!summaryError && !summary && <p className="py-8 text-center text-sm text-slate-500">Loading operational summary...</p>}
          {summary && <><dl className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[["Evaluations", summary.total_evaluations], ["Successful", summary.total_successful_executions], ["Failed", summary.total_failed_executions], ["Dry run", summary.total_dry_run_executions]].map(([label, value]) => <div key={label}><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt><dd className="mt-1 text-2xl font-semibold">{value}</dd></div>)}</dl><div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-sm text-slate-600"><span>RETRY {summary.retry_count}</span><span>PAYMENT_LINK {summary.payment_link_count}</span><span>REMINDER {summary.reminder_count}</span><span>ESCALATE {summary.escalate_count}</span><span>STOP {summary.stop_count}</span></div></>}
        </section>
        <section className="mt-8 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-4">
            <div><p className="text-sm text-slate-500">Persisted activity</p><h2 className="mt-1 text-lg font-semibold">Recovery history</h2></div>
            <button type="button" onClick={() => void loadHistory()} disabled={historyLoading} className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-50">{historyLoading ? "Loading..." : "Refresh"}</button>
          </div>
          {historyError && <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800">{historyError}</div>}
          {!historyLoading && !historyError && history.length === 0 && <p className="py-8 text-center text-sm text-slate-500">No persisted recovery activity yet.</p>}
          {!historyLoading && !historyError && history.length > 0 && <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-3 py-3">Payment ID</th><th className="px-3 py-3">Action</th><th className="px-3 py-3">Status</th><th className="px-3 py-3">Amount</th><th className="px-3 py-3">Attempt</th><th className="px-3 py-3">Event ID</th><th className="px-3 py-3">Created</th><th className="px-3 py-3">Completed</th></tr></thead><tbody>{history.map((record) => <tr key={record.event_id ?? `${record.payment_id}-${record.created_at}`} className="border-b border-slate-100 last:border-0"><td className="px-3 py-3 font-mono text-xs">{record.payment_id}</td><td className="px-3 py-3 font-semibold">{record.action}</td><td className="px-3 py-3">{record.status}</td><td className="px-3 py-3">{record.amount}</td><td className="px-3 py-3">{record.attempt_number ?? "-"}</td><td className="px-3 py-3 font-mono text-xs">{record.event_id ?? "-"}</td><td className="px-3 py-3 whitespace-nowrap">{formatTimestamp(record.created_at)}</td><td className="px-3 py-3 whitespace-nowrap">{record.completed_at ? formatTimestamp(record.completed_at) : "-"}</td></tr>)}</tbody></table></div>}
        </section>
      </section>
    </main>
  );
}

function DecisionResult({ result }: { result: RecoveryWorkflowResponse }) {
  const decision = result.decision;
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

  return <div>
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 pb-5"><div><p className="text-sm text-slate-500">Validated recovery decision</p><h2 className="mt-1 text-2xl font-semibold">{result.action}</h2></div><span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">DRY RUN</span></div>
    <dl className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{details.map(([label, value]) => <div key={label}><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt><dd className="mt-1 text-sm font-semibold">{value}</dd></div>)}</dl>
    <div className="mt-6 space-y-5 text-sm"><TextBlock label="Diagnosis" value={decision.diagnosis} /><TextBlock label="Reasoning" value={decision.reasoning} /><TextBlock label="Expected outcome" value={decision.expected_outcome} /><ListBlock label="Risk factors" items={decision.validation_notes} /><ListBlock label="Policy constraints" items={decision.policy_constraints} /><div className="rounded-md bg-slate-50 p-4"><p className="font-semibold">Dry-run result</p><p className="mt-1 text-slate-600">{result.result.message}</p><p className="mt-2 text-xs font-medium uppercase text-slate-500">Status: {result.result.status}</p></div></div>
  </div>;
}

function TextBlock({ label, value }: { label: string; value: string }) { return <div><p className="font-semibold">{label}</p><p className="mt-1 leading-6 text-slate-600">{value}</p></div>; }
function ListBlock({ label, items }: { label: string; items: string[] }) { return <div><p className="font-semibold">{label}</p><ul className="mt-1 list-disc space-y-1 pl-5 text-slate-600">{items.map((item) => <li key={item}>{item}</li>)}</ul></div>; }
function formatTimestamp(value: string) { return new Date(value).toLocaleString(); }
