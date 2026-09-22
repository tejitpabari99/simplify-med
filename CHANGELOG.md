# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-09-14

### Changed

- Fidelity and soundness hardening across the four-call pipeline (PRDs 10, 11, 12, 13,
  14, 18):
  - **Numeric integrity (PRD 10).** Added a `NUMERACY` block to the shared
    `_STYLE_RULES` prompt include (reaching both `assemble_and_render.txt` and
    `correct.txt`) instructing the model never to add a label, reference range,
    rounding/truncation, unit conversion, percent/frequency reframe, or unattributed
    severity word to a number. Added a log-only, deterministic numeric-parity check
    (`_check_numeric_parity`) that flags a `WARNING` per rendered number with no
    matching token among its cited facts.
  - **Omission signal (PRD 11).** Added a log-only `coverage_signal` (`{total,
    omitted, rate, omitted_by_category}`), logged once per run by `review()`'s
    `_log_coverage_summary`, read from the review call's already-computed, already-
    discarded per-fact coverage walk.
  - **Extraction provenance (PRD 12).** Added a required `extraction_method:
    Literal["native", "ocr", "pasted"]` field to `SourceSpan` and `Unit`, copied from
    span to unit. Added two log-only aggregates: `extraction_signal` (units by
    `extraction_method`, logged by `unitize()`) and `extraction_signal_facts`
    (verified facts citing an OCR-extracted unit, logged by `ground()`).
  - **Absent-value contract (PRD 13).** `Medication.why`, `Test.why`, `Procedure.why`,
    and `OtherInstruction.why` are now `str | None = None` instead of `str = ""` with
    an app-written placeholder sentinel; the prompts instruct the model to emit `null`
    for a genuinely unstated reason, and the placeholder sentinel string is deleted
    from `assemble_and_render.txt`/`correct.txt`. The frontend's `nextSteps.ts`
    gained a `resolveWhy()` fallback rendering "Not stated in your note." for a
    `null`/`undefined` `why`.
  - **Merge provenance (PRD 14).** Hardened the `assemble_and_render.txt` prompt's
    `MERGE` paragraph by extending its worked example from two sites to three. Added
    a log-only, always-on `merge_candidate_signal` aggregate (`{total, by_section}`)
    counting item-list entries citing more than one fact.
  - **Diagnosis soundness (PRD 18).** Added `source_fact_ids` to `DiagnosisDetail`/
    `ReasonForVisit` and `changed_since_last_visit_fact_ids` to `Diagnosis`; widened
    `_verify_assembly`'s citation-existence check to cover the `reason_for_visit` and
    `diagnosis` blocks, not only the item-list fields. The frontend's
    `CarePlanView.tsx`/`buildPdfHtml.ts` now render "We couldn't confirm the specific
    findings from your note." when every `diagnosis.details` entry has been dropped
    but other visit evidence still exists.

## [0.2.0] - 2026-09-14

### Changed

- Inverted the pipeline from a five-stage, three-Gemini-call design (extract, detect
  terms, simplify language, clarify actions/numbers, structure) to a four-LLM-call,
  ground-then-render design: `ground` → `assemble_and_render` → `review` → `correct`,
  plus a deterministic unitizer (`services/unitizer.py::unitize`) and a
  concurrent glossary-curation background thread.
- Moved a job's resolved input text off Firestore entirely: the API now writes one
  `JobInputPayload{text, provenance}` JSON object to a transient GCS object
  (`upload_job_input`/`load_job_input`), read once by the worker and deleted at job
  termination — `JobDoc` no longer carries raw input text or provenance inline.
- Raised the OCR downscale ceiling (`_MAX_LONG_EDGE_PX`) from 2048px to 4096px.

### Removed

- The dual length-cap on submitted text (a 350,000 UTF-8-byte cap alongside the
  character cap) in favor of a single `MAX_TEXT_LENGTH` (500,000-character) cap — the
  byte cap existed only for Firestore's 1 MiB per-document limit, which no longer
  applies now that input text lives in GCS, not Firestore.

## [0.1.0] - 2026-09-07

### Added

- Initial public release of Simplify: a web app that turns a clinical provider note
  into a structured, plain-language patient care plan using Gemini on Vertex AI.
- Input via pasted text or up to 5 uploaded files (PDF, TXT, DOCX, HTML, or image —
  PNG/JPG/JPEG/WEBP/HEIC, with OCR for image and scanned content), capped at 10 MB
  aggregate; pasted text capped at 500,000 characters / 350,000 UTF-8 bytes.
- A five-stage pipeline — extract text, detect medical terms, simplify language, clarify
  actions and numbers, and structure the care plan — built on three sequential Gemini
  calls on Vertex AI.
- Structured output covering why the patient came in, what the doctor found,
  medications, tests, procedures, other instructions, what to watch for, questions to
  ask at the next visit, follow-up, other items from the visit, a medical-terms
  glossary, and data sources, plus a before/after readability score.
- Downloadable, self-contained HTML report of the generated care plan.
- No-login access via anonymous Firebase Authentication. No account or job data is kept
  beyond the session: the client deletes the job record once results are shown, backed
  by a Firestore TTL and a GCS lifecycle rule as automatic backstops, plus a scheduled
  cleanup of anonymous auth accounts.
- Abuse and cost controls: a per-IP rate limit on job submission, Cloud Run instance
  ceilings, and Cloud Tasks queue concurrency limits.
- Backend: Python/Flask on Cloud Run (separate API and worker services), Firestore for
  job state, Cloud Tasks for dispatch, and Cloud Storage for uploaded input.
- Frontend: React + Vite + TypeScript, deployed to Firebase Hosting.
