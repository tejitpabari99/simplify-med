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

The NUMERACY block is landed: `backend/care_plan/prompts/_style_rules.txt`
carries it today (PRD 10), enforced at both `assemble_and_render` and
`correct` (content-regression tests assert `"NUMERACY" in _STYLE_RULES` and
in both prompts, `backend/tests/care_plan/test_pipeline_prompts.py`).
