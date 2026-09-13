# PRD 14 — Merge Provenance

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here). Recommendation source: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/comparison-drive-research-bundle.v1.md` §5 R6 ("A `merged: bool` flag on assembled items. Cost M. ADOPT-REDUCED, low priority.").

Branch: `docs/fidelity-concision-brief`.

Depends on: 01 (schema — the six item models this PRD would have touched, and the precedent that a default/self-reported value must earn its place), 04 (`assemble_and_render.txt`'s MERGE paragraph and `_verify_assembly`, both owned by this PRD's edits).

Depended on by: nothing directly. Shares two files with 13 (absent-value-contract) — `care_plan.py` and `assemble_and_render.txt` — see §4.7 for the resolved seam. 16/17 (technical/scientific documentation) will document whatever this PRD lands on.

## 1. Problem

The brief names its own open risk directly (`brainstorm.v1.md` §5): *"Merging near-duplicate findings may quietly lose an anatomical variant."* Its stated cheapest test: *"One fixture with three affected vessels. Assert all three site names survive in the merged text."* Today, nothing makes a merge — successful or botched — findable at all: it happens silently inside one LLM call (`assemble_and_render`) and leaves no trace that a merge occurred, only whatever text came out the other side.

Two separate things are missing, and this PRD treats them separately because they have different costs and different honest values:

1. **A fixture that actually tests the brief's own named risk.** Grepping the current suite (`backend/tests/care_plan/test_pipeline_assembly.py:144`, `test_pipeline_prompts.py:97`) finds a merge test, but it stops at **two** sites, not three:

   ```python
   def test_assemble_and_render_preserves_merged_diagnosis_variants():
       ...
       "description": "heavy plaque in your left and right heart arteries",
       ...
       description = result.diagnosis.details[0].description
       assert "left" in description
       assert "right" in description
   ```

   Two sites is exactly the number the prompt's own worked example uses (`assemble_and_render.txt`'s MERGE paragraph, quoted in full in §4.2 below). A test built to the same shape as the example it's checking risks proving nothing more than "the model can copy the prompt's own example" — it can't distinguish "the model generalizes variant-preservation" from "the model pattern-matches two named sites." The brief asks for three specifically because three is the smallest number that forces generalization past the worked example. **This fixture does not exist today** — this is the finding the task brief asked this PRD to check for, and the answer is: not yet, the existing test undershoots the brief's own bar by one site.

2. **Whether a merge, once it happens, should be independently recorded** so a merge is findable in logs without re-reading the rendered prose by eye. This is the R6 recommendation under evaluation.

## 2. Goals

- Settle, with a concrete argument rather than a default "add the field" reflex, whether a new `merged: bool` on the six item models earns its place over the already-free `len(source_fact_ids) > 1` (§4.1).
- Harden the MERGE paragraph in `assemble_and_render.txt` against the specific generalization gap §1 identifies: an example that only ever shows two variants (§4.2).
- Specify the regression fixture the brief's §5 risk table asks for — three affected vessels, all three site names asserted present in the merged output — as a deterministic unit test against a canned LLM response, plus a second fixture exercising the same rule on one of the six `source_fact_ids`-bearing item models, not just `diagnosis` (§4.3).
- Give the brief's "findable in logs" goal a concrete, log-only, non-gating implementation that does not require inventing a new unverifiable field (§4.4).
- State explicitly, per the initiative-wide provenance rule, whether any new internal field needs the same treatment `_strip_internal_provenance` already gives `source_fact_ids`/`summary_fact_ids` (§4.5) — the answer this PRD reaches is that none is added, so nothing needs stripping, and it says so rather than leaving it implicit.
- Resolve the file-sharing seam with PRD 13 stated at PRD 13 §4.8, and confirm it lands cleanly (§4.7).
- Flag the `Constants.Observability.LOG_EXTRA_KEYS` coordination point for whoever lands 10/11/12/14 (§9).

## 3. Non-Goals

- No fifth pipeline call, no change to the `ground → assemble_and_render → review → correct` shape.
- No patient-facing surface, no release gate. Per the initiative-wide instruction, every signal in this batch is log-only; this PRD does not add a UI affordance, a PDF row, or anything `CarePlanView.tsx`/`buildPdfHtml.ts` read.
- **No `merged: bool` field.** §4.1 makes the affirmative case for rejecting it; this line just records the resulting non-goal so it isn't mistaken for an oversight.
- No change to `Diagnosis`/`DiagnosisDetail` — they carry no `source_fact_ids` field today (confirmed in §4.1 and flagged as an `[OPEN]` gap in §9), and adding one is a schema change to a family PRD 01 already settled, not something this PRD's scope (the six `source_fact_ids`-bearing item models) authorizes.
- No change to `review.txt` or `correct.txt`. The reviewer's job is fidelity/coverage against facts, not taxonomy of *how* an item was assembled (brief §3.5: "the reviewer does not adjudicate which section an item belongs in... loading taxonomy onto the reviewer dilutes the one thing it is for" — the same reasoning applies to loading "was this a merge" onto it). The corrector only ever applies named corrections; a merge signal is not a correction target.
- No deterministic post-check that tries to *verify* a merge happened correctly (e.g., diffing rendered text against source quotes token-by-token). That is a substantially larger undertaking than this PRD's brief, and the brief's own cheapest test (assert all N site names survive) is a strictly cheaper, sufficient proxy for the one failure mode actually named (a dropped variant).
- No versioning, no migration (global constraint) — moot here since no schema field changes.

## 4. Architecture Decisions

### 4.1 `merged: bool` does not earn its place — reject it, keep `len(source_fact_ids) > 1`

**The comparison.** Every item that a genuine MERGE-rule merge produces already carries `source_fact_ids` with more than one id — the SOURCE_FACT_IDS paragraph in `assemble_and_render.txt` requires it ("more than one id if MERGE below combines facts into one item"), and `_verify_assembly` (`backend/care_plan/pipeline.py:394-448`) already computes, per item, a cleaned `cited` list of exactly those ids. `len(item.source_fact_ids) > 1` (post-`_verify_assembly` cleanup, so hallucinated ids are already excluded) is therefore available **today, for every one of the six item models, at zero marginal schema or prompt cost.**

A `merged: bool` field would be a second, model-self-reported signal layered on top of that. Three questions decide whether it's worth adding:

**1. Does it have strictly better recall than the free signal?** No — it can only have *equal or worse* recall. Every true merge necessarily produces `len(source_fact_ids) > 1` (a merge is definitionally built from ≥2 facts), so the free signal already catches 100% of merges by construction, with zero chance of a false negative from the mechanism itself. A `merged: bool` field adds a second place the model could fail to flag a merge it performed (forgetting to set the bool is a new failure mode the free signal doesn't have, since the free signal isn't a separate instruction the model can forget — it falls out of already-mandatory bookkeeping).

**2. Does it have better precision?** Only if the model's self-report is trustworthy enough to distinguish "this multi-fact item is a true near-duplicate merge" from "this multi-fact item legitimately cites several complementary, non-duplicate facts" (a medication whose dose is one fact and whose side-effect warning is a separate fact, say — both routine, neither the risk case). This is exactly the class of claim the project has already declined to trust the model to self-report unverified: PRD 02 (`docs/agent_files/2026-09-09-docs-fidelity-concision-brief/prds/02-unitization-and-provenance/PRD.md`) chose a deterministic code-side lookup for `file`/`page` specifically **because** "a model field cannot be checked" and a lookup "costs no output tokens and cannot be hallucinated" (brief §3.2). A `merged: bool` is the same shape of claim — a statement about the model's own process, not about the note's content — with no deterministic check available to confirm it. Nothing downstream can tell a correctly-set `True` from an incorrectly-set one; unlike the `file`/`page` case, there is no code-side computation that could replace it with a verified value, because "did the model perform a MERGE-rule collapse, as opposed to ordinary multi-fact composition" is not a fact about the note — it's a fact about the model's internal reasoning, unobservable and unverifiable either way. A field nobody can check is not evidence, and having it does not make the noisier free signal's false positives (routine multi-fact items) go away, because there's no way to confirm the field is more accurate than the noise it's supposed to replace.

**3. Is the extra noise on the free signal actually costly for what this PRD needs it for?** No. The free signal's imprecision (it flags every multi-fact item, not just true near-duplicate merges) is a false-positive-only failure mode for a log-only, non-gating, "make it findable" signal — a human skimming logs sees a few ordinary multi-fact items alongside genuine merges and dismisses them at a glance; nothing acts on the signal automatically, so a false positive costs nothing but a moment's read. A false negative would be the actually dangerous failure mode (an anatomical variant silently dropped, invisible in both the text and the signal) — and the free signal structurally cannot produce one, per point 1. An unverifiable field can fail in *either* direction with no way to tell which.

**Conclusion: reject `merged: bool`.** `len(source_fact_ids) > 1` is a strict superset with guaranteed recall and no added unverifiable surface. This is a "the cheaper signal suffices" outcome, consistent with the comparison doc's own framing of R6 as its lowest-priority adopted item ("ADOPT-REDUCED, low priority") — reduced here all the way to "prompt hardening plus the fixture," which the comparison doc explicitly anticipated as an acceptable landing (task framing: "a well-argued 'reject the field, keep the prompt hardening and the fixture' is a perfectly good outcome").

**The one place the free signal doesn't reach.** `Diagnosis`/`DiagnosisDetail` (`backend/models/care_plan/care_plan.py:26-31`) carry **no `source_fact_ids` field at all** — confirmed by reading the model and by the assemble prompt's own SOURCE_FACT_IDS paragraph: *"reason_for_visit and diagnosis items have no such field."* This matters concretely here because the MERGE paragraph's own worked example, and the only merge fixture that exists today, is a **diagnosis** merge ("heavy plaque in your left and right heart arteries"). For a diagnosis-category merge, the free signal is not merely noisier than a `merged` field — it is **entirely absent**, on either side of this decision: rejecting `merged: bool` costs diagnosis nothing it had, because diagnosis was never in this PRD's six-model scope, and *keeping* `merged: bool` (scoped, per the task framing, to the six `source_fact_ids`-bearing models) would not have helped diagnosis either, since `Diagnosis`/`DiagnosisDetail` are not among those six models. This is recorded as an `[OPEN]` item in §9 rather than silently patched: extending source-fact provenance to `Diagnosis` is a schema change to a family PRD 01 already settled, out of scope for a "low priority, cost-reduced" sub-project, and arguably a bigger ask than the one this PRD was scoped to evaluate.

### 4.2 Hardening the MERGE paragraph in `assemble_and_render.txt`

**Current text (verbatim, `backend/care_plan/prompts/assemble_and_render.txt`, the `MERGE --` paragraph):**

```
MERGE -- if two or more facts describe the identical underlying clinical fact (the same finding or instruction, stated more than once, possibly with different specific details), merge them into ONE item. Preserve every differing detail explicitly in the merged wording -- never drop one to shorten the sentence. Example: plaque reported separately in the left and right coronary arteries merges to "heavy plaque in your left and right heart arteries," NEVER to "heavy plaque in your heart arteries." Do not merge facts that are merely related; only merge facts that say the same thing.
```

**Gap against the brief's variant-preservation requirement.** The rule's prose is already correctly generalized ("two or more facts," "every differing detail") — it does not literally say "at most two." But its **only worked example is a two-site merge**, and a worked example is what a model actually pattern-matches against under token-budget pressure, not the surrounding generalized prose. A rule stated generally but demonstrated narrowly risks the model learning the narrower case: preserve site A and site B, but for a third simultaneous finding, either drop it or synthesize a vaguer collective noun the moment a literal two-slot template ("your left and right X") is filled and a third item doesn't fit the pattern shown. This is precisely the risk the brief names in §5 and precisely why its own cheapest test asks for three sites, not two — the existing prompt has never been asked to demonstrate, and never demonstrates, that it generalizes past its own example.

**New text:**

```
MERGE -- if two or more facts describe the identical underlying clinical fact (the same finding or instruction, stated more than once, possibly with different specific details), merge them into ONE item. Preserve every differing detail explicitly in the merged wording, no matter how many facts merge -- never drop one to shorten the sentence, and never fall back to a vaguer collective term once naming each one individually gets long.
Example (two variants): plaque reported separately in the left and right coronary arteries merges to "heavy plaque in your left and right heart arteries," NEVER to "heavy plaque in your heart arteries."
Example (three variants): calcified plaque reported separately in the right coronary artery, the left anterior descending artery, and the circumflex artery merges to "heavy calcified plaque in your right coronary, left anterior descending, and circumflex arteries," NEVER to "heavy calcified plaque in your heart arteries," and NEVER to "heavy calcified plaque in your right coronary and left anterior descending arteries" (silently dropping the third site is exactly as wrong as dropping to a collective term -- every site names once, however many there are).
Do not merge facts that are merely related; only merge facts that say the same thing. Record the id of every fact that went into a merged item in that item's source_fact_ids (see SOURCE_FACT_IDS) -- an item built from more than one fact is the signal that a merge happened here.
```

**Old → new, summarized:**

| Aspect | Old | New |
|---|---|---|
| Worked examples | One (2 sites) | Two (2 sites, 3 sites) |
| Explicit N-generalization | Implicit in "two or more" only | Explicit: "no matter how many facts merge" |
| Explicit anti-partial-drop warning | Absent (only "never drop one to shorten the sentence," which reads as being about wording economy, not enumeration) | Explicit: a worked example of dropping just the third of three is called out as "exactly as wrong" as collapsing to a collective term |
| Cross-reference to `source_fact_ids` as the merge's own record | Absent from this paragraph (present only in the separate SOURCE_FACT_IDS paragraph, which the model reads once, earlier, about a different topic) | Restated here, adjacent to the rule it documents the effect of |

The last row is deliberate: this paragraph is where the model is reasoning about merges specifically, so restating "this is what makes a merge findable afterward" here — rather than trusting the model to recall a sentence from a different, earlier paragraph — costs one sentence and directly serves this PRD's "findable" goal without adding a field.

### 4.3 The regression fixture(s)

**Decision: deterministic unit test against a canned LLM response, not a live-model test.** `assemble_and_render` is a single LLM call; nothing in this codebase runs a real Vertex AI call inside `pytest` (confirmed by the existing convention throughout `test_pipeline_assembly.py`, which monkeypatches `pipeline._generate_json` to return a canned dict and tests only the deterministic code around that call — prompt construction, parsing, `_verify_assembly`). A live-model assertion of "does the model actually preserve three variants" cannot be a `pytest` case (non-deterministic, costs a real API call per CI run, and the brief's global scope explicitly excludes building the clinical-fidelity evaluation suite this would really belong to). What *can* and must be a deterministic test is the half that's actually mechanical: given a correctly-merged canned response, does the pipeline layer preserve it untouched (no post-processing accidentally truncates or rewrites it)? This is the same shape PRD 04 §7.4 already chose for the existing 2-site test ("proves the pipeline layer doesn't undo it, the merge itself is the model's job per the prompt") — this PRD extends that shape, it doesn't invent a new one. The live-model side of the question — does the model, in practice, actually do this — is a manual smoke-test item, specified in §8, exactly where PRD 04 §8 put its own "confirm a note with two findings at different anatomical sites merges to one item naming both sites" item.

**Fixture 1 — upgrade the existing diagnosis test to three sites**, `backend/tests/care_plan/test_pipeline_assembly.py:144`:

```python
def test_assemble_and_render_preserves_merged_diagnosis_variants_three_way():
    """Regression fixture for brainstorm.v1.md §5's named risk: 'merging
    near-duplicate findings may quietly lose an anatomical variant.' Uses
    three sites, not two, deliberately -- two is the number the prompt's
    own worked example uses, so a two-site fixture cannot distinguish
    genuine generalization from copying the example verbatim."""
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    facts = [Fact(id=1, category="diagnosis", unit_id=1, char_start=0, char_end=1, text="x")]
    pipeline._generate_json = lambda *a, **k: {
        **_minimal_care_plan_response(),
        "diagnosis": {
            "changed_since_last_visit": "",
            "details": [
                {
                    "title": "Coronary artery disease",
                    "plain_name": "clogged heart arteries",
                    "description": (
                        "heavy calcified plaque in your right coronary, "
                        "left anterior descending, and circumflex arteries"
                    ),
                    "what_it_means_for_you": "",
                    "severity": None,
                }
            ],
        },
    }

    result = pipeline.assemble_and_render(facts, [], [], [])

    description = result.diagnosis.details[0].description
    assert "right coronary" in description
    assert "left anterior descending" in description
    assert "circumflex" in description
```

Kept alongside (not replacing) the existing two-site test — both are cheap, and the two-site case is still the one the prompt's example literally shows, so it's still worth its own regression guard.

**Fixture 2 — the same rule on a `source_fact_ids`-bearing item, not just diagnosis**, new test in the same file:

```python
def test_assemble_and_render_merged_item_carries_all_source_fact_ids():
    """The merge signal this PRD keeps (§4.1): a merged item's
    source_fact_ids length is the free, always-available 'a merge may
    have happened here' marker. This fixture proves it survives
    _verify_assembly's citation-existence check (PRD 04 §4.4) intact --
    a merge is not itself flagged as a hallucination just because it
    cites more than one fact."""
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    facts = [
        Fact(id=1, category="tests", unit_id=1, char_start=0, char_end=1, text="x"),
        Fact(id=2, category="tests", unit_id=2, char_start=0, char_end=1, text="y"),
    ]
    pipeline._generate_json = lambda *a, **k: {
        **_minimal_care_plan_response(),
        "tests": [
            {
                "description": "elevated readings on your left and right arm blood pressure cuffs",
                "status": "done",
                "source_fact_ids": [1, 2],
            }
        ],
    }

    result = pipeline.assemble_and_render(facts, [], [], [])

    assert result.tests[0].source_fact_ids == [1, 2]
    assert "left" in result.tests[0].description
    assert "right" in result.tests[0].description
```

**Prompt-text guard**, new test in `test_pipeline_prompts.py` alongside `test_assemble_prompt_contains_merge_example` (`:97`):

```python
def test_assemble_prompt_contains_three_way_merge_example():
    assert "circumflex" in _ASSEMBLE_PROMPT
    assert "left anterior descending" in _ASSEMBLE_PROMPT
```

The existing `test_assemble_prompt_contains_merge_example` (asserting `"left and right heart arteries" in _ASSEMBLE_PROMPT`) is unchanged and still passes — §4.2's new text keeps the two-site example verbatim.

### 4.4 The "findable in logs" goal, without a new field

The brief's own framing for R6 is "makes merged items findable in logs" — that goal doesn't require a new schema field, only a place that reads the free signal (`len(source_fact_ids) > 1`) and writes it somewhere a person can find. `_verify_assembly` (`backend/care_plan/pipeline.py:394-448`) already loops over every item in every one of the six `_ITEM_LIST_FIELDS` and already computes `cited` (the post-hallucination-cleanup `source_fact_ids`) per item — the cheapest possible integration point, reusing a value already in hand rather than adding a second pass over the data.

**Current code (`_verify_assembly`, the `for field in _ITEM_LIST_FIELDS:` loop, `pipeline.py:425-444`):**

```python
    for field in _ITEM_LIST_FIELDS:
        items = getattr(model, field)
        kept = []
        changed = False
        for item in items:
            cited = [i for i in item.source_fact_ids if i in valid_ids]
            if not cited:
                logger.warning(
                    "assemble_and_render: dropping unbacked %s item -- "
                    "source_fact_ids=%r cited nothing in the ledger",
                    field, item.source_fact_ids,
                )
                changed = True
                continue
            if len(cited) != len(item.source_fact_ids):
                logger.warning(
                    "assemble_and_render: dropping hallucinated source_fact_ids "
                    "on a %s item: %s", field,
                    [i for i in item.source_fact_ids if i not in valid_ids],
                )
                item = item.model_copy(update={"source_fact_ids": cited})
                changed = True
            kept.append(item)
        if changed:
            updates[field] = kept

    return model.model_copy(update=updates) if updates else model
```

**New (added lines marked `+`):**

```python
    multi_fact_counts: dict[str, int] = {}
    for field in _ITEM_LIST_FIELDS:
        items = getattr(model, field)
        kept = []
        changed = False
+       multi_fact = 0
        for item in items:
            cited = [i for i in item.source_fact_ids if i in valid_ids]
            if not cited:
                logger.warning(
                    "assemble_and_render: dropping unbacked %s item -- "
                    "source_fact_ids=%r cited nothing in the ledger",
                    field, item.source_fact_ids,
                )
                changed = True
                continue
            if len(cited) != len(item.source_fact_ids):
                logger.warning(
                    "assemble_and_render: dropping hallucinated source_fact_ids "
                    "on a %s item: %s", field,
                    [i for i in item.source_fact_ids if i not in valid_ids],
                )
                item = item.model_copy(update={"source_fact_ids": cited})
                changed = True
+           if len(cited) > 1:
+               multi_fact += 1
            kept.append(item)
+       if multi_fact:
+           multi_fact_counts[field] = multi_fact
        if changed:
            updates[field] = kept

+   total_multi_fact = sum(multi_fact_counts.values())
+   logger.info(
+       "assemble_and_render: %d item(s) across %d section(s) cite more than "
+       "one fact -- candidate near-duplicate merges (a superset: an item "
+       "legitimately built from several complementary facts also counts), "
+       "by section: %s",
+       total_multi_fact, len(multi_fact_counts), multi_fact_counts,
+       extra={"merge_candidate_signal": {
+           "total": total_multi_fact, "by_section": multi_fact_counts,
+       }},
+   )
+
    return model.model_copy(update=updates) if updates else model
```

**Design choices, stated explicitly:**

- **Named `merge_candidate_signal`, not `merged_items` or similar** — the log message and the key name both say "candidate," on purpose, so nobody reading Cloud Logging later mistakes this for a confirmed-merge count. §4.1 already established this signal is a strict superset of true merges; the name has to carry that caveat since the field-level self-report that would have disambiguated it was rejected.
- **Counted post-cleanup (`cited`, not `item.source_fact_ids`)** — a merge-candidate count built from ids that are about to be dropped as hallucinated would overstate the signal with exactly the noise `_verify_assembly`'s other guard already exists to remove.
- **`logger.info`, always-on, not sampled** — same reasoning PRD 11 §4.2 and PRD 12 §4.8.1 give for their own per-run signals: this is routine per-run telemetry (every job either has multi-fact items or doesn't; neither is a code-level anomaly), so `WARNING` would drown out this file's genuinely anomaly-signaling `WARNING`s, and always-on (rather than "only log when nonzero") is what makes a true population-level rate computable later, not just a raw event count on the runs that happen to trip it.
- **One aggregate `logger.info` call per run, not one per item** — matches PRD 11's and PRD 12's shape (one aggregate call, not a call per fact/unit), keeping this run's log volume addition to one line, not N.
- **Placed at the end of `_verify_assembly`, after the loop, not inside it** — the per-field counts have to be fully accumulated before the cross-section aggregate can be logged; a per-field log call would fragment one signal into up to six lines per run for no benefit.

**`Constants.Observability.LOG_EXTRA_KEYS`** (`backend/utils/constants.py:164-171`) gates whether `extra={"merge_candidate_signal": ...}` actually survives into Cloud Logging's structured JSON output in production (`StructuredJsonFormatter.format()` only copies a key it's whitelisted for — confirmed by reading `observability/logging_config.py`, same mechanism PRD 11 §4.3 and PRD 12 §4.9 already document for their own keys). Without the entry, this would work in local/plain-text logging and silently vanish in the deployed path. This PRD adds one entry:

```python
LOG_EXTRA_KEYS: list[str] = [
    "user_id", "function", "care_plan_version", "grading_version", "input_version",
    "operation", "metric", "metric_type", "duration_ms", "success", "outcome",
    "step_name", "status", "http_method", "http_path", "http_status",
    "http_status_code", "total_duration_ms", "saved_id", "input_chars",
    "error", "labels", "duration_ms_observed", "OpOutcome",
    "service", "environment",
    "merge_candidate_signal",   # PRD 14
]
```

See §9 for the coordination note: PRDs 10, 11, and 12 each independently touch this same list.

### 4.5 `_strip_internal_provenance` — no change, and why

The initiative-wide rule requires this PRD to say explicitly whether any new internal field needs the same treatment `_strip_internal_provenance` (`backend/routes/worker.py:36-54`) already gives `source_fact_ids`/`summary_fact_ids`. **This PRD adds no new field to `CarePlan` or to any of the six item models** — §4.1 rejects `merged: bool`, and §4.4's signal is a `logger.info` call inside the pipeline, never attached to the `CarePlan` object or serialized into `output_data["care_plan"]`. There is nothing new for `_strip_internal_provenance` to strip, and `_strip_internal_provenance` itself requires zero code changes from this PRD. This is stated affirmatively rather than left as a silent absence, per the task's explicit instruction to say so either way.

### 4.6 `_diff_item`/corrector-diff interaction — moot, confirmed by walkthrough

Since no new field is added, `_verify_correction_diff`/`_diff_item` (`backend/care_plan/pipeline.py:568-625`) need no change and see no new leaf to compare. Recorded here only because PRD 13 §4.8 flagged this exact question for whichever of 13/14 lands with an actual new field — the answer for 14 turns out to be "no new field, so the question doesn't arise here."

### 4.7 Seam with PRD 13 — confirmed, no conflict

PRD 13 (`why: str | None`) states its assumptions about this PRD at PRD 13 §4.8, written on the premise that PRD 14 would add `merged: bool` to all six item models and a validator-adjacent change. Since §4.1 rejects that field:

- **`care_plan.py`**: this PRD makes **no edit** to the file at all. PRD 13's `_normalize_why` validators on `Medication`, `Test`, `Procedure`, `OtherInstruction` (its §4.1) have nothing from this PRD to rebase against — the shared-file seam PRD 13 anticipated collapses to "PRD 13 edits this file, PRD 14 does not."
- **`assemble_and_render.txt`**: this PRD edits the `MERGE --` paragraph (§4.2 above); PRD 13 edits the adjacent `NOT STATED --` paragraph. PRD 13 §4.8 already confirmed these are "adjacent but textually independent; no shared sentence needs to satisfy both PRDs' requirements" — true before this PRD's edit and unaffected by it, since §4.2's changes stay entirely inside the MERGE paragraph's own text.
- **Net effect**: landing 13 and 14 in either order is now a strictly smaller rebase risk than PRD 13's author anticipated, since only one of the two files (the prompt) is touched by both, and only in non-adjacent-enough-to-matter paragraphs.

## 5. API Change Summary

No wire-shape change. `CarePlanInternal.care_plan`'s JSON shape is untouched — no field added, none removed, none retyped. The one behavioral addition (`logger.info` with `extra={"merge_candidate_signal": ...}`) is server-side observability only; it never reaches an HTTP response, the frontend, or the PDF, consistent with every other signal in this batch (10, 11, 12) being log-only and non-gating.

## 6. Frontend Change Summary

None. No field, no UI affordance, no PDF row.

## 7. Testing

### 7.1 `backend/tests/care_plan/test_pipeline_assembly.py` — additions

| Test | Purpose |
|---|---|
| `test_assemble_and_render_preserves_merged_diagnosis_variants_three_way` | §4.3 Fixture 1 — the brief's own named regression test, upgraded from 2 to 3 sites. |
| `test_assemble_and_render_merged_item_carries_all_source_fact_ids` | §4.3 Fixture 2 — the same rule exercised on a `source_fact_ids`-bearing item model (`tests`), not just `diagnosis`. |
| `test_verify_assembly_logs_merge_candidate_signal_aggregate` | Build a `CarePlan` with one `medications` item citing 2 facts and one `tests` item citing 1; assert (via `caplog`) one `logger.info` call whose `extra["merge_candidate_signal"]` equals `{"total": 1, "by_section": {"medications": 1}}`. |
| `test_verify_assembly_logs_merge_candidate_signal_zero_when_no_multi_fact_items` | All items cite exactly one fact each; assert the log still fires (always-on, §4.4) with `{"total": 0, "by_section": {}}`. |
| `test_verify_assembly_merge_candidate_count_excludes_dropped_hallucinated_ids` | An item with `source_fact_ids=[1, 999]` where only `1` is valid; assert it does **not** count toward `multi_fact_counts` (post-cleanup `cited` has length 1, not 2) — regression guard for the "counted post-cleanup, not pre-cleanup" design choice in §4.4. |

### 7.2 `backend/tests/care_plan/test_pipeline_prompts.py` — additions

| Test | Purpose |
|---|---|
| `test_assemble_prompt_contains_three_way_merge_example` | §4.3 — asserts the new three-site worked example text is present. |
| `test_assemble_prompt_merge_rule_names_source_fact_ids` | Assert the MERGE paragraph itself (sliced the same way `test_assemble_prompt_not_stated_rule_names_all_four_why_fields` slices its own paragraph, `\nMERGE --` to the next `\n<NAME> --`) contains `"source_fact_ids"` — guards §4.2's added cross-reference sentence. |

### 7.3 `backend/tests/utils/test_constants.py` — addition

- Extend to assert `"merge_candidate_signal" in Constants.Observability.LOG_EXTRA_KEYS` (mirrors the existing `assert "user_id" in ...` pattern this file already uses, and the identical addition PRD 11 §7.3 and PRD 12 make for their own keys).

### 7.4 Existing tests confirmed unaffected

- `test_assemble_prompt_contains_merge_example` (`test_pipeline_prompts.py:97`) — the two-site worked example text is preserved verbatim in §4.2's new prompt text, so this passes unchanged.
- `test_assemble_and_render_preserves_merged_diagnosis_variants` (`test_pipeline_assembly.py:144`) — kept as-is alongside the new three-way version (§4.3); not replaced, since the two-site case is still the one the prompt's first example literally demonstrates.
- Every existing `_verify_assembly` test in PRD 04 §7.4's list (`test_verify_assembly_drops_item_with_empty_source_fact_ids`, `test_verify_assembly_returns_same_object_when_no_correction_needed`, etc.) — unaffected, since §4.4's addition only ever reads `cited` (already computed) and appends to a local dict; it never changes what `_verify_assembly` returns, drops, or corrects.

## 8. Manual Intervention Required From You

- **Prompt smoke test against real notes**, once this PRD's prompt text is live (run via ngrok + pm2, `SERVICE_MODE=combined`, against 2-3 real or realistic de-identified notes containing a genuine multi-site finding — e.g., a cardiac catheterization or angiogram report naming plaque, stenosis, or occlusion at three or more named vessels): confirm the model actually names all affected sites in the merged item, not a collective term and not a silent partial drop. This is the live-model half of §4.3's fixture that cannot be a deterministic `pytest` case — matching PRD 04 §8's identical two-site item, extended to three, and PRD 03 §8's reasoning that a real-model judgment call is not automatable without a real Vertex AI call.
- **Spot-check the `merge_candidate_signal` log line** on the same smoke-test runs: confirm it appears in local/plain-text logs with sane `by_section` counts, and (if you have Cloud Logging access for a deployed environment at the point this eventually ships) confirm the structured JSON payload actually carries the field once `K_SERVICE` is set — the exact "looks fine locally, silently vanishes in production" footgun PRD 11 §4.3 already called out for its own key, worth re-checking rather than assuming the `LOG_EXTRA_KEYS` addition alone guarantees it end-to-end.
- No new environment variables, credentials, or console configuration — this sub-project is prompt text, one small pipeline.py diff, and tests only.

## 9. Open Questions & Decisions

- **[RESOLVED] `merged: bool` rejected.** §4.1: `len(source_fact_ids) > 1` has guaranteed-superset recall over any model self-report and cannot be improved on precision by an equally unverifiable field, per the same reasoning PRD 02 already applied to `file`/`page`. This PRD's footprint is prompt hardening (§4.2), two regression fixtures (§4.3), and a log-only aggregate built from the already-free signal (§4.4) — no schema change.
- **[OPEN] Diagnosis-category merges have no `source_fact_ids`-shaped signal at all, by either path.** `Diagnosis`/`DiagnosisDetail` carry no such field (§4.1), so the free signal this PRD relies on for the six item models is structurally unavailable for the very category the MERGE paragraph's own worked example uses. This PRD does not propose extending source-fact provenance to `Diagnosis` — that's a schema change to a family PRD 01 already settled, and a bigger ask than this "cost-reduced, low priority" sub-project's scope. Left open for whoever next revisits `Diagnosis`'s schema, if diagnosis-merge observability is ever prioritized.
- **[OPEN] Whether `multi_fact_counts`/`merge_candidate_signal` is worth a follow-on log-based metric or alert.** Out of scope here (matches PRD 11 §7.3's identical deferral for `coverage_signal` — "the *optional* follow-up (a log-based metric) would need console/IaC work, and that is explicitly deferred, not required").
- **Coordination note — `Constants.Observability.LOG_EXTRA_KEYS`**, per the task's explicit instruction to flag this: PRDs 10, 11, and 12 each independently touch this same list (per PRD 12 §4.9's own merge-seam note: PRD 11 adds `"coverage_signal"`, PRD 12 adds `"extraction_signal"` and `"extraction_signal_facts"`, PRD 10 adds none). This PRD adds a **fourth** independent entry, `"merge_candidate_signal"` (§4.4). If 10/11/12/14 are implemented as separate, sequential tasks against this one list — as this initiative's dev-tasks/dev-code workflow does — each addition is a small, non-conflicting append, but whoever lands second, third, or fourth must **merge** their addition into the list as it stands at that point, not overwrite it wholesale from this PRD's snippet (which shows only this PRD's own addition appended to today's 24-entry list, not the other three PRDs' entries, which may already be present by the time this lands).
