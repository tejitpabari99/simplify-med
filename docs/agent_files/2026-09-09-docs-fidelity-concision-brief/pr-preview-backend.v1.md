# Per-PR backend preview environment

Date: 2026-09-09
Status: designed, not built. Build when there is pipeline work to point it at.

## Purpose

Today a pull request gets a frontend-only preview. `preview.yml` deploys `frontend/` to a Firebase Hosting channel and the preview build talks to the **production** backend — `juno-api` and `juno-worker` stay pointed at prod, deliberately, so an unreviewed PR cannot mutate the shared live project.

That means a PR that changes the pipeline gets no preview of its own behaviour: the link runs the old backend behind a new frontend. This document describes how to give each PR a full-stack environment.

## Two things that look like blockers and are not

**The Cloud Tasks queue is not bound to a worker URL.** Each task's target is built at enqueue time from the api service's `WORKER_URL` env var, and the OIDC audience is set to that same URL (`backend/utils/cloud_tasks.py:46-57`). One shared queue can therefore dispatch to any worker. No new queue is needed — which matters, because the deploy service account deliberately holds no Cloud Tasks IAM at all (it is the Cloud Run runtime SA that enqueues, not the deploy SA).

**The worker's OIDC check computes its own expected audience.** `verify_oidc_token` builds the expected audience from the incoming request's own host — `f"{proto}://{request.host}{request.path}"` (`backend/utils/firebase.py:194-196`) — rather than comparing against a hardcoded production URL. A tagged worker revision at its own URL therefore validates tokens Cloud Tasks minted for that URL, with no code change. The service-account email check (`WORKER_SERVICE_ACCOUNT`) is unaffected, since the preview uses the same invoker SA.

## The one real blocker: CORS

Allowed origins are a hardcoded Python list (`backend/app.py:38-50`):

```python
origins=[
    "https://juno-medical-clarity.web.app",
    "https://juno-medical-clarity.firebaseapp.com",
    "http://localhost:5173",
],
```

A Hosting preview channel serves from `https://juno-medical-clarity--pr-<N>-<hash>.web.app`, which is not in that list, so the preview frontend's preflight to the preview backend fails.

**Required change before any of the below works:** read the origin list from an environment variable, defaulting to the current three values.

```python
_DEFAULT_ORIGINS = [
    "https://juno-medical-clarity.web.app",
    "https://juno-medical-clarity.firebaseapp.com",
    "http://localhost:5173",
]
origins = [
    o.strip()
    for o in os.environ.get("CORS_ALLOWED_ORIGINS", ",".join(_DEFAULT_ORIGINS)).split(",")
    if o.strip()
]
```

Prefer this over a wildcard regex such as `https://juno-medical-clarity--.*\.web\.app`. Production and preview run the **same container image**, so a regex baked into the code would permanently widen production's accepted origins to every preview channel that ever exists. An env var keeps production's list exactly as tight as it is now, and only the preview revision is loosened.

## Design: Cloud Run revision tags

Cloud Run revision tags give a revision its own stable URL while serving zero production traffic. No new services, no new queues, no new IAM.

```
gcloud run deploy juno-worker --image=$PR_IMAGE --no-traffic --tag pr-<N> ...
   └─▶ https://pr-<N>---juno-worker-<hash>.run.app

gcloud run deploy juno-api    --image=$PR_IMAGE --no-traffic --tag pr-<N> \
      --set-env-vars WORKER_URL=<tagged worker URL>,CORS_ALLOWED_ORIGINS=<channel URL> ...
   └─▶ https://pr-<N>---juno-api-<hash>.run.app

frontend built with VITE_API_PROCESSING_URL=<tagged api URL>
   └─▶ Firebase Hosting channel pr-<N>
```

Production keeps serving its own revision throughout. The tagged revisions are addressable only by their tag URLs.

### What is per-revision and what is per-service

This distinction decides what a preview can and cannot change.

| Setting | Scope | Consequence for previews |
|---|---|---|
| Env vars, secrets | Revision | A preview revision can carry its own `WORKER_URL` and `CORS_ALLOWED_ORIGINS`. This is what makes the whole approach work. |
| `--min-instances`, `--max-instances` | Revision | Set `--min-instances=0` on previews (see gotchas). |
| `--memory`, `--timeout` | Revision | Mirror production: api 2Gi/300s, worker 2Gi/900s. |
| `--ingress` | **Service** | `juno-worker` is `--ingress=internal`. A tagged revision inherits it; Cloud Tasks still reaches it, as in production. Do not attempt to change this per preview. |
| `--allow-unauthenticated` | **Service** | `juno-api` is public, so the tagged api URL is publicly reachable. Acceptable for a preview; be aware it is not access-controlled. |

## Implementation

Extend `.github/workflows/preview.yml`. It already runs on `pull_request` with `types: [opened, synchronize, reopened, closed]`, sets `CHANNEL_ID: pr-${{ github.event.number }}`, and is gated to non-fork branches because it needs `FIREBASE_SERVICE_ACCOUNT`. A teardown path for closed PRs already exists (added in `7bec56f`).

1. **Build the PR image.** Reuse the `gcloud builds submit --async` + poll pattern from `deploy.yml` — the deploy SA cannot stream build logs, which is why that workflow decouples submission from status polling. Tag the image distinctly per PR so previews never overwrite the production image.

2. **Deploy the tagged worker revision** with `--no-traffic --tag pr-<N>`, `SERVICE_MODE=worker`, `--min-instances=0`, `--memory=2Gi`, `--timeout=900`, and the worker env set from `deploy.yml`'s `WORKER_ENV_VARS`.

3. **Read back the tagged worker URL.** `gcloud run services describe juno-worker --format='value(status.traffic)'` and select the entry whose `tag` matches, or construct it from the revision's tag URL returned by the deploy.

4. **Deploy the tagged api revision** with `--no-traffic --tag pr-<N>`, `SERVICE_MODE=api`, `--min-instances=0`, `--memory=2Gi`, `--timeout=300`, `WORKER_URL` set to step 3's URL, `CORS_ALLOWED_ORIGINS` set to the channel URL from step 6, and the `FIREBASE_SERVICE_ACCOUNT_JSON=firebase-service-account:latest` secret. Keep `CLOUD_TASKS_QUEUE` pointed at `care-plan-jobs-trial`, as production does.

5. **Ordering problem.** The api revision needs the Hosting channel URL for CORS, but the channel is created by the frontend deploy, which needs the api URL. Break the cycle by deriving the channel URL deterministically — Firebase preview channels follow `https://<site>--<channel-id>-<hash>.web.app`, where the hash is stable per channel — or by deploying the frontend first with a placeholder, then updating the api revision's `CORS_ALLOWED_ORIGINS` once the real URL is known. The second is more robust; prefer it.

6. **Build and deploy the frontend** with `VITE_API_PROCESSING_URL` set to the tagged api URL, to Hosting channel `pr-<N>`, as the workflow already does.

7. **Post the preview links** as a PR comment: both the frontend channel URL and the tagged api URL, so a reviewer can hit `/health` directly.

## Gotchas

- **Set `--min-instances=0` on preview revisions.** Production `juno-api` is pinned to `--min-instances=1` (commit `85c5155`, to avoid cold starts on the live site). Inheriting that would hold a warm instance per open PR, billed continuously for something nobody is using.
- **Never deploy Firestore rules from a preview.** The current workflow does not, and this must not change — rules are global to the shared database.
- **Use `--set-env-vars`, not `--update-env-vars`.** `deploy.yml` uses the replacing form deliberately, to wipe stale vars carried over from main Juno's deploys. Previews should match, so a preview revision's environment is exactly what the workflow states and nothing inherited.
- **Tags accumulate.** Every open PR adds a tag route to both services. Teardown is not optional.
- **Check Firebase Auth authorized domains.** Anonymous sign-in does not redirect, so this usually just works for `*.web.app`, but confirm on the first preview rather than assuming.

## Teardown

Hang this off the existing `closed` handler:

```
gcloud run services update-traffic juno-api    --region "$GCP_REGION" --remove-tags pr-<N>
gcloud run services update-traffic juno-worker --region "$GCP_REGION" --remove-tags pr-<N>
```

Removing the tag drops the route. The underlying revisions become untagged and inactive, and Cloud Run garbage-collects them under its own retention limits. Optionally delete the per-PR image from Artifact Registry in the same step.

The Hosting channel already expires or is deleted by the existing teardown.

## What stays shared, and the risk that comes with it

Preview backends read and write the **live** Firestore database, the **live** GCS bucket, and the **live** Vertex AI project. There is no data isolation.

- Preview jobs write real documents into `care_plan_outputs`, in the same shape production writes, under real anonymous UIDs.
- Those documents are ephemeral by design — deleted when the result screen is reached, with the retention job and GCS lifecycle rule as backstops — so the blast radius is small.
- But a badly broken pipeline in a PR will write malformed documents into the live collection, and a runaway loop will spend real Vertex AI quota.

This is acceptable for a personal project with no real users. It would not be acceptable once there are. The clean answer at that point is a separate staging GCP project, which is real setup work and is deliberately out of scope here.

## Verification checklist for the first preview

1. `curl https://pr-<N>---juno-api-<hash>.run.app/health` returns healthy.
2. The preview frontend loads and completes anonymous sign-in.
3. A submitted job reaches `completed` — this proves the api enqueued to the shared queue with the tagged `WORKER_URL` and the tagged worker accepted the OIDC token.
4. Browser devtools show no CORS errors on the `POST /jobs` preflight.
5. Production `juno-api` and `juno-worker` are still serving their pre-existing revisions — check `gcloud run services describe ... --format='value(status.traffic)'` shows 100% on the untagged revision.
6. After closing the PR, the tag routes are gone from both services.

## Open questions

- Whether to derive the Hosting channel URL deterministically or use the two-pass CORS update (step 5). The two-pass approach is more robust but adds a workflow step and a second `gcloud run services update`.
- Whether preview revisions should use a cheaper Vertex model than production's `gemini-3.5-flash` to limit spend. Argues against: a preview that does not exercise the real model tests the wrong thing.
- Whether to gate preview backend deploys behind a PR label, so that documentation-only PRs do not spin up infrastructure. Probably worth it.
