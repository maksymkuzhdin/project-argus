# Argus Frontend

Next.js App Router frontend for Project Argus. It renders:
- dashboard (`/`),
- declaration detail (`/declaration/[id]`),
- person timeline (`/person/[id]`).

All views consume the FastAPI backend and are intentionally no-cache in dev.

## Prerequisites

- Node.js 20+
- npm 10+
- Running backend API (default `http://localhost:8000`)

## Local Development

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Environment Variables

- `NEXT_PUBLIC_API_URL`:
	Browser-side API base URL. Defaults to `http://localhost:8000`.
- `INTERNAL_API_URL`:
	Server-side API base URL used during SSR. Defaults to `http://backend:8000` in Docker.

These are read by `src/lib/api.ts`.

## Quality Commands

```bash
npm run lint
npm run build
npm run e2e        # Run all Playwright e2e tests
npm run e2e:debug  # Run with interactive debugger
npm run e2e:ui     # Run with test UI
```

`npm run lint` and `npm run build` are enforced by CI. E2E tests are run in the CI pipeline after backend tests pass.

## E2E Test Prerequisites & Fixture Strategy

The Playwright smoke tests run against a **lightweight in-process mock HTTP
server** (`e2e/mock-api-server.ts`) that serves deterministic fixture data
for all backend API endpoints.  No live backend or pre-populated database is
required.

### How it works

1. `globalSetup` (wired in `playwright.config.ts`) starts the mock server on
   port **19999** before the Next.js dev server launches.
2. `playwright.config.ts` sets `INTERNAL_API_URL=http://localhost:19999` in
   the Next.js dev server's environment so all SSR `fetch` calls resolve to
   fixture responses.
3. `globalTeardown` stops the mock server after all tests finish.

### Local gotcha

If you already have `npm run dev` running (e.g., for regular development),
Playwright will *reuse* that process (`reuseExistingServer: true`) and the
`INTERNAL_API_URL` override will not apply.  **Stop any running dev server
before running `npm run e2e`** to ensure the mock server is used.

In CI, `reuseExistingServer` is always `false`, so a fresh dev server with
the mock URL is started automatically.

### Fixture constants

`e2e/mock-api-server.ts` exports `FIXTURE_DECLARATION_ID` and
`FIXTURE_USER_DECLARANT_ID`.  Both the config layer and the smoke tests
import these constants to stay in sync.

## Docker Notes

When started via root `docker-compose.yml`, this app runs at `http://localhost:3000`
and connects to the backend service through Docker network hostnames.
