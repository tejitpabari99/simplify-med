# Tasks: Technical Documentation

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01–09 (implemented, landed — the pipeline this rewrite documents) and 10–15 (written, not yet implemented — PRD §4.0 is the binding decision that this rewrite documents the post-01-09 state now and does **not** wait for or speculatively describe 10–15). Depended on by: 17 (scientific-documentation) — the two doc families cross-reference each other (PRD §3); nothing else in this batch depends on 16 landing.

**Cross-PRD file ownership — read this before Task 1.** `docs/uncalibrated-constants.md` is created by **this** PRD's task list (Task 1 below), not by PRD 17. PRD 15 §4.3 is the sole author of the file's *content* (its exact seven-column format and seed rows, transcribed verbatim in Task 1); PRD 17's own task list only adds links *into* this file from `docs/science/evidence-map.md`/`design-rationale.md` and must not re-create it. This split is confirmed identically in PRD 15 §4.3 ("created by PRD 16... not this PRD's job either... and not PRD 17's job either"), PRD 16 §9 (`[RESOLVED: PRD 16 creates docs/uncalibrated-constants.md...]`), and PRD 17 §9 (`[RESOLVED: PRD 16 creates and owns docs/uncalibrated-constants.md; PRD 17 only links to it.]`). No duplication risk found.

**Audit discrepancy found and flagged — read this before Task 4.** PRD §1.3's audit table for `docs/architecture.md` lists five stale claims (the diagram's "5-step pipeline," the "1–5" stage range, the `input_text`-clearing sentence, the job-doc field list, and the dual length-cap sentence). Verifying the real file turned up a **sixth stale claim the PRD's own audit missed**: `docs/architecture.md:242`, inside the "Frontend structure" section (§4.1.3 item 6), reads *"renders the **five** pipeline steps live"* — but the PRD's own §4.0/§1.3 elsewhere states (and this was independently re-verified against the live file) that `ProcessingScreen.tsx` already has **six** `PIPELINE_STEPS` entries. PRD §4.1.3 item 6 claims "Frontend structure — current §6, unchanged... verified accurate against every file it names," which this one sentence contradicts. Per this task's own charter, the real tree wins: Task 4 below fixes this sentence too, even though PRD §4.1.3 nominally scoped item 6 as "unchanged." No other discrepancies were found — every other quoted line/claim in PRD §1.3's audit table was verified byte-for-byte against the real files (`docs/README.md:7-8`, `docs/pipeline.md:26,50,69-73,79-142,196,226`, `docs/architecture.md:36,71,75,95,122-123`, root `README.md:43,101`, `backend/models/job.py`'s real field list, `CONTRIBUTING.md`, `CHANGELOG.md`) and all matched exactly.

**Conventions**

- This is a documentation-only PRD: no `backend/`/`frontend/` application code changes except Task 12 (the one test file PRD §4.6 authorizes). Most tasks touch only files under `docs/` plus the three root files (`README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`).
- Backend tests (Task 12/13 only): from `backend/`, run `python -m pytest tests/ -q`. Lint: `ruff check .` from `backend/`.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given — later tasks link into content earlier tasks create.
- Every task traces to a PRD `## 4. Architecture Decisions` subsection, cited inline; do not add doc files, sections, or claims beyond what §4 specifies.
- Carry the PRD's exact specified structure/content lists verbatim into each doc's headings/sections where §4 gives them — do not paraphrase a numbered list PRD §4 already wrote out.
- Cross-reference convention to use in every rewritten doc (PRD §3, binding): inline pointer `— see [<doc>.md](<doc>.md) for why` (technical → scientific) is not used by this PRD's own docs pointing at each other (that's for pointing into PRD 17's `docs/science/` family, out of scope until 17 lands); *within* this PRD's own doc family, use plain relative markdown links with one clause of context, matching the current docs' existing style (e.g. `see [pipeline.md](pipeline.md) §7`).

---

### Task 1 — New `docs/uncalibrated-constants.md`

   - Files: `docs/uncalibrated-constants.md` (new file)
   - Changes (PRD §4.1's table row; PRD §9 `[RESOLVED: ... this PRD creates docs/uncalibrated-constants.md ...]`; content authored by PRD 15 §4.3, transcribed verbatim, not re-derived): Create the file with:
     - A one-line intro stating this is the durable register of constants named in this codebase's PRDs as "reasoned, not measured/calibrated" — content owned by PRD 15 §4.3, this file created and maintained here per PRD 16 §4.1/§9 and PRD 17 §9's confirmed split.
     - The exact seven-column table header: `| Constant | Value | Defined in | What it controls | Why this value | How it would be calibrated | Owner (PRD) |`.
     - The six seed rows verbatim from PRD 15 §4.3: `_QUOTE_MIN_LENGTH` (12, `pipeline.py:132`, owner 03), `_QUOTE_LONG_WORD_MIN_LENGTH` (7, `pipeline.py:133`, owner 03), `_MAX_PII_TOKEN_DELTA` (4, `pipeline.py:530`, owner 05), `GLOSSARY_CURATION_TIMEOUT_S` (20, `utils/constants.py:108`, owner 06), `_MAX_LONG_EDGE_PX` (4096, `utils/image_ocr.py:12`, owner 02), `_UNIT_WORD_MAX_LENGTH` (15, not yet landed — PRD 10 §4.2, owner 10) — copy every cell (Value, Defined in, What it controls, Why this value, How it would be calibrated, Owner) exactly as PRD 15 §4.3 gives them; do not shorten or reword any cell.
     - The "Deliberately not seeded, with reasons" paragraph verbatim from PRD 15 §4.3 (the `MAX_TOKENS_LONG_FORM`/`MAX_TEXT_LENGTH`/`TRUSTED_PROXY_HOPS`/rate-limit exclusions and the "register's scope stays narrow" sentence).
     - A "Maintenance rule" line verbatim from PRD 15 §4.3: any future PRD introducing or changing a reasoned-not-measured numeric constant adds/updates a row here as part of its own scope.
   - Acceptance criteria:
     - `grep -c "^|" docs/uncalibrated-constants.md` shows at least 8 table rows (1 header + 1 separator + 6 seed rows).
     - `grep -c "_QUOTE_MIN_LENGTH\|_QUOTE_LONG_WORD_MIN_LENGTH\|_MAX_PII_TOKEN_DELTA\|GLOSSARY_CURATION_TIMEOUT_S\|_MAX_LONG_EDGE_PX\|_UNIT_WORD_MAX_LENGTH" docs/uncalibrated-constants.md` returns 6 (each constant named exactly once, in its own row).
     - `grep -c "Deliberately not seeded" docs/uncalibrated-constants.md` returns 1.
     - No mention of RF/DJ/PD tagging or the evidence-labeling convention itself appears in this file (that's PRD 15's own doc, out of scope here — this file is the register only).

### Task 2 — Rewrite `docs/pipeline.md`

   - Files: `docs/pipeline.md`
   - Dependency: after Task 1 (this doc's footer links to `docs/uncalibrated-constants.md`).
   - Changes (PRD §4.1.2, ten items — follow this exact structure top to bottom, replacing the current five-stage doc entirely):
     1. **Input extraction and unitization.** Keep the current per-format extraction table (TXT/PDF/DOCX/HTML/image dispatch, §1 of the current doc — verified still accurate) as-is. Remove the `--- Source: <filename> ---` marker sentence (current line 26 — `source_separator` was deleted by PRD 02 §4.6). Add: `resolve_uploaded_files` building `provenance: list[SourceSpan]` at (file, page) granularity in the API process; the GCS `JobInputPayload` round-trip (mechanics owned by `architecture.md`, this section only explains *why* — so grounding can cite `[unit_id]` instead of the model inventing a location); `services/unitizer.py::unitize`/`provenance_for_pasted_text` materializing `list[Unit]` once, in the worker, immediately before grounding. Include the `Unit.file`/`Unit.page`/`Unit.line` semantics table per source type (PDF real page numbers with gaps for blank pages; TXT/DOCX/HTML/image constant page 1; pasted text as the `"text_input"` sentinel) — copy this table verbatim from PRD 02 §4.2.
     2. **Image OCR.** Keep current §2 mechanism (Gemini-vision-call, `NO_TEXT_FOUND` sentinel), correct the downscale ceiling from "2048 px" (current line 50) to **4096px**, sourced from `_MAX_LONG_EDGE_PX` in `backend/utils/image_ocr.py`.
     3. **Length limits.** Replace the dual-cap description (current lines 69-73, "350,000 UTF-8-encoded bytes... checked alongside") with the single `MAX_TEXT_LENGTH` (500,000 chars) cap only. State plainly the former dual-cap design is gone because Firestore's 1 MiB limit no longer applies once input text lives in GCS, not Firestore (one sentence, link to `architecture.md`'s transport section, do not re-derive PRD 09's argument).
     4. **The pipeline: four LLM calls plus their deterministic checks** — this replaces the current "## 4. The five pipeline stages" section (current lines 79-142) entirely. One subsection per call, each per PRD §4.1.2 item 4:
        - **Term detection** (deterministic, unchanged) — carry over current §4 "Step 2" content verbatim.
        - **Grounding (`ground`)** — inputs (`units`, abbreviations), `_GroundedFactRaw` → verified `Fact`, the three deterministic post-checks inside `_verify_ledger` (unit-existence, verbatim-quote check tolerant of OCR noise, the informativeness floor `_QUOTE_MIN_LENGTH`/`_QUOTE_LONG_WORD_MIN_LENGTH`), fatal-on-failure, one sentence on why (no whole-document prose survives to fall back to).
        - **Assembly and render (`assemble_and_render`)** — fact-ledger-to-typed-`CarePlan` mapping, the citation-existence check inside `_verify_assembly`, the questions-cap-to-3 truncation, the content-richness logging pass, fatal-on-failure.
        - **Review (`review`)** — the fidelity-correction pass, `_sanitize_review_result`'s drop-and-log policy (unresolvable paths, `not_stated` outside the four `why` fields, contradiction guard where `remove` wins over `correct`/`not_stated` on the same item), non-fatal (ships assembly's output unmodified on failure).
        - **Correct (`correct`)** — named corrections plus a bounded PII sweep, the corrector-diff check (`_verify_correction_diff`), non-fatal (reverts to the pre-correction `care_plan` on failure).
        - **The glossary-curation background thread** — starts right after term detection, runs concurrently with all four LLM calls on its own `ThreadPoolExecutor(max_workers=1)`, the eager-`LLMClient()`-construction reasoning (avoids a `vertexai.init()` race with the main thread's client), the 20-second timeout backstop and its fallback to uncurated terms.
        - **The deterministic close** — glossary re-detection against the final `care_plan` (`build_glossary_from_care_plan`).
        - A six-row table: step number → label → LLM call? → fatal/non-fatal → fallback, sourced from `Constants.Pipeline.PIPELINE_STEPS` (`backend/utils/constants.py:71-76`: `READ_NOTE`, `DETECT_TERMS`, `GROUND`, `ASSEMBLE_AND_RENDER`, `REVIEW`, `CORRECT`) and PRD 06 §4.9's composite policy table — replaces the current five-row table.
     5. **Term detection and the jargon dictionaries** — current §5, unchanged (untouched by 01–15).
     6. **Readability scoring** — current §6, corrected: the "after" score is computed via `render_care_plan_text(care_plan)` (PRD 07), not "step 4's output" (current line 196). Everything else (`utils/scoring.py`'s composite + six named-method approximations) unchanged.
     7. **Output shape** — current §7, corrected: state explicitly that no `simplified`/`clarified` artifacts ever exist to drop (remove the "raw text artifacts (original / simplified / clarified)" sentence, current line 226); only `raw` (deleted per PRD 01) and the internal fact-ID provenance fields (`summary_fact_ids`/`source_fact_ids`, stripped by `routes/worker.py::_strip_internal_provenance`) are pipeline-internal fields that never reach the frontend.
     8. **Error taxonomy** — replace the current full "## 8. Error taxonomy" section with one link plus one sentence pointing to the new `docs/error-taxonomy.md` (created in Task 3).
     9. **Footer callout linking `docs/uncalibrated-constants.md`** wherever a described behavior is gated by a listed constant — at minimum: the glossary-curation timeout (`GLOSSARY_CURATION_TIMEOUT_S`), the grounding quote-informativeness floor (`_QUOTE_MIN_LENGTH`/`_QUOTE_LONG_WORD_MIN_LENGTH`), and the OCR downscale ceiling (`_MAX_LONG_EDGE_PX`).
     10. This item (creating `docs/uncalibrated-constants.md` itself) is Task 1, already done — do not duplicate it here; this task only adds the item-9 footer links pointing at it.
     - Update the doc's opening sentence (current line 4, "the three Gemini calls") to "the four LLM calls."
   - Acceptance criteria:
     - `grep -c "simplify_language\|clarify_and_action\|structure_note" docs/pipeline.md` returns 0.
     - `grep -c "five pipeline stages\|five stages\|three Gemini calls\|three sequential" docs/pipeline.md` returns 0.
     - `grep -c "2048" docs/pipeline.md` returns 0; `grep -c "4096" docs/pipeline.md` returns at least 1.
     - `grep -c "350,000" docs/pipeline.md` returns 0.
     - `grep -c "unitizer\|SourceSpan\|list\[Unit\]" docs/pipeline.md` returns at least 3 (proves §1's new content landed).
     - `grep -c "ground\b.*assemble_and_render\|four LLM calls" docs/pipeline.md` — at minimum, all four call names (`ground`, `assemble_and_render`, `review`, `correct`) each appear at least once: verify individually with `grep -c "assemble_and_render" docs/pipeline.md`, `grep -c "\bcorrect\b" docs/pipeline.md`, etc., each ≥ 1.
     - `grep -c "docs/uncalibrated-constants.md\|uncalibrated-constants.md" docs/pipeline.md` returns at least 3 (one per constant named in item 9).
     - `grep -c "docs/error-taxonomy.md\|error-taxonomy.md" docs/pipeline.md` returns at least 1, and the old §8 category list ("LLM generation failures... Vertex AI API-level errors...") no longer appears in full in this file.
     - `grep -c "clarified" docs/pipeline.md` returns 0.

### Task 3 — New `docs/error-taxonomy.md`

   - Files: `docs/error-taxonomy.md` (new file)
   - Dependency: after Task 2 (pipeline.md's §8 link must point at an existing file; this task supplies the moved content, quoted below from the pre-rewrite doc so no re-reading of a since-changed file is needed).
   - Changes (PRD §4.1.4): Split out of `pipeline.md`'s old §8, carried over verbatim, then expanded:
     - The `codes.py`/`exceptions.py` split, unchanged prose: *"All backend errors funnel through `backend/errors/`: `codes.py` is pure data — every error code plus its metadata (an HTTP status, a developer-facing message, a plain-English user hint, and whether retrying is likely to help); `exceptions.py` holds the logic that raises, classifies, and formats them into responses."*
     - The category list, unchanged: LLM generation failures (Vertex AI finish reasons — output token limit, safety block, blocked recitation, prohibited content, no candidates, invalid JSON), Vertex AI API-level errors (quota exceeded, deadline exceeded, permission denied, service unavailable), pipeline/processing errors (unparseable file, empty document, schema validation failure, job timeout), auth errors, resource errors, input-validation errors, rate limiting.
     - The `message`/`user_hint` split paragraph, unchanged.
     - **New**: a table — step (`READ_NOTE`/`DETECT_TERMS`/`GROUND`/`ASSEMBLE_AND_RENDER`/`REVIEW`/`CORRECT`) → possible `ErrorCode`s → fatal to the job? — sourced from PRD 06 §4.8's verified conclusion that grounding/assembly/review/correct reuse `LLM_INVALID_JSON`/`PIPELINE_VALIDATION_FAILED` rather than adding per-step codes.
     - **New**: one explicit sentence stating the frontend's error rendering is already fully generic over `code`/`message`/`user_hint`, so **no frontend change is ever required** when a new failure mode is added to an existing step, as long as it reuses an existing `ErrorCode`.
   - Acceptance criteria:
     - The file exists, is non-empty, and contains the literal phrase `"codes.py"` and `"exceptions.py"`.
     - `grep -c "READ_NOTE\|DETECT_TERMS\|GROUND\|ASSEMBLE_AND_RENDER\|REVIEW\|CORRECT" docs/error-taxonomy.md` returns at least 6 (one per step, in the new table).
     - `grep -c "no frontend change is ever required\|never requires a frontend" docs/error-taxonomy.md` returns at least 1.
     - `docs/pipeline.md` no longer contains the full category list (spot check: `grep -c "blocked recitation" docs/pipeline.md` returns 0, `grep -c "blocked recitation" docs/error-taxonomy.md` returns 1).

### Task 4 — Rewrite `docs/architecture.md`

   - Files: `docs/architecture.md`
   - Dependency: after Task 2 (cross-references `pipeline.md`'s new section numbers) and Task 3 (cross-references `error-taxonomy.md` for the error-envelope shape).
   - Changes (PRD §4.1.3, six items):
     1. **Topology.** Correct the diagram (current line 36, "run the 5-step pipeline") to say "runs the four-call pipeline" or similar brief, correct wording — topology diagram stays brief, full depth belongs in `pipeline.md`/`flow.md`.
     2. **Request and job lifecycle**, rewritten against the real sequence:
        1. Submit (anonymous auth, `POST /jobs`) — unchanged.
        2. **Resolve input and write the GCS input payload** — rewritten: the API extracts text (unitizing spans, not concatenating with a separator marker), computes `SourceSpan` provenance, writes one JSON object (`JobInputPayload{text, provenance}`) via `upload_job_input`, returning `input_payload_gcs_uri`. The merged-PDF audit copy (`upload_combined_pdf` → `input_pdf_gcs_uri`) is a separate, optional GCS write for uploads only — distinguish the two objects clearly.
        3. Create the job — `JobDoc` carries `input_payload_gcs_uri` and `input_pdf_gcs_uri` (both optional-shaped, `input_payload_gcs_uri` always populated in practice), never raw text or provenance inline.
        4. Enqueue — unchanged.
        5. Execute — the worker calls `load_job_input(job)` (one GCS read), then `unitize(text, provenance)` to materialize `list[Unit]`, then runs the four-call pipeline, writing `stage` **1–6** (correct current line 71's "1–5").
        6. Complete — the worker's `finally` block deletes **both** GCS objects (`input_pdf_gcs_uri` if present, `input_payload_gcs_uri` unconditionally) — correct current line 75's "clear the job's raw `input_text` field" (that field does not exist on `JobDoc`; there is nothing to clear).
        7. Display and delete — unchanged, cross-reference `data-and-privacy.md`.
        - **Job document as a state machine** — correct the field list (current line 95) to exactly match `backend/models/job.py`: `uid`, `status`, `stage` (1–6), `output_data`, `error_data`, `input_source_kind`, `input_source_filename`, `input_pdf_gcs_uri`, `input_payload_gcs_uri`, `input_version`, `grading_enabled`, `expires_at`, `skipped_files` — explicitly state `input_text`/`input_provenance` **do not exist** on this model.
        - **Idempotency and the processing lease** — unchanged mechanism; update any "three sequential Vertex AI calls" wording in this section's double-billing comment context to "four sequential LLM calls" (PRD 06 §4.6).
     3. **API surface** — correct `POST /jobs`'s validation description (current lines 122-123) to drop the byte-cap half of the dual-cap description, leaving only the 500,000-character cap; note `DELETE /jobs/<job_id>` also deletes the payload GCS object (§1.3 finding).
     4. **Abuse protection** — unchanged, current §4 is accurate.
     5. **Firestore, Cloud Tasks, and GCS** — split the current GCS bullet into two: the merged-PDF audit copy (unchanged) and the new input-payload object bullet (what it contains, its lifecycle — written once by the API, read once by the worker, deleted at job termination or explicit user delete, small-integers-plus-filename size profile per PRD 02 §4.1's Option 2 accounting, cross-referenced not restated).
     6. **Frontend structure** — carry over current §6 **except** one fix required by this task's audit-discrepancy note above: correct `"renders the five pipeline steps live"` (current line 242) to **six**, matching the live `ProcessingScreen.tsx`'s `PIPELINE_STEPS` array (`frontend/src/components/ProcessingScreen.tsx:25-36`). Nothing else in §6 changes.
   - Acceptance criteria:
     - `grep -c "5-step\|five pipeline steps\|five-step" docs/architecture.md` returns 0.
     - `grep -c "\b1–5\b\|(1-5)" docs/architecture.md` returns 0; `grep -c "1–6\|(1-6)" docs/architecture.md` returns at least 1.
     - `grep -c "input_text" docs/architecture.md` returns 0.
     - `grep -c "input_payload_gcs_uri" docs/architecture.md` returns at least 3 (state-machine field list, GCS section, lifecycle step 2).
     - `grep -c "350,000" docs/architecture.md` returns 0.
     - `grep -c "JobInputPayload" docs/architecture.md` returns at least 2.
     - Every field in `backend/models/job.py`'s field list that this doc's "Job document as a state machine" section names must be a real field: cross-check by running, from `backend/`, `python -c "from models.job import JobDoc; print(sorted(JobDoc.model_fields.keys()))"` and confirming every name this doc's field list cites (except any deliberately internal ones) appears in that output.

### Task 5 — Rewrite `docs/data-and-privacy.md` (data table + deletion-path table only)

   - Files: `docs/data-and-privacy.md`
   - Dependency: after Task 4 (cross-references `architecture.md`'s corrected GCS-object names) and Task 2 (cross-references `pipeline.md` §7 for the dropped-fields sentence).
   - Changes (PRD §1.3's finding, folded into PRD §4.1's `data-and-privacy.md` "Rewritten (data table and deletion-path table only)" row): Safety/identity/rate-limiting/third-parties sections carry over near-verbatim (unchanged — PRD confirms these are still correct). Rewrite only:
     - The data-holdings description (current line 30, "Holds job status, stage, the resolved input text (until the job finishes)...") — the resolved input text never touches Firestore post-PRD-09; it lives only in the transient GCS payload object.
     - **Path 4** in the deletion-path table (current lines 41, 63-67, `input_text` field clearing) — replace with the real mechanism: the GCS input-payload object is deleted unconditionally in the worker's `finally` block (`routes/worker.py:264-269`, alongside `input_pdf_gcs_uri`) and on `DELETE /jobs/<job_id>` (`routes/jobs.py:174-179`, alongside the merged-PDF object) — rename this path something like "GCS input-payload cleanup," describing object deletion, not field deletion.
     - **Path 3** (current "Cloud Storage input cleanup") — expand to state explicitly that the worker's `finally` block deletes **two** GCS objects (`input_pdf_gcs_uri` and `input_payload_gcs_uri`), not one, and that `DELETE /jobs/<job_id>` deletes both as well — this was previously entirely undocumented (§1.3 finding).
   - Acceptance criteria:
     - `grep -c "input_text" docs/data-and-privacy.md` returns 0.
     - `grep -c "input_payload_gcs_uri" docs/data-and-privacy.md` returns at least 2 (Path 3 and Path 4 areas).
     - The deletion-path table still has 7 rows (row count unchanged — only Path 3's and Path 4's *description* changes, not the table's structure).
     - Safety/identity/rate-limiting sections are unchanged: `diff <(git show HEAD:docs/data-and-privacy.md | sed -n '1,25p') <(sed -n '1,25p' docs/data-and-privacy.md)` shows no differences (adjust line range if the data-table edit starts earlier than line 25 — the intent is "top safety/identity sections are untouched").

### Task 6 — New `docs/flow.md`

   - Files: `docs/flow.md` (new file)
   - Dependency: after Task 2, Task 4, Task 5 (links into all three for depth).
   - Changes (PRD §4.2 — the owner's stated priority document): One continuous narrative tracing one concrete note from upload to rendered care plan, addressed to a reader who has never seen the codebase. Every function/file/Firestore/GCS-write name mentioned must be a real, grep-able symbol. Exactly the thirteen beats, each one paragraph (per-call depth is `pipeline.md`'s job, not this doc's):
     1. Anonymous sign-in (`useAnonAuth.ts`).
     2. Upload/paste (`UploadScreen.tsx`, `validateFiles.ts`'s client-side mirror of server caps).
     3. `POST /jobs` reaches `simplify-api` — `_resolve_job_input` extracts text, builds `SourceSpan` provenance, writes the GCS `JobInputPayload` — link to `architecture.md` §2 for the object shape.
     4. `JobDoc` created in Firestore, `status="not_started"` — link to `architecture.md`'s job-doc field table.
     5. Cloud Task enqueued, OIDC-signed, targeting `simplify-worker`.
     6. `202 {"job_id": ...}` returns; frontend attaches the Firestore listener (`useJobSnapshot.ts`), shows `ProcessingScreen.tsx`.
     7. Worker picks up the task, verifies OIDC, checks the processing lease — link to `architecture.md`'s idempotency section.
     8. `load_job_input` downloads/parses the GCS payload; `unitize()` materializes `list[Unit]` — link to `pipeline.md` §1.
     9. Term detection runs; the glossary-curation thread starts in the background.
     10. The four LLM calls run in sequence, each writing a `stage` update the frontend's listener picks up live — one paragraph for all four (not one per call — "too deep for this document"), with the mermaid diagram carrying the sequencing, link to `pipeline.md` §4 for depth.
     11. The deterministic close (glossary re-detection); `output_data` assembled, internal fields stripped (`_strip_internal_provenance`).
     12. `complete_job` writes the terminal Firestore update; both GCS objects deleted in the worker's `finally` block.
     13. The frontend's listener sees the terminal state, renders `ResultScreen.tsx`/`CarePlanView.tsx`, fires `DELETE /jobs/<job_id>` on mount — link to `data-and-privacy.md`'s deletion-path table.

     **The diagram** — one mermaid ` ```mermaid ` fenced `sequenceDiagram` block, four participants exactly: `Browser`, `simplify-api`, `Firestore`, `simplify-worker` (GCS and Cloud Tasks folded in as notes/implicit actions on arrows, not separate participants — keeps it to four swimlanes). It must show, precisely, per PRD §4.2:
     - The `POST /jobs` call and its two possible GCS writes (payload always, merged PDF only for uploads) as a note on the `simplify-api` lifeline.
     - The Firestore job-doc creation and the Cloud Task enqueue as two distinct arrows from `simplify-api`, both **before** the `202` response returns to `Browser` (make this ordering visually obvious).
     - A loop-like block on the `simplify-worker` lifeline representing the four-call pipeline as one labeled block ("ground → assemble_and_render → review → correct, writing stage 3-6"), not four separate arrows.
     - A note/parallel annotation for the glossary-curation background thread, visually distinct from the sequential four-call chain (e.g. a note spanning the loop block).
     - The live Firestore listener as a dashed/async arrow from `Firestore` back to `Browser`, distinct from the synchronous `202` response.
     - The two terminal GCS deletes and the `DELETE /jobs/<job_id>` call as the diagram's final beats.
   - Acceptance criteria:
     - The file exists, contains a ` ```mermaid ` fenced code block, and the block contains `sequenceDiagram`.
     - `grep -c "participant Browser\|Browser ->" docs/flow.md`, similarly for `simplify-api`, `Firestore`, `simplify-worker` — all four participants appear in the diagram block; `grep -c "participant" docs/flow.md` shows exactly 4 (no GCS/Cloud Tasks as separate participants).
     - `grep -c "useAnonAuth\|UploadScreen\|_resolve_job_input\|JobInputPayload\|useJobSnapshot\|ProcessingScreen\|load_job_input\|unitize\|_strip_internal_provenance\|ResultScreen\|CarePlanView" docs/flow.md` returns at least 10 (one hit per distinct named symbol across the 13 beats).
     - The doc contains exactly 13 numbered/paragraph beats matching the sequence above (spot-check: `grep -c "^#\{2,3\} " docs/flow.md` or paragraph markers, whichever heading style is used, matches 13 sections or the doc reads as one continuous narrative with 13 identifiable beats — reviewer judgment, since PRD doesn't mandate a heading-per-beat format).
     - `grep -c "202" docs/flow.md` returns at least 1, and the surrounding text/diagram places the Firestore-doc-creation and Cloud-Task-enqueue arrows before it.

### Task 7 — New `docs/testing.md`

   - Files: `docs/testing.md` (new file)
   - Dependency: after Task 3 (`error-taxonomy.md` must exist to link to).
   - Changes (PRD §4.4): Explains what each test layer is *for* — genuinely new content, not a correction (commands stay in `local-development.md`/`CONTRIBUTING.md`, unchanged). Contents:
     - The directory layout: `backend/tests/{care_plan,models,routes,services,utils,integration,scripts}/`, `frontend/src/tests/`.
     - What `test_pipeline_prompts.py`-style prompt-content regression tests check: that a named rule's literal text is present in a prompt file (PRD 04 §7.2's pattern, reused by PRD 10's planned `NUMERACY` block tests).
     - What `test_dead_code_removed.py` checks: module-non-existence guards — the direct precedent this PRD's own accuracy mechanism (Task 12) extends.
     - A pointer to `docs/error-taxonomy.md`'s step→error-code table for anyone adding a new failure mode.
     - Depth: backend-focused (unit / integration / prompt-content-regression / dead-code-guard, each explained in a short paragraph), with a **short** frontend pointer only (a few sentences plus a link to `frontend/src/tests/` — PRD §9 `[RESOLVED]` explicitly rejects padding this doc to match the backend's depth).
   - Acceptance criteria:
     - The file exists, is non-empty, and names all seven backend test subdirectories (`care_plan`, `models`, `routes`, `services`, `utils`, `integration`, `scripts`) plus `frontend/src/tests/`.
     - `grep -c "test_dead_code_removed" docs/testing.md` returns at least 1.
     - `grep -c "docs/error-taxonomy.md\|error-taxonomy.md" docs/testing.md` returns at least 1.
     - The frontend section is visibly shorter than the backend section (reviewer judgment: fewer lines/paragraphs, no per-layer breakdown for frontend).

### Task 8 — Amend `docs/README.md` (index + new data-model cross-cutting table)

   - Files: `docs/README.md`
   - Dependency: after Tasks 1–7 (indexes and links to every file they create/rewrite).
   - Changes (PRD §4.1's "Amended" row; PRD §4.3's cross-cutting table):
     - Fix the `pipeline.md` one-line description (current lines 7-8, "the five simplification stages... the three sequential Gemini calls") to match the real content: input extraction/unitization, the four LLM calls and their deterministic checks, the glossary thread, readability scoring — cross-reference `error-taxonomy.md` rather than re-listing it inline.
     - Fix the `architecture.md` description if it understates the GCS input-payload transport or the unitizer (check current wording; add these as topics if missing).
     - Add index entries for `docs/flow.md` (as the recommended entry point for a first-time reader — PRD §4.1's stated purpose), `docs/error-taxonomy.md`, `docs/testing.md`, `docs/uncalibrated-constants.md`.
     - Add **one new table** (PRD §4.3, the one piece of genuinely new cross-cutting content this PRD's structure adds): a flat table of every named type — `Unit`, `Fact`, `SourceSpan`, `JobInputPayload`, `CarePlan`, `JobDoc`, `ReviewResult`/`Correction` — with columns "what it is," "where it's defined," "where it lives and dies" (e.g. never persisted / GCS, transient / GCS, one-per-file / Firestore, one-per-file / Firestore-and-frontend), and a link to the doc section covering it in depth.
   - Acceptance criteria:
     - `grep -c "five simplification stages\|three sequential Gemini calls" docs/README.md` returns 0.
     - `grep -c "flow.md\|error-taxonomy.md\|testing.md\|uncalibrated-constants.md" docs/README.md` returns at least 4 (one link per new file).
     - `grep -c "Unit\b" docs/README.md` and similarly for `Fact`, `SourceSpan`, `JobInputPayload`, `CarePlan`, `JobDoc` — each returns at least 1 (in the new table).
     - `docs/flow.md` is presented as (or clearly marked as) the recommended starting point for a first-time reader.

### Task 9 — Amend root `README.md`

   - Files: `README.md` (repo root)
   - Dependency: after Task 8 (mirrors the doc-table fix there).
   - Changes (PRD §1.3, §4.1's "Amended" row):
     - Fix current line 43 ("runs the actual pipeline: deterministic term detection followed by three sequential calls to Gemini on Vertex AI") to say four sequential calls (or name all four: ground, assemble_and_render, review, correct).
     - Fix the documentation table row for `pipeline.md` (current line 101, "the five pipeline stages... the three Gemini calls") to match `docs/README.md`'s corrected description from Task 8.
     - Add table rows/mentions for `docs/flow.md`, `docs/error-taxonomy.md`, `docs/testing.md`, `docs/uncalibrated-constants.md` in the documentation table.
     - Do **not** touch the ASCII architecture diagram (PRD §9 `[RESOLVED: root README.md's diagram stays terse ASCII, topology-only — not replaced or supplemented by a reduced mermaid diagram]`) beyond the one-word/phrase fix above if the diagram itself names "5-step" anywhere (check; the diagram in this file is topology-only per the PRD and was not found to name a step count in the audit — confirm during this task and only edit if found).
   - Acceptance criteria:
     - `grep -c "three sequential calls to Gemini\|three Gemini calls" README.md` returns 0.
     - `grep -c "flow.md\|error-taxonomy.md\|testing.md\|uncalibrated-constants.md" README.md` returns at least 4.
     - The ASCII diagram block (fenced with triple backticks, topology sketch) is otherwise byte-identical to before this task, confirmed via `git diff README.md` showing no changes inside the fenced diagram block.

### Task 10 — Amend `CONTRIBUTING.md` (doc-currency checklist line)

   - Files: `CONTRIBUTING.md`
   - Dependency: none (independent of all doc-content tasks).
   - Changes (PRD §4.6): Under the existing "Branch and PR conventions" section (current bullets: branch off main, keep PRs focused, CI must pass, prefer small commits), add one new bullet, verbatim:
     > If your PR changes the pipeline's step sequence, call signature, prompt files, job-document schema, or GCS transport shape, update the corresponding section of `docs/` in the same PR.
   - Acceptance criteria:
     - `grep -c "update the corresponding section of \`docs/\` in the same PR" CONTRIBUTING.md` returns 1.
     - The new bullet is under "## Branch and PR conventions" (or the file's equivalent existing heading), not a new section.
     - No other line in `CONTRIBUTING.md` changes (`git diff CONTRIBUTING.md` shows a single added line).

### Task 11 — Amend `CHANGELOG.md` (new entry for the 01–09 pipeline inversion)

   - Files: `CHANGELOG.md`
   - Dependency: none (independent — describes already-landed 01-09 behavior, verified throughout Tasks 2/4).
   - Changes (PRD §4.1's "Amended" row; PRD §1.3's finding that no entry exists for 01–09's changes): Add one new dated entry **above** the existing `## [0.1.0] - 2026-09-07` entry, dated the day this PR actually merges (do not backdate; do not reuse 2026-09-07). Describe, at minimum: the pipeline inversion from five stages/three Gemini calls to four LLM calls (`ground`/`assemble_and_render`/`review`/`correct`) plus a deterministic unitizer and glossary-curation thread; the move of job input text from Firestore to a GCS `JobInputPayload` object; the OCR downscale ceiling raised from 2048px to 4096px; the removal of the dual length-cap (350,000 UTF-8 bytes) in favor of the single 500,000-character cap. Use a `### Changed` (and/or `### Removed`) subsection, matching Keep a Changelog conventions already used by the existing `[0.1.0]` entry's `### Added` heading.
   - Acceptance criteria:
     - `CHANGELOG.md` has a new `## [` heading above `## [0.1.0]`.
     - The new entry's date is not `2026-09-07`.
     - `grep -c "ground\|assemble_and_render\|four LLM calls\|four sequential" CHANGELOG.md` returns at least 1 in the new entry.
     - `grep -c "JobInputPayload\|GCS" CHANGELOG.md` returns at least 1 in the new entry.
     - The existing `[0.1.0]` entry is byte-for-byte unchanged (it is a correct historical record per PRD §1.3 — do not edit it).

### Task 12 — New `backend/tests/integration/test_docs_reference_real_symbols.py`

   - Files: `backend/tests/integration/test_docs_reference_real_symbols.py` (new file)
   - Dependency: after Task 2 (pipeline.md's final prompt-filename and step-table content) and Task 4 (architecture.md's final job-doc field table) — this test parses the *shipped* doc content.
   - Changes (PRD §4.6 — the sole code/test task this documentation PRD authorizes, matching the `test_dead_code_removed.py` precedent): three narrowly-scoped, symbol-existence checks, no prose/semantic assertions:
     1. **Prompt filenames.** Parse `docs/pipeline.md` for the regex `` `care_plan/prompts/([a-z_]+\.txt)` `` and assert every matched filename is a real file under `backend/care_plan/prompts/`.
     2. **Pipeline step labels.** Import `Constants.Pipeline.PIPELINE_STEPS`; assert its member count (6) and each member's `.label` string (e.g. `"Reading your note"`, `"Finding difficult and medical terms"`, `"Finding the facts in your note"`, `"Putting your care plan together"`, `"Double-checking your care plan"`, `"Finishing touches"`) appear verbatim somewhere in `docs/pipeline.md`.
     3. **Job-doc fields.** Import `JobDoc`; assert every field name this doc's "Job document as a state machine" table in `docs/architecture.md` names (parse the bullet/table listing those field names, e.g. via a regex over the known field-list sentence) is a real key in `JobDoc.model_fields.keys()`.
   - Acceptance criteria:
     - `python -m pytest tests/integration/test_docs_reference_real_symbols.py -q` (from `backend/`) passes.
     - Each of the three checks is its own test function (not one monolithic test), matching `test_dead_code_removed.py`'s style.
     - Deliberately breaking one check locally (e.g. renaming a prompt-file reference in a scratch copy) makes that one test fail with a message naming the missing symbol — spot-check this once during development, then revert; not part of the committed diff.
     - `ruff check backend/tests/integration/test_docs_reference_real_symbols.py` is clean.

### Task 13 — Full verification

   - Files: none (verification only)
   - Changes: none.
   - Dependency: after Tasks 1–12.
   - Acceptance criteria:
     - From `backend/`: `python -m pytest tests/ -q` passes with zero failures/errors, including Task 12's new test file.
     - From `backend/`: `ruff check .` is clean.
     - Every "Stale" cell in PRD §1.3's audit table has a corresponding corrected sentence in the rewritten docs, and every "Missing" cell has corresponding new content (PRD §7 item 3's stated acceptance bar) — walk the table row by row: `docs/README.md`, `docs/pipeline.md`, `docs/architecture.md`, `docs/data-and-privacy.md`, root `README.md` all confirmed changed; `docs/deployment.md`, `docs/local-development.md` confirmed **unchanged** (`git diff --stat` shows no changes to either).
     - `grep -rln "simplify_language\|clarify_and_action\|structure_note\|five.stage\|five pipeline\|5-step\|three sequential.*Gemini\|three Gemini calls\|350,000\|2048 px\b" docs/*.md README.md` (repo root) returns **no files** — the core factual error and every stale companion claim found during authoring (including the `docs/architecture.md:242` discrepancy this task list flagged, not originally in PRD §1.3's table) is gone repo-wide.

---

## Notes — PRD §4 decisions that require no task

- **§4.1 table / §4.4**: `docs/deployment.md` and `docs/local-development.md` need **no rewrite** — PRD §1.3 verified both fully accurate against the live deploy workflow and env-var/test-command setup; no PRD in 01–15 touches infra. No task in this file touches either file.
- **§4.3**: no separate "data model" document is created — `Unit`/`Fact`/`SourceSpan` content stays in `pipeline.md` (Task 2), `JobInputPayload`/`CarePlan`/`JobDoc` stays in `architecture.md` (Task 4); the only new cross-cutting artifact is the one index table added to `docs/README.md` in Task 8.
- **§4.5 / §5 / §6**: API and frontend change summaries are both N/A — this PRD changes no route, response shape, `ErrorCode`, or frontend file; every frontend fact the rewritten docs state was independently verified against the live files during PRD authoring (§1.3) and found already correct, except the one `docs/architecture.md:242` discrepancy this task list's Task 4 fixes.
- **§9 `[DEFERRED]`**: retrofitting `docs/deployment.md`/`docs/local-development.md` with Task 12's symbol-existence-test treatment is explicitly deferred, not owed by this task list — noted only so a future maintainer doesn't wonder why no test guards those two files.

## Summary of what requires you (not a dev agent)

Per PRD §7/§8, these cannot be executed by a dev agent:

1. **One-time manual check: confirm `docs/flow.md`'s mermaid `sequenceDiagram` (Task 6) actually renders correctly on GitHub** once this branch's PR is open — mermaid rendering is a GitHub platform feature the PRD explicitly declines to test automatically (PRD §7: "not tested, and is not claimed to be").
2. **Final cell-by-cell review against PRD §1.3's audit table** (PRD §7 item 3) — a human or `dev-review` pass confirming every "Stale" cell got a corrected sentence and every "Missing" cell got new content, as the acceptance bar for the rewrite itself. Task 13 above gives the mechanical half of this (greps); the qualitative "does the new prose actually read well and say the right thing" half is reviewer judgment, not a dev-agent task.
3. **PRD §8's three confirmation items** (sequencing choice, the three-new-files file-split choice, and asking whoever designs PRD 17 to sanity-check the §3 cross-reference convention from its side) are already recorded `[RESOLVED]` in PRD §9 — the gate check for this task-generation pass confirmed §9 has no live `[OPEN]` items, so no outstanding owner action blocks these tasks. Flagged here only for completeness, matching PRD §8's own framing.

No new environment variables, credentials, or console configuration are needed for this PRD — every task is a markdown edit/creation or one pure-Python test file (no `SimplifyError`, `vertexai`, or network access involved).
