# Research corpus

This repo vendors a condensed summary of the team's own research memos and
the good-summary criteria doc — not the third-party papers they cite. See
"Why vendor, and why only this much" in PRD 17 §4.6 for the reasoning
(against citing Drive URLs only; against vendoring the papers themselves;
what tips the team's own memos and the criteria doc the other way).

## Team memos (condensed, vendored)

One subsection per memo, ~1 paragraph each, capturing its decision and its
own stated evidence boundary — not a full reproduction. Each links to the
original Drive file for anyone with access who wants the full memo. Memos
00 and 03 are condensed below from PRD 17's own quoted content; memos 01,
02, 04, 05, 06, and 07 are left as explicitly flagged placeholders — this
task-authoring pass has no Drive access to condense memos PRD 17's own text
never quoted, and this doc does not fabricate summaries for them (PRD 17
§8, item 4).

### 00 — Component map

The six-component decomposition of the pipeline, and its own explicit
"repository observations vs. research findings vs. recommendations"
framing — the same three-way split this doc family's RF/DJ/PD vocabulary
(PRD 15 §4.1) formalizes for this branch's own prose.

Original: [Drive link]

### 01 — [topic not captured — no Drive access from this task]

[condensed summary not yet authored — no Drive access from this task; see §8]

Original: [Drive link]

### 02 — [topic not captured — no Drive access from this task]

[condensed summary not yet authored — no Drive access from this task; see §8]

Original: [Drive link]

### 03 — Grounding and provenance

Atomic claims, source edges, and the Asgari atomization-risk discussion in
full — load-bearing for `design-rationale.md`'s "The ledger is
clause-granular, not atomic" section, which reads the same finding as an
argument for clause-level (not fully atomic) extraction.

Original: [Drive link]

### 04 — [topic not captured — no Drive access from this task]

[condensed summary not yet authored — no Drive access from this task; see §8]

Original: [Drive link]

### 05 — [topic not captured — no Drive access from this task]

[condensed summary not yet authored — no Drive access from this task; see §8]

Original: [Drive link]

### 06 — [topic not captured — no Drive access from this task]

[condensed summary not yet authored — no Drive access from this task; see §8]

Original: [Drive link]

### 07 — [topic not captured — no Drive access from this task]

[condensed summary not yet authored — no Drive access from this task; see §8]

Original: [Drive link]

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
| Asgari et al. (clinical safety / hallucination + omission taxonomy) | Drive-hosted PDF, linked from memos 03/04/05 | [Drive link] — access-gated; no public arXiv identifier found during this research pass |
| Croxford et al. / PDSQI-9 | Drive-hosted PDF, linked from memo 04 | [Drive link] — access-gated; no public arXiv identifier found during this research pass |
| Fact-Controlled Diagnosis of Hallucinations | Drive-hosted PDF, linked from memo 03 | [Drive link] — access-gated; no public arXiv identifier found during this research pass |
| AHRQ Health Literacy Universal Precautions Toolkit | Drive-hosted PDF, linked from memo 02/07 | [Drive link] — publicly available from ahrq.gov independent of this Drive copy |
| Post-hoc attribution unfaithfulness | [arXiv:2412.18004](https://arxiv.org/abs/2412.18004) | Public, durable |
| LLM verifier rubber-stamping | [arXiv:2310.08118](https://arxiv.org/pdf/2310.08118) | Public, durable |
| Enumerate-then-verify omission detection | [arXiv:2608.31016](https://arxiv.org/html/2608.31016v1) | Public, durable |

**`[RESOLVED]`** — four of the seven third-party sources above (AgenticSum,
Asgari et al., Croxford et al., Fact-Controlled Diagnosis) are known to this
repo only via a Drive-hosted copy; no public arXiv/DOI identifier for any
of them was found during this research pass, and no literature search is
performed as part of this PRD. The Drive copy is the source of record for
these four. The single-point-of-failure risk that carries is acknowledged
and recorded here, not hidden — adding a public identifier later would
remove it and is a welcome improvement, but it is unowned and not a
blocking question for this doc family. See PRD 17 §8.
