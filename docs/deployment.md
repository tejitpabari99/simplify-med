# Deployment

The application deploys onto the **shared `juno-medical-clarity` GCP/Firebase project**
(Cloud Run, Firestore, Cloud Storage, Cloud Tasks, Cloud Scheduler, Vertex AI, Firebase
Hosting) via the GitHub Actions workflows at `.github/workflows/deploy.yml` (production) and
`.github/workflows/preview.yml` (per-PR frontend previews).

This is a **takeover of existing infrastructure**, not a fresh stand-up: `juno-medical-clarity`
previously ran a different application ("Juno") on the same Cloud Run services and the same
Firebase Hosting default site. That app's own API routes are retired for good (its frontend was
never released), and this repo's backend (`/jobs` only) now runs on those services instead.
Nothing below is `simplify-*`-prefixed or newly created where an existing resource could be
reused — see the resource list below for exact names.

## Live resource names

| Resource | Name |
|---|---|
| GCP project | `juno-medical-clarity` |
| Region | `us-central1` |
| Cloud Run service (public API) | `juno-api` |
| Cloud Run service (internal worker) | `juno-worker` |
| Backend container image | `us-central1-docker.pkg.dev/juno-medical-clarity/juno/simplify-backend` |
| Artifact Registry repository | `juno` |
| Cloud Tasks queue (used by this app) | `care-plan-jobs-trial` (2/s, max 5 concurrent) |
| Cloud Tasks queue (NOT used by this app) | `care-plan-jobs` (500/s main queue — belongs to the retired Juno app's own routes; left alone) |
| Cloud Run Job (retention) | `juno-trial-anon-cleanup` |
| Cloud Scheduler trigger | `juno-trial-anon-cleanup-daily` (`0 4 * * *` UTC) |
| Worker-invoker service account | `juno-worker-invoker@juno-medical-clarity.iam.gserviceaccount.com` |
| Scheduler-invoker service account | `juno-scheduler-invoker@juno-medical-clarity.iam.gserviceaccount.com` |
| Secret Manager secret (Firebase Admin SDK) | `firebase-service-account` |
| GCS bucket | `juno-medical-clarity-backend` |
| Firestore database | `(default)`, location `nam5` |
| Firebase Hosting site (live) | `juno-medical-clarity` (serves `https://juno-medical-clarity.web.app`) |

`juno-api` and `juno-worker` run the **same container image**, distinguished by the
`SERVICE_MODE` environment variable (`api` / `worker`) — this repo's own contract; it does not
use the previous app's `JUNO_MODE` variable, which deploy.yml removes.

## GCP prerequisites

A GCP project with the following APIs enabled (already true for `juno-medical-clarity`):

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
Authentication** enabled — this application does not use any other sign-in method. This is
already the case for `juno-medical-clarity`.

## Required GitHub Actions secrets

Already provisioned on `tejitpabari99/simplify-med`.

| Secret | Purpose |
|---|---|
| `GCP_SA_KEY` | JSON key for a GCP service account that can run Cloud Build, deploy/update Cloud Run services and jobs, manage Cloud Scheduler jobs, and update the upload bucket's lifecycle rules. |
| `FIREBASE_SERVICE_ACCOUNT` | Firebase Admin SDK service-account JSON, used by `firebase-tools` to deploy Firestore rules and Hosting, and by the preview workflow to deploy Hosting preview channels. |
| `RATE_LIMIT_SALT` | Secret salt for hashing client IPs in the per-IP rate limiter. |
| `VITE_FIREBASE_API_KEY` | Firebase web app config, baked into the frontend build. |
| `VITE_FIREBASE_AUTH_DOMAIN` | Firebase web app config. |
| `VITE_FIREBASE_PROJECT_ID` | Firebase web app config. |
| `VITE_FIREBASE_STORAGE_BUCKET` | Firebase web app config. |
| `VITE_FIREBASE_MESSAGING_SENDER_ID` | Firebase web app config. |
| `VITE_FIREBASE_APP_ID` | Firebase web app config. |
| `VITE_API_PROCESSING_URL` | Public base URL of the deployed `juno-api` Cloud Run service (`https://juno-api-tmvzwqeigq-uc.a.run.app`), baked into the frontend build. Used by both `deploy.yml` and `preview.yml`, so preview builds hit the same production API as production. |

## Required GitHub Actions variables

Already provisioned on `tejitpabari99/simplify-med`.

| Variable | Purpose |
|---|---|
| `GCP_PROJECT_ID` | `juno-medical-clarity` |
| `GCP_REGION` | `us-central1` |
| `GCP_BUCKET_NAME` | `juno-medical-clarity-backend` |
| `GCP_ARTIFACT_REPO` | `juno` |
| `API_MAX_INSTANCES` | Optional. Max Cloud Run instances for `juno-api`. Default `10`. |
| `WORKER_MAX_INSTANCES` | Optional. Max Cloud Run instances for `juno-worker`. Default `5`. |

## One-time manual setup

All of the following was already true on `juno-medical-clarity` at the time this repo took
over the infrastructure (inherited from the previous app, or completed as part of the
takeover) — nothing further is required:

1. **Artifact Registry repository** `juno`, in `us-central1` — already exists.
2. **IAM service accounts** `juno-worker-invoker@` and `juno-scheduler-invoker@` — already
   exist, already carry the `run.invoker` grants this app needs. (There are no
   `simplify-worker-invoker`/`simplify-scheduler-invoker` accounts — the deploy workflow
   never references those names.)
3. **Secret Manager secret** `firebase-service-account` — already exists, already readable by
   the Cloud Run runtime service account.
4. **Native Firestore TTL policies**, enabled on:

   ```bash
   gcloud firestore fields ttls update expires_at \
     --collection-group=care_plan_outputs --database="(default)" --enable-ttl

   gcloud firestore fields ttls update expires_at \
     --collection-group=rate_limits --database="(default)" --enable-ttl
   ```

   `care_plan_outputs` already had TTL active (inherited). `rate_limits` TTL was enabled as
   part of this takeover, since this repo's rate limiter uses that collection name (the
   previous app's equivalent, `trial_rate_limits`, already had TTL active and is unaffected).
   This is one half of the zero-retention design described in
   [`data-and-privacy.md`](data-and-privacy.md); the Cloud Storage lifecycle rule is the
   other half, and it *is* applied automatically on every deploy (see below).

Both Cloud Tasks queues this section used to describe as auto-created already exist
(`care-plan-jobs`, `care-plan-jobs-trial`) — inherited from the previous app and managed
outside this workflow. The deploy workflow deliberately neither creates nor inspects either
queue: at runtime it's the Cloud Run runtime service account (default compute), not the
deploy service account, that enqueues tasks, so the deploy service account intentionally
holds no Cloud Tasks IAM permissions.

## Firestore rules on a shared database

`firestore.rules` in this repo deploys onto the **same, shared** Firestore database the
previous app used. Before the takeover, the two rule sets were diffed: the previous app's
rules covered only `care_plan_outputs` (identical `get`/`list`/`write` conditions to this
repo's); this repo's rules are a strict superset, adding an explicit deny-all block for
`rate_limits` (defense-in-depth — the collection is written only via the Admin SDK, which
bypasses rules entirely). The previous app's live frontend only ever read
`care_plan_outputs/{jobId}` documents directly by ID; nothing it depends on is omitted here.
Deploying this repo's rules does not remove access to anything the running app needs.

## How the deploy workflow works

Trigger: a direct `push` to `main`, or a manual `workflow_dispatch`. Deploy runs on every
push to `main` independently of the `CI` workflow — it no longer waits on, or depends on the
outcome of, CI passing. (`ci.yml` still runs lint/type-check/test/build on its own on every
push and pull request to `main`; it just no longer gates this deploy.) A concurrency group
prevents overlapping production deploys.

1. **Build.** One container image is built from `backend/` via Cloud Build and pushed to
   Artifact Registry (`juno` repo, `simplify-backend` image).
2. **Deploy both Cloud Run services from that one image**, distinguished by the
   `SERVICE_MODE` environment variable:
   - `juno-worker` — `SERVICE_MODE=worker`, `--no-allow-unauthenticated`, `--ingress=internal`.
   - `juno-api` — `SERVICE_MODE=api`, `--allow-unauthenticated`.

   Each is deployed twice in the workflow: a bare first pass (so the revision exists and the
   worker's URL can be read back), then a second pass that sets the full environment (GCP
   project/bucket/location, the Vertex AI model, the trial Cloud Tasks queue name, the
   worker's own URL, the rate-limit salt) and injects the Firebase service account from Secret
   Manager. The second pass uses `--set-env-vars` (full replace, not merge) specifically so
   that env vars left over from the previous app (`JUNO_MODE`, `TRIAL_RATE_LIMIT_SALT`,
   `CLOUD_TASKS_QUEUE_TRIAL`) are removed rather than accumulating alongside this repo's own
   vars; the worker deploy additionally uses `--remove-secrets` to detach the previous app's
   Athena Health secret refs, which this repo's code never reads.

   Both services deploy at `--min-instances=0`, per this repo's stated zero-idle-cost design.
   **Note:** `juno-api` ran at `--min-instances=1` before this takeover (no cold starts on
   the live site) — deploying at `0` is a deliberate departure from that prior behavior, not
   an oversight; see the comment at the top of `deploy.yml` if that trade-off needs revisiting.

   `GCP_LOCATION` is set to `global` (not `GCP_REGION`), matching what was already running
   live in production for both services, rather than switching Vertex AI's endpoint to a
   regional one as part of an unrelated infra change.
3. **Deploy the retention Cloud Run Job** (`juno-trial-anon-cleanup`, running
   `scripts/cleanup_anonymous_users.py`) and **ensure its daily Cloud Scheduler trigger**
   (`juno-trial-anon-cleanup-daily`) **exists** (idempotent update-or-create), targeting the
   Cloud Run Job's `:run` API via an OAuth-authenticated service account
   (`juno-scheduler-invoker@`).
4. **Apply the Cloud Storage lifecycle rule** on the upload bucket. The bucket is shared with
   the previous app, which already had a rule protecting its own `care_plan_trial/` prefix;
   since `gcloud storage buckets update --lifecycle-file` replaces the entire rule set, this
   step always writes both prefixes (`care_plan_inputs/` for this app, `care_plan_trial/` for
   the previous app) so neither loses retention coverage.
5. **Build and deploy the frontend**: `npm ci`, `npm run build` (with the `VITE_*` secrets
   injected at build time), deploy Firestore security rules, then deploy to Firebase Hosting
   site `juno-medical-clarity` (see `firebase.json`'s `hosting.site` key) — the same site that
   served the previous app's live frontend.
6. **Tag the release.** On success, a `prod-<timestamp>` git tag is created and pushed
   against the deployed commit, marking a known-good production state.

## Preview deployments

`.github/workflows/preview.yml` deploys `frontend/` to a temporary Firebase Hosting preview
channel (`pr-<PR number>`, expiring after 7 days) on every push to a same-repo pull request
(forked PRs are skipped, since they cannot read repo secrets). The preview build uses the
same `VITE_*` secrets as production, so it talks to the **live production API and Firestore
rules** (`https://juno-api-tmvzwqeigq-uc.a.run.app`) — there is no per-PR backend, and the
preview workflow never deploys Firestore rules. The channel URL is posted as a PR comment,
which is edited in place on subsequent pushes rather than duplicated.

`ci.yml` remains lint/type-check/test/build on every push and pull request to `main`, and is
unrelated to deployment.
