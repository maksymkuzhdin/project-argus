export const API_URL = typeof window === 'undefined'
    ? process.env.INTERNAL_API_URL || 'http://backend:8000'
    : process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
    score: number;
    triggered_rules: string[];
    explanation: string;
    name: string;
    role: string;
    institution: string;
    rule_details?: {
        rule_name: string;
        score: number;
        triggered: boolean;
        explanation: string;
    }[];
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
        cash: string | null;
        bank: string | null;
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
        monetary_prev: string | null;
        monetary_curr: string | null;
        monetary_delta: string | null;
        monetary_ratio: number | null;
        cash_prev: string | null;
        cash_curr: string | null;
        cash_delta: string | null;
    }[];
    timeline_score: {
        total_score: number;
        triggered_rules: string[];
        explanation: string;
        rule_details: {
            rule_name: string;
            score: number;
            triggered: boolean;
            explanation: string;
        }[];
    };
}

// ------------------------------------------------------------------
// API methods
// ------------------------------------------------------------------

export async function fetchStats(): Promise<StatsResponse> {
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
    query = ''
): Promise<PaginatedDeclarations> {
    const params = new URLSearchParams({
        limit: limit.toString(),
        offset: offset.toString(),
        min_score: minScore.toString(),
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
    const res = await fetch(`${API_URL}/api/declarations/${id}`, {
        cache: 'no-store',
    });
    if (!res.ok) throw new Error(`Failed to fetch declaration ${id}`);
    return res.json();
}

export async function fetchPersonTimeline(userDeclarantId: number): Promise<PersonTimelineResponse> {
    const res = await fetch(`${API_URL}/api/persons/${userDeclarantId}`, {
        cache: 'no-store',
    });
    if (!res.ok) throw new Error(`Failed to fetch person timeline ${userDeclarantId}`);
    return res.json();
}
