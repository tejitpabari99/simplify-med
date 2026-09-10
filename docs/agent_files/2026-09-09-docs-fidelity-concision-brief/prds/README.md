# PRD index — fidelity and concision

These eight PRDs decompose [`../brainstorm.v1.md`](../brainstorm.v1.md) into implementable sub-projects. They are design only — no tasks have been generated yet. `dev-tasks` is the next step for each, but it cannot run on a PRD with unresolved `[OPEN]` items (see §f below), so those need settling first.

## Sub-projects

| # | Sub-project | Scope | Depends on | Lines |
|---|---|---|---|---|
| 01 | schema-and-config | Pydantic model changes, new ledger models, firestore.rules dead clause, CORS env var | — | 471 |
| 02 | unitization-and-provenance | Deterministic `{id,file,page,line,text}` unitizer, source-marker removal, OCR ceiling 2048→4096px | 01 | 832 |
| 03 | grounding | Grounding LLM call, category criteria prompt, deterministic quote/unit checks | 01, 02 | 330 |
| 04 | assemble-and-render | The LLM call replacing simplify/clarify/structure; field-level rendering | 01, 03 | 380 |
| 05 | review-and-correct | Fidelity review, correction ops, coverage check, corrector | 01, 04 | 510 |
| 06 | pipeline-orchestration | Step enum, wiring, threading, error taxonomy, ProcessingScreen | 03, 04, 05, 07 | 521 |
| 07 | glossary | `matched_term` bug fix, stoplist prune, curation call, rendered-text projection | 01 | 484 |
| 08 | frontend-and-pdf | 13→8 cards, Next Steps, checkboxes, single score, TS types | 01 | 523 |

Total across all eight PRDs: **4,051 lines**.

## Dependency graph

```
01 schema-and-config ──┬── 02 unitization ── 03 grounding ──┬── 04 assemble-render ── 05 review-correct ──┬── 06 orchestration
                       │                                    │                                             │
                       ├── 07 glossary ────────────────────┘─────────────────────────────────────────────┘
                       └── 08 frontend-and-pdf
```

## Recommended implementation order

1. **01 — schema-and-config.** Foundation; every other PRD depends on it directly or transitively.
2. **02 — unitization-and-provenance.** Needed before grounding can cite units.
3. **03 — grounding.** Needed before assembly can consume a fact ledger.
4. **07 — glossary.** Can land any time after 01 (only depends on 01), but must land *before* 06, since 06 depends on 07's `render_care_plan_text()` for the "after" readability score.
5. **04 and 05 — assemble-and-render, then review-and-correct — must be treated as one unit with 06.**
   - **04 and 06 must land together.** 04 deletes `simplify_language_with_term_plan`, `clarify_and_action` and `structure_appointment_note` while `iter_steps` still calls them by name, so `CarePlanPipeline.run()` throws `AttributeError` between the two landing.
   - **05 retrofits `_style_rules.txt`**, a file 04 creates, so 05 lands after or with 04.
6. **06 — pipeline-orchestration.** Lands last among the backend PRDs, once 03, 04, 05, and 07 are all in — it is the integration point that wires the four LLM calls together and depends on 07's readability projection.
7. **08 — frontend-and-pdf.** Only depends on 01; can be built in parallel with the pipeline PRDs, but real end-to-end validation of its content (fixture regeneration, precedence ordering) waits on 06's live output.

## Cross-PRD couplings

Decisions made in one PRD that reach into another's territory:

| Coupling | Where decided | Reaches into |
|---|---|---|
| `JobDoc.input_provenance` field added | 02 | 01 (schema) |
| `_style_rules.txt` shared prompt fragment | 05 | 04 (owns the file) |
| `render_care_plan_text()` projection | 07 | 06 (readability score) |
| `ProcessingScreen.tsx` / `useJobSnapshot.ts` step labels | 06 | 08 (owns frontend) |
| `PipelineRunResult` carries no `list[Fact]`, departing from 01's suggestion | 06 | 01 |
| `close_coverage` runs BEFORE glossary re-detection | 06 | 05, 07 |

## Consolidated open questions

Every `[OPEN]` item across the eight PRDs. **`dev-tasks` cannot run on a PRD with unresolved `[OPEN]` items** — these six, across five PRDs, need a decision before task generation can start on them (01, 02, and 06 have none and are clear to proceed).

| PRD | Item | Why it matters |
|---|---|---|
| 03 grounding | No minimum length/informativeness constraint on a fact's `quote`. A technically-verbatim but content-free quote (a single common word) would pass the substring check as "evidence." | Weak evidence undermines the grounding guarantee the whole architecture is built around; but an arbitrary character floor risks rejecting legitimately short, valid quotes (a lab value, a drug name). Product judgment call. |
| 04 assemble-and-render | How 06 (pipeline wiring) and 07 (glossary re-detection) should source flat text to re-scan for terms, now that `assemble_and_render` returns a typed `CarePlan` instead of the prose string `build_glossary_from_simplified_text` was built to consume. | The brief describes re-detection against "the final corrected output" without specifying its shape once that output is no longer prose. Blocks 06/07's re-detection wiring until a projection helper is agreed. |
| 05 review-and-correct | `_COVERAGE_OVERLAP_THRESHOLD` (0.5) and `_MAX_PII_TOKEN_DELTA` (4) are reasoned starting points with no empirical grounding. | These thresholds gate whether the coverage check and PII-diff guard actually fire correctly; wrong values mean false negatives (missed omissions/PII) or false positives (rejected valid corrections). Needs tuning against real notes. |
| 07 glossary | Whether including short, non-sentence label fields (titles, dosage strings, timeframes) as their own "paragraphs" in `render_care_plan_text` measurably skews the readability score's sentence-length statistics versus the old whole-document prose. | Directly affects the readability score 06 wires up and surfaces to the user; not resolvable without a real pipeline run. If skewed, the fix narrows the field list for the readability consumer specifically. |
| 08 frontend-and-pdf | Whether done-state Next Steps rows deserve a stronger visual treatment than a color change (e.g. strikethrough). | Not adopted in this PRD — the brief specifies only the checkbox affordance, and unrequested visual weight risks reading as the UI grading the patient's compliance. Revisit if manual QA finds the color change too subtle. |
| 08 frontend-and-pdf | No fixture exercises a null-urgency warning sign alongside non-null ones in a realistic (non-synthetic) narrative. | The synthetic test covers the mechanism, but a real example needs 06's pipeline wiring to exist before it can be authored. |

## Decisions needing the user specifically

1. **`source_fact_ids` on extracted items.** 05 found the brief's promised deterministic close ("every ledger fact maps to something in the output") is not buildable as specified, because only `summary` cites its facts — no care-plan item carries per-item fact provenance. 05 fell back to a token-overlap heuristic and filed exact coverage-closing as `[DEFERRED]`. Adding `source_fact_ids` to extracted items would make the close a set difference rather than a similarity score, but requires revising PRD 01. Omission detection is the capability the inverted architecture was built to enable, so this trades away part of it.

2. **PDF scope inversion.** 08 found `downloadReport.ts` already passes `includeReadability`, `includeGlossary` and `includeLowPriority` as `false`, so the seven-method readability breakdown is already dead in production. Mirroring the app's eight sections in the PDF means the glossary and "Other Items" become *included* in downloads — a widening of today's behaviour, not just a removal.

## Consolidated manual steps

Every §8 item across the eight PRDs, deduplicated and attributed:

- **01** — Add each session's ngrok domain to Firebase Auth's authorized domains (console action, no automation possible). Set `CORS_ALLOWED_ORIGINS` locally before each ngrok session (the env var mechanism is built; setting it per session is manual).
- **02** — OCR ceiling smoke test: confirm the 4096px ceiling completes without a Vertex payload-size/timeout error and visibly improves small-print transcription versus the old 2048px ceiling. Optionally confirm Vertex AI's inline-request size limits against current docs/quotas.
- **03** — Prompt smoke test against real notes: contrast-dye lands in `tests`/`procedures` not `medications`; a dense abbreviation line expands in `text` while `quote` stays verbatim; a realistic multi-page note doesn't hit the 65,536-token output budget.
- **04** — Prompt smoke test against real notes: clinician/facility names render as "your doctor"/"the hospital" everywhere, not just `summary`; a medication with no stated reason renders the exact "Not stated in your note." sentinel; two findings at different sites merge into one item naming both; a fully-answered note produces zero `questions`; token budget holds on a realistic ledger.
- **05** — Prompt smoke test against real notes (dose correction, fabricated warning-sign removal, PII sweep, token budget). Run the injected-error catch-rate protocol (§7.5) and judge whether the rate is acceptable. Tune `_COVERAGE_OVERLAP_THRESHOLD` and `_MAX_PII_TOKEN_DELTA` against real notes.
- **06** — Full end-to-end smoke test once every sub-project has landed: one real note through all six processing steps, plus a deliberately-corrupted note producing a clean error screen. Watch whether the 20-second glossary-curation timeout fires under normal conditions. Confirm `stage_reached` values 3-6 appear correctly in any external analytics (outside this repo's visibility).
- **07** — Review the stoplist prune's diff by hand before treating it as final (particular attention to `foot, feet`, flagged as borderline); extend `common_word_stoplist.json` if the review surfaces more everyday words. Prompt smoke test: a common word gets dropped, a named gap-term (e.g. `calcified`, `contrast`, `angiogram`) gets proposed with a definition, and its `matched_term` appears verbatim in rendered text.
- **08** — Visual QA of the `☑`/`☐` Next Steps glyphs across real browsers/OSes (fall back to inline SVG if they render as tofu boxes). Print-preview QA of the same glyphs. Confirm the `follow_up`-before-`other` type precedence reads sensibly against real care plans. Spot-check the regenerated `realCarePlanOutput.fixture.json` for narrative coherence.

## Locked decisions (apply across all eight)

- No versioning, no backward compatibility, no migration code — mutate schemas and code in place.
- Never push to `main`; never deploy.
- Local testing is via ngrok + pm2 with `SERVICE_MODE=combined`.
- Out of scope everywhere: a per-PR backend preview environment, and the clinical-fidelity evaluation suite.
