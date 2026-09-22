# Good-summary criteria conformance

This file reproduces the team's own "good summary" criteria doc's category
structure (an adaptation of AHRQ/PEMAT into a feature checklist — see
`research-corpus.md`), with three added columns filled in against the real,
current pipeline: `Does Juno do it?`, `Mechanism or reason`, `How to
verify`. The source doc's `Medical device?` column is carried over, but
every row's cell carries the explicit marker `Not assessed — requires
regulatory/legal judgment (see §8)` rather than a blank: FDA SaMD
classification is a regulatory/legal judgment this documentation is not
positioned to make, and saying so plainly is more honest than a silent
blank a reader could mistake for an oversight. Determining the actual
classification remains an owner-only task (PRD 17 §8).

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

## Conformance table

| Category | Feature | Priority | Medical device? | Does Juno do it? | Mechanism / reason | How to verify |
|---|---|---|---|---|---|---|
| Language & Style | Simple/everyday words | Must | Not assessed — requires regulatory/legal judgment (see §8) | **Yes** | LANGUAGE RULES in `_style_rules.txt`; enforced at render (assemble_and_render, correct) | Read `backend/care_plan/prompts/_style_rules.txt` |
| Language & Style | Active voice | Must | Not assessed — requires regulatory/legal judgment (see §8) | **Yes** | `_style_rules.txt`: "Active voice. Address the patient as 'you.'" | Read `backend/care_plan/prompts/_style_rules.txt` |
| Language & Style | No acronyms/abbreviations | Must | Not assessed — requires regulatory/legal judgment (see §8) | **Yes** | `_style_rules.txt`: "Expand every abbreviation." Abbreviation list also fed into grounding to aid extraction from dense source text | Read `backend/care_plan/prompts/_style_rules.txt`; PRD 03 §4.7 |
| Numeracy | Numbers explained qualitatively alongside the number (e.g. "1 out of 10,000") | Should | Not assessed — requires regulatory/legal judgment (see §8) | **No** | Would require adding a qualitative frame the source note doesn't state — direct conflict with "never invent... beyond what a fact states." Declined by design, not an oversight | `_style_rules.txt` LANGUAGE RULES; absence confirmed by grep for any such rendering rule |
| Numeracy | Percentages expressed as frequencies | Should | Not assessed — requires regulatory/legal judgment (see §8) | **No** | PRD 10's NUMERACY block explicitly *forbids* "a percentage-to-frequency (or reverse) reframe" as a banned rendering transformation — this is a deliberate fidelity guard against exactly this feature | PRD 10 §4 (NUMERACY block text) |
| Numeracy | Evaluative labels alongside values, only when the source already has labels | Could — "has to check if it would be a medical interpretation... only when the source already has labels" | Not assessed — requires regulatory/legal judgment (see §8) | **Yes (convergence)** | PRD 10's NUMERACY block forbids adding a normal/abnormal/elevated label the fact doesn't itself state — independently arrived at, matches the criteria doc's own caveat exactly | PRD 10 §4; see `design-rationale.md`'s numeracy section for the convergence discussion |
| Extraction of information | Remove or hide distracting content (repeated med lists, billing codes, admin detail) | Must | Not assessed — requires regulatory/legal judgment (see §8) | **No — live design disagreement** | Global branch principle is "remove nothing... `low_priority` demotes, never deletes" (brainstorm.v1.md §2 row 39). The criteria doc's Must and this repo's settled decision are opposite answers to the same question; both are defensible, and this repo ships the "keep, demote" side | brainstorm.v1.md §2, "remove nothing" row; PRD 08 §4 (`low_priority` card) |
| Explaining meaning/purpose | Explain reason of a medication | Must | Not assessed — requires regulatory/legal judgment (see §8) | **No — live design disagreement** | Renders the sentinel "Not stated in your note." when the source is silent, rather than fabricating a reason to satisfy the Must. PRD 04 explicitly deleted the mandatory-reason rule as a fabrication cause (brainstorm.v1.md §2 row 34) | PRD 04 §4.1 (sentinel); PRD 13 (moves the sentinel to the render layer, same patient-visible behavior) |
| Faithfulness/safety | No adding, removing, exaggerating, or diagnosing | Must | Not assessed — requires regulatory/legal judgment (see §8) | **Yes** | This is the core design philosophy end to end: grounding's verbatim-quote check, assembly's citation-existence check, review's fidelity pass, the corrector's diff check. The single PII exception (names) is the only sanctioned departure from source-fidelity, and it is bounded and logged | brainstorm.v1.md §2 ("global principle: remove nothing... PII is the single exception"); PRD 03/04/05 in full |
| Assessment of the output | Safety (assessment) | Must | Not assessed — requires regulatory/legal judgment (see §8) | **No** | No release gate exists at all — `review()`/`correct()` are both explicitly non-fatal by design (PRD 05 §4.8); a document that fails every check silently ships anyway, with no signal to the reader. This is the sharpest asymmetry against the independent research bundle's design (comparison-drive-research-bundle.v1.md §4.7) | PRD 05 §4.8; comparison doc §4.7 |
| Personalization to health literacy | Offer 2-3 levels of language/explanation | Should | Not assessed — requires regulatory/legal judgment (see §8) | **No** | Not implemented; one fixed output for every reader | Absence confirmed — no branching render path exists anywhere in `assemble_and_render.txt` or the frontend |

## Appendix: original criteria doc (unmodified)

The complete original table this repo's criteria doc supplies — Category,
Feature, Details, Priority, Medical device?, and the original (empty)
"Does Juno do it?" column — reproduced verbatim, per PRD 17 §4.6's
vendoring decision. This is the row set PRD 17's own text quotes; a Google
Doc URL is deliberately not linked here (§4.6). `Details` and `Medical
device?` cells below are marked as not captured where PRD 17's quoted
excerpt of the source doc did not include that cell's text — this appendix
does not fabricate detail text PRD 17 itself never saw.

| Category | Feature | Details | Priority | Medical device? | Does Juno do it? |
|---|---|---|---|---|---|
| Language & Style | Simple/everyday words | *not captured in PRD 17's quoted excerpt* | Must | *not captured in PRD 17's quoted excerpt* | |
| Language & Style | Active voice | *not captured in PRD 17's quoted excerpt* | Must | *not captured in PRD 17's quoted excerpt* | |
| Language & Style | No acronyms/abbreviations | *not captured in PRD 17's quoted excerpt* | Must | *not captured in PRD 17's quoted excerpt* | |
| Numeracy | Numbers explained qualitatively alongside the number (e.g. "1 out of 10,000") | *not captured in PRD 17's quoted excerpt* | Should | *not captured in PRD 17's quoted excerpt* | |
| Numeracy | Percentages expressed as frequencies | *not captured in PRD 17's quoted excerpt* | Should | *not captured in PRD 17's quoted excerpt* | |
| Numeracy | Evaluative labels alongside values, only when the source already has labels | *not captured in PRD 17's quoted excerpt* | Could — "has to check if it would be a medical interpretation... only when the source already has labels" | *not captured in PRD 17's quoted excerpt* | |
| Extraction of information | Remove or hide distracting content (repeated med lists, billing codes, admin detail) | *not captured in PRD 17's quoted excerpt* | Must | *not captured in PRD 17's quoted excerpt* | |
| Explaining meaning/purpose | Explain reason of a medication | *not captured in PRD 17's quoted excerpt* | Must | *not captured in PRD 17's quoted excerpt* | |
| Faithfulness/safety | No adding, removing, exaggerating, or diagnosing | *not captured in PRD 17's quoted excerpt* | Must | *not captured in PRD 17's quoted excerpt* | |
| Assessment of the output | Safety (assessment) | *not captured in PRD 17's quoted excerpt* | Must | *not captured in PRD 17's quoted excerpt* | |
| Personalization to health literacy | Offer 2-3 levels of language/explanation | *not captured in PRD 17's quoted excerpt* | Should | *not captured in PRD 17's quoted excerpt* | |

A future revision with access to the full source table (§9 of PRD 17)
extends both this appendix and the conformance table above with any
remaining rows; this task does not invent rows PRD 17 itself never saw.
