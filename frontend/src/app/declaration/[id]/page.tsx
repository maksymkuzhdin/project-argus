import Link from "next/link";
import { fetchDeclaration, type DeclarationDetail } from "@/lib/api";
import IncomeAssetsChart from "@/components/IncomeAssetsChart";
import ScoreBreakdownChart from "@/components/ScoreBreakdownChart";
import { getScoreBand } from "@/lib/scoreBands";

export const revalidate = 0;

function formatField(field: unknown): string {
    if (field === null || field === undefined) return "";
    if (typeof field === "object") {
        if (Array.isArray(field)) {
            return field.map(f => formatField(f)).join(", ");
        }
        if ('value' in field || 'status' in field) {
            const valueField = (field as Record<string, unknown>).value;
            const statusField = (field as Record<string, unknown>).status;
            const val = valueField !== null && valueField !== undefined ? valueField : `[${String(statusField || 'unknown')}]`;
            return Array.isArray(val) || typeof val === 'object' ? JSON.stringify(val) : String(val);
        }
        try {
            return JSON.stringify(field);
        } catch {
            return "[Complex Object]";
        }
    }
    return String(field);
}

function composeDeclarantName(bio: DeclarationDetail["bio"]): string {
    return [bio.lastname, bio.firstname, bio.middlename]
        .map((part) => formatField(part).trim())
        .filter(Boolean)
        .join(" ");
}

export default async function DeclarationDetail({ params }: { params: Promise<{ id: string }> }) {
    const resolvedParams = await params;
    let data: DeclarationDetail | null = null;
    let renderError: string | null = null;

    try {
        data = await fetchDeclaration(resolvedParams.id);
    } catch (e: unknown) {
        renderError = e instanceof Error ? e.message : String(e);
    }

    if (renderError || !data) {
        return (
            <div className="min-h-screen bg-zinc-950 text-zinc-300 font-sans p-8" data-testid="error">
                <div className="max-w-5xl mx-auto space-y-4">
                    <Link href="/" className="text-sm text-zinc-500 hover:text-zinc-300">&larr; Back</Link>
                    <div className="bg-red-900/30 border border-red-700 rounded-xl p-6">
                        <h1 className="text-xl font-bold text-red-400 mb-2">Error loading declaration</h1>
                        <p className="font-mono text-xs text-red-300 whitespace-pre-wrap">{renderError}</p>
                    </div>
                </div>
            </div>
        );
    }

    const summary = data.summary;
    const bio = data.bio;
    const rawMetadata = data.raw_metadata;
    const scoreBand = getScoreBand(Number(summary.score || 0));
    const recordId = formatField(resolvedParams.id);
    const nazkRecordUrl = `https://public.nazk.gov.ua/documents/${encodeURIComponent(recordId)}`;

    return (
        <div className="min-h-screen bg-zinc-950 text-zinc-300 font-sans p-8">
            <div className="max-w-5xl mx-auto space-y-8">

                {/* Navigation */}
                <nav>
                    <Link href="/" className="text-sm font-medium text-zinc-500 hover:text-zinc-300 transition-colors flex items-center gap-2">
                        &larr; Back to Dashboard
                    </Link>
                </nav>

                {/* Disclaimer Banner */}
                <div className="bg-zinc-900/80 border border-zinc-700 rounded-lg px-5 py-3 text-xs text-zinc-400 leading-relaxed">
                    <span className="font-semibold text-zinc-300">Disclaimer:</span>{" "}
                    Anomalies shown below are statistical patterns, not evidence of illegality.
                    This tool surfaces data inconsistencies for further human review.
                    All data is from publicly available NAZK records.
                </div>

                {/* Header */}
                <header className="border-b border-zinc-900 pb-8">
                    <div className="flex justify-between items-start">
                        <div>
                            <h1 className="text-3xl font-bold tracking-tight text-zinc-50 mb-2">
                                {composeDeclarantName(bio)}
                            </h1>
                            <div className="text-lg text-zinc-400">{formatField(bio.work_post)}</div>
                            <div className="text-zinc-500">{formatField(bio.work_place)}</div>
                            {data.user_declarant_id ? (
                                <Link
                                    href={`/person/${data.user_declarant_id}`}
                                    className="inline-block mt-3 text-sm text-amber-400 hover:text-amber-300 transition-colors"
                                >
                                    View multi-year timeline
                                </Link>
                            ) : null}
                        </div>
                        <div className="text-right">
                            <div className="text-sm text-zinc-500 mb-1">Anomaly Score</div>
                            <div className={`text-4xl font-mono font-bold ${scoreBand.textClass}`}>
                                {Number(summary.score || 0).toFixed(1)}
                            </div>
                            <div className="mt-2">
                                <span className={`inline-flex items-center justify-center rounded-full px-2.5 py-0.5 text-xs font-medium ${scoreBand.badgeClass}`}>
                                    {scoreBand.label}
                                </span>
                            </div>
                        </div>
                    </div>

                    <div className="flex gap-4 mt-6 text-sm">
                        <div className="bg-zinc-900 border border-zinc-800 rounded-md px-3 py-1.5 flex items-center gap-2">
                            <span className="text-zinc-500">Year</span>
                            <span className="text-zinc-300 font-medium">{formatField(rawMetadata.year)}</span>
                        </div>
                        <div className="bg-zinc-900 border border-zinc-800 rounded-md px-3 py-1.5 flex items-center gap-2">
                            <span className="text-zinc-500">ID</span>
                            <span className="text-zinc-300 font-mono text-xs">{recordId}</span>
                        </div>
                        <div className="bg-zinc-900 border border-zinc-800 rounded-md px-3 py-1.5">
                            <a
                                href={nazkRecordUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-amber-400 hover:text-amber-300 transition-colors font-medium"
                            >
                                View on NACP
                            </a>
                        </div>
                    </div>
                </header>

                {/* Scoring & Anomalies */}
                <section data-testid="score-section">
                    <h2 className="text-xl font-semibold text-zinc-100 mb-4">Anomaly Analysis</h2>
                    <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
                        {Array.isArray(summary.triggered_rules) && summary.triggered_rules.length > 0 ? (
                            <div className="space-y-4" data-testid="rule-section">
                                <div className="flex items-center gap-2 text-amber-500 font-medium mb-4">
                                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                                    </svg>
                                    {summary.triggered_rules.length} flags detected
                                </div>
                                <div className="space-y-3">
                                    {formatField(summary.explanation).split("\n").map((line, i) => (
                                        <div key={i} className="text-zinc-300 bg-zinc-900 rounded p-4 border border-zinc-800/50">
                                            {line.replace("• ", "")}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        ) : (
                            <div className="flex items-center gap-2 text-emerald-500 font-medium">
                                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                </svg>
                                No deterministic anomaly signals detected.
                            </div>
                        )}
                    </div>
                </section>

                {/* Financial Summary */}
                <section>
                    <h2 className="text-xl font-semibold text-zinc-100 mb-4">Financial Summary</h2>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="bg-zinc-900/30 border border-zinc-800 rounded-xl p-6">
                            <div className="text-sm font-medium text-zinc-500 mb-2">Total Declared Income</div>
                            <div className="text-3xl font-mono text-zinc-100 mb-4">
                                {summary.total_income ? Number(formatField(summary.total_income)).toLocaleString() : "0"}
                            </div>
                            <div className="text-xs text-zinc-600">Across {formatField(data.incomes?.length || 0)} reported sources</div>
                        </div>

                        <div className="bg-zinc-900/30 border border-zinc-800 rounded-xl p-6">
                            <div className="text-sm font-medium text-zinc-500 mb-2">Total Monetary Assets & Acquisitions</div>
                            <div className="text-3xl font-mono text-zinc-100 mb-4">
                                {summary.total_assets ? Number(formatField(summary.total_assets)).toLocaleString() : "0"}
                            </div>
                            <div className="text-xs text-zinc-600">{formatField(data.monetary?.length || 0)} monetary items + {formatField(data.real_estate?.length || 0)} properties</div>
                        </div>
                    </div>
                </section>

                {/* Charts */}
                <section>
                    <h2 className="text-xl font-semibold text-zinc-100 mb-4">Visual Analysis</h2>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div className="bg-zinc-900/30 border border-zinc-800 rounded-xl p-6">
                            <h3 className="text-sm font-medium text-zinc-500 mb-4">Income vs Assets</h3>
                            <IncomeAssetsChart
                                totalIncome={summary.total_income ? Number(formatField(summary.total_income)) : 0}
                                totalAssets={summary.total_assets ? Number(formatField(summary.total_assets)) : 0}
                                incomeCount={data.incomes?.length || 0}
                                monetaryCount={data.monetary?.length || 0}
                                realEstateCount={data.real_estate?.length || 0}
                            />
                        </div>
                        <div className="bg-zinc-900/30 border border-zinc-800 rounded-xl p-6">
                            <h3 className="text-sm font-medium text-zinc-500 mb-4">Score Breakdown by Rule</h3>
                            <ScoreBreakdownChart
                                ruleDetails={summary.rule_details || []}
                                totalScore={summary.score || 0}
                            />
                        </div>
                    </div>
                </section>

                {/* Family Members */}
                {Array.isArray(data.family_members) && data.family_members.length > 0 && (
                    <section>
                        <h2 className="text-xl font-semibold text-zinc-100 mb-4">Family Members</h2>
                        <div className="bg-zinc-900/30 border border-zinc-800 rounded-xl overflow-hidden">
                            <table className="w-full text-left text-sm text-zinc-400">
                                <thead className="bg-zinc-900/50 text-zinc-500 border-b border-zinc-800">
                                    <tr>
                                        <th className="px-6 py-3 font-medium">Relation</th>
                                        <th className="px-6 py-3 font-medium">Name</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800/50">
                                    {data.family_members.map((member: Record<string, unknown>, i: number) => (
                                        <tr key={i} className="hover:bg-zinc-800/20 transition-colors">
                                            <td className="px-6 py-3">{formatField(member.relation)}</td>
                                            <td className="px-6 py-3">{formatField(member.lastname)} {formatField(member.firstname)} {formatField(member.middlename)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </section>
                )}

                {/* Real Estate */}
                {Array.isArray(data.real_estate) && data.real_estate.length > 0 && (
                    <section>
                        <h2 className="text-xl font-semibold text-zinc-100 mb-4">Real Estate</h2>
                        <div className="bg-zinc-900/30 border border-zinc-800 rounded-xl overflow-hidden">
                            <table className="w-full text-left text-sm text-zinc-400">
                                <thead className="bg-zinc-900/50 text-zinc-500 border-b border-zinc-800">
                                    <tr>
                                        <th className="px-6 py-3 font-medium">Type</th>
                                        <th className="px-6 py-3 font-medium">Area (m²)</th>
                                        <th className="px-6 py-3 font-medium">Location</th>
                                        <th className="px-6 py-3 font-medium">Owner</th>
                                        <th className="px-6 py-3 font-medium">Ownership Type</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800/50">
                                    {data.real_estate.map((item: Record<string, unknown>, i: number) => (
                                        <tr key={i} className="hover:bg-zinc-800/20 transition-colors">
                                            <td className="px-6 py-3">{formatField(item.object_type)}</td>
                                            <td className="px-6 py-3 font-mono">{formatField(item.total_area)}</td>
                                            <td className="px-6 py-3">{formatField(item.city)} {item.region && formatField(item.region) !== "" ? `(${formatField(item.region)})` : ""}</td>
                                            <td className="px-6 py-3 text-emerald-400/80">{formatField(item.right_belongs_resolved)}</td>
                                            <td className="px-6 py-3">{formatField(item.ownership_type)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </section>
                )}

                {/* Vehicles */}
                {Array.isArray(data.vehicles) && data.vehicles.length > 0 && (
                    <section>
                        <h2 className="text-xl font-semibold text-zinc-100 mb-4">Vehicles</h2>
                        <div className="bg-zinc-900/30 border border-zinc-800 rounded-xl overflow-hidden">
                            <table className="w-full text-left text-sm text-zinc-400">
                                <thead className="bg-zinc-900/50 text-zinc-500 border-b border-zinc-800">
                                    <tr>
                                        <th className="px-6 py-3 font-medium">Brand & Model</th>
                                        <th className="px-6 py-3 font-medium">Year</th>
                                        <th className="px-6 py-3 font-medium">Owner</th>
                                        <th className="px-6 py-3 font-medium">Ownership Type</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800/50">
                                    {data.vehicles.map((item: Record<string, unknown>, i: number) => (
                                        <tr key={i} className="hover:bg-zinc-800/20 transition-colors">
                                            <td className="px-6 py-3 text-zinc-300">{formatField(item.brand)} {formatField(item.model)}</td>
                                            <td className="px-6 py-3 font-mono">{formatField(item.graduation_year)}</td>
                                            <td className="px-6 py-3 text-emerald-400/80">{formatField(item.right_belongs_resolved)}</td>
                                            <td className="px-6 py-3">{formatField(item.ownership_type)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </section>
                )}

                {/* Bank Accounts */}
                {Array.isArray(data.bank_accounts) && data.bank_accounts.length > 0 && (
                    <section>
                        <h2 className="text-xl font-semibold text-zinc-100 mb-4">Bank Accounts</h2>
                        <div className="bg-zinc-900/30 border border-zinc-800 rounded-xl overflow-hidden">
                            <table className="w-full text-left text-sm text-zinc-400">
                                <thead className="bg-zinc-900/50 text-zinc-500 border-b border-zinc-800">
                                    <tr>
                                        <th className="px-6 py-3 font-medium">Institution</th>
                                        <th className="px-6 py-3 font-medium">Owner</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800/50">
                                    {data.bank_accounts.map((item: Record<string, unknown>, i: number) => (
                                        <tr key={i} className="hover:bg-zinc-800/20 transition-colors">
                                            <td className="px-6 py-3">{formatField(item.institution_name)}</td>
                                            <td className="px-6 py-3 text-emerald-400/80">{formatField(item.account_owner_resolved)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </section>
                )}

                {/* Incomes */}
                {Array.isArray(data.incomes) && data.incomes.length > 0 && (
                    <section>
                        <h2 className="text-xl font-semibold text-zinc-100 mb-4">Incomes</h2>
                        <div className="bg-zinc-900/30 border border-zinc-800 rounded-xl overflow-hidden">
                            <table className="w-full text-left text-sm text-zinc-400">
                                <thead className="bg-zinc-900/50 text-zinc-500 border-b border-zinc-800">
                                    <tr>
                                        <th className="px-6 py-3 font-medium">Type</th>
                                        <th className="px-6 py-3 font-medium">Source</th>
                                        <th className="px-6 py-3 font-medium text-right">Amount (UAH)</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800/50">
                                    {data.incomes.map((item: Record<string, unknown>, i: number) => (
                                        <tr key={i} className="hover:bg-zinc-800/20 transition-colors">
                                            <td className="px-6 py-3">{formatField(item.income_type)}</td>
                                            <td className="px-6 py-3 line-clamp-2" title={String(formatField(item.source_name))}>{formatField(item.source_name)}</td>
                                            <td className="px-6 py-3 text-right font-mono text-zinc-300">
                                                {item.amount ? (typeof item.amount === 'object' ? formatField(item.amount) : Number(formatField(item.amount)).toLocaleString()) : ""}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </section>
                )}

                {/* Monetary Assets */}
                {Array.isArray(data.monetary) && data.monetary.length > 0 && (
                    <section>
                        <h2 className="text-xl font-semibold text-zinc-100 mb-4">Monetary Assets</h2>
                        <div className="bg-zinc-900/30 border border-zinc-800 rounded-xl overflow-hidden">
                            <table className="w-full text-left text-sm text-zinc-400">
                                <thead className="bg-zinc-900/50 text-zinc-500 border-b border-zinc-800">
                                    <tr>
                                        <th className="px-6 py-3 font-medium">Type</th>
                                        <th className="px-6 py-3 font-medium">Organization</th>
                                        <th className="px-6 py-3 font-medium text-right">Amount</th>
                                        <th className="px-6 py-3 font-medium">Currency</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800/50">
                                    {data.monetary.map((item: Record<string, unknown>, i: number) => (
                                        <tr key={i} className="hover:bg-zinc-800/20 transition-colors">
                                            <td className="px-6 py-3">{formatField(item.asset_type)}</td>
                                            <td className="px-6 py-3">
                                                {formatField(item.organization)}
                                            </td>
                                            <td className="px-6 py-3 text-right font-mono text-zinc-300">
                                                {item.amount ? (typeof item.amount === 'object' ? formatField(item.amount) : Number(formatField(item.amount)).toLocaleString()) : ""}
                                            </td>
                                            <td className="px-6 py-3">{formatField(item.currency_code)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </section>
                )}

            </div>
        </div>
    );
}
