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

## Docker Notes

When started via root `docker-compose.yml`, this app runs at `http://localhost:3000`
and connects to the backend service through Docker network hostnames.
