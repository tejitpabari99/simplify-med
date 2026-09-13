# PRD index — fidelity and concision, plus input-transport follow-on

PRDs 01-08 decompose [`../brainstorm.v1.md`](../brainstorm.v1.md) into implementable sub-projects — the fidelity-and-concision brief itself. PRD 09 is a separate, independent follow-on the owner raised after 01-08 were settled (see "Deferred follow-on" history below): it moves `JobDoc.input_text`/`input_provenance` off Firestore and onto GCS. All nine are design only — no tasks have been generated yet. `dev-tasks` is the next step for each.

**Status: all nine PRDs are settled.** 01-08 went through a prior revision pass that resolved every `[OPEN]` item blocking `dev-tasks` and reconciled cross-references after concurrent edits. 09 was written afterward, against the post-01-08 codebase, as a self-contained follow-on. `grep -rn "\[OPEN" prds/` surfaces nothing but prose that references past open items as history, across all nine files.

**A third wave — PRDs 10-18 — was added after 01-09 landed.** It decomposes `../comparison-drive-research-bundle.v1.md` (an external, evidence-backed research bundle independently compared against this branch's own design) into nine further sub-projects, and is covered in full in its own section, ["Wave 3 — PRDs 10-18"](#wave-3--prds-10-18-fidelity-hardening-and-documentation), near the end of this document. Everything above this point (01-09) is the original, unmodified index; nothing in this revision rewrites or degrades it.

## Sub-projects

| # | Sub-project | Scope | Depends on | Lines |
|---|---|---|---|---|
| 01 | schema-and-config | Pydantic model changes, new ledger models (`Unit`/`Fact` as an offset-pair contract), firestore.rules dead clause, CORS env var | — | 542 |
| 02 | unitization-and-provenance | Deterministic `{id,file,page,line,text}` unitizer, source-marker removal, OCR ceiling 2048→4096px | 01 | 833 |
| 03 | grounding | Grounding LLM call, category criteria prompt, deterministic quote/unit/informativeness checks, offset recovery | 01, 02 | 545 |
| 04 | assemble-and-render | The LLM call replacing simplify/clarify/structure; field-level rendering; the citation-existence (soundness) check | 01, 03 | 476 |
| 05 | review-and-correct | Fidelity review, correction ops, corrector, corrector diff check | 01, 03, 04 | 470 |
| 06 | pipeline-orchestration | Step enum, wiring, threading, error taxonomy, ProcessingScreen, provenance stripping | 01, 02, 03, 04, 05, 07 | 588 |
| 07 | glossary | `matched_term` bug fix, stoplist prune, curation call, rendered-text projection | 01, 04 | 485 |
| 08 | frontend-and-pdf | 13→8 cards, Next Steps, checkboxes, single score, TS types, PDF section activation, result-screen/PDF parity | 01, 04, 07 | 604 |
| 09 | input-transport | Move `input_text`/`input_provenance` off `JobDoc` (Firestore) into one GCS object per job (`JobInputPayload`); delete `MAX_TEXT_BYTES`; delete `resolve_input_from_job_doc`/`resolve_units_from_job_doc` | 01, 02, 06 | 682 |

Total across 01-08 (the fidelity-and-concision set): **4,543 lines**. Adding 09 (the independent input-transport follow-on): **5,225 lines** across all nine.

## Dependency graph

```
01 schema-and-config
   │
   ├────────────────────────────────────────────────────────┐
   ▼                                                          │
02 unitization-and-provenance ───────────────────┐            │
   │                                              │            │
   ▼                                              │            │
03 grounding                                      │            │
   │                                              │            │
   ▼                                              │            │
04 assemble-and-render ──────────────┐            │            │
   │                                 ▼            │            │
   │                             07 glossary       │            │
   ▼                                 │            │            │
05 review-and-correct                │            │            ▼
   │                                 │            │    08 frontend-and-pdf
   └───────────────┬─────────────────┘            │    (also reads 01, 04, 07
                    ▼                              │     directly; leaf, nothing
          06 pipeline-orchestration                │     depends on it)
          (integration point; depends              │
           on every backend PRD above) ────────────┤
                    │                               │
                    │ (01-08 land first, exactly     │
                    │  as written, in full)          │
                    ▼                                │
          09 input-transport  ◄───────────────────────┘
          (independent follow-on; reads 01's JobDoc shape,
           02's SourceSpan/unitize/provenance design, and
           06's routes/worker.py call site — but is not a
           prerequisite for any of 01-08 and does not block
           them; leaf, nothing depends on it)
```

01 is the root every other backend PRD depends on directly or transitively. 07 depends on both 01 (schema) and 04 (its §4.4 closes the re-detection interface gap 04 §9 flags once assembly stops producing whole-document prose). 06 is the sink among 01-08: nothing in that set depends on it. 08 is the other leaf in that set, reading 01/04/07's settled contracts without needing their code to exist first. **09 sits entirely outside the 01-08 dependency graph as a follow-on stage**: it depends on 01, 02, and 06 having already landed exactly as written (it edits the transport those three establish), but nothing in 01-08 depends on 09, and 09 is not implementable alongside or before them — see its own §3 ordering note.

## Recommended implementation order

1. **01 — schema-and-config.** Foundation; every other PRD depends on it directly or transitively.
2. **02 — unitization-and-provenance.** Needed before grounding can cite units.
3. **03 — grounding.** Needed before assembly can consume a fact ledger.
4. **04 — assemble-and-render.** Needed before review/correct have a `CarePlan` to check, and before 07 can close its interface gap. **04 and 06 must land together** in the sense that nothing may run between them: 04 deletes `simplify_language_with_term_plan`, `clarify_and_action` and `structure_appointment_note` while `iter_steps` still calls them by name, so `CarePlanPipeline.run()` throws `AttributeError` between the two landing. Nothing is deployed in the interim (global no-deploy constraint), so this is a confined, disclosed sequencing gap, not a production risk.
5. **07 — glossary.** Depends on 01 (schema) and 04 (07 §4.4's `render_care_plan_text`/`build_glossary_from_care_plan` operate on 04's `CarePlan` output and close the re-detection gap 04 §9 flags) — can land in parallel with 05 once 04 is in. Must land before 06, since 06 depends on 07's `render_care_plan_text()` for both glossary re-detection and the "after" readability score.
6. **05 — review-and-correct.** Retrofits `_style_rules.txt`, a file 04 creates, so 05 lands after or with 04. Also depends on 04's citation-existence check having already run (05 does not re-implement it — 05 §4.7) so review/correct never have to reason about unsound items.
7. **06 — pipeline-orchestration.** Lands last among the backend PRDs, once 02, 03, 04, 05, and 07 are all in — it is the integration point that wires the four LLM calls together, threads `units`/`facts` through, and depends on 07's readability projection. No standalone citation-existence check needs wiring here (§4.10) — 04 already enforces it inline.
8. **08 — frontend-and-pdf.** Depends on 01, 04, and 07's *settled contracts* (schema shape, the "not stated" sentinel and nullable `urgency`, and confirmation that glossary highlighting needs no frontend code change) — not on their code landing first, so it can be built in parallel with the pipeline PRDs. Real end-to-end validation of its content (a genuine mixed-urgency fixture, narrative coherence) waits on 06's live output.
9. **09 — input-transport.** Lands only after 01-08 are all in, exactly as written — it is not part of the fidelity-and-concision work and does not block it. Independent of the other eight in every respect except that it edits code they introduce (`JobDoc.input_text`/`input_provenance`, `resolve_input_from_job_doc`/`resolve_units_from_job_doc`); nothing about `care_plan/pipeline.py`, any prompt, or `CarePlan`/`Fact`/`Unit`'s shape is touched.

## Cross-PRD couplings

Decisions made in one PRD that reach into another's territory:

| Coupling | Where decided | Reaches into |
|---|---|---|
| `JobDoc.input_provenance` field added | 02 | 01 (schema) |
| `Fact` becomes an offset pair (`char_start`/`char_end`) instead of a stored `quote`; `quote_for(fact, units_by_id)` rehydrates on demand | 01 (schema), 03 (offset recovery) | 04, 05 (both must call `quote_for()`, never read `Fact.quote` — though as of the currently-landed PRDs, neither actually needs to; see 06 §4.2a) |
| The citation-existence (soundness) check that replaces the deleted `close_coverage()` is enforced entirely inline inside `assemble_and_render` | 04 | 05 (relies on the invariant without re-checking it, 05 §4.7), 06 (wires no separate call for it, 06 §4.10) |
| `_style_rules.txt` shared prompt fragment, extracted from 04's `assemble_and_render.txt` | 05 | 04 (owns the file's content; 05 only relocates it) |
| `render_care_plan_text()` projection | 07 | 04 (closes 04 §9's flagged gap), 06 (consumes it for glossary re-detection and the "after" readability score) |
| `_strip_internal_provenance()` helper for `summary_fact_ids`/`source_fact_ids` | 06 | 01 (01 specified the fix and flagged the field-shape gap; 06 lands it in `routes/worker.py`, 06's file) |
| `ProcessingScreen.tsx` / step labels (backend `Constants.Pipeline.PIPELINE_STEPS` renumbering) | 06 | 08 (owns the frontend directory `ProcessingScreen.tsx` lives in, but is not scoped to touch it — 06 does, explicitly) |
| `PipelineRunResult` carries no `list[Fact]`, departing from 01's suggested shape | 06 | 01 |
| Quote/field informativeness floor (`_QUOTE_MIN_LENGTH`=12, `_QUOTE_LONG_WORD_MIN_LENGTH`=7) | 03 | 04 (reuses the identical constants and function verbatim, same module — no import needed) |
| PDF's `includeGlossary`/`includeReadability`/`includeLowPriority` all flip to `true`, activating three previously-dead sections; result screen widened (`hideLowPriority` deleted from `CarePlanView`/`ResultScreen.tsx`) so the screen and the PDF show the identical eight sections | 08 | — (self-contained; a real behavior change to what patients see and download, not a cross-PRD reach) |
| `input_text`/`input_provenance` removed from `JobDoc` entirely, replaced by `input_payload_gcs_uri`; `resolve_input_from_job_doc`/`resolve_units_from_job_doc` (02 §4.7) deleted, worker calls `load_job_input(job)` then `services.unitizer.unitize(text, provenance)` directly; `MAX_TEXT_BYTES` deleted (backend constant, its check, and its frontend mirror in `validateFiles.ts`) | 09 | 01 (`JobDoc` shape), 02 (transport decision superseded — see 02 §9's forward-pointer — provenance design itself untouched), 06 (`routes/worker.py` call site it wired is replaced) |

## Consolidated open questions

**None remaining that block `dev-tasks`, across all nine PRDs.** Every PRD's own §9 ends with `[OPEN] — none remaining` (01, 02, 06, 09) or carries no undecided `[OPEN]` item at all (03, 04, 05, 07, 08) — verified directly, not just by absence of the literal string. The three project-wide owner decisions that closed out the largest remaining gaps in 01-08:

1. **Fact provenance is an offset pair, not a stored quote.** `Fact` is `{id, category, unit_id, char_start, char_end, text}`. The grounding LLM still emits a verbatim `quote` in its raw JSON response — that is what makes fabrication mechanically detectable — and the verbatim-substring check is unchanged; only after it passes does code deterministically derive `(char_start, char_end)` and discard the copy. `quote_for(fact, units_by_id)` (`backend/models/ledger.py`) rehydrates the text on demand; no consumer needs it today (04/05/06 all verified they read only `fact.text`).
2. **The ledger-closing check is inverted — soundness, not completeness.** Old contract: every fact must appear in the output (omission detection). New contract: every emitted care-plan item must cite at least one fact via `source_fact_ids`, and every cited id must exist in the ledger (nothing unbacked). A fact no item cites is legitimate, not an error — the assembly LLM selects what belongs in a patient-facing report under its AHRQ-guided prompt. Omission is no longer mechanically detectable; fabrication still is. 04 owns the check, enforced inline in `_verify_assembly` with an item-level drop-and-log policy. 05's token-overlap `close_coverage` heuristic and its `_COVERAGE_OVERLAP_THRESHOLD` were deleted outright, not reimplemented.
3. **Assorted items resolved:** a quote/field informativeness floor (a digit, OR a 7+ character word, OR 12+ characters total; `_QUOTE_MIN_LENGTH`/`_QUOTE_LONG_WORD_MIN_LENGTH`) applied identically in 03 (the grounding quote) and 04 (the content-richness floor on rendered `why`/`description` fields, reusing 03's constants verbatim); the PDF now carries all eight sections (`includeReadability`/`includeGlossary`/`includeLowPriority` all flipped `true`) and the result screen was widened to match (`hideLowPriority` deleted, per a later revision to 08 — commit `561609b`) rather than the PDF narrowed back down, so screen and PDF now agree on all eight sections; the report adopts strikethrough on done-state rows for print/accessibility; 07's readability projection keeps short label fields, pending a real-run skew check (§8); `_MAX_PII_TOKEN_DELTA` stays 4 as a documented, not-yet-calibrated tunable; 06 owns stripping `summary_fact_ids`/`source_fact_ids` from the completed job doc via a `_strip_internal_provenance` helper in `routes/worker.py` — an exposure gap 01 flagged and left for 06 to close, now closed.

09, written later as a self-contained follow-on, resolved its own open questions entirely within itself (§9): one GCS object per job, the exact prefix/naming/URI-field choice, non-optional write semantics, the `PIPELINE_ERROR` failure mapping, outright deletion (not signature changes) of `resolve_input_from_job_doc`/`resolve_units_from_job_doc`, `input_payload_gcs_uri` never `DELETE_FIELD`'d, and the outright deletion of `MAX_TEXT_BYTES`. None of it reopens any of 01-08's own decisions.

A small number of genuinely open items remain across the set, but none of them block task generation — each requires either a live pipeline run, a manual data-curation pass, or a one-time manual/infra check that has no bearing on whether the design itself is decided:

- **03, 05** — empirically measuring extraction recall (03) and reviewer catch-rate against injected errors (05) both require a real model call and a judgment call on an acceptable rate; protocols are specified (03 §8, 05 §7.5/§8), running them is manual.
- **07** — the exact final size of `common_word_stoplist.json` beyond its 14-word verified starter list is a data-curation task, not a design decision (07 §8/§9).
- **07/06** — whether `render_care_plan_text`'s inclusion of short label fields skews the readability score is only observable once 06 wires a real pipeline run (07 §8/§9, 06 §9); the escape hatch (narrow the field list for the readability consumer specifically) is already specified if the skew turns out to be real.
- **09** — whether the `juno-worker` runtime service account already has `storage.objects.get` on `GCP_BUCKET_NAME` (it has only ever needed delete) is an IAM fact this PRD cannot verify from inside the repo (09 §8).

## Consolidated manual steps

Every §8 item across all nine PRDs, deduplicated and attributed:

- **01** — Add each session's ngrok domain to Firebase Auth's authorized domains (console action, no automation possible). Set `CORS_ALLOWED_ORIGINS` locally before each ngrok session (the env var mechanism is built; setting it per session is manual).
- **02** — OCR ceiling smoke test: confirm the 4096px ceiling completes without a Vertex payload-size/timeout error and visibly improves small-print transcription versus the old 2048px ceiling. Optionally confirm Vertex AI's inline-request size limits against current docs/quotas.
- **03** — Prompt smoke test against real notes: contrast-dye lands in `tests`/`procedures` not `medications`; a dense abbreviation line expands in `text` while `quote` stays verbatim; a realistic multi-page note doesn't hit the 65,536-token output budget.
- **04** — Prompt smoke test against real notes: clinician/facility names render as "your doctor"/"the hospital" everywhere, not just `summary`; a medication with no stated reason renders the exact "Not stated in your note." sentinel; two findings at different sites merge into one item naming both; a fully-answered note produces zero `questions`; token budget holds on a realistic ledger; spot-check a sample of `source_fact_ids` for relevance (existence is mechanically checked, relevance is not).
- **05** — Prompt smoke test against real notes (dose correction, fabricated warning-sign removal, PII sweep, token budget). Run the injected-error catch-rate protocol (§7.5) and judge whether the rate is acceptable. Tune `_MAX_PII_TOKEN_DELTA` (4) against real notes once the corrector is exercised end-to-end.
- **06** — Full end-to-end smoke test once every sub-project has landed: one real note through all six processing steps, plus a deliberately-corrupted note producing a clean error screen. Watch whether the 20-second glossary-curation timeout fires under normal conditions. Confirm `stage_reached` values 3-6 appear correctly in any external analytics (outside this repo's visibility).
- **07** — Review the stoplist prune's diff by hand before treating it as final (particular attention to `foot, feet`, flagged as borderline); extend `common_word_stoplist.json` if the review surfaces more everyday words. Prompt smoke test: a common word gets dropped, a named gap-term (e.g. `calcified`, `contrast`, `angiogram`) gets proposed with a definition, and its `matched_term` appears verbatim in rendered text. Once 06 produces a real before/after readability score, check whether short label fields in `render_care_plan_text` visibly skew it.
- **08** — Visual QA of the `☑`/`☐` Next Steps glyphs across real browsers/OSes (fall back to inline SVG if they render as tofu boxes). Print-preview QA of the same glyphs, and black-and-white print QA of the done-state strikethrough specifically (the reason strikethrough was adopted over color alone). Confirm the `follow_up`-before-`other` type precedence reads sensibly against real care plans. Spot-check the regenerated `realCarePlanOutput.fixture.json` for narrative coherence. Once 06's pipeline produces a real note whose `warning_signs` mix a null urgency with non-null ones, capture that as a fixture and add coverage against it, supplementing (not replacing) the synthetic unit tests.
- **09** — Confirm the `juno-worker` Cloud Run service's runtime service account has `storage.objects.get` (read), not just delete, on `GCP_BUCKET_NAME` — the worker has never before needed to read GCS object *content*, only delete-by-URI, so this is a genuinely new IAM requirement, checkable via `gcloud storage buckets get-iam-policy gs://$GCP_BUCKET_NAME` against the worker's runtime SA. Smoke-test the new failure path once deployed: delete a `care_plan_inputs/.../inputs/*.json` object for a job stuck in `processing` (simulating the crash-before-terminal-write race, §4.10) and confirm a redelivered/retried execution produces a clean `error_data.code == "PIPELINE_ERROR"` doc rather than an uncaught 500. No new GCS lifecycle rule or `deploy.yml` change is needed — the new object reuses the already-covered `care_plan_inputs/` prefix.

## Locked decisions (apply across all nine)

- No versioning, no backward compatibility, no migration code — mutate schemas and code in place.
- Never push to `main`, never deploy.
- Local testing is via ngrok + pm2 with `SERVICE_MODE=combined`.
- Out of scope everywhere: a per-PR backend preview environment, and the clinical-fidelity evaluation suite.
- Fact provenance is an offset pair (`char_start`/`char_end`) into a `Unit`'s text, not a stored `quote` — see "Consolidated open questions" above. Unaffected by 09 (09 changes only where `(input_text, input_provenance)` lives in transit, not how facts cite units).
- The evidence/coverage contract is soundness (every item cites a real fact), not completeness (every fact appears somewhere) — see "Consolidated open questions" above.
- 01-08 are the fidelity-and-concision brief; 09 is an independent follow-on that lands only after all eight are in, exactly as written — never alongside or before them (09 §3).

## Deferred follow-on — now PRD 09

An earlier revision of this index recorded a separate architectural concern the owner raised, explicitly out of scope for PRDs 01-08 at the time: moving `JobDoc.input_text`/`input_provenance` off Firestore and onto GCS, since the Firestore job document exists only as the API→worker transport (the Cloud Tasks payload carries just the job id) and `MAX_TEXT_BYTES` existed solely to keep that document under Firestore's 1 MiB limit.

**That follow-on is no longer deferred or unwritten — it is [`09-input-transport/PRD.md`](09-input-transport/PRD.md).** It replaces both Firestore fields with a single GCS object per job (`JobInputPayload`, holding `text` and `provenance` together) under the existing `care_plan_inputs/{user_id}/inputs/` prefix, referenced from `JobDoc` by a new `input_payload_gcs_uri` field; deletes `MAX_TEXT_BYTES` outright (constant, backend check, and frontend mirror) now that its sole justification no longer applies; and deletes `resolve_input_from_job_doc`/`resolve_units_from_job_doc` in favor of the worker calling `load_job_input(job)` then `services.unitizer.unitize(text, provenance)` directly. PRDs 01-08 still land first, exactly as written, with `input_text`/`input_provenance` on `JobDoc` exactly as 02 originally specifies (02 §4.1/§4.10) — 09 is a follow-on stage applied after, not a revision bundled into any of the eight. See 02 §9 for the short forward-pointer recording this, and 09 §4.14 for the full accounting of what it supersedes versus what it leaves standing.

---

## Wave 3 — PRDs 10-18 (fidelity hardening and documentation)

PRDs 10-18 decompose [`../comparison-drive-research-bundle.v1.md`](../comparison-drive-research-bundle.v1.md) — an external, evidence-backed research bundle independently compared against this branch's own design — into nine further sub-projects. Seven come from the bundle's own recommendations R1-R7 (10↔R2+R3, 11↔R1, 12↔R4, 13↔R5, 14↔R6, 15↔R7); two (16, 17) are documentation PRDs the owner requested directly, outside the bundle ("someone else accessing this repo should know the full flow, architecture, setup, infra — everything" for 16; "an understanding of the scientific side of things" for 17); one (18) is a soundness gap discovered mid-decomposition, when PRD 14 went looking for a merge signal and found diagnosis-category merges structurally invisible to any fact-based check.

**Status: all nine are design-only.** No code in `backend/`/`frontend/` reflects any of them — verified in PRD 16 §4.0 by direct grep (`extraction_method`, `NUMERACY`, `_UNIT_WORD_MAX_LENGTH` all absent from `backend/`; `Medication.why` is still `str = ""`, not `str | None`). `dev-tasks` is the next step for each, once approved. Unlike 01-08/09, this wave has **not** been through a settling revision pass — each PRD's own `[OPEN]`/`[DEFERRED]` items are real and unresolved, consolidated below rather than cleared.

### Sub-projects (10-18)

| # | Sub-project | Scope | Depends on | Lines |
|---|---|---|---|---|
| 10 | numeric-integrity | `NUMERACY` prompt block (forbids an added normal/abnormal label, reference range, rounding, unit conversion, percent/frequency reframe, or unattributed severity) added to the shared `_style_rules.txt`; a deterministic, model-free `_check_numeric_parity` tokenizer + check at the tail of `_verify_assembly`; log-only | 01, 03, 04, 05 | 367 |
| 11 | omission-signal | Consumes the already-computed, previously-discarded `review_result.coverage` field; one `_log_coverage_summary` INFO aggregate (category-bucketed omission count) inside `iter_steps` step 6; deliberately no fact text logged | 01, 03, 05, 06 | 298 |
| 12 | extraction-provenance | `extraction_method: Literal["native","ocr","pasted"]` added to `SourceSpan`/`Unit`, copied verbatim from the two known producers through `unitize()`; two log-only aggregates (unit-level, fact-level); the grounding prompt never sees the tag | 01, 02, 09 | 552 |
| 13 | absent-value-contract | `why: str \| None = None` on `Medication`/`Test`/`Procedure`/`OtherInstruction`, `""` normalized to `None` by a shared validator; deletes the "Not stated in your note." sentinel from both prompts; the one rendering fallback moves to `frontend/src/utils/nextSteps.ts` | 01, 04, 05, 08 | 524 |
| 14 | merge-provenance | **Rejects** `merged: bool` (an unverifiable model self-report, the same class PRD 02 already rejected for `file`/`page`) in favor of the already-free `len(source_fact_ids) > 1`; hardens the MERGE prompt paragraph with a three-site worked example; one log-only `merge_candidate_signal` aggregate | 01, 04 | 362 |
| 15 | design-doc-evidence-labeling | Defines RF/DJ/PD evidence-provenance labels (orthogonal to the `[OPEN]`/`[RESOLVED]`/`[DEFERRED]` status-tag axis), an inline-tag convention, and seeds `docs/uncalibrated-constants.md` with 6 real constants — no code, no schema, no test | — | 161 |
| 16 | technical-documentation | A line-by-line audit finds 4 of 7 `docs/` files materially false about the current four-call pipeline; specifies a rewritten `pipeline.md`/`architecture.md`/`data-and-privacy.md`, a new `flow.md` (mermaid sequence diagram), `error-taxonomy.md`, and `testing.md`; documents the **post-01-09** state now, not the post-10-18 state | 01-09 (landed), aware of 10-15 (written), 15 specifically for vocabulary/register | 247 |
| 17 | scientific-documentation | Five new files under `docs/science/` (`README.md`, `design-rationale.md`, `good-summary-conformance.md`, `evidence-map.md`, `research-corpus.md`); vendors a condensed summary of the team's own research memos and the criteria doc, never the third-party papers themselves | 15, 16 | 444 |
| 18 | diagnosis-soundness | Closes an undocumented citation-existence blind spot: `ReasonForVisit`, `DiagnosisDetail`, and `Diagnosis.changed_since_last_visit` carry no citation field and are invisible to `_verify_assembly`'s soundness guard; adds the three fields plus a dedicated nested-container check block; exempts `low_priority` (reasoned, written down for the first time); adds a regression test asserting every `CarePlan` field carries a recorded soundness classification | 01, 04, 05, 06, 13, 14 | 422 |

Total across 10-18: **3,377 lines**. Grand total across all eighteen PRDs (01-09 + 10-18): **8,602 lines**.

### Dependency graph (10-18)

```
Wave 1 (01-09, landed) -- the foundation every wave-3 PRD reads from
   │
   ├───────────────┬───────────────┬───────────────┬───────────────┐
   ▼               ▼               ▼               ▼               ▼
10 numeric-      11 omission-    12 extraction-  13 absent-value- 14 merge-
   integrity        signal          provenance      contract         provenance
   (01,03,04,05)    (01,03,05,06)   (01,02,09)      (01,04,05,08)    (01,04)
   │               │                                │                │
   │               │                                └────────┬───────┘
   │               │                                         │ share care_plan.py /
   │               │                                         │ assemble_and_render.txt
   │               │                                         │ (14 makes ZERO care_plan.py
   │               │                                         │  edits once its own field is
   │               │                                         │  rejected -- seam shrinks to
   │               │                                         │  the prompt file only)
   │               │                                         ▼
   │               │                                18 diagnosis-soundness
   │               │                                (declares 01,04,05,06,13,14 as
   │               │                                 deps; ALSO edits _verify_assembly's
   │               │                                 tail / _ITEM_LIST_FIELDS -- an
   │               │                                 UNDECLARED seam with 10, below)
   │               │
   └───────────────┴────────────────────────────────┐
                                                      ▼
                          pipeline.py seam summary: 10 (near _verify_assembly's
                          tail) and 11 (inside iter_steps step 6) are disjoint,
                          confirmed by both PRDs. 10 and 18 are NOT disjoint --
                          both insert new code as "the last statement before
                          _verify_assembly's return" and neither PRD names the
                          other (see Cross-PRD couplings).

15 design-doc-evidence-labeling (needs nothing)
   │
   ▼
16 technical-documentation (needs 01-09 landed + is aware of 10-15 written;
   cites 15's vocabulary/register, not blocked by it; independent of the
   10/11/12/13/14/18 code track since it documents only the landed state)
   │
   ▼
17 scientific-documentation (needs 15 directly + 16 directly; the two
   families' own cross-reference convention is JOINTLY [OPEN] -- see
   Cross-PRD couplings)
```

### Recommended implementation order (10-18)

1. **15 — design-doc-evidence-labeling.** Zero dependencies, zero code/schema/prompt touch — land first so 16 and 17 have a vocabulary and a seeded register to point at from day one.
2. **10, 11, 12 — the three independent, log-only leaf PRDs.** Each depends only on already-landed wave-1 PRDs; land in any relative order among themselves, but coordinate `Constants.Observability.LOG_EXTRA_KEYS` as independent appends, never a wholesale rewrite (11 adds `coverage_signal`, 12 adds `extraction_signal`/`extraction_signal_facts`; **10 does not touch this list at all** — see Cross-PRD couplings for why that matters).
3. **13 — absent-value-contract.** Land before 14 and 18: PRD 14 §4.7 was authored against the assumption that 13 would exist first, and PRD 18 explicitly names 13 as a dependency.
4. **14 — merge-provenance.** Lands after 13, matching the order 18 itself declares. Because 14 ends up making zero `care_plan.py` edits (§4.1's rejection), the actual landing-order risk between 13 and 14 is low regardless — this keeps the dependency chain 18 declares intact rather than for any technical necessity.
5. **18 — diagnosis-soundness.** Depends explicitly on 13 and 14. Also land it after 10: the two share an undeclared seam at the tail of `_verify_assembly` (Cross-PRD couplings), and since 10 has no dependency on 18 and was conceived first, land 10's `_check_numeric_parity` call first and rebase 18's new diagnosis block after it, not the reverse.
6. **16 — technical-documentation.** Independent of the entire 10/11/12/13/14/18 code track, since it documents only the already-landed 01-09 state by explicit sequencing decision (16 §4.0) — can be authored and landed in parallel with the code PRDs. Land before 17.
7. **17 — scientific-documentation.** Depends on both 15 and 16 by its own header (§0); lands last.

### Cross-PRD couplings (10-18)

| Coupling | Where decided | Reaches into |
|---|---|---|
| `Constants.Observability.LOG_EXTRA_KEYS` gains three independent appends to the same list: `coverage_signal`, `extraction_signal`/`extraction_signal_facts`, `merge_candidate_signal` | 11 (§4.3), 12 (§4.9), 14 (§4.4) | `backend/utils/constants.py` — whoever lands second or third must **merge** their addition into the list as it stands at that point, never overwrite it wholesale from their own PRD's snippet. **This is the single most likely way this batch breaks on landing.** Note: **10 does not add an entry to this list** — confirmed by direct reading of PRD 10 §4.4 (it logs via plain string interpolation, no `extra=`) and by PRD 12 §4.9's own cross-check — despite this batch's initial framing assuming it might |
| `care_plan.py` / `assemble_and_render.txt` shared by 13 and 14 | 13 §4.8, 14 §4.7 | 14 rejects its own `merged: bool` field (§4.1), so it makes **zero** `care_plan.py` edits — the seam collapses to the prompt file only, and even there the two paragraphs are adjacent-but-independent (13 rewrites `NOT STATED --`, 14 rewrites `MERGE --`) |
| `care_plan.py` shared by 13 and 18 | 13 §4.1, 18 §4.2/§4.8 | 13 makes `why` nullable on `Medication`/`Test`/`Procedure`/`OtherInstruction`; 18 adds `source_fact_ids` to `ReasonForVisit`/`DiagnosisDetail` and `changed_since_last_visit_fact_ids` to `Diagnosis` — zero class-body overlap, no conflict expected regardless of landing order |
| `assemble_and_render.txt`'s `MAPPING`/`SOURCE_FACT_IDS` paragraphs (18) vs. `MERGE` (14) vs. `NOT STATED` (13) | 13, 14, 18 | Three PRDs each own one paragraph of the same prompt file; all three independently confirm (13 §4.8, 14 §4.7, 18 §4.8) their paragraphs are adjacent but textually independent — no shared sentence needs to satisfy more than one PRD |
| `pipeline.py`'s `_verify_assembly` tail — **10 and 18 both insert new code as the last statement before `return`, and neither PRD names the other as a dependency or seam** | 10 §4.4/§4.7 (names only 11 as a seam), 18 §4.3 (names no `_verify_assembly` seam at all) | A **real, undeclared coupling**, found only by reading both PRDs against each other — not stated in either. Whoever implements both must pick one final in-function ordering; the recommended order (§ above) is 10 first, 18's diagnosis block after |
| `pipeline.py`'s `_verify_assembly` (10) vs. `iter_steps` step 6 (11) | 10 §4.7, 11 §4.1 | Explicitly confirmed disjoint by both PRDs — no conflict |
| `docs/uncalibrated-constants.md` authorship | 15 §4.3 (specifies content, not who creates the file), 16 (assumes it exists, links to it from `pipeline.md`), 17 §9 (proposes "16 creates it, 17 only links" as a default, explicitly unconfirmed) | **`[OPEN]`, jointly, across all three** — needs 16's author to confirm before `dev-tasks` runs on either 16 or 17 |
| The 16↔17 documentation cross-reference convention | 16 §3 (proposes inline `"— see X for why"` / `"— see X for the exact mechanism"`), 17 §9 (proposes a different, blockquote-style `Mechanism:`/`Rationale:` pointer form) | **Two different proposed conventions, neither adopted.** Both PRDs flag this `[OPEN]` and explicitly defer to whichever lands second to reconcile — as written today the two proposals are mutually inconsistent |
| `extraction_method` (12) documented by 16/17, not consumed by either | 12 | Non-blocking in both directions — 16/17 cite whatever 12 lands as, but neither depends on landing order relative to 12 |

### Consolidated open questions (10-18)

**The standing cross-batch fact carried into this wave.** PRD 05 §7.5's injected-error reviewer catch-rate protocol is specified but still unrun (reverified here: no `manual_reviewer_catch_rate.py` or `catch_rate`-named file exists anywhere in the repo). Every non-fatal, LLM-only backstop this wave still leans on inherits the same caveat — the reviewer's real-world value is asserted, not measured. Cited directly by 10 §1, 11 §1/§8, and 18 §9; 18 further ties its own `low_priority` exemption and its residual reliance on review for the newly-covered fields to whatever this protocol eventually shows.

**Three findings, discovered during this batch, owned by no PRD in it:**

1. **A PDF page with no text layer is silently dropped, never OCR'd.** Found while writing PRD 12 (§3, §4.2, §9 `[OPEN]`). `extract_pages_from_pdf` has no per-page OCR fallback — a scanned page inside an otherwise-native PDF vanishes from the document with no warning and no trace, and nothing downstream can detect it, because the content was never in the ledger to check against. `extraction_method`'s per-`(file, page)` `SourceSpan` placement leaves room for a future fallback without a further schema change, but PRD 12 does not build one — this is explicitly out of its scope (12 only tags what *was* extracted).
2. **`Fact.text`'s own numeric fidelity to the source is unchecked.** Found while writing PRD 10 (§4.3, §9 `[OPEN]`). Grounding can mangle a number while paraphrasing into `Fact.text`, and PRD 10's numeric-parity check deliberately validates a rendered field against `Fact.text`, not against the original note or `quote_for()` (§4.3's three-reason argument for that choice) — so a number grounding itself corrupted is invisible to this check by construction. Adjacent to R3, outside its scope.
3. **`frontend/src/types/carePlan.ts` types `CarePlanContent.summary_fact_ids` as required**, but `_strip_internal_provenance` always strips it server-side, so it is always absent at runtime. Found while writing PRD 18 (§6, §9 `[OPEN]`) — a pre-existing type bug predating this batch entirely, flagged for PRD 08 to clean up, not fixed here.

**Per-PRD forward-looking opens, not already covered above or in Cross-PRD couplings:**

- **10** — a standalone ordinal day-of-month ("on the 12th") isn't excluded from the numeric tokenizer and could false-positive; a future numbered `steps[]` prefix in `assemble_and_render.txt` would introduce spurious digit tokens. Neither is built defensively; both wait on the manual smoke test (§8).
- **11** — whether a real-world omission rate, once observed, should feed back into revisiting the soundness-over-completeness inversion itself; whether a Cloud Logging-based metric/alert on `coverage_signal.rate` is worth building (needs a production baseline first).
- **12** — whether the fact-level OCR aggregate (§4.8.2) should also break down by `FactCategory`, the way 11's `coverage_signal` does; not built because no consumer has asked for it yet.
- **13** — `test_pipeline_review.py`'s `_care_plan_with_two_medications()` fixture still hard-codes the old "Not stated in your note." sentinel as ordinary fixture text; recommended, not required, cleanup.
- **14** — diagnosis-category merges had no `source_fact_ids`-shaped signal at all when 14 was written (§9 `[OPEN]`). **This is actually closed by PRD 18**, written later in the same batch, which adds `source_fact_ids` to `DiagnosisDetail` (§4.2) — but 14 and 18 do not cross-reference each other on this point even though 18 directly resolves the open item 14 recorded.
- **16** — exact target filenames for 17's doc family (partially answered now that 17 exists and names `docs/science/{README,design-rationale,good-summary-conformance,evidence-map,research-corpus}.md`, but the cross-reference *convention itself* remains open — see Cross-PRD couplings); whether `testing.md` should document the frontend's Vitest suite in the same depth as the backend's test layers.
- **17** — whether to pursue public arXiv/DOI identifiers for the four Drive-only third-party papers (would reduce, not eliminate, a durability risk); whether `good-summary-conformance.md` needs a re-verification pass once 10-18 move from design to landed code — no PRD has explicitly claimed this as "my job" the way PRD 15's register-maintenance rule binds future PRDs generally.
- **18** — whether a fully-emptied `diagnosis.details` should render an explicit "we couldn't confirm what was found" message instead of silently disappearing (a product/copy decision, out of this PRD's scope, flagged for a follow-up frontend PRD); whether the `low_priority` exemption (§4.6) should be revisited once/if PRD 05 §7.5's study shows a materially worse reviewer miss rate on low-stakes, list-shaped content specifically.

### Consolidated manual steps (10-18)

- **10** — Prompt smoke test (confirm the `NUMERACY` block doesn't make the model over-conservative; spot-check the parity check's log volume for false positives on 5-10 real notes, particularly the disclosed date/ordinal blind spots). Judgment call, not required now: whether the false-positive rate is low enough to eventually promote a numeric-parity failure into a pre-seeded reviewer correction. Tune `_UNIT_WORD_MAX_LENGTH` (15) against real notes if a legitimate compound unit gets truncated or over-captured.
- **11** — Confirm log volume/shape once wired into a live run; decide whether/when to build a Cloud Logging-based metric or alerting policy on `coverage_signal.rate` (console/Terraform, not code, and needs a production baseline first); sanity-check the omission rate against PRD 05 §7.5's catch-rate protocol, if that protocol is ever run.
- **12** — No blocking manual step. Awareness only: a small, permanent per-run log-volume increase (two new `logger.info` calls per job). Optional: a real-OCR-upload smoke test to eyeball `extraction_signal`/`extraction_signal_facts` showing a nonzero `ocr_rate`.
- **13** — Real-pipeline smoke check that the model actually emits JSON `null` for an unstated `why`, rather than prose that merely resembles "not stated." Visual QA that the rendered fallback text is unchanged, on-screen and in the downloaded PDF, now that it originates from the frontend instead of pipeline output.
- **14** — Prompt smoke test against 2-3 real/realistic notes containing a genuine 3+-site finding (e.g. a cardiac catheterization or angiogram report). Spot-check the `merge_candidate_signal` log line's structured JSON payload in a deployed environment specifically, not just locally — the same "looks fine locally, silently vanishes in production" risk PRD 11 already named for its own key.
- **15** — Decide whether to retrofit the comparison doc (`comparison-drive-research-bundle.v1.md`) with RF/DJ/PD tags. Decide whether to add the one-line pointer to `design-agent-prompt-template.md` — **a machine-level skill file outside this repository**; per this machine's own orchestration rules that edit is routed through the `update-config` skill or the owner directly, never a `simplify-med` sub-agent. Have `dev-tasks` create `docs/uncalibrated-constants.md` from PRD 15 §4.3's content, transcribed verbatim.
- **16** — Confirm the sequencing decision (document the post-01-09 state now, not post-10-18). Confirm the file-split decisions (`error-taxonomy.md`, `testing.md`, `flow.md` as new files, versus folding one or more back into `pipeline.md`/`architecture.md`). Sanity-check the §3 cross-reference convention once 17's actual doc filenames exist. Approve before `dev-tasks` runs.
- **17** — Decide the `Medical device?` column (a regulatory/legal, owner-only judgment). Approve the vendoring decision (§4.6 — condensing, not verbatim-reproducing except the criteria doc's own table, the team's own memos into the repo). Check whether the four Drive-only third-party papers (AgenticSum, Asgari et al., Croxford et al., Fact-Controlled Diagnosis) have a public arXiv/DOI identifier. Finalize the cross-reference convention with 16's author. Decide `docs/uncalibrated-constants.md` authorship. Have `dev-tasks`/`dev-code` author the five files once approved.
- **18** — Prompt smoke test against a real note with a diagnosis section: (a) confirm `diagnosis.details[]`/`reason_for_visit[]` items carry non-empty, plausible `source_fact_ids` in the pipeline's internal output; (b) confirm `changed_since_last_visit` and `changed_since_last_visit_fact_ids` always appear together, never one without the other; (c) confirm the diagnosis-vs-`low_priority` judgment call still tracks correctly now that `diagnosis.details` carries a citation obligation; (d) confirm the "What the Doctor Found" card still renders normally end-to-end for a well-behaved note.

### Locked decisions — wave 3 additions (apply across 10-18, in addition to the locked decisions above)

- Every new signal introduced in 10, 11, 12, and 14 is log-only and non-gating, with no patient-facing surface and no release gate — stated explicitly in each PRD's own Non-Goals, not merely assumed by omission.
- 14 rejects `merged: bool` outright: an unverifiable model self-report does not earn its place over an already-free, guaranteed-recall signal (`len(source_fact_ids) > 1`) — the same standard PRD 02 already set for `file`/`page`. This is a deliberate rejection, recorded as such, not a silently-dropped feature.
- 15, 16, and 17 are design-only: none of them rewrites a doc, edits a prompt, or touches application code (16 §4.6 specifies exactly one new, narrowly-scoped test file as its sole exception, not yet written) — `dev-tasks`/`dev-code` is the next step for all three once approved.
- The clinical-fidelity evaluation suite remains out of scope everywhere in this wave too (10 §3, 11 §3, 17 §3) — PRD 05 §7.5's protocol is the only evaluation mechanism named anywhere in this batch, and it is still unrun.
- No versioning, no migration (reiterated from the wave-1 locked decisions) — 12, 13, and 18 all mutate schemas in place. 12's GCS `JobInputPayload` shape change needs no dual-read path because the object's lifetime (per-job, deleted at completion, backstopped by a 1-day GCS lifecycle rule) makes a version-skew window inconsequential (12 §4.7).
- PRD 16 documents the post-01-09 (currently-landed) state, not the post-10-18 state — 10-18's eventual landings are scoped as later, targeted amendments to an already-correct doc set, not a reason to wait (16 §4.0).
