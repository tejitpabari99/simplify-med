# Deployment

The application deploys to Google Cloud (Cloud Run, Firestore, Cloud Storage, Cloud
Tasks, Cloud Scheduler, Vertex AI) and Firebase (Authentication, Hosting) via the
GitHub Actions workflow at `.github/workflows/deploy.yml`.

## GCP prerequisites

A GCP project with the following APIs enabled:

- Cloud Run
- Cloud Build
- Artifact Registry
- Firestore (Native mode database)
- Cloud Storage
- Cloud Tasks
- Cloud Scheduler
- Vertex AI
- IAM

The same project (or a linked one) needs a Firebase project with **Anonymous
Authentication** enabled — this application does not use any other sign-in method.

## Required GitHub Actions secrets

| Secret | Purpose |
|---|---|
| `GCP_SA_KEY` | JSON key for a GCP service account that can run Cloud Build, deploy/update Cloud Run services and jobs, manage Cloud Tasks queues, manage Cloud Scheduler jobs, and update the upload bucket's lifecycle rules. |
| `FIREBASE_SERVICE_ACCOUNT` | Firebase Admin SDK service-account JSON, used by `firebase-tools` to deploy Firestore rules and Hosting. |
| `RATE_LIMIT_SALT` | Secret salt for hashing client IPs in the per-IP rate limiter. |
| `VITE_FIREBASE_API_KEY` | Firebase web app config, baked into the frontend build. |
| `VITE_FIREBASE_AUTH_DOMAIN` | Firebase web app config. |
| `VITE_FIREBASE_PROJECT_ID` | Firebase web app config. |
| `VITE_FIREBASE_STORAGE_BUCKET` | Firebase web app config. |
| `VITE_FIREBASE_MESSAGING_SENDER_ID` | Firebase web app config. |
| `VITE_FIREBASE_APP_ID` | Firebase web app config. |
| `VITE_API_PROCESSING_URL` | Public base URL of the deployed API Cloud Run service, baked into the frontend build. |

## Required GitHub Actions variables

| Variable | Purpose |
|---|---|
| `GCP_PROJECT_ID` | GCP project to deploy into. |
| `GCP_REGION` | Cloud Run / Artifact Registry / Vertex AI region (e.g. `us-central1`). |
| `GCP_BUCKET_NAME` | GCS bucket used for uploaded input files. |
| `GCP_ARTIFACT_REPO` | Artifact Registry repository name the backend image is pushed to. |
| `API_MAX_INSTANCES` | Optional. Max Cloud Run instances for the API service. Default `10`. |
| `WORKER_MAX_INSTANCES` | Optional. Max Cloud Run instances for the worker service. Default `5`. |

## One-time manual setup

The following is deliberately not automated by the deploy workflow — infrequent,
higher-consequence changes that are safer as an explicit action:

1. **Artifact Registry repository** named `GCP_ARTIFACT_REPO`, in `GCP_REGION`.
2. **IAM service accounts** for the worker and the retention scheduler, each granted
   only the Cloud Run invoker role on the specific service/job it calls:
   - a worker-invoker service account (used as the Cloud Tasks OIDC identity that
     invokes the worker service)
   - a scheduler-invoker service account (used by Cloud Scheduler to invoke the
     retention Cloud Run Job)
3. **A Secret Manager secret** holding the Firebase Admin SDK service-account JSON
   (the same credential as the `FIREBASE_SERVICE_ACCOUNT` GitHub secret above),
   readable by the Cloud Run runtime service account, so both Cloud Run services can
   initialize the Firebase Admin SDK without a mounted key file.
4. **A native Firestore TTL policy** enabled on `care_plan_outputs.expires_at` and
   `rate_limits.expires_at`:

   ```bash
   gcloud firestore fields ttls update expires_at \
     --collection-group=care_plan_outputs --database="(default)" --enable-ttl

   gcloud firestore fields ttls update expires_at \
     --collection-group=rate_limits --database="(default)" --enable-ttl
   ```

   This is one half of the zero-retention design described in
   [`data-and-privacy.md`](data-and-privacy.md); the Cloud Storage lifecycle rule is the
   other half, and it *is* applied automatically on every deploy (see below).

The Cloud Tasks queue itself does **not** need manual creation — the deploy workflow
creates it idempotently on every run if it doesn't already exist.

## How the deploy workflow works

Trigger: a `workflow_run` event on the `CI` workflow completing successfully on `main`,
or a manual `workflow_dispatch`. This means an automatic deploy only happens after CI
has actually passed against the exact commit being deployed. A concurrency group
prevents overlapping production deploys.

1. **Build.** One container image is built from `backend/` via Cloud Build and pushed to
   Artifact Registry.
2. **Ensure the Cloud Tasks queue exists** (idempotent create-or-skip).
3. **Deploy both Cloud Run services from that one image**, distinguished by the
   `SERVICE_MODE` environment variable:
   - `simplify-worker` — `SERVICE_MODE=worker`, `--no-allow-unauthenticated`,
     `--ingress=internal`.
   - `simplify-api` — `SERVICE_MODE=api`, `--allow-unauthenticated`.

   Each is deployed twice in the workflow: a bare first pass (so the revision exists
   and the worker's URL can be read back), then a second pass that sets the full
   environment (GCP project/bucket/region, the Vertex AI model, the Cloud Tasks queue
   name, the worker's own URL, the rate-limit salt) and injects the Firebase service
   account from Secret Manager. Both services deploy at `--min-instances=0`.
4. **Deploy the retention Cloud Run Job** (`simplify-anon-cleanup`, running
   `scripts/cleanup_anonymous_users.py`) and **ensure its daily Cloud Scheduler trigger
   exists** (idempotent update-or-create), targeting the Cloud Run Job's `:run` API via
   an OAuth-authenticated service account.
5. **Apply the Cloud Storage lifecycle rule** on the upload bucket (age-based delete,
   scoped to the upload-input prefix) — idempotent on every deploy.
6. **Build and deploy the frontend**: `npm ci`, `npm run build` (with the `VITE_*`
   secrets injected at build time), deploy Firestore security rules, then deploy to
   Firebase Hosting.
7. **Tag the release.** On success, a `prod-<timestamp>` git tag is created and pushed
   against the deployed commit, marking a known-good production state.

There is no separate rollback or preview-environment workflow in this repository — only
`ci.yml` (lint/type-check/test/build on every push and pull request to `main`) and
`deploy.yml` (production deploy, described above).
