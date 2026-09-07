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
Cloud Run: simplify-api  ──create job doc──▶  Firestore (care_plan_outputs)
   │                                                 ▲
   └──enqueue Cloud Task─────────────────────────────┼──▶ Cloud Run: simplify-worker
                                                       │        │
                              live Firestore listener │        ├─▶ Vertex AI (Gemini)
                              (job status/stage)       │        └─▶ GCS (input storage)
   Browser ◀────────────────────────────────────────┘
```

`simplify-api` and `simplify-worker` are the **same container image**, deployed as two
Cloud Run services and distinguished only by a `SERVICE_MODE` environment variable.
`simplify-api` is the public, unauthenticated front door; it creates a Firestore job
document and enqueues a Cloud Task. `simplify-worker` is reachable only via
Cloud Tasks (OIDC-verified) and runs the actual pipeline: deterministic term detection
followed by three sequential calls to Gemini on Vertex AI. The browser never polls an
HTTP endpoint for status — it attaches a live Firestore listener to the job document.

Full detail: [`docs/architecture.md`](docs/architecture.md).

## Quickstart

See [`docs/local-development.md`](docs/local-development.md) for running the backend
and frontend locally, required environment variables, and test commands.

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
