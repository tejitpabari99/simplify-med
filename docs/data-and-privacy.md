# Data and Privacy

## Safety and scope

- **Not medical advice.** Output is generated automatically by an AI model and may
  contain errors, omissions, or inaccuracies. It is not a substitute for professional
  clinical judgment.
- **Not a HIPAA-covered service.** No Business Associate Agreement covers this
  application. **Do not upload real, identifiable patient health information (PHI).**
  Use sample, redacted, or fictional content only.

## Identity: anonymous authentication only

There is no login and no account. On page load, the browser calls Firebase's
`signInAnonymously()` (`frontend/src/hooks/useAnonAuth.ts`) — no email, password, or
personal information is collected. The resulting anonymous Firebase UID is the only
identity involved; it is used solely to scope ownership of a job document (so one
session cannot read or delete another session's job) and is not linked to any
identifying information.

The backend's auth decorator denies anonymous Firebase tokens by default across the
whole application; the two `/jobs` routes are the only ones that opt in to accepting
them (`allow_anonymous=True`), since every caller of this application is anonymous by
design.

## What is stored, and where

| Store | Shape | Notes |
|---|---|---|
| Firestore `care_plan_outputs` | One document per job | Holds job status, stage, and the completed result. The resolved input text never touches Firestore at all — it lives only in the transient GCS input-payload object (below), read once by the worker and deleted at job termination. Carries `expires_at`, one hour after creation. |
| Firestore `rate_limits` | One document per `{IP hash, hour}` | Per-IP request counters for the abuse guard on `POST /jobs`. Carries its own `expires_at`, set past the counter's own natural expiry with a safety margin. Client IPs are never stored in plaintext — only an HMAC-SHA256 hash. |
| Cloud Storage | One merged PDF per job that included a file upload | A stored copy of the original submission (not what the pipeline processes — the pipeline works from extracted text), stored under a dedicated upload prefix in the configured bucket. |

## Every deletion path

| # | Path | Trigger | Timing |
|---|---|---|---|
| 1 | Explicit client `DELETE /jobs/<id>` | Fires the instant the result screen mounts for a completed or errored job | Effectively immediate |
| 2 | Best-effort delete on page unload | `pagehide` (any non-upload screen) or `visibilitychange`→hidden (result screen only) | Immediate, best-effort |
| 3 | Cloud Storage input cleanup | The worker's `finally` block, on every job outcome (success, failure, or exception) | End of job execution |
| 4 | GCS input-payload cleanup | Unconditional, in the same worker `finally` block, and again on explicit `DELETE /jobs/<job_id>` | End of job execution, or the moment the caller deletes the job |
| 5 | Firestore native TTL sweep | `expires_at` = 1 hour after job creation | Firestore's documented TTL sweep SLA is "typically within 24 hours" of expiry — worst case roughly **25 hours** |
| 6 | Cloud Storage lifecycle rule | Bucket-level age-based delete rule applied by the deploy workflow | 1 day |
| 7 | Scheduled anonymous-account cleanup | Daily Cloud Scheduler trigger → Cloud Run Job | Deletes anonymous Firebase Auth accounts (no linked sign-in provider) older than 24 hours |

**Path 1 — explicit delete.** `ResultScreen.tsx` calls `DELETE /jobs/<id>` the instant
the result screen mounts for a completed-or-errored job; the visitor does not need to
close the tab or navigate away. A shared guard prevents this from double-firing against
path 2.

**Path 2 — unload cleanup.** `useUnloadCleanup.ts` wires `window.pagehide` (fires on
genuine navigation-away or tab close, including back/forward-cache eviction) for any
non-upload screen state, and `visibilitychange`→hidden only once the app is on the
result screen — deliberately *not* while a job is still processing, so switching tabs or
locking the phone mid-processing can never delete a still-running job. An abandoned
processing job is left to the TTL backstop (path 5) instead.

**Path 3 — Cloud Storage input cleanup.** The worker's `finally` block deletes **two**
GCS objects at the end of job execution, not one: the stored input PDF
(`input_pdf_gcs_uri`, uploads only) and the input-payload object
(`input_payload_gcs_uri`, described in Path 4 below) — after the pipeline has already
extracted whatever text it needed from the latter. Both deletes are best-effort and
swallow their own errors — a cleanup failure must never fail the job. This second
object's deletion here was previously entirely undocumented.

**Path 4 — GCS input-payload cleanup.** There is no raw-text field on the job
document to clear — input text was moved off Firestore entirely (PRD 09) into a
transient GCS object, `JobInputPayload{text, provenance}`, referenced by the job
document's `input_payload_gcs_uri`. That object — not a Firestore field — is what gets
deleted: unconditionally in the worker's `finally` block (alongside `input_pdf_gcs_uri`,
Path 3) and again on `DELETE /jobs/<job_id>` (alongside the merged-PDF object). This is a
genuinely different mechanism from the old field-clearing description — object deletion,
not field deletion. (The internal pipeline's fact-ID provenance fields are also stripped
from the stored result before it is written — see [`pipeline.md`](pipeline.md) §7.)

**Path 5 — Firestore TTL.** `expires_at` is set to one hour after job creation.
Firestore's native TTL feature is the backstop that eventually removes the document if
neither path 1 nor path 2 ever fires — for example, the visitor closes the tab
mid-processing and never returns. Firestore's own documented TTL sweep SLA is "typically
within 24 hours" of the expiry timestamp, not immediate, so the honest worst case for an
abandoned job is **1 hour (`expires_at`) + up to ~24 hours (sweep latency) ≈ 25 hours**
before the document is guaranteed gone. This is stated as "typically within a day," not
"within an hour," in the product's own privacy copy.

**Path 6 — Cloud Storage lifecycle rule.** The deploy workflow applies a bucket-level
lifecycle rule that deletes objects under the upload-input prefix after 1 day, as a
backstop independent of path 3's per-job delete.

**Path 7 — anonymous account cleanup.** A scheduled Cloud Run Job scans Firebase Auth
for accounts with no linked sign-in provider (i.e., created via anonymous sign-in) and
deletes those older than 24 hours, on a daily schedule. This targets stray anonymous
*identities*, not job data — a separate cleanup surface from paths 1–6.

## Third parties involved in processing

Submitted content is sent to Google Cloud Vertex AI (Gemini) to generate the simplified
result and to Google Firebase to coordinate the background job and briefly store its
status and result while it runs. No other third party receives document content.

## Analytics

An optional Google Analytics 4 integration is gated on a measurement ID being configured
at build time; if unset, no analytics script loads at all. Every tracked event parameter
is one of: a fixed literal, a count, a category string built from file extensions (never
filenames), a numeric score or duration, an error-code enum, or a page path — never
document content, filenames, extracted text, or generated care-plan text.

## Rate limiting

Submissions are limited per client IP (5 per hour) to keep the service available to
everyone without requiring an account. See [`architecture.md`](architecture.md) §4 for
the mechanism.
