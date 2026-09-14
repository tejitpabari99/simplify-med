# Simplify

Simplify turns a clinical provider note (PDF, TXT, DOCX, HTML, or a photo/scan) into a
structured, plain-language patient care plan: what happened at the visit, what
medications and tests mean, what to watch for, and what to do next. It also computes a
readability score for the note before and after simplification.

There is no account and no login. A visitor gets an anonymous, temporary session, submits
a document or pasted text, and receives a structured result. Submitted content is deleted
as soon as the result has been shown, with automated backstops that remove anything left
behind if that never happens (see [`docs/data-and-privacy.md`](docs/data-and-privacy.md)).

## Safety

- **Not medical advice.** Output is generated automatically by an AI model and may
  contain errors, omissions, or inaccuracies. It is not a substitute for professional
  clinical judgment and must not be used as the basis for a treatment decision.
- **Not a HIPAA-covered service.** No Business Associate Agreement covers this
  application. **Do not upload real, identifiable patient health information.** Use
  sample, redacted, or fictional content only.

## Architecture, in brief

```
Browser (anonymous Firebase Auth)
   │  POST /jobs
   ▼
Cloud Run: juno-api      ──create job doc──▶  Firestore (care_plan_outputs)
   │                                                 ▲
   └──enqueue Cloud Task─────────────────────────────┼──▶ Cloud Run: juno-worker
                                                       │        │
                              live Firestore listener │        ├─▶ Vertex AI (Gemini)
                              (job status/stage)       │        └─▶ GCS (input storage)
   Browser ◀────────────────────────────────────────┘
```

The API and worker roles are deployed as two Cloud Run services (`juno-api` and
`juno-worker` — this app took over existing infrastructure rather than standing up its own;
see [`docs/deployment.md`](docs/deployment.md)) running the **same container image**,
distinguished only by a `SERVICE_MODE` environment variable. `juno-api` is the public,
unauthenticated front door; it creates a Firestore job document and enqueues a Cloud Task.
`juno-worker` is reachable only via Cloud Tasks (OIDC-verified) and runs the actual pipeline: deterministic term detection
followed by three sequential calls to Gemini on Vertex AI. The browser never polls an
HTTP endpoint for status — it attaches a live Firestore listener to the job document.

Full detail: [`docs/architecture.md`](docs/architecture.md).

## Quickstart

See [`docs/local-development.md`](docs/local-development.md) for running the backend
and frontend locally, required environment variables, and test commands.

## Local testing over an ngrok tunnel

For end-to-end testing against a real device or a Firebase Auth flow that needs a
public URL, expose one half of the local stack (backend on `8080` or the frontend
dev server on `5173`, running with `SERVICE_MODE=combined`) through the static
ngrok domain `helene-unreconnoitred-overslowly.ngrok-free.dev`.

**One-time setup:**

- Add `helene-unreconnoitred-overslowly.ngrok-free.dev` (bare host, no scheme) to
  Firebase Auth's authorized domains: Console → Authentication → Settings →
  Authorized domains.
- Put `CORS_ALLOWED_ORIGINS` in `backend/.env` (see `backend/.env.example`).

**The one-tunnel constraint:** a free ngrok account runs one tunnel at a time, so
the static domain points at *either* the backend *or* the frontend dev server, not
both. Pick the arrangement that matches what you're testing:

- **Tunnel the backend** — the browser stays on `http://localhost:5173`; set
  `VITE_API_PROCESSING_URL` (in `frontend/.env.local`) to the tunnel URL. Use this
  for most end-to-end testing.
  ```
  ngrok http 8080 --url=https://helene-unreconnoitred-overslowly.ngrok-free.dev
  ```
- **Tunnel the frontend** — opens the app itself on another device (e.g. a phone,
  to exercise the camera/OCR upload path). The tradeoff: that device can't reach a
  backend on `localhost`, so the backend needs its own reachable URL too.
  ```
  ngrok http 5173 --url=https://helene-unreconnoitred-overslowly.ngrok-free.dev
  ```

`backend/.env` and `frontend/.env.local` are gitignored and never committed. They
don't need to be exported into the shell either: `load_dotenv()`
(`backend/utils/firebase.py`, imported by `backend/app.py` before the CORS
configuration is read) loads `backend/.env` automatically on backend startup.

## Repository layout

```
backend/    Python/Flask API and worker (routes, pipeline, models, tests)
frontend/   React + Vite + TypeScript single-page app
```

## Documentation

| Doc | Covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Topology, request/job lifecycle, API surface, Firestore/Cloud Tasks/GCS roles, frontend structure |
| [`docs/pipeline.md`](docs/pipeline.md) | Input extraction and OCR, the five pipeline stages, term detection, the three Gemini calls, readability scoring, error taxonomy |
| [`docs/data-and-privacy.md`](docs/data-and-privacy.md) | Anonymous auth, every deletion path, retention timing, safety statements |
| [`docs/deployment.md`](docs/deployment.md) | GCP prerequisites, GitHub Actions secrets/variables, one-time manual setup, how the deploy workflow works |
| [`docs/local-development.md`](docs/local-development.md) | Running both halves locally, environment variables, test suites |

## License

MIT — see [`LICENSE`](LICENSE).
