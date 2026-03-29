# API Notes

This document covers both:
- upstream NAZK API usage notes,
- Project Argus backend API contract notes.

## Base URL

```
https://public-api.nazk.gov.ua/v2
```

## Endpoints

### Single declaration
```
GET /v2/documents/{document_id}
```
Returns the full declaration JSON.

### Search / list
```
GET /v2/documents/list
```

#### Parameters

| Parameter | Type | Notes |
|---|---|---|
| `query` | string (3–255 chars) | Text search; results sorted by relevance |
| `user_declarant_id` | int (1–10M) | Declarant's internal ID |
| `document_type` | int (1–3) | Document type |
| `declaration_type` | int (1–4) | Declaration type |
| `declaration_year` | int | Reporting period year |
| `responsible_position` | int | Position type |
| `corruption_affected` | 0 or 1 | High corruption risk position |
| `start_date` / `end_date` | int (UNIX epoch) | Submission date range |
| `page` | int (1–100) | Pagination |

#### Pagination
- Max 100 results per page
- Max 100 pages (10,000 results per query)
- For broader coverage, partition by `declaration_year` and/or `declaration_type`

### Countries directory
```
GET /v2/countries/list
```

---

## Project Argus Backend API

Base URL (local):

```
http://localhost:8000
```

### Health

```
GET /health
```

### Declarations list

```
GET /api/declarations
```

Query constraints:

| Parameter | Type | Constraints |
|---|---|---|
| `limit` | int | 1–200 |
| `offset` | int | 0–500000 |
| `min_score` | float | 0.0–100.0 |
| `query` | string | max 120 chars |

### Declarations stats

```
GET /api/declarations/stats
```

### Declaration detail

```
GET /api/declarations/{declaration_id}
```

### Person timeline

```
GET /api/persons/{user_declarant_id}
```

Path constraint: `user_declarant_id > 0`.

### Error envelope

All API errors return a consistent shape:

```json
{
	"error": {
		"code": "validation_error",
		"message": "Invalid request parameters.",
		"path": "/api/declarations",
		"details": []
	}
}
```

Common codes:
- `validation_error` (HTTP 422)
- `http_error` (HTTP 4xx)
- `internal_error` (HTTP 500)

## Data structure notes
- Declaration data lives in `data.step_<0..17>.data` arrays
- `declaration_year` field is at the top level
- `date` field replaced the old `lastmodified_date`
- Step 2.1 fields (`postType`, `postCategory`, etc.) are duplicated at the top level
