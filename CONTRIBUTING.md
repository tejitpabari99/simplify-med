# Contributing to Simplify

Thanks for your interest in improving Simplify. This document covers local setup,
testing, and the conventions this repo follows.

## Prerequisites

- Python 3.12
- Node.js 20+ (CI runs on Node 24)
- A Google Cloud project with Vertex AI, Firestore, Cloud Storage, and Cloud Tasks
  enabled, and a Firebase project (can be the same GCP project) with Anonymous
  Authentication turned on — only needed if you want to run the full pipeline against
  real services. Frontend-only or unit-test work does not require any of this.

## Backend setup (`backend/`)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # fill in values described below
python app.py          # serves on http://0.0.0.0:8080
```

Key variables in `.env.example`:
- `FIREBASE_SERVICE_ACCOUNT_PATH` — path to a Firebase Admin SDK service-account JSON
  (local dev). In production this is injected as `FIREBASE_SERVICE_ACCOUNT_JSON` instead.
- `GCP_PROJECT_ID`, `GCP_BUCKET_NAME`, `GCP_LOCATION` — your GCP project, GCS bucket, and
  Vertex AI region.
- `VERTEX_AI_MODEL` — the Gemini model to call.
- `SERVICE_MODE` — `api` (public routes), `worker` (internal job execution route), or
  `combined` (both, for a single local/preview process).
- `CLOUD_TASKS_QUEUE`, `WORKER_URL`, `WORKER_SERVICE_ACCOUNT` — required for
  `POST /jobs` to enqueue work onto the worker service.
- `RATE_LIMIT_SALT` — salt for hashing client IPs in the per-IP rate limiter; required in
  any real deployment.
- `TRUSTED_PROXY_HOPS` — number of trusted reverse-proxy hops in front of the API; only
  change this if you put another proxy/load balancer in front of Cloud Run.
- `RETENTION_DRY_RUN` — controls whether `scripts/cleanup_anonymous_users.py` actually
  deletes anonymous auth accounts or just logs what it would delete.

Running the app end-to-end locally (`SERVICE_MODE=combined`) also requires the two-service
routing described above to point at itself; for most contributions, running just the
tests below is enough.

## Frontend setup (`frontend/`)

```bash
cd frontend
npm ci
cp .env.example .env.local   # fill in Firebase web config + API URL
npm run dev                  # serves on http://localhost:5173
```

`.env.example` documents each `VITE_*` variable: your Firebase web app config
(`VITE_FIREBASE_*`), the backend base URL (`VITE_API_PROCESSING_URL`), and an optional
analytics measurement ID.

## Tests and linters

Backend, from `backend/`:

```bash
ruff check . --config pyproject.toml
python -m pytest tests/ -q
```

Frontend, from `frontend/`:

```bash
npx tsc --noEmit
npm run lint
npm test
npm run build
```

These are exactly the checks CI runs (`.github/workflows/ci.yml`) — run them before
opening a PR.

## Branch and PR conventions

- Branch off `main`; use a short, descriptive branch name.
- Keep PRs focused on one change. Include a brief description of what changed and why.
- CI must pass (backend lint + tests, frontend type-check + lint + tests + build) before
  a PR is merged.
- Prefer small, reviewable commits over one large commit.

## Code style

- Python: [ruff](https://docs.astral.sh/ruff/) (`backend/pyproject.toml`), currently
  configured for pyflakes (`F`) rules. Run `ruff check .` from `backend/` before
  committing.
- TypeScript/React: ESLint (`frontend/eslint.config.js`) and the TypeScript compiler in
  strict mode (`frontend/tsconfig.app.json`). Run `npm run lint` and `npx tsc --noEmit`
  from `frontend/` before committing.
- Match the existing style in the file you're editing over introducing a new pattern.

## Reporting security issues

Please do not file a public GitHub issue for a suspected security vulnerability. Instead,
report it privately via this repository's GitHub Security Advisory feature (Security tab
→ "Report a vulnerability") so it can be assessed and fixed before public disclosure.

## Code of conduct

Be respectful and constructive in issues, PRs, and discussions.
