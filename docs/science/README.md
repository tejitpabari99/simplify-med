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
  didn't assign. (DJ) See `design-rationale.md` for the full reasoning
  and its citations.
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
| [design-rationale.md](design-rationale.md) | *Why* the pipeline is shaped the way it is, decision by decision |
| [good-summary-conformance.md](good-summary-conformance.md) | Whether this product meets an external, literacy-focused summary standard |
| [evidence-map.md](evidence-map.md) | Exactly which claim rests on which source, and what that source does *not* prove |
| [research-corpus.md](research-corpus.md) | The underlying research memos and criteria doc themselves |

> For *how* the pipeline works mechanically — the four-call sequence, the
> data shapes, the request lifecycle — see [pipeline.md](../pipeline.md)
> and [architecture.md](../architecture.md). This folder never repeats
> that content; it only explains why it exists.
