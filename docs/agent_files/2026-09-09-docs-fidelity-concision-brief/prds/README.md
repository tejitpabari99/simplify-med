# PRD index — fidelity and concision, plus input-transport follow-on

PRDs 01-08 decompose [`../brainstorm.v1.md`](../brainstorm.v1.md) into implementable sub-projects — the fidelity-and-concision brief itself. PRD 09 is a separate, independent follow-on the owner raised after 01-08 were settled (see "Deferred follow-on" history below): it moves `JobDoc.input_text`/`input_provenance` off Firestore and onto GCS. All nine are design only — no tasks have been generated yet. `dev-tasks` is the next step for each.

**Status: all nine PRDs are settled.** 01-08 went through a prior revision pass that resolved every `[OPEN]` item blocking `dev-tasks` and reconciled cross-references after concurrent edits. 09 was written afterward, against the post-01-08 codebase, as a self-contained follow-on. `grep -rn "\[OPEN" prds/` surfaces nothing but prose that references past open items as history, across all nine files.

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
