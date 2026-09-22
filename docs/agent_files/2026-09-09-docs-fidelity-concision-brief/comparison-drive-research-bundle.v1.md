# Branch pipeline vs. the Drive research bundle — comparison and recommendations

Date: 2026-09-13
Branch: `docs/fidelity-concision-brief`
Status: analysis only, no code changes.

Compares `brainstorm.v1.md` + PRDs 01–09 (implemented, on this branch) against the Drive folder
`19FQYm6oixrQpidEUhGszvfVZ6kXVH4xt` (8 research memos, design-only, never implemented against this
repo).

---

## 1. Summary verdict

The two designs were produced independently and converge on the core architectural thesis to a
striking degree. The Drive bundle ("A") independently validates the branch's ("B") biggest and most
expensive bet — inverting the pipeline so that evidence-linked extraction happens on the pristine
original *before* any generation. **The recommendation is not to change course.**

What A offers is a small number of specific, cheap mechanisms that plug real holes in B, plus one
documentation practice worth stealing. It does not offer a reason to revisit the architecture.

Read A's apparatus with its provenance in mind: A is design-only, reasons largely in the abstract,
and never engages the product's actual constraints — an anonymous visitor with no account, no
clinician anywhere in the loop, no durable state (the job document is deleted the instant
`ResultScreen` mounts on the frontend, and PRD 09 moves the raw input off Firestore onto a GCS
object with the same non-durable lifecycle), a four-LLM-call cost/latency budget
(`Constants.Deadlines.SINGLE_JOB_INTERNAL_DEADLINE_S = 270`), and a split API/worker process pair
bounded by Firestore's 1 MiB document transport limit (PRD 02 §4.1/§4.13). A's Stage 4–8 apparatus —
independent verifier, advisory document judge, four-way release disposition, human-review hold
states — is sized for a product with staffed clinical review and iterative calibration cycles. It
must be read as scoped for a different product than the one on this branch, and most of it does not
survive contact with B's actual constraints. Sections 5 and 6 below separate the small number of
mechanisms worth taking from the larger apparatus that isn't.

---

## 2. What the two approaches are

**A (Drive bundle).** Eight memos (`00`–`07`) proposing a six-component, eight-runtime-stage
pipeline: source reconstruction (an immutable, hashed `SourcePackage` of segments) → a candidate
fact ledger with per-fact attributes and mandatory coverage obligations → one AHRQ-guided structured
draft (evidence-conditional, capped at three "key points") → deterministic structure and
protected-field checks → bidirectional claim-to-source grounding (a separate alignment call) → an
independent claim verifier plus an advisory PDSQI-9-style document judge → targeted, bounded repair
with reverification → a deterministic release controller (release / suppress-field-and-release /
hold-for-review / abstain). A sixth component — an offline evaluation and monitoring programme
(clinician/patient annotation, judge calibration, regression, slice analysis) — is explicitly
"design now, implement later," not part of the runtime MVP.

A labels every substantive claim with one of three tags — **RF** (Research Finding, cited inline to
a real paper), **DJ** (Design Judgment, the authors' own call), or **PD** (Proposed Default, an
explicitly uncalibrated number) — and keeps a per-document evidence ledger mapping claims to
sources. Its research base is real, cited literature: AgenticSum, Asgari et al.
(hallucination/omission taxonomy under atomization), Croxford et al. / PDSQI-9 (judge reliability),
a fact-controlled diagnosis study, and the AHRQ Health Literacy Universal Precautions Toolkit.

**B (this branch).** Four LLM calls — ground → assemble-and-render → review → correct — wrapped
around a deterministic line-based unitizer and deterministic pre/post checks, replacing a prior
three-call simplify/clarify/structure pipeline (one fewer call, not one more). B's brainstorm cites
a different, smaller literature: arXiv:2412.18004 (post-hoc attribution/hallucination),
arXiv:2310.08118 (verifier rubber-stamping), and arXiv:2608.31016 (enumerate-then-verify detection
rates). B's PRDs use `[RESOLVED]`/`[OPEN]`/`[DEFERRED]` markers rather than A's RF/DJ/PD scheme, and
per `prds/README.md` "Consolidated open questions," all nine PRDs are settled with no open items
blocking `dev-tasks`.

---

## 3. Where they agree (do not under-sell this — it is the main finding)

Two efforts, starting from different literatures and never in contact with each other, landed on the
same architecture. That convergence is the strongest available evidence the architecture is right,
and it should be stated plainly rather than buried under the delta list below.

- **Ground before generate.** Both independently arrive at "extract evidence-linked facts from the
  pristine original before any rewriting" as the core fix for the same diagnosed failure mode:
  structuring/generation prompts fabricate when forced to complete required fields the source
  doesn't support. A's Stage 1→Stage 3 ordering and B's ground→assemble ordering are the same
  inversion. (DJ)
- **Delete the forced-inference quotas.** Both independently identified the same root-cause bug in the
  same shape of prompt and deleted the same four rules: mandatory medication reason, mandatory
  warning-sign urgency/action, an exactly-three-sentence summary, and exactly-three questions. A
  calls this invariant 5 ("no quota completion"); B's brainstorm §1 opens with the identical
  diagnosis ("rules 4, 5, 9, 10... cannot both be satisfied") and decision-log row 34 records the
  same four deletions, confirmed live in the shipped schema. (DJ)
- **No clinically meaningful schema defaults.** A's invariant 1 and B's `WarningSign.urgency:
  Literal[...] | None` with no default (confirmed in `backend/models/care_plan/care_plan.py`) are
  the same fix — a nullable field, not a default that quietly asserts a clinical judgment nobody
  made. (DJ)
- **Per-item, machine-checkable source citation with a deterministic drop guard.** A requires every
  non-empty patient-facing item to carry at least one source-fact ID, checked at Stage 4. B's
  `source_fact_ids` plus `_verify_assembly`'s citation-existence check
  (`backend/care_plan/pipeline.py`) drops any item whose citations don't resolve into the ledger.
  Independently derived, functionally identical. (DJ)
- **Verbatim quote as the fabrication detector.** A requires a claim to quote its exact supporting
  substring; B's `_is_verbatim_quote` does the same normalized-substring check. Both treat a
  non-matching quote as a hard, deterministic failure signal, not a soft one. (DJ)
- **The model cites an ID; metadata is recovered by lookup, never trusted from the model.** A's
  `segment_id` design and B's `Unit.id` (file/page recovered by code lookup, "cannot be
  hallucinated," brainstorm §3.2) are the same idea, with the same stated rationale: a
  model-supplied metadata field can be hallucinated, a code-side lookup cannot. (DJ)
- **Deterministic checks run first and are pass/fail, not scored.** A's "hard status gates rather than
  aggregate confidence" (Stage 5) and B's three deterministic post-checks in
  `_verify_ledger`/`_verify_assembly` (drop-and-log, never vote) are the same philosophy:
  deterministic gates precede and outrank LLM judgment. (DJ)
- **Readability is telemetry, never a gate.** Both treat a readability/style score as diagnostic,
  never as proof of comprehension or a pass/fail safety condition. A states this throughout; B's
  decision-log row 65 keeps one before/after score and explicitly deletes a seven-method breakdown
  from primary display. (DJ)
- **AURA/attention-derived grounding is rejected as unavailable.** A explicitly declines to replicate
  AgenticSum's attention-based grounding signal because the product runs against a hosted Gemini API
  with no exposed internals. B never even considers such a mechanism — convergent by omission, from
  the same underlying constraint (a hosted, non-open-weights model). (DJ)
- **"Translate, don't interpret."** A's constrained-generation instructions ("must not use clinical
  knowledge... treat only the supplied source as evidence") and B's LANGUAGE RULES ("never invent a
  number... never add urgency, prognosis, or medical advice beyond what a fact states,"
  `backend/care_plan/prompts/_style_rules.txt`) are the same source-only extraction discipline,
  forbidding plausible clinical inference in the same place in the pipeline. (DJ)

---

## 4. Area-by-area comparison

### 4.1 Source representation and ingestion

| | B (`Unit`) | A (`SourcePackage`/segments) |
|---|---|---|
| Granularity | One line, page-scoped for PDF, whole-file for TXT/DOCX/HTML/image (`backend/models/ledger.py::Unit{id,file,page,line,text}`) | Variable-granularity `Segment{segment_id, file_id, ordinal, kind, coordinates, raw_text, normalized_text, quality, parent_segment_id}`, hierarchical and table-cell-aware |
| Raw vs. normalized | One field; normalization is applied at comparison time only (`normalize_with_offsets`) | Persisted `raw_text` + `normalized_text` with a bidirectional offset map, both stored |
| Extraction method/quality | None on `Unit` — an OCR line is structurally identical to a native-text line | `extraction_method` (`pdf_text`/`docx`/`html`/`txt`/`vision_ocr`) and `quality.status` (`clear`/`uncertain`/`unreadable`) per segment |
| Persistence | Transient — `SourceSpan` lives only for one job's processing window, then deleted; `Unit` is never persisted | Durable, versioned, audit-retained artifact for cross-job evaluation |

Both converge on segment-then-offset over document-then-offset addressing — B's line ID and A's
`segment_id` are the same robustness move against OCR-noise-shattered raw character offsets, arrived
at from different angles (brainstorm §2.5 cites OCR-noise brittleness directly).

B solves a real engineering problem A never touches at all: the API process holds the original file
bytes, the worker process runs the pipeline, and Firestore's 1 MiB document limit bounds what can
travel between them. PRD 02 §4.1/§4.13 works this arithmetic explicitly — a compact `SourceSpan`
line-range map versus materializing a full `list[Unit]` a second time inside the same document. A's
design simply assumes segments are freely available to every downstream stage without ever asking
where the bytes physically live between processes, which is exactly the gap you'd expect from a
design that was never run against this repo's actual API/worker split.

A's `content_hash` and durable, cross-job-versioned `SourcePackage` are real capabilities B doesn't
have — B computes no hash of the input and persists neither `Unit` nor `SourceSpan` past the job's
processing window (PRD 09 tightens this further: the raw input moves from a Firestore field to a
short-lived GCS object, same non-durable lifecycle, different transport). This matters for exactly
one thing A is built for and B isn't: comparing pipeline versions against the same held-out input,
or reproducing a specific run's exact input against its output during an incident investigation. For
a product with no durable state and no evaluation harness to feed, this is a scoped-out gap, not an
oversight — but it is worth flagging that if B ever builds the evaluation suite deferred in §4.8, a
job-scoped content hash (logged, not persisted with the patient's data) is a prerequisite it doesn't
currently have.

A broader pattern worth naming once, because it recurs throughout §4: **A frequently defers a hard
question to "future evaluation," where B picks a concrete number and ships.** (DJ) OCR-confidence
thresholds, chronology-resolution rules, duplicate-clustering thresholds, and
coverage-severity/release thresholds are all explicitly left unresolved in A's docs, pending
clinician-annotated calibration data A's own MVP section admits doesn't exist yet. B, by contrast,
picks and documents concrete tunables everywhere — `_QUOTE_MIN_LENGTH=12`,
`_QUOTE_LONG_WORD_MIN_LENGTH=7`, `_MAX_PII_TOKEN_DELTA=4` — and flags them honestly as
not-yet-calibrated rather than blocking implementation on calibration that has no infrastructure to
run. (PD) That is a more pragmatic sequencing choice for a product this size, but it is also exactly the
gap R7 targets: B's prose flags "not yet calibrated" but doesn't systematically distinguish a
guessed number from an evidenced one the way A's RF/DJ/PD tagging would. (DJ)

### 4.2 Fact ledger granularity

| | B (`Fact`) | A (`FactLedger.facts[]`) |
|---|---|---|
| Shape | One fact per clause: `{id, category, unit_id, char_start, char_end, text}` | Atomic-with-attributes: `subject{value,status}`, `polarity`, `certainty`, `temporality`, `values[{label,raw,unit}]`, `instruction{...}`, `duplicate_of`, `conflict_group_id` |
| Example | "Continue metoprolol 25 mg twice daily" is one fact | Age/sex/condition would be extracted as three separate facts |

Both cite the same paper (Asgari et al.) on the risk of atomizing before generation, and both use
category taxonomies of comparable size (A: 15 categories; B: 8, each with an explicit boundary
rule). (RF) Here is the sharp point: Asgari et al.'s finding is that an atomization-before-generation
intermediate **worsened both major hallucinations and omissions**. (RF) A names this risk in its own
conflicts-and-limitations section and then builds atomize-then-generate anyway — its Stage 3 (AHRQ
transformation) still drafts from the atomic ledger, hedged only as "must not become the sole
input... empirically ablate later." B acted on the same evidence instead of hedging around it:
brainstorm §2.5 rejects finer atomization explicitly, reasoning that over-atomizing "pushes real
judgement into re-composition — which is where content gets dropped," and lands on clause
granularity specifically to avoid the failure mode the citation warns about. (DJ) On this specific point,
B is the more internally consistent reading of the shared evidence than A is of its own. (DJ)

### 4.3 Evidence anchoring and grounding checks

| | B | A |
|---|---|---|
| Anchor mechanism | `unit_id` (int) + LLM-emitted verbatim `quote` | `evidence[{segment_id, start, end, quote}]` |
| Verification | `_is_verbatim_quote`: normalized-substring check against the cited unit's text | "Must quote the exact supporting substring for every fact" — same check, no informativeness floor specified |
| What's stored after verification | Quote discarded; deterministic `_locate_quote_offsets`/`normalize_with_offsets` derive `(char_start, char_end)` into the unit's raw text; `quote_for()` rehydrates on demand | Quote and offsets both stored permanently, together |
| Informativeness floor | `_QUOTE_MIN_LENGTH=12`, `_QUOTE_LONG_WORD_MIN_LENGTH=7` (digit, or a word of at least 7 characters, or at least 12 characters total) — rejects a real-but-vacuous match like citing "with" | None specified |
| Category-assignment ambiguity | Named per-category boundary rule (e.g. the contrast-dye rule: "anything administered during a test belongs to that item, never medications") | No equivalent — 15 categories, richer per-fact attributes, no boundary-rule mechanism |

B's mechanism: `unit_id` plus an LLM-emitted verbatim `quote`, verified as a normalized substring of
the cited unit's text (`_is_verbatim_quote`), then deterministically converted to `(char_start,
char_end)` — after which the quote string itself is discarded (`Fact` carries no `quote` field;
`quote_for()` rehydrates on demand from the unit). A's mechanism keeps the quote stored permanently
alongside the offsets rather than verifying then discarding it.

B has a third deterministic gate A has no equivalent of: the informativeness floor above, guarding
against a real-but-vacuous substring match. Nothing in A's docs proposes an equivalent floor against
trivially-true-but-meaningless quotes — a fact whose entire evidentiary support is the word "with"
would pass A's check exactly as written.

B's category boundary rules are also a mechanism A never proposes: each of B's 8 categories carries
a named exclusion rule, directly fixing a concrete, previously-shipped bug where contrast dye was
misfiled as a take-home medication, reproduced verbatim in the shipped `ground.txt` prompt and
locked down with `test_ground_prompt_contains_contrast_dye_boundary_rule`. A's 15-category schema is
richer in per-fact structured attributes (negation, certainty, temporality are independently
taggable) but has no comparable mechanism for resolving category-assignment ambiguity — a note item
that could plausibly fit two categories has no tie-breaker in A's design at all.

One further point of convergence worth naming explicitly: both designs reject offset-only anchoring
from different angles, and both are right to. A stores offsets against the raw segment because its
normalized_text diverges from raw_text; B needs offset-recovery specifically because its one
`Unit.text` is compared post-normalization, and a naive raw `.find()` would silently miss a
legitimate OCR-noisy match. Different mechanisms, same underlying worry: never let normalization
silently corrupt the pointer back to the source.

### 4.4 Transformation and generation

| | B | A |
|---|---|---|
| Shape | One LLM call, `list[Fact]` → typed `CarePlan` (`assemble_and_render`) | One LLM call, ledger (+ optional `ContextView`) → AHRQ-guided structured draft (Stage 3) |
| Absent field | Literal sentinel baked into the prompt: `why: str = ""`, rendered as "Not stated in your note." | `null`/absent, never manufactured to satisfy JSON shape (invariant 1) |
| Content-selection discipline | "Remove nothing" — one `summary` paragraph, no schema-enforced point cap | Up to 3 ranked, source-grounded `key_points`; everything else demoted, never deleted (AHRQ Tool #4) |
| Questions | Freely generated, 0–3, constrained to not assert new clinical content | Generated only from a documented question already in the source; otherwise zero, by design |

Agreement: one LLM call from the fact ledger to a typed output object, replacing a prior multi-pass
prose pipeline. A's Stage 3 and B's `assemble_and_render` are architecturally identical decisions,
independently reached.

Genuine divergences:

**Absent field representation.** A's invariant: an unsupported field stays `null`/absent, never
manufactured to satisfy JSON shape. B bakes the literal sentinel "Not stated in your note." into the
generation prompt, so the schema carries `why: str = ""` with no absent-marker type — even though
`WarningSign.urgency` two fields away in the same schema *is* nullable. A's approach is strictly
more machine-checkable; B's is more legible to a solo patient reading a rendered page with no
engineer decoding JSON, and is directly actionable ("gives the patient a real question to ask").
This is a rendering-layer decision masquerading as a schema decision — B could store `null` and
inject the string only at render time for zero extra engineering cost. Worth doing when a second
consumer of `why` exists (translation, an eval harness); not before (see R5).

**Max-three key points vs. "remove nothing."** A imports AHRQ Tool #4 directly: the top layer may
contain up to three ranked, source-grounded `key_points`, with everything else demoted to a
subordinate section but never deleted — a literacy-grounded triage mechanism, not a deletion rule.
B's global principle is flatter: "remove nothing... PII is the single exception" (brainstorm row
39), with no schema-capped, ranked "read this first" tier — `summary` is one generated paragraph
with no lint on point count. This is a real philosophical conflict, not a terminology mismatch. A
has the stronger clinical-literature grounding (AHRQ Tool #4's citation that patients act reliably
on only 1–3 things). B is more consistent with its own root-cause diagnosis: a hard count is exactly
the shape of rule that produced the original forced-inference bug, and re-introducing a "top 3"
quota — even a source-grounded one — reintroduces the shape of risk the whole redesign exists to
fix. Neither side is simply right. **Do not re-litigate this as a bolt-on field** (see §6).

**Questions** show the same pattern from a different angle. Both agree the old exactly-three quota
was a bug and that a question must never smuggle in a new clinical assertion — B's shipped prompt
states this directly: "A question must not assert or presuppose any clinical fact... not already
stated in the facts above." They diverge on whether ungrounded question-generation belongs in this
stage at all. A's position: a `questions` item exists only if the source documents an actual patient
question; where the note has none, generate zero, full stop, and treat open-ended questions as a
UI/interaction feature rather than a pipeline output. B considered and explicitly rejected that
stance (brainstorm §2.5 records "derive questions only from fields that came back not_stated" as a
rejected alternative), landing instead on freely generated questions, 0–3, guarded only by the
no-new-clinical-content rule. A's position is the more conservative one and requires no generative
judgment at all; B's is more useful to a patient who has no other prompt to think of what to ask, at
the cost of a purely generative field with no source anchor of its own.

### 4.5 Output schema, glossary, frontend

| | B | A |
|---|---|---|
| Bugs found | `matched_term`/`term` glossary keying bug; contrast-dye taxonomy fix | None at this depth — A's methodology never reads implementation files |
| Merge handling | Worked rule + regression test: "left and right heart arteries," never the lossy merged form | Principle only ("no qualifier lost"), no worked example |
| Patient-actionable state | Required `status: to_do`/`done`, reasoned from asymmetric harm | No equivalent concept |
| Content-type separation | `GlossaryTerm.source = "llm_proposed"`, scoped to glossary only | Schema-wide `assertion_mode`: `patient_note`/`definition`/`education`/`editorial` |
| Card count | 13 → 8 | N/A (no frontend engagement) |

B does concrete bug-level work that A's document-only method structurally cannot produce, because A
never reads implementation files at this depth:

- The `build_terms_glossary` `matched_term`/`term` keying bug: the function keyed glossary
  highlighting on the dictionary's canonical `term` string (e.g. `"plaque (in an artery)"`) instead
  of the literal alias appearing in body text (`"plaque"`), silently breaking highlighting for every
  parenthesized dictionary entry. Fixed in `backend/utils/jargon_db.py`. A's glossary discussion
  never reaches this level of implementation detail.
- The contrast-dye category-boundary fix (§4.3 above) — domain-specific taxonomy work grounded in an
  actual observed defect, not a general principle.
- Near-duplicate merge with variant preservation: a worked rule and regression test requiring "plaque
  in the left and right coronary arteries" to merge into "your left and right heart arteries," never
  the lossy "your heart arteries." A's Stage 3 mentions merging without qualifier loss abstractly
  but never derives a worked example.
- A required `status: "to_do" | "done"` field, reasoned from asymmetric harm: "telling a patient to do
  something already done costs a phone call; telling them a pending action is complete is a missed
  follow-up" (brainstorm row 41). A has no analogous patient-actionable-state concept anywhere.
- 13 cards collapsed to 8, driven by the same "remove nothing from content, but don't multiply
  surfaces" discipline.

A contributes one thing B has no equivalent of: `assertion_mode` (`patient_note | definition |
education | editorial`), a schema-level, structurally-enforced separation between patient-specific
claims and general educational content, underlying A's "external-education boundary." B's only
comparable marker is `GlossaryTerm.source = "llm_proposed"`, scoped narrowly to the glossary, with
no schema-wide equivalent — but this is a road not taken (B has no education layer at all, and none
is planned), not an oversight; see R7's discussion and §6 for why the narrow fix already covers the
practically important half.

### 4.6 Verification and repair

| | B | A |
|---|---|---|
| Reviewer | One LLM call: field-level `corrections` (fixed 3-op vocabulary) plus a per-fact coverage walk | Independent verifier, separate from the generator, with per-dimension exactness (semantic/entity/numeric/unit/negation/certainty/temporality/subject) |
| Second opinion | None | Advisory PDSQI-9-derived document judge, shadow mode |
| Repair | `correct()` applies only named corrections, one attempt | Targeted repair, bounded, with regression checks on unchanged claims |
| Guard against scope creep | `_verify_correction_diff`, bounded by `_MAX_PII_TOKEN_DELTA=4` | "Reject unrequested changes" (principle, no named mechanism) |

B's review call produces field-level `corrections` in a fixed three-op vocabulary plus a per-fact
coverage walk; correct applies named corrections only, guarded by a deterministic diff check
(`_verify_correction_diff`) bounded by `_MAX_PII_TOKEN_DELTA=4`. A's mechanism is heavier: a
claim-verdict contract with per-dimension exactness
(semantic/entity/numeric/unit/negation/certainty/temporality/subject), an independent verifier
distinct from the generator, an advisory PDSQI-9-derived document judge, and bounded repair with
regression checks on unchanged claims.

Strong agreement on the shape of repair, independent of the verifier apparatus around it: the
reviewer must never rewrite directly; repair is strictly narrower than regeneration; one repair
attempt only, not an iterative loop; a document-level aggregate score must never override a
claim-level hard failure; and — citing Croxford et al.'s finding that a single well-specified judge
(best-single ICC 0.818) outperformed the best multi-agent committee (ICC 0.768) — a single judge
beats a multi-agent ensemble. B's `_verify_correction_diff` is arguably ahead of A here: it is the
concrete, shipped, testable implementation of what A states only as a principle ("reject unrequested
changes").

### 4.7 Safety and release control

| | B | A |
|---|---|---|
| Gate | None — `review()`/`correct()` are both explicitly non-fatal (PRD 05 §4.8) | Deterministic release controller, 4 dispositions: release / suppress_field_and_release / hold_for_review / abstain |
| Backing apparatus | None | Protected-field registry, hazard taxonomy with reason codes, S0–S3 severity |
| Failure path | A failed review ships assembly's unchecked output; a rejected corrector output falls back to the pre-correction plan | Hazard routes to hold/abstain/suppress per severity |
| Who acts on a hold | No one — no account, no clinician, no durable state | A staffed reviewer (assumed, not built) |

This is the sharpest asymmetry in the whole comparison. A's Stage 8 is a deterministic release
controller with four dispositions, backed by a protected-field registry, a hazard taxonomy with
reason codes, and an S0–S3 severity scale.

**B has no release gate at all.** `review()` and `correct()` are both explicitly non-fatal by design
(PRD 05 §4.8) — a failed review ships assembly's unchecked output, and a rejected corrector output
falls back to the pre-correction plan. State the trade honestly: B's choice follows directly from
the brief's own framing that failing an anonymous user's job entirely over a fidelity nit is the
wrong trade, and from the fact that there is genuinely no one to address a `hold_for_review` to in a
single-shot, no-account, no-clinician product. But the residual is real, and it is currently
undisclosed to the patient: a document that fails every check silently ships anyway, with no signal
to the reader that anything went wrong.

### 4.8 Evaluation and monitoring

| | B | A |
|---|---|---|
| Status | Deliberate non-goal, deferred | Component 6, "design now, implement later" |
| Contents | Manual smoke-test protocols recorded per-PRD §8 (e.g. PRD 05 §7.5 injected-error catch rate, PRD 03 §8 extraction recall) | 4 evaluation units, bidirectional clinician annotation, natural-vs-perturbed sets reported separately, judge calibration, slice analysis, regression gates |
| Most transferable idea | — | Design logging before implementation, so a failure is attributable to extraction vs. transformation vs. alignment vs. review |

A's Component 6 is a full offline evaluation programme: four evaluation units, bidirectional
clinician annotation, natural vs. controlled-perturbation test sets reported separately (because,
per the cited study, performance on controlled perturbations did not transfer to natural
hallucinations), a judge calibration protocol, slice analysis, and regression gates. B deferred the
entire evaluation suite as a deliberate non-goal, recording intended fixtures and manual smoke-test
protocols in brainstorm §5 and each PRD's own §8 (e.g., PRD 05 §7.5's injected-error catch-rate
protocol, PRD 03 §8's extraction-recall protocol).

This is not a disagreement — it is a sequencing choice both sides made deliberately. A's most
transferable single instruction, independent of the rest of its evaluation machinery, is that
logging should be designed *before* implementation, so a failure can later be attributed to
extraction vs. transformation vs. alignment vs. review rather than showing up only as an unexplained
bad output.

---

## 5. Recommendations — ranked

### R1 — Consume the coverage signal the pipeline already pays for. Cost S. ADOPT — top priority.

This is the single best value-for-effort item, and it is a bug, not a design change. `review()`
emits a `ReviewResult.coverage` list — one `CoverageEntry{fact_id, present}` per ledger fact — which
is exactly the enumerate-then-check-presence shape brainstorm §3.5 calls mandatory, and it is paid
for in prompt and output tokens on every single run. `_sanitize_review_result`
(`backend/care_plan/pipeline.py:463-497`) even back-fills `present=False` for any fact the reviewer
silently skipped (line 491-495: `coverage = [e for e in result.coverage if e.fact_id in fact_ids]`
followed by `coverage += [CoverageEntry(fact_id=i, present=False) for i in missing]`) and logs a
warning when it does. Then `iter_steps` reads only `review_result.corrections` (`pipeline.py:899`,
`if review_result and review_result.corrections:`) — the coverage list is computed, sanitized, and
discarded. Verified: `grep -rn "\.coverage\b" backend/` outside the review machinery and its tests
turns up nothing.

The omission direction is exactly the failure mode A's evidence (Asgari et al.) identifies as
genuinely distinct from fabrication, (RF) and it is exactly the one B's soundness-over-completeness
inversion (`prds/README.md` "Consolidated open questions" item 2) made structurally invisible
everywhere else in the pipeline. (DJ) It is being computed and thrown away.

Minimum fix: log the `present=False` fact ids with their `text` and `category` at WARNING. Better:
fold the count into the run's structured log so the real omission rate becomes observable across
runs. This costs nothing at the model layer — no new LLM call, no new prompt tokens, the call is
already being made — and it is also the cheapest possible way to get *evidence* about whether the
soundness-over-completeness inversion was the right call. Right now that decision is unfalsifiable
in production; R1 makes it falsifiable for the cost of a log line.

### R2 — Add a numeracy ruleset to the shared style rules. Cost S. ADOPT.

`backend/care_plan/prompts/_style_rules.txt` currently has exactly one numeric rule: "Never invent a
number, and never convert vague wording ('a few weeks') into an exact one ('3 weeks') unless a fact
states the exact number." That covers fabrication and vague-to-exact conversion only. It says
nothing about rounding an already-exact value, converting units, adding a reference range, labeling
a result normal/abnormal/elevated, attaching a severity or color to a bare lab value, or reframing a
percentage as a frequency (or vice versa).

A's Stage 3 numeracy section supplies exactly this, with negative examples: source "A1c 7.2%" must
never render as "A1c 7.2% (above normal)." B's domain — clinical notes — is saturated with labs,
vitals, and doses, and nothing in `_verify_assembly`'s deterministic guards or B's LANGUAGE RULES
currently catches a model quietly adding an interpretive label to a bare number. (DJ) This is a pure
prompt addition to `_style_rules.txt`, testable with two or three prompt-content regression tests in
the style PRD 04 §7.2 already uses for other rules.

### R3 — A deterministic protected-value parity check at assembly. Cost M. ADOPT-REDUCED.

`_verify_assembly` (`backend/care_plan/pipeline.py:394-`) runs three deterministic guards, and all
three are about *citation existence*: questions truncated to 3, `summary_fact_ids` filtered to real
ids, and per-item `source_fact_ids` filtered with fully-unbacked items dropped. Nothing checks that
the *value inside a rendered field survived rendering intact*. An item that correctly cites fact 47
and renders its dose as "250 mg" when fact 47's text says "25 mg" passes every deterministic check
in the pipeline — the only thing standing between that and the patient is the review LLM, which is
(a) non-fatal by design, (b) documented in the brief's own cited literature as prone to
rubber-stamping (arXiv:2310.08118), (RF) and (c) whose catch rate has never been measured — PRD 05 §7.5's
injected-error protocol is specified but still unrun.

A's Stage 4 protected-token parity check is the right mechanism, but its full form (a registry of
protected fields plus hazard reason codes plus S0–S3 severity) is over-built for this product. (DJ)
Reduced form: for each assembled item, tokenize numbers-with-units out of its rendered fields and
out of the `text`/`quote_for()` of each fact in its `source_fact_ids`; if a number appears in the
item that appears in none of its cited facts, log it. Once the false-positive rate is known from
real logs, consider routing it into the reviewer's correction list as a pre-seeded finding. This is
deterministic, model-free, and catches the highest-consequence error class in the product — a
silently altered dose or value. Do **not** adopt A's full protected-field registry, hazard reason
codes, or S0–S3 severity scale: there is no release controller in B to consume any of that
classification.

### R4 — Carry extraction method (OCR vs. native) through to `Unit`. Cost S. ADOPT.

B currently cannot tell, during a run or afterward, whether a given fact rests on OCR'd text or on
native extraction — a `Unit` built from a garbled scan is structurally identical to one built from
crisp PDF text. Worse, `_is_verbatim_quote` supplies *false confidence* here: a plausible OCR
misread (a scanned "5 mg" misread as "6 mg") passes the substring check with complete certainty,
because the check only asks whether the model's quote matches the unit's stored text, never whether
that text was reliably extracted in the first place. This is, as the brief itself notes in its
OCR-ceiling discussion, the one failure mode invisible to every other safeguard in the design —
raising the downscale ceiling 2048→4096px helps legibility but does nothing to flag the residual
misreads that remain. (DJ)

All the plumbing points already exist — the image/OCR branch of extraction is a distinct code path
from native PDF/DOCX/TXT/HTML extraction. Add `extraction_method: Literal["native","ocr"]` to
`SourceSpan`/`Unit`, thread it through `backend/services/unitizer.py`, and log it. Scope this to
logging only — do not build a confidence gate on it; there is no consumer for a gate yet, and
building one now would be exactly the kind of unearned apparatus rejected in §6.

### R5 — `why` as `str | None` at the schema layer, sentinel at the render layer. Cost M. DEFER.

B bakes the literal "Not stated in your note." into the generation prompt (§4.4 above), so the typed
schema carries `why: str = ""` with no absent-marker type, even though `WarningSign.urgency` two
fields away in the same schema is nullable. A's `null` is strictly more machine-checkable. But the
patient-visible behavior is identical either way, and there is no second consumer of `why` today —
no eval harness, no translation path, nothing that would benefit from distinguishing "genuinely
absent" from "the string happens to be this English sentence" by type rather than string comparison.
Worth doing when a second consumer appears (a future eval harness, a translation feature); not
before, as speculative generality for a consumer that doesn't exist yet.

### R6 — A `merged: bool` flag on assembled items. Cost M. ADOPT-REDUCED, low priority.

A requires a closed-vocabulary transformation tag
(`copied`/`reordered`/`split`/`plain_language_substitution`/`abbreviation_expansion`/`defined_term`)
on every claim, with a matching deterministic lint. The full taxonomy is unearned for a stateless
product with no reviewer or downstream consumer to act on a rich tag set (DJ) — but one bit targets a
risk B's own brief already names in §5: "merging near-duplicate findings may quietly lose an
anatomical variant." A boolean `merged` flag makes merged items findable in logs and in the one
fixture the brief already wants (the left/right coronary artery merge case), at a fraction of A's
schema cost.

### R7 — Steal A's evidence-labeling discipline for future design docs. Cost S. ADOPT (process, not code).

A tags every substantive claim RF (research finding, cited inline), DJ (product design judgment), or
PD (proposed default, explicitly flagged as not evidence-calibrated), and keeps a per-document
evidence ledger mapping each claim to its source and role. B's PRDs do something adjacent with
`[RESOLVED]`/`[OPEN]`/`[DEFERRED]` markers, but those track decision *status*, not evidence
*provenance* — they do not separate "the literature says this" from "we decided this as a product
judgment" from "this number is a guess we haven't calibrated yet." B has several uncalibrated
constants that are honestly flagged in prose but not systematically distinguishable from decisions
backed by evidence: `_MAX_PII_TOKEN_DELTA=4`, `_QUOTE_MIN_LENGTH=12`,
`GLOSSARY_CURATION_TIMEOUT_S=20`. (PD) Adopting A's RF/DJ/PD tagging convention in future design docs
(starting with this branch's own follow-on work) costs nothing but discipline and would make exactly
this kind of "is this evidenced or guessed" question answerable at a glance.

---

## 6. Explicitly rejected, with reasons

| A mechanism | Why rejected for B |
|---|---|
| Deterministic release controller (4 dispositions) | Nobody to address a `hold_for_review` to; no durable state to hold anything in; `abstain` for an anonymous single-shot upload means the patient gets nothing at all, which is worse than a flagged imperfect result. |
| Advisory PDSQI-9-derived document judge (shadow mode) | A fifth LLM call whose output nothing downstream can act on, in a product with no calibration loop and no clinician raters to validate it against. A's own docs concede this must stay uncalibrated and advisory — it would ship as pure cost with no acted-upon signal. |
| `ContextView` (selection artifact before generation) | A itself defers this to "later, only after evaluation" — it is not even part of A's own MVP. A's own cited Asgari evidence argues against a pre-generation selection/atomization layer, the same evidence B already acted on in choosing clause granularity (§4.2). |
| Full coverage-obligation state machine (`omitted_intentional`/`suppressed_for_safety`/`unresolved_source`) | Ceremony with no actor. R1 already recovers the practically useful part (a present/absent signal, logged) without a multi-state disposition nobody in this product's runtime consumes. |
| Persisted raw/normalized text split on `Unit` | B's `normalize_with_offsets` already computes an equivalent raw-to-normalized character mapping on demand, exactly where it's needed (offset recovery), rather than paying storage/complexity cost on every unit up front. |
| `duplicate_of`/`conflict_group_id` on `Fact` | B already handles the practical instance (near-duplicate anatomical findings) by merging at assembly with an explicit preservation rule (§4.5). True contradiction detection has no mechanical way to verify the LLM did the cross-referencing correctly, unlike quote-verbatim's substring check — unearned complexity with no corresponding check. |
| Schema-wide `assertion_mode` | B's `GlossaryTerm.source = "llm_proposed"` plus the substring-of-note groundedness guard in `curate_glossary_terms` already gets the practically important half (auditability, no-fabrication) at a fraction of the schema cost. The remaining gap — no structural barrier stopping a future feature from treating `terms` as equal-authority to `medications` — is real but speculative; nothing today actually does this. |
| A's max-three key points as a bolt-on `key_points` field | Two competing "what matters" surfaces (`summary` and a separate ranked `key_points`) that can disagree with each other is worse than either alone. If B wants to pursue AHRQ-style triage, it should be a deliberate re-run of the brainstorm skill on the information-architecture question, not a delta patched onto the current design. |

---

## 7. Where B is ahead of A

- **PII and clinician-name leakage.** A never mentions PII, clinician names, facility names, or
  redaction anywhere in the memos read for this comparison — checked directly: no "PII," "clinician
  name," "hospital," or "redact" language appears in `02-ahrq-transformation.md` or
  `07-final-evidence-backed-pipeline.md` beyond boilerplate. A's fidelity-first framing would, if
  implemented as written, faithfully preserve "Doctor Alok Singh" as a correctly-grounded fact — a
  clinician's real name genuinely is present and accurate in the source, and A's whole apparatus
  (grounding, provenance, release gating) is built to protect fidelity-to-source, not to
  deliberately violate it. B recognized this needs a deliberate, source-unfaithful exception and
  implemented it twice (assemble stage and corrector, both drawing from the shared
  `_style_rules.txt`): "This is the one case where you do not preserve a fact's exact wording — a
  generic form loses the patient no clinical information." (DJ)
- The `matched_term`/`term` glossary keying bug — a concrete, shipping defect A's document-only
  methodology structurally cannot find, because A's evidence ledger cites `docs/pipeline.md` only
  and never reads `jargon_db.py` at implementation depth.
- The contrast-dye category-boundary rule — domain-specific taxonomy work grounded in an actual
  observed failure, not a general principle stated in the abstract.
- The required `status: to_do | done` field and the Next Steps information architecture, reasoned from
  asymmetric harm between two kinds of patient-facing mistakes A's schema has no vocabulary for at
  all.
- Clause granularity as the more internally consistent reading of the shared Asgari evidence (§4.2) (RF) —
  A names the atomization risk and builds around it anyway; B names it and changes its own design in
  response. (DJ)
- The API/worker transport constraint and Firestore byte budget (§4.1) — a real, quantified
  engineering problem A's design never engages with because A never reads the current architecture
  beyond `docs/pipeline.md`.
- The four-call cost/latency budget (ground, assemble-and-render, review, correct — one fewer call
  than the pipeline it replaces) against A's implied six-to-eight calls for a comparable pipeline:
  generator, a separate independent alignment/verification call, a separate coverage-disposition
  pass, and a separate document-level judge, on top of the base generation call — for a product with
  no account to amortize infrastructure cost across and an anonymous, single-request-response usage
  pattern, this is a first-order cost difference A's docs never budget or even acknowledge as a
  constraint.
- The corrector's deterministic diff check (`_verify_correction_diff`) — the concrete, shipped
  implementation of a principle ("reject unrequested changes") A states only in prose with no named
  mechanism.
- Simply: B is built, tested, and committed on this branch, with regression tests locking in the
  specific bugs it fixed (contrast dye, glossary keying, merge preservation). A is a set of design
  memos that has never been run against this repository, and several of its own sections say so.

---

## 8. Open items this comparison surfaces

- The soundness-over-completeness inversion (`prds/README.md` "Consolidated open questions" item 2) is
  the single decision most worth revisiting, and R1 is the cheap way to gather evidence on it rather
  than argue about it in the abstract.
- PRD 05 §7.5's injected-error catch-rate protocol is still unrun. Until it runs, the reviewer's value
  as the fidelity backstop is asserted, not measured — and because review is non-fatal by design, a
  reviewer that silently rubber-stamps everything is indistinguishable in production from one that
  genuinely finds nothing wrong.
- A's evaluation programme (Component 6) is the natural shape for B's deferred evaluation suite when
  it eventually gets built. Its single most useful instruction, independent of the rest of its
  apparatus: report natural and synthetically-perturbed test cases separately, because in the cited
  study, performance on controlled perturbations did not transfer to natural hallucinations.

---

## Sources

- Drive folder: `19FQYm6oixrQpidEUhGszvfVZ6kXVH4xt` — `README.md`, `00-component-map.md`,
  `01-source-reconstruction.md`, `02-ahrq-transformation.md`, `03-grounding-provenance.md`,
  `04-verification-llm-judge.md`, `05-clinical-safety-release.md`, `06-evaluation-monitoring.md`,
  `07-final-evidence-backed-pipeline.md`.
- Branch side: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md`,
  `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/prds/README.md` and PRDs 01–09.
- Area reports underlying this comparison: `area1-ingestion-grounding.md` (source representation, fact
  ledger, evidence anchoring, coverage obligations), `area2-transformation-output.md`
  (transformation/generation, output schema, glossary, numeracy, rendering).
