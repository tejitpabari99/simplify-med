# Fidelity and Concision — design brief

Date: 2026-09-09
Status: approved in brainstorm; not yet turned into PRDs
Revision: pipeline architecture inverted after a follow-up round (see 2.5 and section 3). Supersedes the rewrite-then-extract design in the first draft.

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
| Mutate schema, prompts and UI in place | New `v1-3` alongside `v1-2` | Not live, no users, no stored documents. Versioning would be pure cost. |

### Correctness

| Decision | Alternative rejected | Why |
|---|---|---|
| Delete forced-inference rules 4, 5, 9, 10 from `structure_note.txt` | Keep them; rely on the reviewer to catch fabrication | They are the direct cause. Rule 1 ("use only information found in the source") and rule 4 ("every medication must have a 'why'") cannot both be satisfied by a note that never states why. |
| Remove clinically meaningful defaults: `WarningSign.urgency` becomes nullable; the `importance` field is deleted outright; `CarePlan.urgency` and `Diagnosis.main_conclusion` are deleted entirely (see 2.5) | Keep defaults, mark them "unverified" in the UI | A default is an affirmative claim the model never made. `DiagnosisDetail.severity` is already nullable and is the precedent. `importance` is a `HIGH`/`LOW` that defaults `LOW` on every item and has no remaining consumer once Next Steps orders by status. |
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

### 2.5 Architecture inversion (follow-up round)

The first draft kept the existing rewrite-then-extract ordering and patched its drift. A follow-up round replaced the ordering entirely. Extraction now happens FIRST, on the pristine original; simplification becomes a rendering concern applied to already-extracted facts.

| Decision | Alternative rejected | Why |
|---|---|---|
| Invert the pipeline: ground (extract evidence-linked facts from the original) → assemble + render → review → correct | Rewrite-then-extract with the original passed alongside as a tiebreaker | The drift patch solved a problem that only existed because we rewrote before extracting. Three literatures converge: grounding before generation beats attributing after (up to 57% of post-hoc citations are unfaithful — the model did not actually use the source it cites, [arXiv:2412.18004](https://arxiv.org/abs/2412.18004)); every clinical simplification study measuring both readability and fidelity found a tradeoff, with one ophthalmology study finding 91% of simplified sentences locally accurate but only 86% of reports retaining ALL critical information; and a verifier bolted onto ungrounded prose largely rubber-stamps (an LLM verifier passed 38 invalid plans out of ~92 it approved, [arXiv:2310.08118](https://arxiv.org/pdf/2310.08118)). Cost is four sequential LLM calls, one FEWER than the design it replaces. |
| Both whole-document prose passes (`simplify_language`, `clarify_and_action`) are deleted | Merge them into one prose pass | Merging was the earlier plan and was already the weaker option. With rendering moved to field level, no whole-document rewrite exists anywhere in the pipeline. Their content rules survive, relocated into the render step. |
| Grounding emits a FLAT ledger of atomic facts, each carrying a category tag, a line ID and a quote. Assembly into the typed `CarePlan` is a separate step. | Grounding emits the typed `CarePlan` directly with evidence per field; or an untagged flat ledger | The atomic ledger is the unit that makes omission checking work. The category tags let the extractor be prompted with the care-plan categories as a recall checklist, which is the one advantage direct typed extraction had. The objection that a separate assembly step can drop things is neutralised by deterministic coverage checking. |
| A "fact" is one clinical statement at roughly the granularity of a note clause | Finer atomisation, one fact per attribute | "Continue metoprolol 25 mg twice daily" is one fact, not four. Over-atomising makes the ledger enormous, makes coverage checks noisy, and pushes real judgement into re-composition — which is where content gets dropped. At clause granularity, assembly is close to a 1:1 map. |
| Evidence is a deterministic LINE ID plus a short verbatim QUOTE, with a substring check that the quote appears in the cited line | Character offsets; quote alone; sentence index; paraphrased reference | Offsets are brittle under OCR noise, and the robustness literature notes moderate corruption (spurious spaces, character substitutions) is more dangerous than obvious garbling because it silently fails a match rather than failing loudly. A line ID cannot shatter that way; the quote localises within the line and catches fabrication. Both checks are deterministic and free. |
| Plain-language rendering happens at FIELD level during assembly; `summary` is generated from the assembled structure | A whole-document prose pass; a separate rendering call over the structured plan | Rendering `"metoprolol 25mg BID"` into `"metoprolol 25 mg twice a day"` is a bounded value transformation over a few tokens. Whole-document rewriting is where the 14% of critical content goes missing. Make each simplification operation as small as possible. |
| The reviewer's coverage check MUST be shaped as enumerate-facts-then-check-presence-of-each, not open-ended "does this look complete" | Open-ended completeness review | Not a preference — a requirement. LLM judges discriminate ADDED content at 0.79–0.94 but OMITTED content at 0.50–0.63, near chance, with a mechanical explanation: an omission leaves nothing to point at. Restructuring into enumerate-then-verify raised omission detection to 24.6% at 2.7% false alarms, and a blinded physician comparison favoured it 10/10 ([arXiv:2608.31016](https://arxiv.org/html/2608.31016v1)). |

| Source provenance is carried by the deterministic unitizer, not by fields the model fills in: each unit is `{id, file, page, line, text}` and the model cites only `id` | Add `file` and `page` fields to each ledger fact | The extractors already compute this and throw it away — `resolve_uploaded_files` concatenates multiple files behind a plain-text `--- Source: {filename} ---` marker (`utils/misc.py:106`), and `extract_text_from_pdf` knows the page number inside its loop, logs it to debug, and joins pages with `"\n\n"` (`utils/pdf.py:20-30`). Recovering file and page by lookup costs no output tokens and cannot be hallucinated. The plain-text source markers become redundant in model-facing text. |
| Every category passed to the grounding step carries explicit criteria AND a boundary rule, not just a name (see 3.3) | Category names alone, as today | The contrast-dye misclassification was a definitional failure: the structuring prompt supplies a JSON schema and zero definitions. Naming the categories without defining their edges reproduces the bug for every ambiguous item, not just that one. |
| Care-plan fields are split three ways — extracted (grounded 1:1 to ledger facts), derived (computed from the assembled whole), generated (not from the note at all) — and only the extracted set forms the grounding checklist | Treat every schema field as extractable | `summary` is not a category and cannot be grounded to one fact; `questions` are by definition things the note does NOT say. Conflating these with extracted content either forces fabrication or makes coverage checking incoherent. |
| `summary` is the ONLY derived field, and it cites the set of fact IDs it was built from | Exempt derived fields from review; check them against the whole ledger | Citing its source set turns the hardest field to verify into the easiest: the reviewer checks that each cited fact supports what the summary says about it, and that nothing uncited crept in. Exempting it would leave the most-read card on the page as the only unchecked one. |
| `Diagnosis.main_conclusion` is deleted | Keep it as a second derived prose field | It can be built from the rest, and once it can, it should not exist. `summary` delivers the headline and `diagnosis.details` carries the findings, so keeping it means a second derived field to verify for no additional information. |
| `CarePlan.urgency` is deleted | Keep it nullable | A whole-document mood judgement with no single supporting fact and no consumer in the UI. `WarningSign.urgency` is unaffected — it is extracted (the note says "go to the emergency room"), stays nullable, and still drives sort order and badges. |
| `questions` are freely generated, exempt from grounding, but constrained to interrogative form that asserts no new clinical claim; at most three, with no minimum | Derive questions only from fields that came back `not_stated`; drop the card; unconstrained free generation | Questions are the one genuinely generative element in the output — deriving them purely from gaps would make them mechanical. But "exempt from review" without a guard is a hole: "Should I be worried about my kidney function?" invents a concern the note never raised. The reviewer does not check grounding here; it checks that no clinical claim smuggled itself in as a premise. The old "generate exactly 3" rule is the same forced-inference bug as the rest — a complete note deserves zero questions. |
| Build the inverted pipeline directly; do not gate on a prior recall experiment | Run a 30–50 note recall comparison (raw vs pre-simplified extraction) before building | The experiment was scoped and then dropped deliberately. The inverted architecture wins on three independent axes (grounding-before-generation, bounded field-level simplification, tractable omission checking), and extraction recall is measurable from the grounding step's own output once it exists — the ledger IS the measurement. Recall risk is instead mitigated in the design: the deterministic abbreviation list is fed into grounding (3.3) specifically to help it read dense abbreviated source. |

## 3. Design

### 3.1 Pipeline shape

```
OCR (conditional, 4096px) ─▶ deterministic line numbering ─▶ detect_terms (deterministic)
   │
   ▼
GROUND (LLM)             atomic facts, each with a category tag, a line ID and a quote;
   │                     prompted with the care-plan categories as a recall checklist
   ▼
[deterministic]          every quote must be a substring of its cited line
   │
   ▼                                        ┌─ [thread] glossary curation (LLM) ─┐
ASSEMBLE + RENDER (LLM)  typed CarePlan; field-level plain language;              │
   │                     summary written from the assembled structure             │
   ▼                                        │                                     │
REVIEW (LLM)             fidelity + coverage, as enumerate-then-check-presence    │
   │                                        │                                     │
   ▼                                        │                                     │
CORRECT (LLM)            applies named corrections only; PII scrub                │
   │                                        │                                     │
   ▼                                        │                                     │
[deterministic]          every ledger fact reached the output; glossary re-detect ◀┘
```

Four sequential LLM calls — one fewer than the superseded design and one more than the three running today. Glossary curation runs on a background thread, reusing the `ThreadPoolExecutor` pattern already at `care_plan_pipeline.py:51`, because it depends only on the detected terms and not on anything the reviewer produces.

### 3.2 Unitization (deterministic)

Before grounding, our own code — not the model — splits the input into numbered units:

```
{ id: 47, file: "cardiology-note.pdf", page: 2, line: 14,
  text: "Pt to cont. metoprolol 25mg BID; f/u cards 4/12." }
```

Both extractors already have this data and currently discard it. `resolve_uploaded_files` concatenates every uploaded file into one blob behind a plain-text `--- Source: {filename} ---` marker (`services/care_plan_input.py:308`, `utils/misc.py:106`), so file identity survives only as prose the model has to notice. `extract_text_from_pdf` knows the page number inside its loop, logs it at debug level, and joins pages with `"\n\n"` (`utils/pdf.py:20-30`), so page boundaries are computed and then thrown away.

The model cites one integer. File and page are recovered by lookup, which costs no output tokens and cannot be hallucinated — strictly better than asking the model to fill in `file` and `page` fields we would have no way to check. Once units carry file identity, the plain-text source markers are redundant in model-facing text.

For images, one image is one unit source at `page: 1`; a multi-image upload gives each image its own file identity, which it does not currently have.

### 3.3 Grounding

Input: the line-numbered original, plus the deterministic abbreviation list from term detection (feeding the expansion list in here directly attacks the one real weakness of this architecture — extraction recall on abbreviated raw text).

Output: a flat ledger. Each entry carries a category tag drawn from the care-plan taxonomy, a line ID, a verbatim quote, and the fact's content at clause granularity.

The prompt presents the categories as an explicit checklist, each with criteria AND a boundary rule — a name alone reproduces the contrast-dye failure for every ambiguous item:

| Category | Criteria | Boundary rule |
|---|---|---|
| `reason_for_visit` | Why the patient presented — complaint, symptom, or referral reason | Not the diagnosis. What they came *with*, not what was *found*. |
| `diagnosis.details` | Conditions, findings and interpretations the clinician recorded | Includes imaging and lab findings stated as conclusions. Excludes the raw measurement, which belongs to the test. |
| `medications` | Substances the patient takes **themselves, at home** | Anything administered *during* a test or procedure belongs to that item. This is the contrast-dye rule. |
| `tests` | Diagnostic investigations — labs, imaging, tracings | Both already performed and newly ordered; `status` distinguishes them. |
| `procedures` | Interventions performed **on** the patient | Carries any substance administered during it. |
| `other` | Instructions that are none of the above — diet, activity, wound care, self-monitoring | If it has a date or an appointment, it is `follow_up`. |
| `follow_up` | A future appointment or contact, with timing | Not a general instruction. Must involve seeing or contacting someone. |
| `warning_signs` | Symptoms the note tells the patient to watch for | Must come with what to do, from the note. Not a side effect merely listed. |

Every fact gets exactly one category; where two could apply, the boundary rules decide.

`low_priority` is deliberately absent from this list. It is a priority judgement made at assembly — normal results, routine findings, administrative detail — not a clinical type the grounder can see.

Two deterministic checks run immediately: every cited line ID must exist, and every quote must be a substring of the line it cites. A failure means fabricated evidence, detected with certainty and without a model.

### 3.4 Assemble and render

Input: the ledger. Output: the typed `CarePlan`.

It does four things and nothing else:

1. Maps each fact to a care-plan item of its category.
2. Splits the fact's content into the item's typed fields.
3. Renders each field in plain language — `"BID"` becomes `"twice a day"`.
4. Writes `summary` from the assembled whole.

`summary` is the only derived field in the schema, and it carries the set of fact IDs it was built from so the reviewer can check it. `questions` are generated rather than extracted: at most three, no minimum, interrogative form only, and they may not assert a clinical claim the ledger does not already carry. `low_priority` is assigned here, not by the grounder — it is a priority judgement over already-categorised facts.

The content rules from the deleted prose prompts relocate here: active voice, address the patient as "you", one idea per sentence, no fabricated numbers, no added urgency, no new medical advice, and the extended PII rule covering all person and facility names. So does the near-duplicate merge rule, which must preserve every variant explicitly ("your left and right heart arteries", never "your heart arteries"), and the section-boundary definitions — `medications` means things you take home and take yourself; anything administered during a test or procedure belongs to that item.

Because rendering is field-level, no whole-document rewrite exists anywhere in the pipeline. `summary` is the single exception and is generated from structure, not from the note.

### 3.5 Review

Input: the ledger and the assembled care plan. Two jobs:

**Fidelity** — nothing in the output that its fact does not support. Emits field-level corrections only, never prose. Three operations: `correct` (the output contradicts its evidence — supply the right value), `not_stated` (the output asserts something the evidence does not support), `remove` (an item with no support at all).

**Coverage** — shaped as enumerate-then-check-presence: for each ledger fact, does it appear in the output, yes or no. This shape is mandatory. Open-ended "is anything missing" review performs at near chance.

**Derived and generated fields** are checked differently. `summary` is verified against the specific fact IDs it cites — each cited fact must support what the summary says about it, and nothing uncited may appear. `questions` are exempt from grounding by design, but are checked for smuggled clinical claims: a question may presuppose only what the ledger already establishes.

The reviewer does not adjudicate which section an item belongs in; that is the render step's job, and loading taxonomy onto the reviewer dilutes the one thing it is for.

### 3.6 Correct

Applies only the named corrections, plus a PII scrub of any person or facility name that survived rendering. Must not touch fields no correction names.

This is the design's soft spot: it is an LLM writer, and it can reintroduce drift. The mitigation is mechanical — diff its output against its input and assert only fields named in the correction list changed.

### 3.7 Deterministic close

Two final non-model checks: every ledger fact maps to something in the output (a drop during assembly or correction is caught here rather than being invisible), and `build_glossary_from_simplified_text` re-detects terms against the final corrected output, so a term whose sentence was rewritten drops out automatically.

### 3.8 Glossary path

1. Deterministic detection, now against a stoplist-pruned dictionary.
2. LLM curation on a background thread: drop terms a general reader can define; propose terms the dictionary missed, tagged with a distinct source.
3. Deterministic re-detection against the final output (3.7).
4. `build_terms_glossary` keys on `matched_term`, not `term`.

### 3.9 Schema changes

- `CarePlan.additional_info` — deleted.
- `CarePlan.urgency` — deleted (derived whole-document judgement, no consumer).
- `Diagnosis.main_conclusion` — deleted (buildable from `summary` plus `diagnosis.details`).
- `WarningSign.urgency` — nullable, no default. Extracted, not derived; still drives sort order and badges.
- `summary` — carries the set of fact IDs it was built from.
- `importance` — deleted from every model that carries it.
- `source` enum — deleted from all models.
- `status: Literal["to_do", "done"]` — added and REQUIRED on `Medication`, `Test`, `Procedure`, `OtherInstruction`, `FollowUp`.
- `Medication.change` / `change_description` — folded into one field.
- `RawArtifacts` — `simplified_text` and `clarified_text` no longer exist as pipeline stages. Replaced by the evidence ledger.

### 3.10 Frontend

Eight cards: What You Need to Know, Why You Came In, What the Doctor Found, Next Steps, What to Watch For, Questions to Ask at Your Next Visit, Other Items From Your Visit, Medical Terms Glossary.

Next Steps merges `medications`, `tests`, `procedures`, `other` and `follow_up`, split into To-do then Already-done, each group ordered by a fixed type precedence so the same plan always renders identically in the app and in the PDF. Each row is a checkbox or check mark plus a one-line detail. `buildPdfHtml` mirrors the structure and drops the readability breakdown.

The evidence ledger is NOT displayed. It exists to make grounding and coverage checkable, not to show provenance to the patient.

## 4. Non-goals

- No authentication, saved history, sharing, or any durable state.
- No user-visible source citations or provenance UI. The evidence ledger is internal.
- No follow-up conversation.
- No versioning, migration, or backward compatibility.
- No OCR confidence signals or per-page verification.
- No developer/admin mode.
- No automated evaluation harness in this unit of work.

## 5. Open risks

| Risk | Cheapest test |
|---|---|
| **Extraction recall on raw clinical text may be worse than on pre-simplified text.** No published work measures this — a real gap in the literature, not just in our knowledge. Accepted as a build-time risk rather than gated on. | Measure it from the grounding step's own output once built: run it over a set of notes and score the ledger against a hand-annotated fact list. The ledger is already the right shape for this, so the check costs annotation time only. If recall is the problem, feeding the abbreviation list into grounding (3.3) is the designed mitigation. |
| The corrector is an LLM writer and can reintroduce the drift the reviewer exists to catch. | Diff the corrector's output against its input; assert only fields named in the correction list changed. Mechanical and cheap. |
| The reviewer may rubber-stamp rather than catch errors — documented behaviour for LLM verifiers. | Inject known errors at a known rate (a dropped medication, a wrong dose, an invented follow-up) and measure catch rate. If it is low, the reviewer needs restructuring before it can be trusted as the fidelity backstop. |
| Coverage checking may miss omissions even in enumerate-then-verify form — the published detection rate is 24.6%, better than chance but far from complete. | Synthetically delete a known fact from the ledger's downstream output and measure detection at a fixed false-alarm rate. Accept that this is a mitigation, not a guarantee. |
| Model-proposed glossary definitions are unsourced clinical content. | Route them through the reviewer like any other generated claim; the distinct `source` tag keeps them auditable. |
| Requiring `status` may produce a confident, wrong `done` on a scheduled future procedure. | One fixture: a note ordering a procedure for next month. Assert `to_do`. |
| Merging near-duplicate findings may quietly lose an anatomical variant. | One fixture with three affected vessels. Assert all three site names survive in the merged text. |
| The "after" readability score has no prose document to score once the prose stages are deleted. | Score the rendered care plan's own text. Arguably more honest — it measures what the patient actually reads. |
| The common-word stoplist may strip a term that is jargon in clinical context. | Diff the pruned dictionary against the full one and read the removals once, by hand. |
| No test in the repo checks clinical fidelity today; every decision above is unguarded until the deferred suite exists. | Accepted deliberately. Intended fixtures: medication started vs considered; treatment accepted vs declined; "no evidence of X" vs "X"; possible vs confirmed diagnosis; changed vs unchanged dose; return precautions with exact urgency; conflicting notes; missing medication purpose; "no restriction documented" vs affirmative clearance; OCR decimal and unit errors. Deterministic assertions, not an LLM judge. |
| Attribution research is almost entirely on clean digital text (Wikipedia, PubMed abstracts, clean EHR exports), not OCR'd scans with realistic noise. The line-ID approach is reasoned from that literature, not validated on our input distribution. | Inject realistic OCR noise into a handful of notes and compare how often line-ID, offset and quote-only attribution still resolve to the right source line. Half a day. |
| `questions` are the single ungrounded surface in the output. The interrogative-form guard is reasoned, not tested. | Fixture set of notes with known gaps; assert no question presupposes a clinical fact absent from the ledger. |
| Requiring `summary` to cite its fact IDs may degrade summary quality, or the model may cite loosely without the citations meaning anything. | Compare summaries generated with and without the citation requirement on the same notes; separately, spot-check whether cited facts actually support the sentences they are attached to. |
