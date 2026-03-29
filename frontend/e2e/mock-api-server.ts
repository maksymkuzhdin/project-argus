/**
 * Lightweight in-process HTTP mock server for E2E tests.
 *
 * Serves deterministic fixture data so smoke tests never rely on a live
 * backend or an opportunistic local database state.  The server is started
 * in Playwright's globalSetup and stopped in globalTeardown; the Next.js
 * dev server (launched by playwright.config.ts webServer) is configured to
 * point INTERNAL_API_URL at this server so that all SSR fetch calls resolve
 * to predictable fixture responses.
 *
 * Exported constants (FIXTURE_DECLARATION_ID, FIXTURE_USER_DECLARANT_ID,
 * MOCK_API_PORT) are imported by both the configuration layer and the smoke
 * tests so that all three files share a single source of truth.
 */

import http from "http";

// ---------------------------------------------------------------------------
// Stable fixture identifiers — shared with smoke-tests.spec.ts
// ---------------------------------------------------------------------------

export const FIXTURE_DECLARATION_ID = "fixture-decl-e2e-001";
export const FIXTURE_USER_DECLARANT_ID = 9001;
export const MOCK_API_PORT = 19999;
export const MOCK_API_BASE = `http://localhost:${MOCK_API_PORT}`;

// ---------------------------------------------------------------------------
// Fixture data
// ---------------------------------------------------------------------------

const FIXTURE_STATS = {
  total_declarations: 2,
  flagged_declarations: 1,
  average_score: 55.0,
  rule_distribution: { cash_to_bank_ratio: 1 },
};

const FIXTURE_SUMMARY = {
  declaration_id: FIXTURE_DECLARATION_ID,
  user_declarant_id: FIXTURE_USER_DECLARANT_ID,
  declaration_year: 2023,
  family_members: 1,
  incomes: 2,
  monetary_assets: 1,
  real_estate_rights: 0,
  total_income: "500000",
  total_assets: "2000000",
  score: 55.0,
  triggered_rules: ["cash_to_bank_ratio"],
  explanation:
    "• Cash-to-bank ratio anomaly detected. Cash holdings are unusually high relative to declared bank assets.",
  name: "Fixture Person",
  role: "Test Official",
  institution: "Test Institution",
  rule_details: [
    {
      rule_name: "cash_to_bank_ratio",
      score: 55.0,
      triggered: true,
      explanation:
        "Cash holdings are unusually high relative to declared bank assets.",
    },
  ],
};

// Second declaration for the same person (different year) — enables the
// "Open multi-year profile" link on the dashboard.
const FIXTURE_SUMMARY_2 = {
  declaration_id: "fixture-decl-e2e-002",
  user_declarant_id: FIXTURE_USER_DECLARANT_ID,
  declaration_year: 2024,
  family_members: 1,
  incomes: 2,
  monetary_assets: 1,
  real_estate_rights: 0,
  total_income: "600000",
  total_assets: "2500000",
  score: 0.0,
  triggered_rules: [],
  explanation: "",
  name: "Fixture Person",
  role: "Test Official",
  institution: "Test Institution",
  rule_details: [],
};

const FIXTURE_LIST = {
  items: [FIXTURE_SUMMARY, FIXTURE_SUMMARY_2],
  total: 2,
  offset: 0,
  limit: 50,
};

const FIXTURE_DETAIL = {
  id: FIXTURE_DECLARATION_ID,
  user_declarant_id: FIXTURE_USER_DECLARANT_ID,
  raw_metadata: {
    year: 2023,
    date: "2023-04-01",
    declaration_type: 1,
  },
  family_members: [],
  real_estate: [],
  vehicles: [],
  bank_accounts: [],
  incomes: [],
  monetary: [],
  summary: FIXTURE_SUMMARY,
  bio: {
    firstname: "Fixture",
    middlename: "Test",
    lastname: "Person",
    work_post: "Test Official",
    work_place: "Test Institution",
  },
};

const FIXTURE_TIMELINE = {
  user_declarant_id: FIXTURE_USER_DECLARANT_ID,
  name: "Fixture Person",
  snapshot_count: 2,
  snapshots: [
    {
      declaration_id: FIXTURE_DECLARATION_ID,
      declaration_year: 2023,
      declaration_type: 1,
      total_income: "500000",
      total_monetary: "200000",
      total_real_estate: null,
      total_assets: "2000000",
      cash: "150000",
      bank: "50000",
      unknown_share: 0.1,
      income_count: 2,
      monetary_count: 1,
      real_estate_count: 0,
      vehicle_count: 0,
      role: "Test Official",
      institution: "Test Institution",
    },
    {
      declaration_id: "fixture-decl-e2e-002",
      declaration_year: 2024,
      declaration_type: 1,
      total_income: "600000",
      total_monetary: "250000",
      total_real_estate: null,
      total_assets: "2500000",
      cash: "180000",
      bank: "70000",
      unknown_share: 0.08,
      income_count: 2,
      monetary_count: 1,
      real_estate_count: 0,
      vehicle_count: 0,
      role: "Test Official",
      institution: "Test Institution",
    },
  ],
  changes: [
    {
      from_year: 2023,
      to_year: 2024,
      income_prev: "500000",
      income_curr: "600000",
      income_delta: "100000",
      income_ratio: 1.2,
      income_growth: 0.2,
      monetary_prev: "200000",
      monetary_curr: "250000",
      monetary_delta: "50000",
      monetary_ratio: 1.25,
      assets_prev: "2000000",
      assets_curr: "2500000",
      asset_growth: 0.25,
      cash_prev: "150000",
      cash_curr: "180000",
      cash_delta: "30000",
      unknown_share_prev: 0.1,
      unknown_share_curr: 0.08,
      unknown_share_delta: -0.02,
      role_prev: "Test Official",
      role_curr: "Test Official",
      role_changed: false,
      major_assets_appeared: 0,
      major_assets_disappeared: 0,
      max_appeared_value: null,
      max_disappeared_value: null,
      one_off_income_curr: null,
    },
  ],
  timeline_score: {
    total_score: 30.0,
    triggered_rules: ["income_growth_spike"],
    explanation: "Income grew by 20% year-over-year.",
    rule_details: [
      {
        rule_name: "income_growth_spike",
        score: 30.0,
        triggered: true,
        explanation: "Income grew by 20% year-over-year.",
      },
    ],
  },
};

// ---------------------------------------------------------------------------
// Request handler
// ---------------------------------------------------------------------------

function handleRequest(
  req: http.IncomingMessage,
  res: http.ServerResponse
): void {
  const rawUrl = req.url ?? "/";
  const path = rawUrl.split("?")[0]; // strip query string

  res.setHeader("Content-Type", "application/json");
  res.setHeader("Access-Control-Allow-Origin", "*");

  // Handle CORS preflight
  if (req.method === "OPTIONS") {
    res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type");
    res.statusCode = 204;
    res.end();
    return;
  }

  if (path === "/api/declarations/stats") {
    res.statusCode = 200;
    res.end(JSON.stringify(FIXTURE_STATS));
  } else if (path === `/api/declarations/${FIXTURE_DECLARATION_ID}`) {
    res.statusCode = 200;
    res.end(JSON.stringify(FIXTURE_DETAIL));
  } else if (path.startsWith("/api/declarations/")) {
    // Unknown declaration ID → trigger error UI in the frontend
    res.statusCode = 404;
    res.end(JSON.stringify({ detail: "Declaration not found" }));
  } else if (path === "/api/declarations") {
    res.statusCode = 200;
    res.end(JSON.stringify(FIXTURE_LIST));
  } else if (path.startsWith("/api/persons/")) {
    res.statusCode = 200;
    res.end(JSON.stringify(FIXTURE_TIMELINE));
  } else {
    res.statusCode = 404;
    res.end(JSON.stringify({ detail: "Not found" }));
  }
}

// ---------------------------------------------------------------------------
// Module-level server handle (shared between global-setup and global-teardown
// which run in the same Playwright main process and therefore share Node.js
// module cache).
// ---------------------------------------------------------------------------

let _server: http.Server | null = null;

export function startMockApiServer(): Promise<void> {
  return new Promise((resolve, reject) => {
    _server = http.createServer(handleRequest);
    _server.once("error", reject);
    _server.listen(MOCK_API_PORT, "127.0.0.1", () => resolve());
  });
}

export function stopMockApiServer(): Promise<void> {
  return new Promise((resolve) => {
    if (_server) {
      _server.close(() => {
        _server = null;
        resolve();
      });
    } else {
      resolve();
    }
  });
}
