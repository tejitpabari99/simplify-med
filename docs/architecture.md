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
                                             ├─ resolve input text (GCS payload read)
                                             ├─ runs the four-call pipeline (Vertex AI / Gemini)
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
2. **Resolve input and write the GCS input payload.** `simplify-api`
   (`routes/jobs.py::_resolve_job_input`) extracts text — unitizing it into
   per-(file, page) `SourceSpan` provenance rather than concatenating it with a
   separator marker — and writes **one JSON object**, `JobInputPayload{text,
   provenance}`, to Cloud Storage via `upload_job_input`, getting back
   `input_payload_gcs_uri`. For a file upload, a **separate, optional** GCS write also
   happens: `upload_combined_pdf` merges the accepted files into one audit-copy PDF
   (PDF/TXT/image bytes merged as-is; DOCX/HTML sources merged as a rendered page of
   their *extracted text*) and uploads it, returning `input_pdf_gcs_uri`. These are two
   distinct GCS objects with two distinct purposes: `input_payload_gcs_uri` is what the
   worker actually reads to run the pipeline; `input_pdf_gcs_uri` is a stored copy of
   the original submission, for uploads only, that the pipeline never reads back. See
   [`pipeline.md`](pipeline.md) §1 for *why* unitization needs page/line identity.
3. **Create the job.** A Firestore document is created in `care_plan_outputs` with
   `status="not_started"`, carrying `input_payload_gcs_uri` and `input_pdf_gcs_uri`
   (both optional-shaped on `JobDoc`, though `input_payload_gcs_uri` is always
   populated in practice) — never raw text or provenance inline — and an `expires_at`
   timestamp one hour in the future. `POST /jobs` returns `202 {"job_id": "<uuid>"}`
   immediately — the pipeline itself runs later, in the worker.
4. **Enqueue.** A Cloud Task is created against the `care-plan-jobs` queue, targeting
   `{WORKER_URL}/internal/jobs/execute/{job_id}` and signed with an OIDC token for the
   worker's service account. `simplify-api` validates the Cloud Tasks configuration
   (`CLOUD_TASKS_QUEUE`, `WORKER_URL`, `WORKER_SERVICE_ACCOUNT`) **before** writing the
   Firestore job document, so a configuration error can never leave an orphaned job doc
   with no task behind it. Both the Firestore job-doc write and the Cloud Task enqueue
   happen before `POST /jobs` returns its `202`.
5. **Execute.** `simplify-worker` receives the signed request, verifies it really came
   from Cloud Tasks, marks the job `status="processing"`, calls `load_job_input(job)`
   (one GCS read, downloading and parsing the `JobInputPayload`), then
   `unitize(text, provenance)` to materialize `list[Unit]` in memory, then runs the
   four-call pipeline described in [`pipeline.md`](pipeline.md), writing a `stage`
   update **1–6** to the job document as each step starts.
6. **Complete.** On success the worker writes the structured result to `output_data` and
   sets `status="completed"`; on an unrecoverable failure it writes `error_data` and sets
   `status="error"`. Either way, the worker's `finally` block deletes **both** GCS
   objects — `input_pdf_gcs_uri` if present, and `input_payload_gcs_uri` (always
   populated in practice, so this always fires). There is no Firestore field holding
   the raw input text to clear: `JobDoc` has never had one since input text moved off
   Firestore entirely.
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

Key fields, matching `backend/models/job.py` exactly: `uid` (the anonymous Firebase UID
that owns the job), `status`, `stage` (1–6, set once the worker starts), `output_data`
(present only on success), `error_data` (present only on failure),
`input_source_kind` (`"text"` or `"upload"`), `input_source_filename`,
`input_pdf_gcs_uri`, `input_payload_gcs_uri`, `input_version`, `grading_enabled`,
`expires_at`, and `skipped_files` (filenames from a multi-file upload that were
individually unusable and skipped rather than aborting the whole request).
**Neither a raw-text field nor an inline provenance field exists on this model** — a
reader expecting one (e.g. from an old version of this doc, or from reading only the
earlier unitization design before the GCS-transport change) would be wrong; the raw
document and its provenance map live only in the GCS object `input_payload_gcs_uri`
points at, never inline on `JobDoc` itself.

### Idempotency and the processing lease

Cloud Tasks is at-least-once delivery, so the worker route can be invoked more than once
for the same job. `routes/worker.py` handles this with a lease pattern: if a job is
already `completed` or `error`, the redelivered request is a no-op (`200`, nothing
re-run). If a job is `processing` and its lease (time since `started_at`) is still
within the internal deadline (`SINGLE_JOB_INTERNAL_DEADLINE_S` = 270 seconds), the
redelivery is also treated as a no-op — this is what prevents re-running the pipeline's
four sequential LLM calls a second time and double-billing every Vertex AI call already
made. If the lease has expired, the prior attempt is presumed crashed and the job is
allowed to run again from the start.

## 3. API surface (`backend/routes/`)

All routes except `GET /health` and `GET /` require
`Authorization: Bearer <Firebase ID token>`. Every caller of this application is
anonymous by design — the auth decorator (`verify_firebase_token`) denies anonymous
tokens by default and both job routes opt in explicitly with `allow_anonymous=True`.

### `POST /jobs`

Creates a job. Accepts one of:

- **Pasted text** — a `text` field (multipart form or JSON body). Validated against a
  single 500,000-character cap (`MAX_TEXT_LENGTH`) — see [`pipeline.md`](pipeline.md)
  §3 for why the former second, byte-count cap was removed.
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

Deletes a job document and both of its GCS objects, if present: the stored input PDF
(`input_pdf_gcs_uri`, uploads only) and the input-payload object
(`input_payload_gcs_uri`) — each deletion is best-effort and swallows its own errors.
Not rate-limited — deletion is a cleanup action, not a cost-incurring one. Requires the
caller's Firebase UID to match the job document's `uid`.

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
retrying the same request is likely to help. See [`error-taxonomy.md`](error-taxonomy.md)
for the full error taxonomy.

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
- **Cloud Storage — merged-PDF audit copy.** One merged PDF per job that included a file
  upload, at `care_plan_inputs/{uid}/inputs/{uuid}.pdf` in the configured bucket. This is
  a stored copy of the original submission, not what the pipeline actually processes —
  the pipeline works from the extracted-text input-payload object below. Deleted
  unconditionally at the end of every job (success, failure, or exception) and also on
  explicit job deletion.
- **Cloud Storage — input-payload object.** One `JobInputPayload{text, provenance}` JSON
  object per job, at a sibling path under the same `care_plan_inputs/{uid}/inputs/`
  prefix. Written once by `simplify-api` (`upload_job_input`), read exactly once by
  `simplify-worker` (`load_job_input`), and deleted at job termination (worker `finally`
  block) or on explicit job deletion — same lifecycle shape as the merged-PDF object,
  but this is now the *only* channel carrying the note's text and provenance from API to
  worker. Its size profile is small integers plus one filename per (file, page) span,
  not a duplicate of the note text itself — see PRD 02 §4.1's accounting, not restated
  here.

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
- **`components/ProcessingScreen.tsx`** — renders the **six** pipeline steps live
  (`PIPELINE_STEPS`, `frontend/src/components/ProcessingScreen.tsx:25-32`), driven
  by the job document's `stage` field, with a client-side watchdog: if a job never
  reaches a terminal status within 6 minutes, a "taking longer than expected" affordance
  appears (covering the case where the worker container is killed before it can write a
  failure itself).
- **`components/ResultScreen.tsx`** — renders `CarePlanView` (the structured result),
  fires the job's deletion the instant it mounts, and offers a client-generated,
  downloadable HTML report.
- **`components/CarePlanView.tsx`** and **`utils/buildPdfHtml.ts`** — both render "We
  couldn't confirm the specific findings from your note." in place of the diagnosis
  details block when every `diagnosis.details` entry has been dropped but other visit
  evidence still exists (PRD 18's widened citation-existence check, [`pipeline.md`](pipeline.md)
  §4, can drop every detail without dropping the whole visit).
- **`utils/nextSteps.ts`**'s `resolveWhy()` helper and `types/carePlan.ts`'s
  `why?: string | null` type — the frontend-side fallback for a `null` `why`
  (`Medication`/`Test`/`Procedure`/`OtherInstruction`, PRD 13): `resolveWhy()` renders
  "Not stated in your note." whenever `why` is `null`/`undefined`, so no `care_plan.ts`
  consumer reads `.why` directly.
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
