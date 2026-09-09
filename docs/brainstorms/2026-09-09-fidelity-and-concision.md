# Fidelity and Concision — design brief

Date: 2026-09-09
Status: approved in brainstorm; not yet turned into PRDs

## 1. Problem

Simplify takes one clinical note from an anonymous visitor and returns a plain-language care plan. Two defects run through the current implementation:

**It invents things.** The structuring prompt orders the model to use only information in the source, and then, in the same list of rules, requires a reason for every medication, an action and an urgency class for every warning sign, exactly three sentences of summary, and exactly three questions. Where the note is silent, those requirements are satisfied by fabrication. The Pydantic schema compounds it with clinically meaningful defaults — a warning sign with no stated urgency becomes `monitor`, a plan with no stated urgency becomes `normal` — turning missing information into an affirmative clinical claim. Nothing anywhere checks the output against the original note; Pydantic validates shape, not truth.

**It is verbose and imprecise.** Thirteen result cards, most expanded by default. A "Data Sources" card fed by a schema field no prompt rule describes. A glossary that defines `heart` and `pain` while missing `plaque` and `circumflex`. Clinician and hospital names leaking into the patient-facing summary. Near-identical findings repeated once per anatomical site. Contrast dye administered during a scan filed as a medication the patient is expected to take.

For: someone who wants to upload their own document and see it simplified. There is no clinician in the room to catch an invented drug reason.

## 2. Decision log

### Scope — what we are NOT taking from the source critique

| Decision | Alternative rejected | Why |
|---|---|---|
| Public-share sanitization reduces to deleting the dead `resource.data.shared == true` clause from `firestore.rules:7` | Sanitized `public_output` projection | No share feature exists. `JobDoc.shared` is hard-coded `False` (`models/job.py:94`). The rule clause is unreachable but is a latent hole. |
| No grounded follow-up conversation | Stateless follow-up endpoint fed from browser memory | The job document is `DELETE`d the instant `ResultScreen` mounts. Durable state is off the table, and a follow-up feature without the record is not the feature. |
| No deletion-reliability rework | `deletion_pending` marker, cleanup job, retry, audit event | Best-effort GCS delete is acceptable here: a GCS lifecycle rule backstops it and there is nothing durable to orphan. |
| No patient/developer UI split | Debug mode behind a flag | The frontend exposes no trace IDs, session IDs, raw JSON, or console links. Already true. |
| Semantic evaluation suite is documented as a plan, not built | Build fixtures + assertions now | Deferred deliberately. Section 5 records the intended shape. |
| Grounding is internal to the fidelity reviewer; no `source_text` in the output schema | Per-field source quotes displayed to the user | We are not building a provenance UI. The reviewer grounds against the original internally; nothing is shown. Revisit later. |
| Keep `simplify` and `clarify` as separate calls | Merge into one writer call | The cheap drift fix (section 3.2) captures most of the benefit without a rewrite. |
| Mutate schema, prompts and UI in place | New `v1-3` alongside `v1-2` | Not live, no users, no stored documents. Versioning would be pure cost. |

### Correctness

| Decision | Alternative rejected | Why |
|---|---|---|
| The structure step receives the original note AND the clarified draft, with an explicit rule that the original wins on conflict | Structure from clarified text only (current) | `pipeline.py` passes only `clarified` to `structure_appointment_note`. Anything a rewrite dropped is unrecoverable downstream. One-line change. |
| Delete forced-inference rules 4, 5, 9, 10 from `structure_note.txt` | Keep them; rely on the reviewer to catch fabrication | They are the direct cause. Rule 1 ("use only information found in the source") and rule 4 ("every medication must have a 'why'") cannot both be satisfied by a note that never states why. |
| Remove clinically meaningful defaults: `WarningSign.urgency` and `CarePlan.urgency` become nullable; the `importance` field is deleted outright | Keep defaults, mark them "unverified" in the UI | A default is an affirmative claim the model never made. `DiagnosisDetail.severity` is already nullable and is the precedent. `importance` is a `HIGH`/`LOW` that defaults `LOW` on every item and has no remaining consumer once Next Steps orders by status. |
| A fidelity review call compares the structured plan against the ORIGINAL note and emits field-level corrections only. It never rewrites. | Reviewer rewrites the output; reviewer only flags; a finding fails the job | A reviewer permitted to rewrite becomes a fourth author and reintroduces the drift it exists to catch. Failing the job costs the user their whole result over a nit. |
| A separate LLM corrector applies the corrections, guided by the same style rules as the writer prompts | Deterministic patch application | Chosen by the user over the deterministic option. Correction ops are: (i) correct a wrong value (note says 500, output says 5000); (ii) replace an unsupported value with "not stated"; (iii) remove an unsupported item entirely. The boundary between (ii) and (iii) is deliberately loose — an unsupported dose becomes "not stated", an entirely invented side effect is removed. |
| Where the note does not state something, render it explicitly: "Reason: not stated in your note" | Omit the row silently | Silence is indistinguishable from an oversight. An explicit "not stated" is the clearest possible signal that the tool does not invent, and it hands the patient a real question to ask. It also makes the failure mode visible during testing. |
| Global principle: remove nothing. We simplify; we do not interpret or discard. | Trim low-value content | Applies to `low_priority`, to duplicate findings, to ungraded warning signs. PII is the single exception. |
| PII: extend `simplify_language.txt` rule 7 to cover ALL person and facility names — clinician, hospital, clinic — and enforce it again in the corrector | Prompt-only, or corrector-only | The only PII rule today covers the patient's name, DOB, address and insurance. Clinician names are not mentioned anywhere, which is how "Doctor Alok Singh" reached a summary. The early rule stops propagation through three rewrites; the late check catches what leaks anyway. This is the one sanctioned exception to "remove nothing" — "your doctor" loses the patient no information. |
| `status: "to_do" \| "done"` is REQUIRED on every actionable item. Strict validation, no null. Prompt rule: when genuinely torn, default to `to_do`. | Nullable status rendering as no checkbox | Reverses an earlier recommendation. Done-vs-to-do is a tense judgement recoverable from almost any note, not a clinical inference like medication `why` — requiring it is asking the model to read, not to guess. The asymmetry decides it: telling a patient to do something already done costs a phone call; telling them a pending action is complete is a missed follow-up. |
| Add explicit per-section definitions to `structure_note.txt`, plus the rule that anything administered DURING a test or procedure belongs to that item, not to `medications` | Make taxonomy a fidelity-review responsibility | Contrast dye was filed as a medication because the structuring prompt supplies a JSON schema and no definitions at all. This is a definitional failure, not a fidelity failure; loading it onto the reviewer dilutes the one job the reviewer has. `medications` means things you take home and take yourself. |
| Merge near-duplicate items at the structuring step, via prompt rule, preserving every variant explicitly | Consolidation pass in the corrector; leave as-is | "Heavy calcified plaque in the right coronary artery" and the same in the left circumflex should merge — but to "your left and right heart arteries", never to "your heart arteries". Structuring is where the model still holds full context. |
| Raise the OCR downscale ceiling from 2048px to 4096px long edge (`image_ocr.py:12`). Leave `IMAGE_OCR_PROMPT` unchanged. | Keep 2048; add illegible-region markers | A letter page at 2048px long edge is ~186 DPI, below where decimals and drug-name suffixes survive. This is the only failure mode in the whole design invisible to every other safeguard: the reviewer compares against the transcription, so a corrupted transcription passes. The prompt is already strict and well-written; adding illegibility markers invites mid-transcription editorialising. |

### Glossary

| Decision | Alternative rejected | Why |
|---|---|---|
| BUG FIX: `build_terms_glossary` (`jargon_db.py:288`) must key on `hit["matched_term"]`, not `hit["term"]` | — | Root cause of "highlights `heart` but not `plaque`". The Michigan entry is literally `plaque (in an artery)`. Alias expansion works correctly and detection matches the bare alias `plaque`; the row builder even preserves the matched variant in `matched_term` with a comment saying so. Then the glossary keys on the canonical string, so `renderTextWithTerms` searches the body for `plaque (in an artery)`, finds nothing, and highlights nothing. `heart` works only because canonical and matched happen to be identical. Every parenthesised and comma-listed entry in the dictionary is silently invisible today. |
| Deterministic one-time prune of `michigan_medical_dictionary.json` against a common-word stoplist | LLM-only filtering | The file is not a medical-jargon list; it is a 1,962-entry plain-language health dictionary containing `heart`, `blood`, `pain`, `brain`, `stomach`, `fever` and `ability` ("To able to or can do."). Stripping everyday words costs nothing per run and needs deciding once. |
| An LLM glossary-curation call both FILTERS the detected terms and PROPOSES terms the dictionary missed, writing plain-language definitions for them. Model-proposed terms carry a distinct `source` value. | Filter only; hand-curated supplement file | The dictionary lacks `calcified`, `contrast`, `angiogram`, `narrowing`, `circumflex`, `electrocardiogram`, `statin` — no mechanical fix surfaces them. Hand-curating per specialty is a treadmill. Distinct `source` keeps unsourced definitions identifiable. |
| Selection is by CRITERION — keep a term a general reader plausibly could not define — with a soft cap as backstop only. The criterion governs INLINE HIGHLIGHTING as well as the glossary card. | Hard cap at N terms | A hard cap makes the model arbitrarily discard real terms at the limit. The criterion is what actually separates `heart` from `circumflex`. Highlighting matters more than the card: a speckled paragraph is the visible symptom. |

### Information architecture and concision

| Decision | Alternative rejected | Why |
|---|---|---|
| Thirteen cards collapse to eight | Keep the structure; add a concise layer above it | An earlier recommendation for a "main point + next steps" layer was withdrawn: `summary` already renders as "What You Need to Know" and follow-up already exists. The problem is card count and content quality, not information architecture layering. |
| `medications` + `tests` + `procedures` + `other` + `follow_up` render as ONE "Next Steps" card | Sub-sections by type inside one card | Sub-sections by type are the thirteen-card problem with one border drawn around them. |
| Next Steps splits by STATUS — "To do" first, "Already done" second — with type as a small label per row. Within each group, ordering is a FIXED type precedence so the same plan always renders in the same order, in the app and in the PDF. | Flat list; group by type | The patient's question is "what do I have to do". Deterministic ordering means reports are comparable across runs. |
| Checkbox affordance: `done` renders a check mark, `to_do` renders an empty checkbox. Identical in the PDF export. | App-only affordance | Explicitly requested for print too. |
| Delete `additional_info` from the schema and delete the "Data Sources" card | Keep it with a real prompt rule and an honest label | The field has no prompt rule anywhere — the model fills an unbriefed vacuum — and the frontend renders it under a fabricated "Data Sources" heading, mapping entries to a variable named `path` (`CarePlanView.tsx:348`). Vestigial from juno. |
| `low_priority` ("Other Items From Your Visit") gets an explicit category definition — normal results, routine findings, administrative detail — plus a length rule of one short line per entry | Cap the array; drop non-qualifying items | Defining the category promotes genuinely important items UP into real sections rather than deleting anything, which is what "only critical" actually meant and what "remove nothing" requires. |
| Readability: a single before/after score. Remove the entire seven-method breakdown from the frontend AND from `buildPdfHtml`. | Keep the breakdown behind a toggle | `ResultScreen` already shows only the combined score; the breakdown survives only in the PDF (`buildPdfHtml.ts:137`). It is developer noise presented to a patient as authoritative health-literacy assessment. |
| Null `urgency` renders grey, sorts LAST, and is never removed | Sort ungraded first; drop severity sorting entirely | Sorting last preserves the genuinely useful signal — a source-stated "go to the ER" belongs at the top. Sorting ungraded first promotes noise to the top of the most safety-critical card. Dropping sorting discards real information in favour of clinical documentation order, which is not patient priority order. |
| Prune `Medication`: delete the dead `source` enum and `importance`; fold `change`/`change_description`. Render dosage/frequency/timing/duration as one line. | Rendering changes only | The `source` enum is `documents \| recording \| notes`; `recording` is dead (no audio path) and the other two are too broad to support anything. Thirteen fields per medication is the concision problem at schema level. |

## 3. Design

### 3.1 Pipeline shape

```
                                  ┌─ [thread] before readability score ─────────────┐
                                  │                                                 │
  input ─▶ detect_terms ─▶ simplify ─▶ clarify ─▶ structure ─▶ review ─▶ correct ─▶ assemble
           (deterministic)  (LLM)      (LLM)      (LLM)        (LLM)     (LLM)
                                  │                                │                │
                                  └─ [thread] glossary curation (LLM) ──────────────┘
```

Five sequential LLM calls, six total. `simplify → clarify → structure → review → correct` is a strict data-dependency chain with nothing to overlap. Glossary curation depends only on the clarified text and the detected terms, so it runs on a background thread alongside review and correct — reusing the `ThreadPoolExecutor` pattern already at `care_plan_pipeline.py:51` for the before-score.

### 3.2 Anti-drift

`structure_appointment_note` takes two arguments instead of one: the original note text and the clarified draft. The prompt states that the clarified draft is the writing to emulate and the original is the authority — where they disagree, the original wins.

### 3.3 The reviewer

Input: the original note text and the structured care plan JSON.
Output: `PASS`, or a list of field-level corrections. Each correction names a JSON path, an operation, and where applicable a replacement value.

Operations:
- `correct` — the output states a value the note contradicts. Supply the note's value.
- `not_stated` — the output states a value the note does not support. Replace with the not-stated marker.
- `remove` — the output contains an item with no support in the note at all.

The reviewer checks: added diagnoses or interpretations; omissions; medication names, doses, frequency, duration, status; dates and measurements; negation and uncertainty ("no evidence of X" vs "X", "possible" vs "confirmed"); declined or conditional treatments; warning instructions and urgency; and the `to_do`/`done` status of each actionable item. It does not adjudicate which section an item belongs in — that is the structuring prompt's job.

The reviewer must not emit prose. If a correction cannot be expressed as a value substitution, a not-stated marker, or a removal, that is a signal the field should become not-stated.

### 3.4 The corrector

A separate LLM call receiving the structured plan, the correction list, and the shared style rules. It applies only the named corrections, and additionally scrubs person and facility names to generic forms ("your doctor", "the hospital"). It must not touch fields no correction names.

### 3.5 Glossary path

1. Deterministic detection against the note (unchanged), now against a stoplist-pruned dictionary.
2. LLM curation: drop terms a general reader can define; propose missing terms with definitions, tagged with a distinct source.
3. After correction, the existing `build_glossary_from_simplified_text` re-detects against the FINAL corrected output, so a term whose sentence the corrector rewrote drops out automatically.
4. `build_terms_glossary` keys on `matched_term`.

### 3.6 Schema changes

- `CarePlan.additional_info` — deleted.
- `CarePlan.urgency` — nullable, no default.
- `WarningSign.urgency` — nullable, no default.
- `importance` — deleted from `Medication`, `Test`, `Procedure`, `OtherInstruction`, `WarningSign`.
- `source` enum — deleted from all models.
- `status: Literal["to_do", "done"]` — added and REQUIRED on `Medication`, `Test`, `Procedure`, `OtherInstruction`, `FollowUp`.
- `Medication.change` / `change_description` — folded into one field.

### 3.7 Frontend

Eight cards: What You Need to Know, Why You Came In, What the Doctor Found, Next Steps, What to Watch For, Questions to Ask at Your Next Visit, Other Items From Your Visit, Medical Terms Glossary.

Next Steps renders To-do then Already-done, each group ordered by fixed type precedence, each row a checkbox or check mark plus a one-line detail. `buildPdfHtml` mirrors the same structure and drops the readability breakdown.

## 4. Non-goals

- No authentication, saved history, sharing, or any durable state.
- No user-visible source citations or provenance UI.
- No follow-up conversation.
- No versioning, migration, or backward compatibility.
- No OCR confidence signals or per-page verification.
- No developer/admin mode.
- No automated evaluation harness in this unit of work.

## 5. Open risks

| Risk | Cheapest test |
|---|---|
| Five sequential LLM calls may push job latency past what the progress UI makes tolerable. | Measure current three-call p50/p95 from existing telemetry, extrapolate, and decide before building the reviewer. |
| The corrector is an LLM writer and can reintroduce the drift the reviewer exists to catch. | Diff the corrector's output against its input; assert only fields named in the correction list changed. Cheap and mechanical. |
| Model-proposed glossary definitions are unsourced clinical content. | Route them through the fidelity reviewer like any other generated claim, and keep the distinct `source` tag so they are auditable. |
| The "after" readability score is computed from `event.clarified` (`care_plan_pipeline.py:106`), which is no longer the final output once corrections are applied. | Decide during implementation whether to score the corrected plan's prose instead. Small, but currently wrong. |
| Requiring `status` may produce a confident, wrong `done` on a scheduled future procedure. | One fixture: a note ordering a procedure for next month. Assert `to_do`. |
| Merging near-duplicate findings may quietly lose an anatomical variant. | One fixture with three affected vessels. Assert all three site names appear in the merged text. |
| The common-word stoplist may strip a term that is jargon in clinical context. | Diff the pruned dictionary against the full one and read the removals once, by hand. |
| No test in the repo checks clinical fidelity today; every decision above is unguarded until section 5's deferred suite exists. | Accepted, deliberately. The suite's intended fixtures: medication started vs considered; treatment accepted vs declined; "no evidence of X" vs "X"; possible vs confirmed diagnosis; changed vs unchanged dose; return precautions with exact urgency; conflicting notes; missing medication purpose; "no restriction documented" vs affirmative clearance; OCR decimal and unit errors. Deterministic assertions, not an LLM judge. |
