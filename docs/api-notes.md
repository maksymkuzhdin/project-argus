# API Notes (Current Contract Audit)

This document describes the **current backend/frontend API contract** for the main UI journeys in Project Argus, based on:

- implemented FastAPI routes in `backend/app/api/`,
- frontend API usage in `frontend/src/lib/api.ts` and route pages,
- smoke-test coverage in `frontend/e2e/smoke-tests.spec.ts`.

Base URL (local): `http://localhost:8000`

## Concise API audit

| Journey | Backend endpoints in use | Frontend usage | Status |
|---|---|---|---|
| Dashboard list + stats | `GET /api/declarations`, `GET /api/declarations/stats` | `fetchDeclarations`, `fetchStats` on `/` | Aligned |
| Declaration detail | `GET /api/declarations/{doc_id}` | `fetchDeclaration` on `/declaration/[id]` and `/declaration?id=...` | Mostly aligned |
| Person timeline/profile | `GET /api/persons/{user_declarant_id}` | `fetchPersonTimeline` on `/person/[id]` | Aligned with notable edge-case mismatch |
| Health | `GET /health` | infra/dev checks | Aligned |

---

## Error envelope (global)

Custom handlers in `backend/app/main.py` wrap most errors into:

```json
{
  "error": {
    "code": "validation_error | http_error | internal_error",
    "message": "Human-readable message",
    "path": "/api/...",
    "details": []
  }
}
```

Notes:
- `422` validation errors include `details`.
- `HTTPException` (for example 404 from endpoints) is returned as `error.code = "http_error"`.
- Generic unhandled errors return `500` with `error.code = "internal_error"`.

---

## 1) Dashboard contracts

### `GET /api/declarations/stats`

Used by dashboard KPI cards and rule distribution chart.

#### Response shape

```json
{
  "total_declarations": 2,
  "flagged_declarations": 2,
  "average_score": 0.525,
  "rule_distribution": {
    "cash_to_bank_ratio": 1,
    "unexplained_wealth": 1
  }
}
```

#### Fields

| Field | Type | Meaning |
|---|---|---|
| `total_declarations` | number | Number of declarations in analyzed dataset |
| `flagged_declarations` | number | Count where score > 0 |
| `average_score` | number | Mean score across declarations |
| `rule_distribution` | object | Rule name -> occurrence count |

---

### `GET /api/declarations`

Used by dashboard table, search, sorting, and pagination.

#### Query parameters

| Param | Type | Default | Constraints | Notes |
|---|---|---:|---|---|
| `limit` | int | `50` | `1..200` | Page size |
| `offset` | int | `0` | `0..500000` | Row offset |
| `min_score` | float | `0.0` | `0.0..100.0` | Minimum anomaly score |
| `query` | string | `null` | max 120 chars | Name/institution text search |
| `sort_by` | string | `"score"` | backend allows `score,income,assets,name,year` | Invalid value falls back to `score` |
| `sort_dir` | string | `"desc"` | `asc|desc` | Invalid value falls back to `desc` |

#### Response shape

```json
{
  "items": [
    {
      "declaration_id": "doc-2",
      "user_declarant_id": 777,
      "declaration_year": 2024,
      "name": "Koval Iryna",
      "role": "Head",
      "institution": "City Council",
      "total_income": "150000",
      "total_assets": "120000",
      "score": 0.8,
      "triggered_rules": ["cash_to_bank_ratio", "unexplained_wealth"],
      "explanation": "High cash concentration and wealth mismatch."
    }
  ],
  "total": 2,
  "offset": 0,
  "limit": 50
}
```

#### Item contract (dashboard-critical)

| Field | Type |
|---|---|
| `declaration_id` | string |
| `user_declarant_id` | number \| null |
| `declaration_year` | number \| null |
| `name` | string |
| `role` | string |
| `institution` | string |
| `total_income` | string \| null |
| `total_assets` | string \| null |
| `score` | number |
| `triggered_rules` | string[] |
| `explanation` | string |

---

## 2) Declaration detail contract

### `GET /api/declarations/{doc_id}`

Used by declaration detail page (`/declaration/[id]` and `/declaration?id=...`).

#### Path parameter

| Param | Type | Notes |
|---|---|---|
| `doc_id` | string | Declaration ID shown in dashboard list |

#### Response shape (trimmed to high-value fields)

```json
{
  "id": "doc-2",
  "user_declarant_id": 777,
  "raw_metadata": {
    "year": 2024,
    "date": null,
    "declaration_type": 1
  },
  "bio": {
    "firstname": "Iryna",
    "lastname": "Koval",
    "middlename": null,
    "work_post": "Head",
    "work_place": "City Council",
    "post_type": "A",
    "post_category": null
  },
  "family_members": [],
  "real_estate": [],
  "vehicles": [],
  "bank_accounts": [],
  "incomes": [],
  "monetary": [],
  "summary": {
    "declaration_id": "doc-2",
    "family_members": 0,
    "incomes": 0,
    "monetary_assets": 0,
    "real_estate_rights": 0,
    "total_income": "150000",
    "total_assets": "120000",
    "score": 0.8,
    "triggered_rules": ["cash_to_bank_ratio", "unexplained_wealth"],
    "explanation": "High cash concentration and wealth mismatch.",
    "name": "Koval Iryna",
    "role": "Head",
    "institution": "City Council",
    "rule_details": [
      {
        "rule_name": "cash_to_bank_ratio",
        "score": 0.5,
        "triggered": true,
        "explanation": "Cash ratio is unusually high."
      }
    ]
  }
}
```

#### Detail page relies on

1. `summary.score`, `summary.triggered_rules`, `summary.explanation`, `summary.rule_details` for anomaly panels/charts.
2. `bio.*` and `raw_metadata.year` for header fields.
3. Arrays (`family_members`, `real_estate`, `vehicles`, `bank_accounts`, `incomes`, `monetary`) for detailed tables.

---

## 3) Person timeline/profile contract

### `GET /api/persons/{user_declarant_id}`

Used by `/person/[id]`.

#### Path parameter

| Param | Type | Constraints |
|---|---|---|
| `user_declarant_id` | int | `> 0` (FastAPI path validation) |

#### Response shape (trimmed to high-value fields)

```json
{
  "user_declarant_id": 777,
  "name": "Koval Iryna",
  "snapshot_count": 2,
  "snapshots": [
    {
      "declaration_id": "doc-1",
      "declaration_year": 2023,
      "declaration_type": 1,
      "total_income": "100000",
      "total_monetary": "50000",
      "total_real_estate": null,
      "total_assets": "50000",
      "cash": "50000",
      "bank": null,
      "unknown_share": 0.0,
      "income_count": 1,
      "monetary_count": 1,
      "real_estate_count": 0,
      "vehicle_count": 0,
      "role": "Head",
      "institution": "City Council"
    }
  ],
  "changes": [
    {
      "from_year": 2023,
      "to_year": 2024,
      "income_prev": "100000",
      "income_curr": "150000",
      "income_delta": "50000",
      "income_ratio": 1.5,
      "income_growth": 0.5,
      "monetary_prev": "50000",
      "monetary_curr": "120000",
      "monetary_delta": "70000",
      "monetary_ratio": 2.4,
      "assets_prev": "50000",
      "assets_curr": "120000",
      "asset_growth": 1.4,
      "cash_prev": "50000",
      "cash_curr": "120000",
      "cash_delta": "70000",
      "unknown_share_prev": 0.0,
      "unknown_share_curr": 0.0,
      "unknown_share_delta": 0.0,
      "role_prev": "Head",
      "role_curr": "Head",
      "role_changed": false,
      "major_assets_appeared": 0,
      "major_assets_disappeared": 0,
      "max_appeared_value": null,
      "max_disappeared_value": null,
      "one_off_income_curr": null
    }
  ],
  "timeline_score": {
    "total_score": 0.0,
    "triggered_rules": [],
    "explanation": "No multi-year anomaly signals detected.",
    "rule_details": []
  }
}
```

#### Timeline page relies on

1. `timeline_score.total_score` and `timeline_score.triggered_rules`.
2. `snapshots` for year-by-year table.
3. `changes` for delta/growth/role-change sections.

---

## Known gaps and mismatches

1. **Stats flow mismatch in stale docs**: old docs focused partly on upstream NAZK endpoints and did not clearly separate the frontend-facing Argus contract. This file now isolates the Argus contract.
2. **Timeline availability mismatch (UI expectation vs backend reality)**: dashboard shows “Open multi-year profile” based only on declarations visible in current page results; backend requires at least 2 declarations globally for that person and may return 404.
3. **`raw_metadata.date` differs by data path**: DB path returns `null`; in-memory fallback may provide the raw date value.
4. **Numeric encoding is mixed by design**: aggregate totals are returned as strings (`"150000"`), while score fields are numeric (`0.8`). Frontend currently handles this, but it is an important contract detail.
5. **Rule details presence differs by endpoint path/data completeness**: dashboard list may omit `rule_details`; declaration detail and timeline score include rule details when available.

Low-risk cleanup candidates (non-breaking, optional):
- standardize `raw_metadata.date` population in DB path if source date is available;
- optionally expose a lightweight person-eligibility flag/count on list items to avoid avoidable timeline 404s.

