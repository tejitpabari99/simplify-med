# Documentation Index

**New to this codebase? Start with [`flow.md`](flow.md)** — it traces one concrete note
from upload to rendered care plan, end to end, with a sequence diagram, and links into
the per-topic docs below for depth.

- [`flow.md`](flow.md) — the recommended entry point: one continuous narrative tracing a
  single request from upload through the four-call pipeline to a rendered, deleted job,
  with a mermaid sequence diagram.
- [`architecture.md`](architecture.md) — system topology, the two Cloud Run services and
  how one image serves both, the full request/job lifecycle from upload to result
  (including the GCS `JobInputPayload` transport and the unitizer), the API surface, and
  the roles of Firestore, Cloud Tasks, GCS, and the frontend.
- [`pipeline.md`](pipeline.md) — the processing pipeline in depth: input extraction and
  unitization, image OCR, the four LLM calls (`ground`, `assemble_and_render`, `review`,
  `correct`) and their deterministic checks, the glossary-curation thread, readability
  scoring, and the six progress steps — see [`error-taxonomy.md`](error-taxonomy.md) for
  what can fail at each step.
- [`error-taxonomy.md`](error-taxonomy.md) — the `codes.py`/`exceptions.py` error split,
  the failure-category list, and a table of which pipeline step can produce which
  `ErrorCode`.
- [`data-and-privacy.md`](data-and-privacy.md) — anonymous authentication, every data
  deletion path and its timing, and the service's safety and compliance posture.
- [`testing.md`](testing.md) — what each backend test layer (unit, integration,
  prompt-content regression, dead-code guard) actually checks, and a short pointer to the
  frontend suite.
- [`uncalibrated-constants.md`](uncalibrated-constants.md) — the durable register of
  constants this codebase's PRDs describe as reasoned, not measured or calibrated.
- [`deployment.md`](deployment.md) — GCP prerequisites, required GitHub Actions secrets
  and variables, one-time manual setup, and how the deploy workflow operates.
- [`local-development.md`](local-development.md) — running the backend and frontend
  locally, required environment variables, and how to run the test suites.

## Data model, at a glance

Every named type used across these docs, with where it's defined and where it lives and
dies. See the linked section for the full shape and behavior.

| Type | What it is | Where it's defined | Where it lives and dies | Depth |
|---|---|---|---|---|
| `Unit` | One numbered, per-line piece of evidence (`file`/`page`/`line`/`extraction_method`) the grounding call cites by id | `backend/models/ledger.py` | Never persisted — materialized in memory by the worker immediately before grounding, discarded after the job finishes | [`pipeline.md`](pipeline.md) §1 |
| `Fact` | A verified, grounded claim (category, cited `unit_id`, located quote) produced by `ground` | `backend/models/ledger.py` | Never persisted — pipeline-internal, held only in memory for the run | [`pipeline.md`](pipeline.md) §4 |
| `SourceSpan` | One (file, page)-granularity provenance span with `extraction_method` | `backend/models/provenance.py` | Transient — written into the GCS `JobInputPayload` object by the API, read once by the worker, deleted at job end | [`pipeline.md`](pipeline.md) §1, [`architecture.md`](architecture.md) §2 |
| `JobInputPayload` | The `{text, provenance}` JSON object carrying a job's resolved input off Firestore | `backend/models/provenance.py` | Transient — one GCS object per job, written once, read once, deleted at job termination or explicit delete | [`architecture.md`](architecture.md) §2/§5 |
| `CarePlan` | The structured, patient-facing result (`summary`, `diagnosis`, `medications`, ... `terms`) | `backend/models/care_plan/care_plan.py` | One per job — written to `JobDoc.output_data` in Firestore, then rendered by the frontend and deleted with the job doc. Item models' `why` is now nullable (`str \| None`, PRD 13), and `DiagnosisDetail`/`ReasonForVisit`/`Diagnosis` carry fact-ID provenance (`source_fact_ids`, `changed_since_last_visit_fact_ids`, PRD 18) | [`pipeline.md`](pipeline.md) §4/§7 |
| `JobDoc` | The Firestore state-machine document tracking one job (`status`, `stage`, GCS URIs, ...) | `backend/models/job.py` | One per job — Firestore document in `care_plan_outputs`, deleted on display or by TTL/lifecycle backstop | [`architecture.md`](architecture.md) §2 |
| `ReviewResult`/`Correction` | The review call's per-field corrections and coverage walk | `backend/models/review.py` | Never persisted — pipeline-internal, consumed by `correct` and then discarded | [`pipeline.md`](pipeline.md) §4 |
