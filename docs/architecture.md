# Architecture

## 1. Topology

The backend (`backend/`) is a single Flask application (`backend/app.py`) deployed
**twice** from the **same container image** as two separate Cloud Run services,
distinguished only by a `SERVICE_MODE` environment variable and which set of route
blueprints it registers (`backend/routes/__init__.py`):

- **`simplify-api`** (`SERVICE_MODE=api`) — registers `routes/jobs.py`. Public,
  `--allow-unauthenticated` Cloud Run service. Accepts `POST /jobs` and
  `DELETE /jobs/<job_id>`.
- **`simplify-worker`** (`SERVICE_MODE=worker`) — registers `routes/worker.py`.
  Deployed `--no-allow-unauthenticated` with `--ingress=internal`; reachable only via a
  signed request from Cloud Tasks. Serves `POST /internal/jobs/execute/<job_id>`.
- A third mode, `SERVICE_MODE=combined`, registers both blueprint sets in one process.
  It exists for local development and any single-process preview deployment, where a
  Cloud Task enqueued by the API routes calls back into the same process's worker
  route.

```
Browser (anonymous Firebase Auth)
   │  Authorization: Bearer <Firebase ID token>
   │  POST /jobs  (multipart files, or {"text": "..."})
   ▼
Cloud Run: simplify-api  (SERVICE_MODE=api, public)
   │
   ├─ create job doc ──────────────▶ Firestore: care_plan_outputs/{job_id}
   │
   └─ enqueue Cloud Task ──────────▶ Cloud Tasks queue: care-plan-jobs
                                             │ OIDC-signed POST
                                             ▼
                              Cloud Run: simplify-worker (SERVICE_MODE=worker, internal)
                                             │
                                             ├─ resolve input text
                                             ├─ run the 5-step pipeline (Vertex AI / Gemini)
                                             ├─ write stage updates ─▶ Firestore
                                             └─ write final result ──▶ Firestore

Browser ── live Firestore listener on care_plan_outputs/{job_id} ── reads status/stage/output_data
```

There is no dedicated status-polling HTTP endpoint. The browser attaches a live
Firestore `onSnapshot` listener directly to the job document
(`frontend/src/hooks/useJobSnapshot.ts`) and renders `status`, `stage`, `output_data`,
and `error_data` as the worker updates them.

## 2. Request and job lifecycle

1. **Submit.** The browser signs in anonymously via Firebase Auth on page load
   (`frontend/src/hooks/useAnonAuth.ts`, `signInAnonymously()`, no email/password) and
   sends the resulting ID token as `Authorization: Bearer <token>` on every request.
   `POST /jobs` accepts either a `text` field (form or JSON) or one or more files under
   a `files` multipart field.
2. **Resolve input.** `simplify-api` extracts text from the request (§3.3 in
   [`pipeline.md`](pipeline.md) covers extraction itself), validates its length, and —
   for file uploads — merges the accepted files into one combined PDF and uploads it to
   Cloud Storage.
3. **Create the job.** A Firestore document is created in `care_plan_outputs` with
   `status="not_started"`, the resolved input, and an `expires_at` timestamp one hour in
   the future. `POST /jobs` returns `202 {"job_id": "<uuid>"}` immediately — the
   pipeline itself runs later, in the worker.
4. **Enqueue.** A Cloud Task is created against the `care-plan-jobs` queue, targeting
   `{WORKER_URL}/internal/jobs/execute/{job_id}` and signed with an OIDC token for the
   worker's service account. `simplify-api` validates the Cloud Tasks configuration
   (`CLOUD_TASKS_QUEUE`, `WORKER_URL`, `WORKER_SERVICE_ACCOUNT`) **before** writing the
   Firestore job document, so a configuration error can never leave an orphaned job doc
   with no task behind it.
5. **Execute.** `simplify-worker` receives the signed request, verifies it really came
   from Cloud Tasks, marks the job `status="processing"`, and runs the pipeline
   described in [`pipeline.md`](pipeline.md), writing a `stage` update (1–5) to the job
   document as each step starts.
6. **Complete.** On success the worker writes the structured result to `output_data` and
   sets `status="completed"`; on an unrecoverable failure it writes `error_data` and sets
   `status="error"`. Both paths clear the job's raw `input_text` field in the same
   Firestore update.
7. **Display and delete.** The browser's live listener picks up the terminal status and
   renders the result screen. The job document is deleted at that point — see
   [`data-and-privacy.md`](data-and-privacy.md) for every deletion path.

### Job document as a state machine

Every job is one Pydantic-typed document (`backend/models/job.py:JobDoc`) in the
`care_plan_outputs` Firestore collection:

```
not_started ──(worker picks up the Cloud Task)──▶ processing ──▶ completed
                                                        │
                                                        └────────▶ error
```

Key fields: `uid` (the anonymous Firebase UID that owns the job), `status`, `stage`
(1–5, set once the worker starts), `output_data` (present only on success),
`error_data` (present only on failure), `input_source_kind` (`"text"` or `"upload"`),
`input_text`, `input_pdf_gcs_uri`, `expires_at`, and `skipped_files` (filenames from a
multi-file upload that were individually unusable and skipped rather than aborting the
whole request).

### Idempotency and the processing lease

Cloud Tasks is at-least-once delivery, so the worker route can be invoked more than once
for the same job. `routes/worker.py` handles this with a lease pattern: if a job is
already `completed` or `error`, the redelivered request is a no-op (`200`, nothing
re-run). If a job is `processing` and its lease (time since `started_at`) is still
within the internal deadline (`SINGLE_JOB_INTERNAL_DEADLINE_S` = 270 seconds), the
redelivery is also treated as a no-op — this is what prevents a duplicate multi-call
Gemini run (and duplicate billing) for the same job. If the lease has expired, the prior
attempt is presumed crashed and the job is allowed to run again from the start.

## 3. API surface (`backend/routes/`)

All routes except `GET /health` and `GET /` require
`Authorization: Bearer <Firebase ID token>`. Every caller of this application is
anonymous by design — the auth decorator (`verify_firebase_token`) denies anonymous
tokens by default and both job routes opt in explicitly with `allow_anonymous=True`.

### `POST /jobs`

Creates a job. Accepts one of:

- **Pasted text** — a `text` field (multipart form or JSON body). Validated against a
  500,000-character cap and, independently, a 350,000-UTF-8-byte cap (both must pass —
  see [`pipeline.md`](pipeline.md) §5 for why both exist).
- **File upload(s)** — one or more files under a `files` multipart field. Up to 5 files,
  10 MB combined, no per-file size cap. A single unusable file (blank scan, corrupt or
  encrypted PDF, unsupported type) is skipped rather than aborting the whole request;
  the request only fails if *no* file yields usable text.

The pipeline version and whether readability grading runs are not client-settable —
they are fixed server-side (currently `"v1-2"` and grading always on).

**Response:**
- `202 {"job_id": "<uuid>"}` on success.
- `400` with the standard error envelope for a client input error (empty/oversized
  text, no usable file, unsupported file type).
- `413` if the raw request body exceeds the server's hard size ceiling.
- `429` if the caller's IP has exceeded the rate limit.
- `500` if the Cloud Tasks configuration is missing or the task could not be enqueued.

### `DELETE /jobs/<job_id>`

Deletes a job document and its stored input PDF (if any). Not rate-limited — deletion is
a cleanup action, not a cost-incurring one. Requires the caller's Firebase UID to match
the job document's `uid`.

**Response:** `204` on success, `404` if the job doesn't exist, `403` if the caller does
not own it.

### `POST /internal/jobs/execute/<job_id>` (internal — not part of the public API)

Reachable only via Cloud Tasks: requires an `X-CloudTasks-QueueName` header and a valid
OIDC bearer token issued for the configured worker service account, with an audience
matching the exact request URL. Runs the pipeline for one job and writes the result back
to Firestore. Always returns `200` on any outcome Cloud Tasks should not retry
(completed, failed, already-processing, missing doc); returns `500` only for a genuinely
unexpected exception, which Cloud Tasks' own queue-level retry policy may redeliver
(safe, because of the processing lease above).

### `GET /health`

No auth required. Returns `{"status": "healthy", "message": "..."}`.

### `GET /`

No auth required. Returns basic API metadata and the list of documented endpoints.

### Error envelope

Every non-2xx response (except the internal worker route, which never returns a JSON
body) uses one shape:

```json
{
  "status": "error",
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit exceeded",
    "user_hint": "You've reached the limit of 5 simplifications per hour. Please try again later.",
    "retryable": true,
    "details": null,
    "timestamp": "2026-01-01T00:00:00+00:00",
    "path": "/jobs"
  },
  "requestId": "..."
}
```

`code` is a stable machine-readable identifier, `message` is developer-facing,
`user_hint` is safe to show a non-technical end user, and `retryable` indicates whether
retrying the same request is likely to help. See [`pipeline.md`](pipeline.md) §6 for the
full error taxonomy.

## 4. Abuse protection

`POST /jobs` is rate-limited to 5 requests per client IP per rolling wall-clock hour
(`backend/utils/rate_limit.py`), enforced with a Firestore transaction (not an in-memory
counter, since Cloud Run instances don't share memory) keyed on a document ID derived
from an HMAC-SHA256 hash of the client IP plus the current hour. The rate limiter fails
**open**: a transient Firestore error allows the request through rather than blocking
every caller — an availability choice appropriate for an abuse guard on a free feature,
not a strict security boundary. Client IPs are read from `X-Forwarded-For` at a
configurable trusted-hop offset (`TRUSTED_PROXY_HOPS`, default 1, matching a direct
Cloud Run deployment with no external load balancer in front of it) and are never stored
in plaintext.

Independent of the rate limiter, every request is also bounded by the hard upload caps
above (5 files / 10 MB aggregate) and, above both, by each Cloud Run service's
`max-instances` ceiling and the Cloud Tasks queue's own dispatch-rate limit — these bound
worst-case Vertex AI spend regardless of per-IP behavior.

## 5. Firestore, Cloud Tasks, and GCS

- **Firestore** holds two collections: `care_plan_outputs` (one document per job, the
  state machine described above) and `rate_limits` (one document per `{ip-hash, hour}`
  counter, each carrying its own `expires_at`). Firestore's native TTL feature is the
  backstop that eventually sweeps expired documents from both collections — see
  [`data-and-privacy.md`](data-and-privacy.md).
- **Cloud Tasks** decouples job creation from job execution: `simplify-api` enqueues a
  task on the `care-plan-jobs` queue; the queue dispatches an OIDC-signed HTTP request to
  `simplify-worker`, which is otherwise unreachable from the public internet.
- **Cloud Storage** stores one merged, audit-copy PDF per job that included a file
  upload, at `care_plan_inputs/{uid}/inputs/{uuid}.pdf` in the configured bucket. This is
  a stored copy of the original submission, not what the pipeline actually processes —
  the pipeline works from extracted text. The stored PDF is deleted unconditionally at
  the end of every job (success, failure, or exception) and also on explicit job
  deletion.

## 6. Frontend structure (`frontend/`)

A single Vite + React + TypeScript app — one build, one deployment target.

- **`App.tsx`** — routes: `/` (the tool itself), `/privacy`, `/terms`, and a catch-all
  back to `/`. Wrapped in an app-root `ErrorBoundary` so an uncaught render error never
  blanks the whole page.
- **`pages/HomePage.tsx`** — a small state machine over `'upload' | 'processing' |
  'result'`, holding the current `jobId` and (once a job reaches a terminal state) a
  captured snapshot of the final job document. Capturing that snapshot — rather than
  continuing to read the live Firestore listener — is what lets the result screen stay
  rendered after the backend deletes the underlying document.
- **`components/UploadScreen.tsx`** — text or file input, with client-side validation
  (`utils/validateFiles.ts`) mirroring the backend's caps.
- **`components/ProcessingScreen.tsx`** — renders the five pipeline steps live, driven
  by the job document's `stage` field, with a client-side watchdog: if a job never
  reaches a terminal status within 6 minutes, a "taking longer than expected" affordance
  appears (covering the case where the worker container is killed before it can write a
  failure itself).
- **`components/ResultScreen.tsx`** — renders `CarePlanView` (the structured result),
  fires the job's deletion the instant it mounts, and offers a client-generated,
  downloadable HTML report.
- **`hooks/useAnonAuth.ts`**, **`hooks/useJobSnapshot.ts`**, **`hooks/useUnloadCleanup.ts`**
  — anonymous sign-in with a bounded timeout and retry affordance, the live Firestore
  listener, and best-effort deletion on tab close/navigation-away (see
  [`data-and-privacy.md`](data-and-privacy.md) for the deletion mechanics).
- **`api/firebase.ts`** — Firebase app/auth/Firestore initialization; fails loudly at
  module load if the backend base URL (`VITE_API_PROCESSING_URL`) is unset, rather than
  silently sending requests to `"undefined/jobs"`.
- **`analytics/ga.ts`** — an optional Google Analytics 4 integration, gated on
  `VITE_GA_MEASUREMENT_ID` being set. Every tracked event parameter is a fixed literal, a
  count, a category string built from file extensions, a numeric score/duration, or an
  error-code enum — never document content, filenames, or extracted/generated text.
