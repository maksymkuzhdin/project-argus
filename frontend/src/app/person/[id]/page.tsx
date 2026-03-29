import Link from "next/link";
import { fetchPersonTimeline } from "@/lib/api";
import { getScoreBand } from "@/lib/scoreBands";

export const revalidate = 0;

function formatMoney(value: string | null): string {
  if (!value) return "-";
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return n.toLocaleString();
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return `${(value * 100).toFixed(1)}%`;
}

function declarationTypeLabel(value: number | null): string {
  if (value === 1) return "Annual";
  if (value === 2) return "Initial";
  if (value === 3) return "Cessation";
  return "Other";
}

export default async function PersonTimelinePage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = await params;
  const personId = Number(resolvedParams.id);

  if (!Number.isInteger(personId) || personId <= 0) {
    return (
      <main className="min-h-screen bg-zinc-950 text-zinc-300 font-sans p-8">
        <section className="max-w-6xl mx-auto space-y-4">
          <Link href="/" className="text-sm text-zinc-500 hover:text-zinc-300">&larr; Back to Dashboard</Link>
          <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
            <h1 className="text-xl font-semibold text-zinc-100">Invalid person ID</h1>
            <p className="text-zinc-400 mt-2">Open this page from a declaration row or profile link.</p>
          </div>
        </section>
      </main>
    );
  }

  let data;
  let loadError: string | null = null;
  try {
    data = await fetchPersonTimeline(personId);
  } catch (err: unknown) {
    loadError = err instanceof Error ? err.message : "Failed to load person timeline.";
  }

  if (loadError || !data) {
    return (
      <main className="min-h-screen bg-zinc-950 text-zinc-300 font-sans p-8">
        <section className="max-w-6xl mx-auto space-y-4">
          <Link href="/" className="text-sm text-zinc-500 hover:text-zinc-300">&larr; Back to Dashboard</Link>
          <div className="bg-red-900/30 border border-red-700 rounded-xl p-6">
            <h1 className="text-xl font-semibold text-red-300">Unable to load timeline</h1>
            <p className="text-red-200 text-sm mt-2">{loadError}</p>
          </div>
        </section>
      </main>
    );
  }

  const scoreBand = getScoreBand(data.timeline_score.total_score);

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-300 font-sans p-8">
      <section className="max-w-6xl mx-auto space-y-8">
        <nav className="flex items-center gap-4 text-sm">
          <Link href="/" className="text-zinc-500 hover:text-zinc-300">&larr; Back to Dashboard</Link>
        </nav>

        <header className="border-b border-zinc-900 pb-6">
          <h1 className="text-3xl font-bold text-zinc-50 tracking-tight">{data.name || "Unknown Official"}</h1>
          <p className="text-zinc-500 mt-2">Multi-year declaration timeline (ID: {data.user_declarant_id})</p>
        </header>

        <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
          <h2 className="text-lg font-semibold text-zinc-100 mb-3">Timeline Score</h2>
          <div className={`text-4xl font-mono font-bold ${scoreBand.textClass}`}>{data.timeline_score.total_score.toFixed(1)}</div>
          <div className="mt-2">
            <span className={`inline-flex items-center justify-center rounded-full px-2.5 py-0.5 text-xs font-medium ${scoreBand.badgeClass}`}>
              {scoreBand.label}
            </span>
          </div>
          {data.timeline_score.triggered_rules.length > 0 ? (
            <ul className="mt-4 text-sm text-zinc-300 space-y-2">
              {data.timeline_score.triggered_rules.map((rule) => (
                <li key={rule} className="bg-zinc-900 border border-zinc-800 rounded-md px-3 py-2">{rule}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-emerald-400">No multi-year anomaly rules triggered.</p>
          )}
        </div>

        <section className="space-y-3" data-testid="timeline">
          <h2 className="text-xl font-semibold text-zinc-100">Yearly Snapshots</h2>
          <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-900 text-zinc-500 border-b border-zinc-800">
                <tr>
                  <th className="px-4 py-3">Year</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Income</th>
                  <th className="px-4 py-3">Monetary</th>
                  <th className="px-4 py-3">Real Estate</th>
                  <th className="px-4 py-3">Total Assets</th>
                  <th className="px-4 py-3">Cash / Bank</th>
                  <th className="px-4 py-3">Unknown Share</th>
                  <th className="px-4 py-3">Counts (I/M/RE/V)</th>
                  <th className="px-4 py-3">Role / Institution</th>
                  <th className="px-4 py-3">Declaration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/50">
                {data.snapshots.map((snap) => (
                  <tr key={snap.declaration_id} className="hover:bg-zinc-800/20 transition-colors">
                    <td className="px-4 py-3 font-mono">{snap.declaration_year}</td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center justify-center rounded-full px-2 py-0.5 text-xs font-medium bg-zinc-800 text-zinc-300 border border-zinc-700">
                        {declarationTypeLabel(snap.declaration_type)}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono">{formatMoney(snap.total_income)}</td>
                    <td className="px-4 py-3 font-mono">{formatMoney(snap.total_monetary)}</td>
                    <td className="px-4 py-3 font-mono">{formatMoney(snap.total_real_estate)}</td>
                    <td className="px-4 py-3 font-mono">{formatMoney(snap.total_assets)}</td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {formatMoney(snap.cash)} / {formatMoney(snap.bank)}
                    </td>
                    <td className="px-4 py-3 font-mono">{formatPercent(snap.unknown_share)}</td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {snap.income_count}/{snap.monetary_count}/{snap.real_estate_count}/{snap.vehicle_count}
                    </td>
                    <td className="px-4 py-3">
                      <div>{snap.role || "-"}</div>
                      <div className="text-xs text-zinc-500">{snap.institution || "-"}</div>
                    </td>
                    <td className="px-4 py-3">
                      <Link href={`/declaration?id=${snap.declaration_id}`} className="text-blue-400 hover:text-blue-300">
                        Open declaration
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {data.changes.length > 0 ? (
          <section className="space-y-3">
            <h2 className="text-xl font-semibold text-zinc-100">Year-over-Year Changes</h2>
            <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-zinc-900 text-zinc-500 border-b border-zinc-800">
                  <tr>
                    <th className="px-4 py-3">Period</th>
                    <th className="px-4 py-3">Income Delta</th>
                    <th className="px-4 py-3">Asset Delta</th>
                    <th className="px-4 py-3">Cash Delta</th>
                    <th className="px-4 py-3">Income Growth</th>
                    <th className="px-4 py-3">Asset Growth</th>
                    <th className="px-4 py-3">Unknown Delta</th>
                    <th className="px-4 py-3">Role Change</th>
                    <th className="px-4 py-3">Major Assets (A/D)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/50">
                  {data.changes.map((chg) => (
                    <tr key={`${chg.from_year}-${chg.to_year}`} className="hover:bg-zinc-800/20 transition-colors">
                      <td className="px-4 py-3 font-mono">{`${chg.from_year} -> ${chg.to_year}`}</td>
                      <td className="px-4 py-3 font-mono">{formatMoney(chg.income_delta)}</td>
                      <td className="px-4 py-3 font-mono">{formatMoney(chg.monetary_delta)}</td>
                      <td className="px-4 py-3 font-mono">{formatMoney(chg.cash_delta)}</td>
                      <td className="px-4 py-3 font-mono">{formatPercent(chg.income_growth)}</td>
                      <td className="px-4 py-3 font-mono">{formatPercent(chg.asset_growth)}</td>
                      <td className="px-4 py-3 font-mono">{formatPercent(chg.unknown_share_delta)}</td>
                      <td className="px-4 py-3 text-xs">
                        {chg.role_changed ? `${chg.role_prev || "-"} -> ${chg.role_curr || "-"}` : "No"}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {chg.major_assets_appeared}/{chg.major_assets_disappeared}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ) : null}

        {data.changes.length > 0 ? (
          <section className="space-y-3">
            <h2 className="text-xl font-semibold text-zinc-100">Major Asset Changes (CR14 Context)</h2>
            <div className="grid gap-3">
              {data.changes.map((chg) => (
                <div
                  key={`asset-${chg.from_year}-${chg.to_year}`}
                  className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-4 text-sm"
                >
                  <div className="text-zinc-300 font-medium">{chg.from_year}{" -> "}{chg.to_year}</div>
                  <div className="mt-2 text-zinc-400">
                    Appeared: <span className="text-zinc-200 font-mono">{chg.major_assets_appeared}</span>
                    {" | "}
                    Disappeared: <span className="text-zinc-200 font-mono">{chg.major_assets_disappeared}</span>
                  </div>
                  <div className="mt-1 text-zinc-500 text-xs">
                    Max appeared value: {formatMoney(chg.max_appeared_value)}
                    {" | "}
                    Max disappeared value: {formatMoney(chg.max_disappeared_value)}
                    {" | "}
                    One-off income (current year): {formatMoney(chg.one_off_income_curr)}
                  </div>
                </div>
              ))}
            </div>
            <p className="text-xs text-zinc-500">
              Growth percentages and unknown-share trends are contextual signals; always review underlying declarations.
            </p>
          </section>
        ) : null}
      </section>
    </main>
  );
}
