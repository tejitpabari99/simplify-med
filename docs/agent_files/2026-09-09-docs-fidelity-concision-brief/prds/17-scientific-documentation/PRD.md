# PRD 17 — Scientific Documentation

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (not re-litigated here — see especially §2, §2.5, §3, §5). Comparison doc: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/comparison-drive-research-bundle.v1.md` (its §3 "where they agree" and §4 area-by-area comparison are this PRD's backbone; §7 records where the branch is ahead of the research).
Branch: `docs/fidelity-concision-brief`.
Depends on: 15 (design-doc-evidence-labeling — this PRD adopts the RF/DJ/PD vocabulary and the `docs/uncalibrated-constants.md` register PRD 15 §4.3 specifies, rather than re-deriving either), 16 (technical-documentation — this PRD's doc set slots into whatever `docs/` structure 16 lands; §9 records the cross-reference convention as a joint, currently-open decision).
Depended on by: none currently in this batch. A future evaluation-suite PRD (explicitly out of scope everywhere per the initiative's locked decisions) would be the natural consumer of this PRD's "what is not evidenced" section (§4.5 below) once it exists.

## 1. Problem

Someone new to `simplify-med` today has no single place to learn what the pipeline is scientifically trying to do, how well-evidenced each of its design choices is, or where the evidence for any of it lives. What exists instead is scattered across five places, none of which is `docs/`:

1. `brainstorm.v1.md` — a decision log with real citations ([arXiv:2412.18004](https://arxiv.org/abs/2412.18004), [arXiv:2310.08118](https://arxiv.org/pdf/2310.08118), [arXiv:2608.31016](https://arxiv.org/html/2608.31016v1)) buried inside a "why we rejected the alternative" table, written for the people making the decision, not for someone arriving after it was made.
2. `comparison-drive-research-bundle.v1.md` — the single richest evidence narrative on the branch (§3's convergence finding, §4's area-by-area comparison, §7's "where B is ahead of A"), framed entirely as a code review of one design against another, not as a standalone explanation of the product's scientific basis.
3. Eight Drive research memos (`00`–`07`) with real, cited literature (AgenticSum, Asgari et al., Croxford et al./PDSQI-9, Fact-Controlled Diagnosis, the AHRQ toolkit) — read for this PRD from a session-scratchpad copy that no longer exists once this session ends, and whose canonical home is a Google Drive folder no future repo reader is guaranteed access to.
4. The "good summary criteria" doc — the team's own adaptation of AHRQ/PEMAT into a feature checklist, with a `Does Juno do it?` column that is **entirely empty**, one Google Doc link away from the repo, not version-controlled with the code it's supposed to be judging.
5. Fourteen landed/in-batch PRDs (01–14) whose own `§9`s carry real evidentiary reasoning (`_QUOTE_MIN_LENGTH=12` is reasoned, not measured; the soundness-over-completeness inversion synthesizes two papers against this repo's constraints) mixed in with ordinary implementation bookkeeping, indistinguishable at a glance per PRD 15's own diagnosis.

None of this is docs/-shaped, none of it is written for the audience the owner named ("someone new to the repo... an understanding of the scientific side of things"), and `docs/` itself is currently stale and being rewritten by PRD 16 for mechanism only. This PRD specifies the doc family that fills the gap 16 explicitly leaves — the *why* and *how well-evidenced*, not the *what* and *how*.

The task is harder than "write it up" for three reasons this PRD does not get to smooth over:

- **Three of the criteria doc's `Must`-priority features directly contradict settled branch decisions** (mandatory medication reason vs. the "not stated" sentinel; "remove distracting content" vs. "remove nothing"; both converge, in the third case, on the *same* answer for evaluative numeric labels from two independent directions). An honest doc says so, on both sides, rather than picking a winner silently.
- **The evidence is genuinely thin in places that matter.** The strongest clinical-safety citation (Asgari et al.) studied transcript-to-clinician-note generation, not patient-facing simplification of an uploaded note. PDSQI-9's ICC 0.818 is provider-facing and this pipeline runs no LLM judge at all. The reviewer's actual catch rate has never been measured (PRD 05 §7.5's protocol is written, not run). A doc family that doesn't say this plainly is worse than no doc family.
- **The source material won't outlive this session.** The Drive memos exist today only as an ephemeral scratchpad copy; the criteria doc lives behind a Google Doc URL. §4.6 below is not optional scaffolding — without a durability decision, everything else this PRD specifies cites sources a future reader can't reach.

## 2. Goals

- A concrete, audience-labeled file list under `docs/` (exact paths, exact purposes) that a `dev-tasks`/`dev-code` pass can author directly — this PRD does not write the docs themselves (§3).
- One doc explaining the product's scientific goal — faithful simplification of a clinician-authored note for a lay reader, "translate, don't interpret" as the boundary — and the evidenced tension between fidelity and readability (§4.1's README, content in §4.2).
- One doc walking the pipeline's major design decisions, each RF/DJ/PD-labeled per PRD 15's convention, with a citation or an explicit "no evidence, product judgment" marker (§4.3).
- One doc that fills in the criteria doc's empty `Does Juno do it?` column against the real, current pipeline, Yes/No/Partial/N/A, with the mechanism or the reason and a falsifiable verification method per row (§4.4).
- One doc mapping every evidentiary claim used elsewhere in this doc family to its source, with what that source does and does not establish, in the "Evidence-to-design traceability" shape the Drive memos already use (§4.5).
- A decided, justified answer to whether the team's own research memos and the criteria doc get vendored into the repo or cited by URL only — explicitly excluding the third-party papers themselves from vendoring either way (§4.6).
- A proposed (not yet finalized — coordinated with 16) cross-reference convention so this doc family and 16's technical docs describe *why* and *how* exactly once each, never twice (§9).

## 3. Non-Goals

- **Not writing the five files.** This PRD specifies their scope, audience, outline, and representative content; a `dev-tasks`/`dev-code` pass authors the actual prose. (Matches this PRD's own charter: planning/design only.)
- **Not building the clinical-fidelity evaluation suite.** Out of scope everywhere per the initiative's locked decisions. §4.5 describes what would need to be measured and how, and is explicit that none of it has been measured.
- **Not resolving the three tensions with the criteria doc.** §4.4 records both positions and which one ships; it does not adjudicate which one *should* ship. That is a product decision for the owner, not a docs PRD.
- **Not a retrofit of PRDs 01–14's prose with RF/DJ/PD tags.** PRD 15 §4.4 already decided this against retrofitting 01–09, for the same "settled, implemented, purely retrospective benefit" reasoning; this PRD does not reopen that call for 10–14 either. Where this PRD's own docs cite a decision made in 01–14, they cite and re-derive the label fresh, in the new doc's own prose — they do not edit the PRD being cited.
- **Not vendoring any third-party research paper.** §4.6 is explicit: AgenticSum, Asgari et al., Croxford et al., the Fact-Controlled Diagnosis paper, and the AHRQ toolkit are never copied into this repo, regardless of the vendoring answer for the team's own memos and the criteria doc.
- **Not new tooling, CI checks, or linters.** §7 proposes greppable, human-run checks only, matching PRD 15 §7's explicit stance against inventing enforcement ceremony for a documentation convention.
- **Not describing pipeline mechanism in depth.** Every doc in this family that needs to reference *how* something works points at 16's docs rather than re-explaining the mechanism; see §9 for the cross-reference convention this depends on.
- **Not a change to `docs/uncalibrated-constants.md`'s content.** PRD 15 §4.3 already specifies its seven columns and seed rows in full; this PRD's evidence-map doc links to it rather than duplicating it.

## 4. Architecture Decisions

### 4.1 The doc set — five files, one per audience

**Decision: five files under a new `docs/science/` directory, not one file and not more than five.**

| # | File | Audience | One-line purpose |
|---|---|---|---|
| 1 | `docs/science/README.md` | Anyone arriving new to the repo, first stop | What the product is trying to do scientifically; the fidelity/readability tension; links to the other four |
| 2 | `docs/science/design-rationale.md` | Engineers and reviewers evaluating or extending the pipeline | Decision-by-decision rationale, RF/DJ/PD-labeled |
| 3 | `docs/science/good-summary-conformance.md` | Product/clinical stakeholders, the owner | The criteria doc's feature table with `Does Juno do it?` filled in, falsifiably |
| 4 | `docs/science/evidence-map.md` | A skeptical reader deciding how much to trust the system; an auditor | Claim → source → what it does/doesn't establish; the unresolved gaps |
| 5 | `docs/science/research-corpus.md` | Anyone who wants to go deeper than the summaries in the other four docs | Durable, in-repo record of the team's own research memos and the criteria doc; the vendoring decision |

**Why five, not one.** A single "scientific-documentation.md" would force four genuinely different readers through four times the material they need: the owner checking the conformance table doesn't want the RF/DJ/PD decision log, and an engineer deciding whether to trust the reviewer doesn't want the full criteria checklist. The Drive memos themselves are already split this way (00–07, one per concern) and the split held up well enough that this PRD's own research relied on it. Five files, one folder, one README linking all four, mirrors that precedent at a scale actually proportionate to this pipeline (a four-call, not eight-stage, system).

**Why not more.** A tempting sixth file ("open risks") is folded into `evidence-map.md` §4.5 rather than split out — the Drive memo pattern this PRD adapts (`07-final-evidence-backed-pipeline.md`'s "Evidence-to-design traceability" immediately followed by "Unresolved evidence gaps") already puts both in one document, because a claim's evidence and a claim's limits are two columns of the same row, not two separate concerns a reader would look for in different places.

**Location, and why not `docs/agent_files/...`.** Per this machine's own memory convention (`agent-docs-location.md`: "design docs go in `docs/agent_files/<date>-<branch>/`, not scattered by type") and PRD 15 §4.3's identical reasoning for `docs/uncalibrated-constants.md`: `docs/agent_files/` is this branch's dated design-session workspace, a record of *how a decision was reached*, not living reference material. The scientific-documentation family is exactly the opposite — it's meant to answer a new reader's question for as long as the product exists, updated as the pipeline changes, sitting next to `docs/pipeline.md` and `docs/architecture.md` the same way `docs/uncalibrated-constants.md` does.

### 4.2 `docs/science/README.md` — the scientific goal and the fidelity/readability tension

Outline: (1) what the product does and does not try to do, (2) the "translate, don't interpret" boundary stated as a testable rule, (3) why fidelity and readability are in genuine tension, with the evidence, (4) a link table to the other four docs plus a pointer into 16's technical docs for mechanism — this closing pointer is this doc's one orientation-signpost cross-reference into 16's family (per the reconciled convention, §9), used once here at the document's head; individual evidentiary claims elsewhere in this doc family (§4.3's RF/DJ-labeled sentences, for instance) link into 16's docs inline instead, per that same convention.

Representative content:

```markdown
# The scientific basis of simplify-med

## What this product is trying to do

Simplify-med takes one clinician-authored note from an anonymous visitor and
returns a plain-language care plan. **There is no clinician in the loop** —
nobody reviews the output before the patient reads it. That single fact
shapes every decision documented in this folder: every fidelity safeguard in
this pipeline exists because a human safety net does not.

The product's boundary is: **translate, don't interpret.** Concretely —

- Render what the note says in plain language. Expand "BID" to "twice a
  day." Never add a clinical interpretation the note doesn't state — no
  inferred cause, no added normal/abnormal label, no urgency the note
  didn't assign. (DJ — see `design-rationale.md` for the full reasoning
  and its citations.)
- Where the note is silent, say so, rather than filling the gap with a
  plausible-sounding guess. "Not stated in your note" is a *design feature*,
  not a fallback — see `good-summary-conformance.md`'s row on medication
  reasons for where this collides with an external checklist that wants
  the opposite.

This is a narrower ambition than several widely-cited health-literacy
recommendations ask for — explaining *why* a result is abnormal, what it
means for daily life, resolving apparent contradictions in a note. Those are
explicitly declined, not overlooked; see `good-summary-conformance.md` for
the full accounting of what this product does not do and why.

## Fidelity and readability are in tension, and the evidence says so

Every clinical-simplification study measured for both readability and
fidelity in the research this team reviewed found a tradeoff. One
ophthalmology-report simplification study found 91% of simplified sentences
were locally accurate, but only 86% of simplified reports retained *all*
critical information — accuracy per-sentence and completeness per-document
moved in different directions (brainstorm.v1.md §2.5). (RF)

This is why the pipeline is not one rewriting pass: extraction (`ground`)
happens on the pristine original, before any sentence is rewritten for
plain language, specifically so that shortening a sentence for readability
can never cost the fact that sentence was carrying. See
`design-rationale.md` for the full decision and its citations.

## Reading this folder

| Doc | Read this if you want to know... |
|---|---|
| [`design-rationale.md`](design-rationale.md) | *Why* the pipeline is shaped the way it is, decision by decision |
| [`good-summary-conformance.md`](good-summary-conformance.md) | Whether this product meets an external, literacy-focused summary standard |
| [`evidence-map.md`](evidence-map.md) | Exactly which claim rests on which source, and what that source does *not* prove |
| [`research-corpus.md`](research-corpus.md) | The underlying research memos and criteria doc themselves |

For *how* the pipeline works mechanically — the four-call sequence, the
data shapes, the request lifecycle — see [`../pipeline.md`](../pipeline.md)
and [`../architecture.md`](../architecture.md). This folder never repeats
that content; it only explains why it exists.
```

### 4.3 `docs/science/design-rationale.md` — decision-by-decision, RF/DJ/PD-labeled

Outline: one subsection per major decision, in pipeline order (ground → assemble/render → review → correct → cross-cutting), each ending with a labeled claim per PRD 15 §4.1's convention. This is the doc most directly answering "how evidence-backed is this."

Representative content (a sample of the full table this doc carries — the actual doc covers every row in this shape, not only the ones shown):

```markdown
# Design rationale, decision by decision

Labels follow PRD 15's convention: **RF** (Research Finding, cited — false
if the citation misrepresents the source), **DJ** (Design Judgment —
evidence, or its absence, reconciled with this repo's specific
constraints), **PD** (Proposed Default — a number picked as reasonable,
not measured). See `../uncalibrated-constants.md` for every PD-labeled
constant in one place, rather than re-deriving its rationale here.

## Grounding precedes generation

An LLM verifier bolted onto ungrounded prose largely rubber-stamps — one
study found 38 invalid plans passed out of ~92 approved
([arXiv:2310.08118](https://arxiv.org/pdf/2310.08118)). (RF) Up to 57% of
post-hoc citations a model produces for its own prior output are unfaithful
— the model did not actually use the source it later claims to cite
([arXiv:2412.18004](https://arxiv.org/abs/2412.18004)). (RF)

Extracting evidence-linked facts from the original note *before* any
generative rewriting, rather than rewriting first and checking after, is
this repo's own architectural response to both findings — no cited source
specifies this exact four-call architecture for an anonymous, single-shot,
no-clinician product; a person weighed the two RF findings above against
this repo's own constraints (no durable state, a ~270-second internal
deadline, no clinician reviewer) and decided the ordering. (DJ)

An independent research bundle, developed without contact with this
branch, converged on the identical inversion from a different, larger
literature (comparison-drive-research-bundle.v1.md §3) — two teams reasoning
from different citations landing on the same architecture is the strongest
evidence available that the inversion is right, though it is convergence
between two designs, not a validation of either against ground truth. (DJ,
noting the corroboration explicitly rather than treating it as RF)

## The ledger is clause-granular, not atomic

An atomization-before-generation intermediate step was shown to *worsen*
both major hallucinations and omissions in one clinical-documentation study
(Asgari et al.; see `evidence-map.md` for the Drive location). (RF)

This branch reads that finding as an argument *for* clause-level facts
("continue metoprolol 25 mg twice daily" as one fact, not four) rather than
finer atomization — over-atomizing pushes real judgment into
re-composition, which is where content gets dropped
(brainstorm.v1.md §2.5). (DJ) Worth stating plainly: the independent
research bundle names the identical risk from the identical citation and
then builds an atomize-then-generate pipeline anyway, hedged only as
"empirically ablate later" (comparison-drive-research-bundle.v1.md §4.2).
On this specific point, this repo's design judgment is the more internally
consistent reading of the shared evidence — not because the evidence is
stronger here, but because the conclusion drawn from it is not contradicted
by the same document that cites it. (DJ)

## Review never rewrites

A reviewer permitted to write becomes a fourth author capable of
reintroducing exactly the drift it exists to catch — no external study is
cited for this specific claim; it is this repo's own generalization from
the rubber-stamping finding above (arXiv:2310.08118) to *any* single LLM
call given both generation and correction authority over the same content.
(DJ, extending an RF rather than restating one)

## The corrector is diff-checked

The corrector is an LLM writer and can, in principle, reintroduce drift the
reviewer exists to catch — the design's own acknowledged soft spot
(brainstorm.v1.md §3.6). No cited research proposes a mitigation for this
specific risk; the deterministic diff check (`_verify_correction_diff`,
PRD 05 §4.6) asserting only named fields changed is a mechanical safeguard
invented for this repo, not derived from a paper. (DJ — no evidence,
product judgment)

## The forced-inference quotas were deleted

Requiring a reason for every medication, an urgency for every warning sign,
exactly three summary sentences, and exactly three questions were each
satisfied by fabrication whenever the source note was silent — this is a
root-cause diagnosis of an observed defect in this product's own prior
implementation, not a finding from external literature. (DJ — no evidence,
product judgment) The independent research bundle names the identical
root-cause diagnosis and the identical fix ("no quota completion") from
zero contact with this branch (comparison-drive-research-bundle.v1.md §3) —
recorded here as corroboration, not as promotion to RF, since neither team
is citing a published source for it.

## Readability is telemetry, not a gate

Readability formulas do not, by themselves, establish comprehension or
actionability (see `evidence-map.md`'s entry for "Assessing the Readability
of Medical Documents"). (RF) Treating a single before/after readability
score as diagnostic rather than a pass/fail condition is this repo's
response to that limit — a document could score well and still misinform,
or score poorly and still be accurate; a readability number is silent on
which. (DJ)

## Numeracy: no added label unless the source already has one

The rendering rule that a bare value never gains an added normal/abnormal/
elevated label, reference range, or severity coloring unless the cited fact
already states it (PRD 10's NUMERACY block) is this repo's own extension of
"translate, don't interpret" to numbers specifically. (DJ) This is one of
the rare points where the criteria doc *independently* arrives at the same
constraint from outside this design process — see
`good-summary-conformance.md`'s numeracy section for the convergence in
full; it is called out there rather than here because it is a conformance
finding, not a citation this repo is claiming credit for originating.
```

### 4.4 `docs/science/good-summary-conformance.md` — the criteria table, filled in

Outline: reproduce the criteria doc's own category structure (vendored per §4.6), with three added columns — `Does Juno do it?` (Yes/No/Partial/N/A), `Mechanism or reason`, `How to verify`. `Medical device?` is carried over from the source doc unfilled, flagged `[OPEN] — legal/regulatory judgment, not an engineering call this doc can make` rather than silently guessed at.

**How each row is verified, stated once, up front, so the table is falsifiable rather than aspirational:**

```markdown
## How to read the "Does Juno do it?" column

Every row was checked against one of three kinds of evidence, named in
"How to verify":

1. **A prompt-text grep** — the rule is a literal instruction in
   `backend/care_plan/prompts/_style_rules.txt`, `assemble_and_render.txt`,
   or another prompt file. Falsify by reading the named file; the rule
   either is or isn't there, word for word.
2. **A schema/code fact** — the rule maps to a Pydantic field, a
   deterministic check function, or a rendered UI element. Falsify by
   reading the named file/function.
3. **A PRD citation** — the rule is a documented, settled design decision
   not yet reducible to a single grep (e.g., a whole information-
   architecture choice). Falsify by reading the cited PRD section.

No row in this table is marked Yes on the strength of this document's own
prose alone — every Yes/Partial/No cites a file, a function, or a PRD
section a reader can independently open.
```

Representative rows (the full doc carries every row of the source criteria table in this shape — this is a representative sample chosen to show the range, including the three tensions and the one convergence the task specifically calls out):

```markdown
| Category | Feature | Priority | Does Juno do it? | Mechanism / reason | How to verify |
|---|---|---|---|---|---|
| Language & Style | Simple/everyday words | Must | **Yes** | LANGUAGE RULES in `_style_rules.txt`; enforced at render (assemble_and_render, correct) | Read `backend/care_plan/prompts/_style_rules.txt` |
| Language & Style | Active voice | Must | **Yes** | `_style_rules.txt`: "Active voice. Address the patient as 'you.'" | Same file |
| Language & Style | No acronyms/abbreviations | Must | **Yes** | `_style_rules.txt`: "Expand every abbreviation." Abbreviation list also fed into grounding to aid extraction from dense source text | `_style_rules.txt`; PRD 03 §3.3 |
| Numeracy | Numbers explained qualitatively alongside the number (e.g. "1 out of 10,000") | Should | **No** | Would require adding a qualitative frame the source note doesn't state — direct conflict with "never invent... beyond what a fact states." Declined by design, not an oversight | `_style_rules.txt` LANGUAGE RULES; absence confirmed by grep for any such rendering rule |
| Numeracy | Percentages expressed as frequencies | Should | **No** | PRD 10's NUMERACY block explicitly *forbids* "a percentage-to-frequency (or reverse) reframe" as a banned rendering transformation — this is a deliberate fidelity guard against exactly this feature | PRD 10 §4 (NUMERACY block text) |
| Numeracy | Evaluative labels alongside values, only when the source already has labels | Could — "has to check if it would be a medical interpretation... only when the source already has labels" | **Yes (convergence)** | PRD 10's NUMERACY block forbids adding a normal/abnormal/elevated label the fact doesn't itself state — independently arrived at, matches the criteria doc's own caveat exactly | PRD 10 §4; see `design-rationale.md`'s numeracy section for the convergence discussion |
| Extraction of information | Remove or hide distracting content (repeated med lists, billing codes, admin detail) | Must | **No — live design disagreement** | Global branch principle is "remove nothing... `low_priority` demotes, never deletes" (brainstorm.v1.md §2 row 39). The criteria doc's Must and this repo's settled decision are opposite answers to the same question; both are defensible, and this repo ships the "keep, demote" side | brainstorm.v1.md §2, "remove nothing" row; PRD 08 §4 (`low_priority` card) |
| Explaining meaning/purpose | Explain reason of a medication | Must | **No — live design disagreement** | Renders the sentinel "Not stated in your note." when the source is silent, rather than fabricating a reason to satisfy the Must. PRD 04 explicitly deleted the mandatory-reason rule as a fabrication cause (brainstorm.v1.md §2 row 34) | PRD 04 §4.1 (sentinel); PRD 13 (moves the sentinel to the render layer, same patient-visible behavior) |
| Faithfulness/safety | No adding, removing, exaggerating, or diagnosing | Must | **Yes** | This is the core design philosophy end to end: grounding's verbatim-quote check, assembly's citation-existence check, review's fidelity pass, the corrector's diff check. The single PII exception (names) is the only sanctioned departure from source-fidelity, and it is bounded and logged | brainstorm.v1.md §2 ("global principle: remove nothing... PII is the single exception"); PRD 03/04/05 in full |
| Assessment of the output | Safety (assessment) | Must | **No** | No release gate exists at all — `review()`/`correct()` are both explicitly non-fatal by design (PRD 05 §4.8); a document that fails every check silently ships anyway, with no signal to the reader. This is the sharpest asymmetry against the independent research bundle's design (comparison-drive-research-bundle.v1.md §4.7) | PRD 05 §4.8; comparison doc §4.7 |
| Personalization to health literacy | Offer 2-3 levels of language/explanation | Should | **No** | Not implemented; one fixed output for every reader | Absence confirmed — no branching render path exists anywhere in `assemble_and_render.txt` or the frontend |
```

`[OPEN]` recorded once for the whole table rather than per-row: **`Medical device?`** is left exactly as blank as the source doc for every row — filling it in requires a regulatory/legal judgment about FDA SaMD classification this PRD is not positioned to make, and guessing at it in either direction would be worse than an honest blank. Flagged in §8 as an owner-only task.

### 4.5 `docs/science/evidence-map.md` — the evidence ledger and its limits

Outline: (1) the evidence-to-design traceability table, adapted from `07-final-evidence-backed-pipeline.md`'s pattern of the same name; (2) unresolved evidence gaps, organized as "what is not evidenced" and "what would have to be measured to close it," which is the section that most protects a future reader from over-trusting the system.

Representative content:

```markdown
# Evidence map

## Evidence-to-design traceability

| Claim | Source | What it establishes | What it does NOT establish | Used in |
|---|---|---|---|---|
| An LLM verifier bolted onto ungrounded prose largely rubber-stamps (38/92 invalid plans approved) | [arXiv:2310.08118](https://arxiv.org/pdf/2310.08118) | A verifier without grounded, per-claim evidence performs poorly at catching fabrication in the studied setting | Nothing about *this* pipeline's specific reviewer, which is grounded (reads a fact ledger, not free prose) — cited as motivation for the architecture, not as a measurement of this reviewer | `design-rationale.md` "Grounding precedes generation," "Review never rewrites" |
| Up to 57% of post-hoc citations are unfaithful to the source the model claims to have used | [arXiv:2412.18004](https://arxiv.org/abs/2412.18004) | Attribution generated *after* a claim is made is unreliable in the studied setting | Not this pipeline's own attribution mechanism (`unit_id` + verbatim quote is checked *before* the claim is trusted, not after) — cited as the general risk grounding-first avoids | `design-rationale.md` "Grounding precedes generation" |
| Enumerate-then-verify raised omission detection to 24.6% at 2.7% false alarms, vs. 0.50–0.63 AUC (near chance) for open-ended "is anything missing" | [arXiv:2608.31016](https://arxiv.org/html/2608.31016v1) | Omission detection is a genuinely hard, near-chance problem for open-ended LLM judging, and enumerate-then-verify is a real, if partial, improvement | 24.6% is far from complete — this is the ceiling this pipeline's `review()` coverage walk is up against, not a demonstrated floor this pipeline achieves | PRD 05 §1/§4.3 (review's JOB 2 shape); PRD 11 (consuming the coverage signal, R1) |
| An atomization-before-generation step worsened both major hallucinations and omissions in one clinical-documentation study | Asgari et al. (Drive; see `research-corpus.md` for the vendored summary and location) | In the studied setting (transcript → clinician-note generation), a specific atomization intermediate made both error types worse, not better | Whether clause-level (not fully atomic) extraction shares this risk — this pipeline's own design judgment (`design-rationale.md`) reads the finding as an argument *for* coarser granularity, which the study itself does not test | `design-rationale.md` "The ledger is clause-granular" |
| A rubric-driven LLM judge (PDSQI-9) can align with clinicians in a defined provider-facing setting; best single judge ICC 0.818 beat the best multi-agent configuration (ICC 0.768) | Croxford et al. (Drive; see `research-corpus.md`) | A well-specified single judge can be reliable in a *provider-facing* setting with *validated* rubric items | This pipeline runs no LLM judge of this kind at all — the ICC figure does not transfer to a patient-facing, unvalidated-rubric, no-judge design. Cited here only to explain why this pipeline doesn't attempt a document-level judge, not as evidence for anything this pipeline does | `design-rationale.md`, discussion of why no advisory judge was added (see also comparison doc §4.6, §6) |
| Readability formulas do not, by themselves, establish comprehension or actionability | "Assessing the Readability of Medical Documents" (Google Doc; see `research-corpus.md`) | A readability score is not a proxy for whether a reader understood or could act on the content | Nothing about what *would* measure comprehension — that requires a study this pipeline does not run | `design-rationale.md` "Readability is telemetry, not a gate" |
```

```markdown
## What is not evidenced

This section exists so a future reader does not mistake "reasoned" for
"measured." Every item below is a real, disclosed gap, not a hidden one.

| Gap | Why it matters | What would close it |
|---|---|---|
| Extraction recall on raw, abbreviated clinical text (vs. pre-simplified text) | No published work measures this at all — brainstorm.v1.md §5 names it as "a real gap in the literature, not just in our knowledge" | Run grounding over a set of real notes; score the ledger against a hand-annotated fact list (protocol specified, PRD 03 §8 — not run) |
| The reviewer's actual catch rate against injected errors | Review is non-fatal by design (PRD 05 §4.8); a reviewer that silently rubber-stamps everything is indistinguishable in production from one that genuinely finds nothing wrong, unless this is measured | PRD 05 §7.5's injected-error protocol (dropped medication, wrong dose, invented follow-up; ~30 perturbed cases) — specified, not run |
| The questions guard (no smuggled clinical claim) | `questions` is the one fully ungrounded surface in the output; the interrogative-form constraint is reasoned, not tested | A fixture set of notes with known gaps; assert no generated question presupposes a fact absent from the ledger (brainstorm.v1.md §5) |
| Line-ID attribution under realistic OCR noise | The attribution literature this design draws on is almost entirely clean digital text (Wikipedia, PubMed abstracts, clean EHR exports), not OCR'd scans. The line-ID approach is reasoned from that literature, not validated on this product's actual input distribution | Inject realistic OCR noise into a handful of notes; compare how often line-ID, offset, and quote-only attribution still resolve to the right source line (brainstorm.v1.md §5, "half a day") |
| Whether the soundness-over-completeness inversion is the right tradeoff in production | It was a reasoned, deliberate call (PRD 05 §4.7), not a mistake — but until observed, it is unfalsifiable | PRD 11's coverage-signal logging (the discarded `review_result.coverage` field, now logged) makes the omission rate observable across real runs, once the pipeline actually runs against real traffic — the logging exists; the observation period has not happened |
| Every constant in `../uncalibrated-constants.md` | `_MAX_PII_TOKEN_DELTA=4`, `_QUOTE_MIN_LENGTH=12`, `_QUOTE_LONG_WORD_MIN_LENGTH=7`, `GLOSSARY_CURATION_TIMEOUT_S=20`, `_MAX_LONG_EDGE_PX=4096`, `_UNIT_WORD_MAX_LENGTH=15` — all PD-labeled, all reasoned, none calibrated against real data | See that file's own "how it would be calibrated" column, per constant — this doc does not duplicate it |
| Asgari et al.'s transfer to this exact task | The strongest clinical-safety evidence studied transcript → clinician-note generation. `simplify-med` transforms a heterogeneous, sometimes-OCR'd, clinician-*authored* upload into a patient-facing artifact — a different input modality and a different generation task | No available study closes this gap; it is a limitation of the evidence base, not something this product can measure its way out of alone |
| PDSQI-9's transfer to this product | Provider-facing, dataset/site-limited (Croxford et al.'s own stated limitations) | Would require a patient-facing rubric, validated on this product's own output distribution — not attempted; this pipeline runs no LLM judge at all |
```

### 4.6 The vendoring decision (`docs/science/research-corpus.md`)

**Decision: vendor a condensed, in-repo summary of the team's own eight Drive memos, the comparison doc's key sections, and the criteria doc's full table — never vendor the third-party research papers themselves.**

The reasoning, stated as a tradeoff rather than a reflex:

- **Against citing Drive URLs only.** A reader without Drive access — which is most future readers of this open-ended, machine-managed repo — gets nothing from a bare link. Worse, the scratchpad copy this PRD itself was written from is explicitly ephemeral (the session announcement mid-task: "the scratchpad directory... is no longer available"), and the Drive folder's own access permissions are not this repo's to guarantee over time. A citation to a source nobody can open is not evidence documentation — it's a promise of evidence documentation that expires whenever a permission changes.
- **Against vendoring the papers themselves.** AgenticSum, Asgari et al., Croxford et al., the Fact-Controlled Diagnosis paper, and the AHRQ toolkit are third-party copyrighted works. This repo has no license to redistribute them, and doing so would be a real legal exposure for a documentation improvement that doesn't need it — every substantive claim this doc family makes about those papers is already extracted, quoted, and cited by page/section in the Drive memos and in this PRD's own evidence map. A reader needs the *claim* and where to verify it, not a personal copy of the PDF.
- **What tips the team's own memos and the criteria doc the other way.** These are not third-party IP — they are this team's own synthesis, written specifically to inform this product, by people with authorship rights over them. `good-summary-conformance.md` (§4.4) *is* the criteria doc's table with one column filled in; vendoring the source table it's built from is not optional if the conformance doc is to be self-contained and falsifiable without a live Google Doc link. The eight Drive memos are the only record, anywhere, of the actual page/section citations this PRD's evidence map depends on (e.g., "Asgari et al., pp. 4–7") — losing access to them would silently downgrade every RF-labeled claim in `design-rationale.md` to an unverifiable assertion.

Concrete form for `research-corpus.md`:

```markdown
# Research corpus

This repo vendors a condensed summary of the team's own research memos and
the good-summary criteria doc — not the third-party papers they cite. See
"Why vendor, and why only this much" below.

## Team memos (condensed, vendored)

One subsection per memo, ~1 paragraph each, capturing its decision and its
own stated evidence boundary — not a full reproduction. Each links to the
original Drive file for anyone with access who wants the full memo.

### 00 — Component map
[condensed summary — the six-component decomposition, and its own
explicit "repository observations vs. research findings vs.
recommendations" framing]
Original: [Drive link]

### 03 — Grounding and provenance
[condensed summary — atomic claims, source edges, the Asgari
atomization-risk discussion in full, since it's load-bearing for
`design-rationale.md`]
Original: [Drive link]

[... 01, 02, 04, 05, 06, 07 following the same pattern ...]

## The good-summary criteria doc (vendored in full)

The complete original table — Category, Feature, Details, Priority,
Medical device?, and the original (empty) "Does Juno do it?" column — is
reproduced verbatim in `good-summary-conformance.md`'s appendix, with the
filled-in conformance columns added alongside, not in place of, the
original. Original: [Google Doc link].

## Third-party research papers — cited, never vendored

| Paper | Where it's cited from | How to obtain it |
|---|---|---|
| AgenticSum | Drive-hosted PDF, linked from memo 00/04/07's Sources | [Drive link] — access-gated; no public arXiv identifier found during this research pass |
| Asgari et al. (clinical safety / hallucination + omission taxonomy) | Drive-hosted PDF, linked from memos 03/04/05 | [Drive link] — same caveat |
| Croxford et al. / PDSQI-9 | Drive-hosted PDF, linked from memo 04 | [Drive link] — same caveat |
| Fact-Controlled Diagnosis of Hallucinations | Drive-hosted PDF, linked from memo 03 | [Drive link] — same caveat |
| AHRQ Health Literacy Universal Precautions Toolkit | Drive-hosted PDF, linked from memo 02/07 | [Drive link] — publicly available from ahrq.gov independent of this Drive copy |
| Post-hoc attribution unfaithfulness | [arXiv:2412.18004](https://arxiv.org/abs/2412.18004) | Public, durable |
| LLM verifier rubber-stamping | [arXiv:2310.08118](https://arxiv.org/pdf/2310.08118) | Public, durable |
| Enumerate-then-verify omission detection | [arXiv:2608.31016](https://arxiv.org/html/2608.31016v1) | Public, durable |

**`[OPEN]`** — four of the seven third-party sources above are known to
this repo only via a Drive-hosted copy with no public arXiv/DOI identifier
recorded anywhere in the memos. If any of them do have a public preprint or
DOI, adding it here would remove the single-point-of-failure risk the Drive
link carries. Checking this requires either Drive access (to read the PDF's
own title page/DOI) or a literature search this PRD did not perform — see
§8.
```

## 5. API Change Summary

N/A. This PRD produces no code, no schema, no endpoint. `backend/` is unaffected.

## 6. Frontend Change Summary

N/A. `frontend/` is unaffected. Nothing in this doc family is patient-facing — like the evidence ledger itself (brief §3.10), the scientific documentation exists for engineers, reviewers, and the owner, never for the anonymous visitor using the product.

## 7. Testing

There is no code to test; being proportionate about what "testing documentation honesty" means, matching PRD 15 §7's posture rather than inventing heavier ceremony for a lighter artifact:

- **Every citation must resolve.** A one-time, human-run check when each doc is authored (and again if a doc is substantially revised): open every link in the doc — arXiv URLs (durable, checkable indefinitely), Drive URLs (checkable today, flagged in §4.6 as a durability risk precisely because they may not stay checkable), and in-repo cross-references (`../pipeline.md`, `../uncalibrated-constants.md`). No tooling is proposed for this — a link-checker script would need network access to Drive and would produce noise on transient failures, for a five-file doc set that changes rarely.
- **Every RF-labeled claim carries an inline citation, checkable by `grep`.** `grep -n "(RF)" docs/science/*.md` finds every RF claim; a reviewer confirms each has a link in the same sentence or the immediately preceding one. This is the same "human review habit, not tooling" posture PRD 15 §7 already established for the labeling convention generally — this PRD does not invent a stricter standard for its own docs than PRD 15 set for the whole branch.
- **Every PD-labeled constant points at the register, not at a re-derived rationale.** A `design-rationale.md` sentence that names a constant (e.g., `_MAX_PII_TOKEN_DELTA`) must link to `../uncalibrated-constants.md` rather than repeating "chosen to comfortably cover a full name..." in its own words — checkable by reading each PD-tagged sentence for a link, not by tooling.
- **The conformance table's falsifiability is the check, not a separate test.** §4.4 already specifies that every row names a file, function, or PRD section a reader can open — the "test" is a reviewer picking five rows at random and confirming the cited evidence actually says what the row claims. No row should ever be marked Yes/No/Partial on the strength of this document's own say-so.
- **No claim of measured fidelity, comprehension, or safety anywhere in this doc family.** Given the clinical-fidelity evaluation suite is out of scope everywhere per the initiative's locked decisions, a lightweight human check on any substantial revision: grep for `"proven"`, `"validated"`, `"guaranteed"`, `"demonstrates that patients"` used without an adjacent hedge (`"reasoned"`, `"not measured"`, `"in the studied setting"`) — a smell test for promotional drift, not a gate. This is the single most important honesty check in this PRD, because it's the one a well-meaning future editor is most likely to violate by accident while "cleaning up" the prose.
- **Ownership for keeping the conformance table current.** Per PRD 15's own maintenance-rule pattern for its register: any future PRD that changes pipeline behavior touching a row in `good-summary-conformance.md` (e.g., a future PRD implementing 13's `why: str | None` change, or any PRD adding a numeracy feature) updates that row's `Does Juno do it?`/mechanism/verification as part of its own scope — stated here so it isn't reinvented per-PRD, exactly as PRD 15 §4.3 states its own maintenance rule once rather than per-constant.

## 8. Manual Intervention Required From You

- **Decide the `Medical device?` column.** Every row in `good-summary-conformance.md` leaves this blank, matching the source doc — filling it in is a regulatory/legal judgment about FDA SaMD classification (or equivalent) this PRD is not positioned to make.
- **Approve the vendoring decision (§4.6)** before `dev-tasks`/`dev-code` authors `research-corpus.md` — specifically, confirm no licensing concern with condensing/summarizing (not reproducing verbatim, except the criteria doc's own table, which the team authored) the eight Drive memos into this repo.
- **Check whether the four Drive-only third-party papers (AgenticSum, Asgari et al., Croxford et al., Fact-Controlled Diagnosis) have a public arXiv/DOI identifier** — reduces the durability risk §4.6 flags for those four specifically; requires either Drive access to read the PDFs' own metadata or a literature search this PRD did not perform.
- **Decide `docs/uncalibrated-constants.md`'s authorship** between 16 and 17 (§9) — this PRD's `evidence-map.md` assumes the file exists and links to it; PRD 15 specifies its content in full but does not assign who actually creates the file.
- **Have `dev-tasks`/`dev-code` author the five files** from this PRD's §4 content once approved — this PRD's own scope ends at the PRD, per its own charter.
- No environment variables, credentials, deploys, or console access needed anywhere in this PRD.

## 9. Open Questions & Decisions

- `[RESOLVED: five files under docs/science/ — README.md, design-rationale.md, good-summary-conformance.md, evidence-map.md, research-corpus.md — one per distinct audience, per §4.1.]`
- `[RESOLVED: docs/science/ (not docs/agent_files/...) is the location, matching PRD 15's identical reasoning for docs/uncalibrated-constants.md — durable reference material, not a dated design-session record.]`
- `[RESOLVED: vendor the team's own eight Drive memos (condensed) and the criteria doc (in full) into docs/science/research-corpus.md and good-summary-conformance.md respectively; never vendor the third-party research papers themselves — cite those by URL only, with the durability risk disclosed explicitly for the four Drive-only sources.]` — §4.6.
- `[RESOLVED: the three tensions with the criteria doc (medication reason, remove-nothing vs. remove-distracting-content, and the numeracy convergence) are recorded as live disagreements in good-summary-conformance.md, both positions stated, with the shipped answer named — not adjudicated by this PRD.]` — §4.4.
- `[RESOLVED: the "Medical device?" column stays blank, flagged [OPEN] for the owner, rather than this PRD guessing at a regulatory classification.]`
- `[RESOLVED: the two proposals are not in conflict — they operate at different granularities. Inline (16's proposal — "— see X for why" / "— see X for the exact mechanism") is the default for a claim-level cross-reference attached to a specific sentence. This family's own blockquote-style pointer form survives, narrowed to the orientation-signpost role its own §4.2 README sample already demonstrates: a document/section-level "here's where the whole other half of this topic lives" pointer, used once per document or major section, never mid-prose for an individual claim. Reconciled jointly with PRD 16 — see 16 §3 for the same decision stated from its side.]`
- `[OPEN] — who creates and owns docs/uncalibrated-constants.md.` PRD 15 §4.3 fully specifies its content and location but assigns creation to "a `dev-tasks`/`dev-code` documentation task" without naming which PRD's task list that falls under. This PRD's `evidence-map.md` and `design-rationale.md` both link to it as an existing artifact; 16's mechanism docs are equally likely to want to link to it (PRD 15 §4.3: "PRD 16 should link to it from `docs/pipeline.md`"). Proposed default, not yet agreed: 16 creates it (it sits beside 16's other durable docs), 17 only links to it — but this needs 16's author to confirm, not this PRD to assert unilaterally.
- `[OPEN] — whether to pursue public arXiv/DOI identifiers for the four Drive-only third-party papers`, per §4.6/§8. Would reduce, not eliminate, the durability risk on those four sources specifically; not performed as part of this PRD since it requires either Drive access or a literature search outside this PRD's read-only, repo-scoped research.
- `[OPEN] — whether good-summary-conformance.md needs a re-verification pass once PRDs 10–16 actually land as code`, since they are currently design-only and several rows in the sample table (§4.4) cite PRD sections rather than landed code (e.g., the numeracy convergence row cites PRD 10, not yet implemented). §7's maintenance-ownership rule assigns this to whichever future PRD changes the relevant behavior, but no PRD has explicitly picked this up as "my job" the way, e.g., PRD 15's register maintenance rule is stated to bind future PRDs generally — worth the owner confirming this is understood as binding once 10–16 move from design to implementation.
- `[DEFERRED] — any tooling, CI check, or linter enforcing citation validity, RF/DJ/PD tagging, or promotional-language drift in docs/science/.` Matches PRD 15 §7's explicit stance: a mechanical check for prose discipline produces more noise than signal at this scale, and inventing it would be exactly the process ceremony the initiative's locked decisions warn against.
