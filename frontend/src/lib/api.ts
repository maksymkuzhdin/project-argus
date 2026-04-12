import { E2E_FIXTURE_DATA } from "@/lib/e2eFixtureData";

export const API_URL = typeof window === 'undefined'
    ? process.env.INTERNAL_API_URL || 'http://backend:8000'
    : process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface RuleDetail {
    rule_name: string;
    score: number;
    triggered: boolean;
    explanation: string;
    category?: string | null;
    severity?: string | null;
    confidence?: number | null;
    metadata?: Record<string, unknown> | null;
}

export interface DeclarationSummary {
    declaration_id: string;
    user_declarant_id?: number | null;
    declaration_year?: number;
    family_members: number;
    incomes: number;
    monetary_assets: number;
    real_estate_rights: number;
    total_income: string | null;
    total_assets: string | null;
    confidential_ratio?: number;
    score: number;
    triggered_rules: string[];
    explanation: string;
    name: string;
    role: string;
    institution: string;
    rule_details?: RuleDetail[] | null;
    // Prozorro enrichment (nullable — only present after enrichment has run)
    prozorro_contract_count?: number | null;
    prozorro_total_contract_value?: number | null;
    prozorro_enriched_at?: string | null;
    prozorro_employer_edrpou?: string | null;
    prozorro_employer_name?: string | null;
    // Cohort assignment metadata
    cohort_key?: string | null;
    cohort_sector?: string | null;
    cohort_role_cluster?: string | null;
    cohort_gov_level?: string | null;
    cohort_size?: number | null;
    scoring_layer?: number | null;
}

export interface PaginatedDeclarations {
    items: DeclarationSummary[];
    total: number;
    offset: number;
    limit: number;
}

export interface StatsResponse {
    total_declarations: number;
    flagged_declarations: number;
    average_score: number;
    rule_distribution: Record<string, number>;
}

export interface DeclarationDetail {
    id: string;
    user_declarant_id?: number | null;
    raw_metadata: {
        year: number;
        date: string;
        declaration_type: number;
    };
    family_members: Record<string, unknown>[];
    real_estate: Record<string, unknown>[];
    vehicles: Record<string, unknown>[];
    bank_accounts: Record<string, unknown>[];
    incomes: Record<string, unknown>[];
    monetary: Record<string, unknown>[];
    summary: DeclarationSummary;
    bio: {
        firstname: string;
        middlename?: string;
        lastname: string;
        work_post: string;
        work_place: string;
    };
}

export interface PersonTimelineResponse {
    user_declarant_id: number;
    name: string;
    snapshot_count: number;
    snapshots: {
        declaration_id: string;
        declaration_year: number;
        declaration_type: number | null;
        total_income: string | null;
        total_monetary: string | null;
        total_real_estate: string | null;
        total_assets: string | null;
        cash: string | null;
        bank: string | null;
        unknown_share: number;
        income_count: number;
        monetary_count: number;
        real_estate_count: number;
        vehicle_count: number;
        role: string | null;
        institution: string | null;
    }[];
    changes: {
        from_year: number;
        to_year: number;
        income_prev: string | null;
        income_curr: string | null;
        income_delta: string | null;
        income_ratio: number | null;
        income_growth: number | null;
        monetary_prev: string | null;
        monetary_curr: string | null;
        monetary_delta: string | null;
        monetary_ratio: number | null;
        assets_prev: string | null;
        assets_curr: string | null;
        asset_growth: number | null;
        cash_prev: string | null;
        cash_curr: string | null;
        cash_delta: string | null;
        unknown_share_prev: number;
        unknown_share_curr: number;
        unknown_share_delta: number;
        role_prev: string;
        role_curr: string;
        role_changed: boolean;
        major_assets_appeared: number;
        major_assets_disappeared: number;
        max_appeared_value: string | null;
        max_disappeared_value: string | null;
        one_off_income_curr: string | null;
        // These were added when CR15 was implemented but never added to the TS type
        real_estate_3yr_ratio?: number | null;
        real_estate_value_prev?: string | null;
        real_estate_value_curr?: string | null;
    }[];
    timeline_score: {
        total_score: number;
        triggered_rules: string[];
        explanation: string;
        rule_details: RuleDetail[];
    };
}

// ------------------------------------------------------------------
// API methods
// ------------------------------------------------------------------

const E2E_FIXTURES_ENABLED =
    process.env.NEXT_PUBLIC_E2E_FIXTURES === "1" || process.env.E2E_FIXTURES === "1";

export async function fetchStats(): Promise<StatsResponse> {
    if (E2E_FIXTURES_ENABLED) {
        return E2E_FIXTURE_DATA.stats;
    }
    const res = await fetch(`${API_URL}/api/declarations/stats`, {
        cache: 'no-store',
    });
    if (!res.ok) throw new Error('Failed to fetch stats');
    return res.json();
}

export async function fetchDeclarations(
    limit = 50,
    offset = 0,
    minScore = 0.0,
    query = '',
    sortBy = 'score',
    sortDir = 'desc'
): Promise<PaginatedDeclarations> {
    if (E2E_FIXTURES_ENABLED) {
        const normalizedQuery = query.trim().toLowerCase();
        const filtered = E2E_FIXTURE_DATA.declarations.filter((item) => {
            if (item.score < minScore) return false;
            if (!normalizedQuery) return true;
            return item.name.toLowerCase().includes(normalizedQuery) || item.institution.toLowerCase().includes(normalizedQuery);
        });
        const sorted = [...filtered].sort((a, b) => {
            const direction = sortDir === "asc" ? 1 : -1;
            if (sortBy === "income") {
                return (Number(a.total_income || 0) - Number(b.total_income || 0)) * direction;
            }
            if (sortBy === "assets") {
                return (Number(a.total_assets || 0) - Number(b.total_assets || 0)) * direction;
            }
            if (sortBy === "name") {
                return a.name.localeCompare(b.name) * direction;
            }
            if (sortBy === "year") {
                return ((a.declaration_year || 0) - (b.declaration_year || 0)) * direction;
            }
            return (a.score - b.score) * direction;
        });
        const items = sorted.slice(offset, offset + limit);
        return {
            items,
            total: sorted.length,
            offset,
            limit,
        };
    }
    const params = new URLSearchParams({
        limit: limit.toString(),
        offset: offset.toString(),
        min_score: minScore.toString(),
        sort_by: sortBy,
        sort_dir: sortDir,
    });
    if (query) {
        params.append('query', query);
    }

    const res = await fetch(`${API_URL}/api/declarations?${params.toString()}`, {
        cache: 'no-store',
    });
    if (!res.ok) throw new Error('Failed to fetch declarations');
    return res.json();
}

export async function fetchDeclaration(id: string): Promise<DeclarationDetail> {
    if (E2E_FIXTURES_ENABLED) {
        const fixture = E2E_FIXTURE_DATA.declarationDetails[id];
        if (!fixture) throw new Error(`Failed to fetch declaration ${id}`);
        return fixture;
    }
    const res = await fetch(`${API_URL}/api/declarations/${id}`, {
        cache: 'no-store',
    });
    if (!res.ok) throw new Error(`Failed to fetch declaration ${id}`);
    return res.json();
}

export async function fetchPersonTimeline(userDeclarantId: number): Promise<PersonTimelineResponse> {
    if (E2E_FIXTURES_ENABLED) {
        if (userDeclarantId !== E2E_FIXTURE_DATA.personTimeline.user_declarant_id) {
            throw new Error(`Failed to fetch person timeline ${userDeclarantId}`);
        }
        return E2E_FIXTURE_DATA.personTimeline;
    }
    const res = await fetch(`${API_URL}/api/persons/${userDeclarantId}`, {
        cache: 'no-store',
    });
    if (!res.ok) throw new Error(`Failed to fetch person timeline ${userDeclarantId}`);
    return res.json();
}
