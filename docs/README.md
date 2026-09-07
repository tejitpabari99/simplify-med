# Documentation Index

- [`architecture.md`](architecture.md) — system topology, the two Cloud Run services and
  how one image serves both, the full request/job lifecycle from upload to result, the
  API surface, and the roles of Firestore, Cloud Tasks, GCS, and the frontend.
- [`pipeline.md`](pipeline.md) — the processing pipeline in depth: input extraction and
  OCR, the five simplification stages, term detection against the jargon dictionaries,
  the three sequential Gemini calls, readability scoring, and the error taxonomy.
- [`data-and-privacy.md`](data-and-privacy.md) — anonymous authentication, every data
  deletion path and its timing, and the service's safety and compliance posture.
- [`deployment.md`](deployment.md) — GCP prerequisites, required GitHub Actions secrets
  and variables, one-time manual setup, and how the deploy workflow operates.
- [`local-development.md`](local-development.md) — running the backend and frontend
  locally, required environment variables, and how to run the test suites.
