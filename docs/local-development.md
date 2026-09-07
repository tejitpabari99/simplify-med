# Local Development

This project has two runnable parts:

- `backend/` — Python/Flask API, default local URL `http://localhost:8080`
- `frontend/` — React + Vite + TypeScript app, default local URL `http://localhost:5173`

## Prerequisites

- Python 3.12 (CI runs on 3.12; the deployed container uses 3.11).
- Node.js 20+ (CI runs on Node 24).
- A Google Cloud project with Vertex AI, Firestore, Cloud Storage, and Cloud Tasks
  enabled, and a Firebase project (can be the same GCP project) with Anonymous
  Authentication turned on. This is only required to run the full pipeline against real
  services — frontend-only work or running the test suites does not need any of this.

## Environment files

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

Never commit filled `.env`/`.env.local` files or service-account JSON.

### Backend (`backend/.env`)

| Variable | Purpose |
|---|---|
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Path to a Firebase Admin SDK service-account JSON file (local dev). In production this is injected as `FIREBASE_SERVICE_ACCOUNT_JSON` instead. |
| `GCP_PROJECT_ID` | Your GCP project. |
| `GCP_BUCKET_NAME` | GCS bucket for uploaded/merged input files. |
| `GCP_LOCATION` | Vertex AI region, e.g. `us-central1`. |
| `FIRESTORE_DATABASE_ID` | Firestore database ID; `(default)` unless you created a named database. |
| `VERTEX_AI_MODEL` | Gemini model name (e.g. `gemini-3.5-flash`). If unset, the code falls back to `gemini-1.5-pro`. |
| `SERVICE_MODE` | `api` (public routes), `worker` (internal job-execution route), or `combined` (both, in one process). |
| `CLOUD_TASKS_QUEUE` | Cloud Tasks queue resource name. Required for `POST /jobs` to enqueue work. |
| `WORKER_URL` | Base URL the worker's job-execution route is reachable at. |
| `WORKER_SERVICE_ACCOUNT` | Service account email used for the Cloud Tasks OIDC token, and checked against incoming worker requests. |
| `WORKER_VERIFY_OIDC` | Set to `false` to skip verifying the Cloud Tasks OIDC token on the worker route (local/dev only — leave enabled for anything resembling a real deployment). |
| `RATE_LIMIT_SALT` | Salt for hashing client IPs in the per-IP rate limiter. Required in production; an unset value falls back to a process-local random salt, logged as an error. |
| `TRUSTED_PROXY_HOPS` | Number of trusted reverse-proxy hops in front of the API. Default `1` (direct Cloud Run, no external load balancer). Only change this if you put another proxy in front. |
| `RETENTION_DRY_RUN` | Controls whether `scripts/cleanup_anonymous_users.py` actually deletes anonymous Auth accounts or just logs what it would delete. |

`POST /jobs` calls the real Cloud Tasks API to enqueue work, so exercising the full
create-job → enqueue → worker-executes flow locally requires either a real Cloud Tasks
queue pointed at a reachable `WORKER_URL` (e.g. via `SERVICE_MODE=combined` and a
publicly reachable local tunnel, or a queue pointed at a deployed worker), or simply
relying on the test suite, which mocks these boundaries. For most contributions, running
the tests below is enough — you do not need working GCP credentials to change code and
have CI validate it.

### Frontend (`frontend/.env.local`)

| Variable | Purpose |
|---|---|
| `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID`, `VITE_FIREBASE_STORAGE_BUCKET`, `VITE_FIREBASE_MESSAGING_SENDER_ID`, `VITE_FIREBASE_APP_ID` | Firebase web app config, from Project Settings → General in the Firebase console. |
| `VITE_API_PROCESSING_URL` | Base URL of the backend API. No trailing slash needed. |
| `VITE_GA_MEASUREMENT_ID` | Optional. Leave unset in local dev — analytics no-ops when empty. |

## Running the app locally

Two terminals.

**Terminal 1 — backend:**

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in values, see table above
python app.py           # serves on http://0.0.0.0:8080
```

Confirm it's up:

```bash
curl http://localhost:8080/health
```

**Terminal 2 — frontend:**

```bash
cd frontend
npm ci
cp .env.example .env.local   # fill in Firebase web config + backend URL
npm run dev                   # serves on http://localhost:5173
```

Open `http://localhost:5173`. The page signs in anonymously on load; there is no login
screen.

### Common issues

- `http://localhost:8080/health` fails: the backend isn't running, crashed during
  Firebase Admin SDK initialization, or is using a different port.
- Backend port conflict: run `PORT=8081 python app.py` and update
  `VITE_API_PROCESSING_URL` in `frontend/.env.local` to match.
- Frontend port conflict: run `npm run dev -- --port 5174` and open the URL Vite prints.
- Requests resolve to `undefined/jobs`: `VITE_API_PROCESSING_URL` is missing from
  `frontend/.env.local`. The app throws loudly at module load in this case — restart Vite
  after fixing the env file.

## Running the test suites

**Backend**, from `backend/` (with the virtualenv active):

```bash
python3 -m pytest tests/ -q
```

Ruff lint (pyflakes rules only):

```bash
ruff check . --config pyproject.toml
```

**Frontend**, from `frontend/`:

```bash
npx tsc --noEmit
npm run lint
npm test -- --run
npm run build
```

These are exactly the checks CI runs (`.github/workflows/ci.yml`) — run them before
opening a pull request.
