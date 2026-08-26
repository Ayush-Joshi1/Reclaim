const metrics = [
  { label: "Revenue at Risk", value: "$12,480" },
  { label: "Revenue Recovered", value: "$3,240" },
  { label: "Recovery Rate", value: "26%" },
  { label: "Payments Analyzed", value: "1,284" },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-slate-50 px-6 py-12 text-slate-900 sm:px-10">
      <section className="mx-auto max-w-6xl">
        <header className="mb-10">
          <p className="text-sm font-medium text-slate-500">Revenue recovery dashboard</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">Reclaim</h1>
        </header>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {metrics.map((metric) => (
            <article
              className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm"
              key={metric.label}
            >
              <p className="text-sm text-slate-500">{metric.label}</p>
              <p className="mt-3 text-2xl font-semibold tracking-tight">{metric.value}</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
