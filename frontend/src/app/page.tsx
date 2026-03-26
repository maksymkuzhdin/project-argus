import Link from "next/link";
import { fetchDeclarations, fetchStats, type DeclarationSummary } from "@/lib/api";
import RuleDistributionChart from "@/components/RuleDistributionChart";

export const revalidate = 0; // Disable static rendering for the dashboard

// Helper: Build a map of user_declarant_id -> set of years they have declarations for
function getMultiYearEligibility(declarations: DeclarationSummary[]): Set<number> {
  const yearsByPerson = new Map<number, Set<number>>();
  
  for (const decl of declarations) {
    if (decl.user_declarant_id && decl.declaration_year) {
      if (!yearsByPerson.has(decl.user_declarant_id)) {
        yearsByPerson.set(decl.user_declarant_id, new Set());
      }
      yearsByPerson.get(decl.user_declarant_id)!.add(decl.declaration_year);
    }
  }
  
  // Return set of user_declarant_ids that have 2+ years of data
  const eligible = new Set<number>();
  for (const [uid, years] of yearsByPerson) {
    if (years.size >= 2) {
      eligible.add(uid);
    }
  }
  return eligible;
}

export default async function Home({ searchParams }: { searchParams: Promise<{ page?: string; query?: string }> }) {
  const resolvedParams = await searchParams;
  const page = parseInt(resolvedParams.page || "1", 10);
  const offset = (page - 1) * 50;
  const query = resolvedParams.query || "";

  let loadError: string | null = null;
  let stats;
  let declarations;

  try {
    stats = await fetchStats();
    declarations = await fetchDeclarations(50, offset, 0, query);
  } catch (err: unknown) {
    loadError = err instanceof Error ? err.message : "Failed to load dashboard data.";
  }

  if (loadError || !stats || !declarations) {
    return (
      <main className="min-h-screen bg-zinc-950 text-zinc-300 font-sans p-8">
        <section className="max-w-7xl mx-auto space-y-6">
          <header className="flex items-end justify-between border-b border-zinc-900 pb-6">
            <div>
              <h1 className="text-3xl font-bold tracking-tight text-zinc-50">Project Argus</h1>
              <p className="text-zinc-500 mt-2">Ukraine asset declaration analysis &amp; anomaly detection</p>
            </div>
          </header>
          <div className="bg-red-900/30 border border-red-700 rounded-xl p-6">
            <h2 className="text-xl font-semibold text-red-300">Unable to load dashboard</h2>
            <p className="text-red-200 text-sm mt-2">{loadError}</p>
          </div>
        </section>
      </main>
    );
  }

  // Build eligibility set by checking across all pages (limited to current page for efficiency)
  const multiYearEligible = getMultiYearEligibility(declarations.items);

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-300 font-sans p-8">
      <section className="max-w-7xl mx-auto space-y-12">
        {/* Disclaimer Banner */}
        <div className="bg-zinc-900/80 border border-zinc-700 rounded-lg px-5 py-3 text-xs text-zinc-400 leading-relaxed">
          <span className="font-semibold text-zinc-300">Disclaimer:</span>{" "}
          This platform surfaces statistical anomalies in public asset declarations.
          Anomalies are not proof of illegality or wrongdoing. All data is sourced from
          publicly available records via the NAZK open API. Flags indicate patterns that
          may warrant further review, not accusations.
        </div>

        {/* Header */}
        <header className="flex items-end justify-between border-b border-zinc-900 pb-6">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-zinc-50">
              Project Argus
            </h1>
            <p className="text-zinc-500 mt-2">
              Ukraine asset declaration analysis &amp; anomaly detection
            </p>
          </div>
          <div className="text-sm text-zinc-600">
            Open Data Transparency Tool
          </div>
        </header>

        {/* Stats Row */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
            <div className="text-zinc-500 text-sm font-medium mb-1">Total Analyzed</div>
            <div className="text-3xl font-semibold text-zinc-100">{stats.total_declarations}</div>
          </div>
          <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
            <div className="text-zinc-500 text-sm font-medium mb-1">Flagged for Review</div>
            <div className="text-3xl font-semibold text-amber-500">{stats.flagged_declarations}</div>
            <div className="text-xs text-zinc-600 mt-1">Score &gt; 0</div>
          </div>
          <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
            <div className="text-zinc-500 text-sm font-medium mb-1">Avg Anomaly Score</div>
            <div className="text-3xl font-semibold text-zinc-100">{stats.average_score.toFixed(3)}</div>
          </div>
        </div>

        {/* Rule Distribution Chart */}
        {Object.keys(stats.rule_distribution).length > 0 && (
          <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
            <h2 className="text-lg font-semibold text-zinc-100 mb-4">Anomaly Rule Distribution</h2>
            <RuleDistributionChart ruleDistribution={stats.rule_distribution} />
          </div>
        )}

        {/* Declarations Table */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold text-zinc-100">Analyzed Declarations</h2>
            <form action="/" method="GET" className="flex gap-2">
              <input type="text" name="query" defaultValue={query} placeholder="Search name or org..." className="bg-zinc-900 border border-zinc-800 rounded-md px-3 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-amber-500" />
              <button type="submit" className="bg-amber-500 text-zinc-950 rounded-md px-4 py-1.5 text-sm font-medium hover:bg-amber-400 transition-colors">Search</button>
            </form>
          </div>

          <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl overflow-hidden" data-testid="declarations-list">
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-900 text-zinc-500 border-b border-zinc-800">
                <tr>
                  <th className="px-6 py-4 font-medium">Declarant</th>
                  <th className="px-6 py-4 font-medium">Institution / Role</th>
                  <th className="px-6 py-4 font-medium text-right">Income</th>
                  <th className="px-6 py-4 font-medium text-right">Assets</th>
                  <th className="px-6 py-4 font-medium text-center">Flags</th>
                  <th className="px-6 py-4 font-medium text-right">Score</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/50">
                {declarations.items.map((decl) => (
                  <tr key={decl.declaration_id} className="hover:bg-zinc-800/20 transition-colors">
                    <td className="px-6 py-4">
                      <Link
                        href={`/declaration?id=${decl.declaration_id}`}
                        className="font-medium text-blue-400 hover:text-blue-300 transition-colors"
                        data-testid={`declaration-link-${decl.declaration_id}`}
                      >
                        {decl.name}
                      </Link>
                      {decl.user_declarant_id && multiYearEligible.has(decl.user_declarant_id) ? (
                        <div className="mt-1">
                          <Link
                            href={`/person/${decl.user_declarant_id}`}
                            className="text-xs text-amber-400 hover:text-amber-300 transition-colors"
                          >
                            Open multi-year profile
                          </Link>
                        </div>
                      ) : null}
                      <div className="text-xs text-zinc-600 font-mono mt-1">
                        {decl.declaration_id.split("-")[0]}...
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-zinc-300">{decl.institution || "—"}</div>
                      <div className="text-zinc-500 text-xs mt-1">{decl.role || "—"}</div>
                    </td>
                    <td className="px-6 py-4 text-right tabular-nums">
                      {decl.total_income ? `${Number(decl.total_income).toLocaleString()}` : "—"}
                    </td>
                    <td className="px-6 py-4 text-right tabular-nums">
                      {decl.total_assets ? `${Number(decl.total_assets).toLocaleString()}` : "—"}
                    </td>
                    <td className="px-6 py-4 text-center">
                      {decl.triggered_rules.length > 0 ? (
                        <span className="inline-flex items-center justify-center bg-amber-500/10 text-amber-500 border border-amber-500/20 rounded-full px-2.5 py-0.5 text-xs font-medium">
                          {decl.triggered_rules.length} flags
                        </span>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className={`font-mono font-medium ${decl.score > 0 ? "text-amber-500" : "text-emerald-500"}`}>
                        {decl.score.toFixed(3)}
                      </div>
                    </td>
                  </tr>
                ))}

                {declarations.items.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-6 py-12 text-center text-zinc-500">
                      {query ? "No declarations match this search." : "No declarations processed yet."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between pt-4">
          <div className="text-sm text-zinc-500">
            Showing <span className="text-zinc-300 font-medium">{declarations.items.length > 0 ? offset + 1 : 0}</span> to <span className="text-zinc-300 font-medium">{offset + declarations.items.length}</span> of <span className="text-zinc-300 font-medium">{declarations.total}</span>
          </div>
          <div className="flex gap-2 text-sm font-medium">
            {page > 1 ? (
              <Link href={`/?page=${page - 1}${query ? `&query=${encodeURIComponent(query)}` : ''}`} className="px-4 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-zinc-300 hover:bg-zinc-800 transition-colors cursor-pointer">
                Previous
              </Link>
            ) : (
              <span className="px-4 py-2 bg-zinc-900/50 border border-zinc-800/50 rounded-lg text-zinc-600 cursor-not-allowed">
                Previous
              </span>
            )}

            {offset + declarations.items.length < declarations.total ? (
              <Link href={`/?page=${page + 1}${query ? `&query=${encodeURIComponent(query)}` : ''}`} className="px-4 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-zinc-300 hover:bg-zinc-800 transition-colors cursor-pointer">
                Next
              </Link>
            ) : (
              <span className="px-4 py-2 bg-zinc-900/50 border border-zinc-800/50 rounded-lg text-zinc-600 cursor-not-allowed">
                Next
              </span>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
