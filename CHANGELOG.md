# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
