# PRD 11 — Omission Signal

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here — see especially §3.5, §5's open-risk table). Comparison-drive research bundle: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/comparison-drive-research-bundle.v1.md` §5 R1 (this sub-project's entire mandate), §4.6, §4.7, §8.
Branch: `docs/fidelity-concision-brief`.
Depends on: 01 (`backend/models/ledger.py` — `Fact`, including `category`), 03 (`ground()` producing the verified `list[Fact]` ledger), 05 (`backend/models/review.py` — `CoverageEntry`/`ReviewResult`; `backend/care_plan/pipeline.py` — `review()`, `_sanitize_review_result`, both unmodified by this PRD, only read from), 06 (`iter_steps`'s step 5/6 wiring — `pipeline.py:880-946`, the exact block this PRD edits).
Depended on by: none. This is a leaf sub-project — a consumption-only change to an already-computed value, with no new model, no new prompt, and no new pipeline step.

## 1. Problem

`review()`'s JOB 2 (`backend/care_plan/prompts/review.txt`) makes the reviewer walk every single ledger fact and answer, for each one, "does this appear in the care plan?" — the enumerate-then-check-presence shape brief §3.5 calls **mandatory**, not a style choice, because open-ended "is anything missing" review performs at near chance. That walk is not free: it is paid for in prompt tokens (the full fact ledger is repeated into JOB 2's instructions) and output tokens (one `CoverageEntry{fact_id, present}` per fact, every single run) on top of JOB 1's fidelity work, in the same LLM call.

Verified at HEAD `43865b7` by direct grep:

```
$ grep -rn "\.coverage\b" backend/ --include=*.py | grep -v /tests/
backend/models/review.py:26:class CoverageEntry(JsonModel):
backend/models/review.py:31:    coverage: list[CoverageEntry] = []
backend/care_plan/pipeline.py:496:    coverage = [e for e in result.coverage if e.fact_id in fact_ids]
backend/care_plan/pipeline.py:499:    coverage += [CoverageEntry(fact_id=i, present=False) for i in missing]
```

Every one of those four hits is inside the model definition or `_sanitize_review_result` (`pipeline.py:471-500`) itself — the sanitizer that filters `coverage` down to known fact ids and back-fills `present=False` for any fact id the reviewer's answer silently skipped (`pipeline.py:497-499`), logging a warning when it does (`pipeline.py:498`). `_sanitize_review_result` returns the sanitized `ReviewResult` with this `coverage` list fully populated — one entry per ledger fact, guaranteed. Then, in `iter_steps` (`pipeline.py:911-915`, `922`):

```python
review_result = _call(_STEP.REVIEW.number, _STEP.REVIEW.label,
                       lambda: self.review(facts, care_plan))
...
if review_result and review_result.corrections:
```

`review_result.coverage` is never read again anywhere in `iter_steps`, anywhere else in `pipeline.py`, or anywhere in `backend/` outside `review.py`/the sanitizer/its own tests. It is computed, sanitized, and discarded on every single run.

This is not cosmetic. Two things make it matter:

1. **The direction this signal points is the one direction nothing else in the pipeline checks.** PRD 04 §4.4's citation-existence guard (soundness: every surviving item cites a real fact) and this PRD's own upstream, PRD 05 §4.7 (which deleted `close_coverage()` outright), together made the *completeness* direction — does every ledger fact make it into the output — structurally invisible everywhere except this one discarded field. The brief's own cited evidence (Asgari et al., via the comparison bundle §5 R1 and brief §3.5) identifies omission as a failure mode genuinely distinct from fabrication, not a lesser version of it: a model that never states something false but quietly drops a warning sign fails the patient in a way none of the soundness machinery is built to catch, by design (soundness only asks "is what's here true," never "is anything missing").
2. **The soundness-over-completeness inversion (`prds/README.md`, "Consolidated open questions" item 2) is currently unfalsifiable in production.** It was a reasoned, deliberate design call (PRD 05 §4.7, §9), not a mistake — but right now there is no way to observe, across real runs, whether facts are actually being dropped at a rate anyone should worry about. `review_result.coverage` is the cheapest possible instrument for that: it costs zero additional LLM calls and zero additional prompt tokens (the call already happens; only the already-returned field goes unread), and it is the only place in the whole system that ever asks the completeness question at all.

This PRD does not change what ships to the patient, does not gate anything, and does not re-litigate the inversion. It stops throwing away data the pipeline already paid for, so the inversion's real-world cost — if any — becomes something a human can look at instead of a decision nobody can check.

**A caveat this PRD must not paper over:** brief §5's own open-risk table states the coverage check's published detection rate at 24.6%, "better than chance but far from complete." An LLM asked to judge omission is a weak instrument (arXiv:2608.31016, cited in PRD 05 §1). Consuming `coverage` does not manufacture a reliable per-fact verdict out of an unreliable one — see §4.4's design decision for how the log record's own wording carries this caveat forward rather than presenting a `present: false` as ground truth.

## 2. Goals

- Consume `review_result.coverage` in `iter_steps` (`pipeline.py`, step 6 block) instead of leaving it unread, with an exact, minimal insertion point relative to the existing `if review_result and review_result.corrections:` branch (§4.1).
- Emit one structured, aggregate log record per run that makes the ledger-fact omission count and rate observable in Cloud Logging, without a second LLM call, without new prompt tokens, and without changing anything the pipeline returns to the caller (§4.2, §4.3).
- Make an explicit, evidenced call on the one genuinely hard question this PRD raises — whether any note-derived text belongs in that log record — rather than defaulting to whatever is easiest to grep (§4.4).
- Decide, explicitly, whether the aggregate also needs to ride on `PipelineRunResult`/the persisted job record, or whether the log record alone satisfies "observable across runs" (§4.5).
- Leave `review()`, `_sanitize_review_result`, `ReviewResult`, and `CoverageEntry` completely unmodified — this PRD is a pure consumer of an existing, already-correct value.

## 3. Non-Goals

- No gate, disposition, hold, abstain, or any patient-facing surface. Per the initiative's locked decisions, every new signal in this batch is log-only and non-gating unless explicitly argued otherwise — this PRD does not argue otherwise. A high omission rate changes nothing about what ships; it is purely observability.
- No change to the reviewer prompt (`review.txt`), the coverage walk's shape, or the enumerate-then-check-presence contract itself (PRD 05 §4.3, brief §3.5). This PRD does not try to make the underlying signal more accurate — it only stops discarding the signal that already exists.
- No re-implementation of `close_coverage()` or any token-overlap heuristic. That mechanism was deleted deliberately (PRD 05 §4.7, §9) because per-item `source_fact_ids` provenance made it obsolete; nothing here resurrects it or any variant of it. This PRD's aggregate is built entirely from `CoverageEntry.fact_id`/`.present` plus `Fact.category` — never from re-deriving overlap between ledger text and rendered output text.
- No empirical measurement of the reviewer's true omission-catch rate. PRD 05 §7.5/§9 already scoped that (the injected-error catch-rate protocol) as a manual, out-of-CI exercise; this PRD's log record is a production-observability instrument, not a substitute for that protocol, and does not claim to validate the reviewer's accuracy.
- No new `ErrorCode` member, no new pipeline step, no new `Constants.Pipeline.PIPELINE_STEPS` entry, no new progress-event step number. Coverage is consumed inside the existing step 6 (`_STEP.CORRECT`) block; nothing about `iter_steps`'s step count or labels changes.
- No frontend change. `coverage` never reached the frontend before this PRD and does not reach it after — see §6.
- No sampling infrastructure, no log-based-metric or alerting-policy configuration (Terraform/console work) — noted as manual follow-up in §8, not built here.
- Not this PRD's territory: PRD 10 (numeric-integrity) also touches `pipeline.py`, specifically near `_verify_assembly`/the assembly-time deterministic checks. This PRD's only edit is inside `iter_steps`'s step 6 block and the new small helper it calls; see §4.1's explicit seam statement.

## 4. Architecture Decisions

### 4.1 Where coverage is consumed in `iter_steps`, and the seam with PRD 10

Current step 5/6 block (`pipeline.py:909-936`, unmodified above this point):

```python
# Step 5: review (LLM, NON-FATAL — PRD 05 §4.8: a fidelity nit must
# never cost the user their whole result)
yield StepEvent(step=_STEP.REVIEW.number, status="active", label=_STEP.REVIEW.label)
try:
    review_result = _call(_STEP.REVIEW.number, _STEP.REVIEW.label,
                           lambda: self.review(facts, care_plan))
except Exception:
    logger.exception("pipeline: review failed — skipping correction, shipping assembly's output")
    review_result = None
yield StepEvent(step=_STEP.REVIEW.number, status="done", label=_STEP.REVIEW.label)

# Step 6: correct (LLM, NON-FATAL) + the deterministic close.
yield StepEvent(step=_STEP.CORRECT.number, status="active", label=_STEP.CORRECT.label)
if review_result and review_result.corrections:
    try:
        care_plan = _call(...)
    except Exception:
        logger.exception(...)
```

**New line, inserted immediately after the step 6 `StepEvent(..., status="active", ...)` yield and immediately *before* `if review_result and review_result.corrections:`:**

```python
# Step 6: correct (LLM, NON-FATAL) + the deterministic close.
yield StepEvent(step=_STEP.CORRECT.number, status="active", label=_STEP.CORRECT.label)

if review_result and review_result.coverage:
    _log_coverage_summary(review_result.coverage, facts)

if review_result and review_result.corrections:
    try:
        care_plan = _call(...)
    ...
```

**Why here, and why before the corrections branch, not after or inside it:**

- Coverage describes the *pre-correction* `care_plan` review actually saw — `correct()` never touches coverage, cannot invalidate it, and its success/failure/skip has no bearing on what was already true about the reviewed plan. Placing the consumption before the corrections branch keeps it visibly independent of `correct()`'s own try/except, rather than looking like it depends on correction succeeding.
- It stays inside the step 6 block (not its own step) for the same reason the existing comment above step 6 gives for bundling correct with the deterministic close: "none of what happens here is something a patient needs itemized." A log-only consumer of review's output is exactly that kind of internal bookkeeping — it does not warrant a seventh `PIPELINE_STEPS` member or its own progress label.
- It reads `facts` and `review_result`, both already in scope at this point in `iter_steps` — no new parameter, no new state threaded through.

**Behavior when `review_result is None` (review raised/failed):** the guard `if review_result and review_result.coverage` short-circuits on `review_result` being `None` (mirroring the existing `if review_result and review_result.corrections:` line immediately below it, same truthiness pattern, same house style) — nothing is logged. This is deliberate, not an oversight: `pipeline.py:914`'s existing `logger.exception("pipeline: review failed — skipping correction, shipping assembly's output")` already records this case distinctly. Conflating "review didn't run" with "review ran and found 0% omission" in the same log shape would corrupt the aggregate — a run where review crashed must never silently read as a perfect-coverage run.

**Behavior when `coverage` is empty:** `_sanitize_review_result` guarantees `len(review_result.coverage) == len(facts)` for any `review_result` that came from a real `review()` call (it filters unknown ids, then back-fills exactly the missing ones — `pipeline.py:496-499` — so the resulting list always has exactly one entry per fact id in `facts`). `coverage` is therefore empty in exactly one case: `facts` itself is empty (grounding produced a ledger with zero facts). `_log_coverage_summary` (§4.2) treats an empty input list as "nothing to summarize" and logs nothing — a 0/0 rate is not a real number and logging one would be misleading noise, not signal. The `if review_result and review_result.coverage:` guard already short-circuits this case before the helper is ever called, so this is stated for completeness rather than left implicit.

**Seam with PRD 10 (numeric-integrity).** PRD 10 edits `pipeline.py` near `_verify_assembly`/the assembly-time deterministic checks (PRD 04 §4.5's territory, step 4) to add a deterministic number/unit parity check. This PRD's only edit is the two-line insertion above, plus one new private helper (`_log_coverage_summary`, §4.2) placed near `_sanitize_review_result` — nowhere near `_verify_assembly` or step 4. The two PRDs touch disjoint regions of the same file and neither reads nor depends on the other's output; no interface needs to be agreed beyond "we both edit `pipeline.py`, in different functions, for different steps."

### 4.2 The aggregation helper

New private function, placed directly below `_sanitize_review_result` (same section of `pipeline.py`, same neighborhood as the `CoverageEntry`-handling code it reads):

```python
def _log_coverage_summary(coverage: list[CoverageEntry], facts: list[Fact]) -> None:
    """Log-only consumer of the reviewer's enumerate-then-check-presence walk
    (PRD 05 §4.3, brief §3.5) — makes the omission signal the pipeline
    already computes and discards observable per-run, at the cost of one
    structured log line (PRD 11 §1). Never raises, never returns a value,
    never affects what iter_steps yields -- this is pure observability.

    `present=False` here is a WEAK signal, not a verdict: an LLM asked
    "is this present" performs near chance on omission (arXiv:2608.31016,
    PRD 05 §1), and the coverage check's own published detection rate is
    24.6% (brief §5's open-risk table) -- better than chance, far from
    complete. This function does not claim otherwise; the log message
    says so explicitly (below) so a reader of Cloud Logging doesn't
    mistake a rate here for a validated omission measurement.

    No fact text and no per-fact log line -- see PRD 11 §4.4 for why.
    """
    if not facts:
        return
    fact_by_id = {f.id: f for f in facts}
    covered_ids = {e.fact_id for e in coverage if e.present and e.fact_id in fact_by_id}
    omitted_ids = [fid for fid in fact_by_id if fid not in covered_ids]

    total = len(fact_by_id)
    omitted = len(omitted_ids)
    by_category: dict[str, int] = {}
    for fid in omitted_ids:
        category = fact_by_id[fid].category
        by_category[category] = by_category.get(category, 0) + 1

    logger.info(
        "review: coverage signal -- %d/%d ledger facts not flagged present by the "
        "reviewer (rate=%.3f); WEAK signal (near-chance per-fact judgment, ~24.6%% "
        "published detection rate) -- trend/observability only, not a per-fact verdict",
        omitted, total, omitted / total,
        extra={"coverage_signal": {
            "total": total,
            "omitted": omitted,
            "rate": round(omitted / total, 4),
            "omitted_by_category": by_category,
        }},
    )
```

Design notes:

- **`total`/`omitted` are computed from `facts` (the ledger), not from `len(coverage)`.** `coverage` and `facts` are the same length for every real `review()` call (§4.1), but the helper does not assume this — it treats `facts` (the authoritative ledger) as the source of truth for "what should have been checked" and reads `coverage` only to learn which of those ids were marked present. A fact id with no `present=True` entry counts as omitted, whether that's because the reviewer marked it `present=False` or because it's missing from `coverage` entirely — the second case cannot actually reach this helper post-sanitization (§4.1), but treating "not affirmatively marked present" as the omitted case, rather than "affirmatively marked absent," is the same pessimistic default `_sanitize_review_result` itself already uses for its own back-fill (`present=False` is what a *missing* answer becomes, `pipeline.py:499`) — this helper is consistent with that existing convention rather than introducing a second one.
- **`by_category` groups by `Fact.category`** (the 8-member `FactCategory` literal, `models/ledger.py`) — a fixed, small, non-identifying vocabulary (`"medications"`, `"warning_signs"`, etc.), safe to log under the same posture that already logs `category=%s` freely elsewhere in this file (e.g. `pipeline.py:256,262,268` in grounding's own drop-and-log warnings). This is the one piece of per-fact structure kept, because "which categories go missing most" is exactly the actionable question this signal exists to answer (a `warning_signs` omission is a materially different finding than an `other` omission), and category alone carries none of the PHI risk `fact.text` would (§4.4).
- **Level is `logger.info`, not `logger.warning`.** House convention in this file uses `WARNING` for anomalies — a model deviating from its contract (`pipeline.py:485,488,491`), a reviewer failing to answer for a fact it was asked about (`pipeline.py:498`, the pre-existing, distinct log this one sits next to — see the naming note below). A nonzero omission rate is not a code-level anomaly; it is the expected, routine output of a documented near-chance signal running on every ordinary job. Logging it at `WARNING` on every run with any omission at all would make `WARNING` noise, drowning out the anomaly-signaling `WARNING`s this file already relies on. `INFO` is the correct severity for "routine per-run telemetry," matching `utils/llm.py:59`'s and `routes/worker.py:84`'s existing use of `INFO` for expected-path status, not `WARNING`.
- **One aggregate line, not one line per omitted fact, and not both.** Considered and rejected: a per-fact line (`fact_id`, `category`, `present`) for every omitted fact. Two independent reasons, not one: (a) PHI — see §4.4; a per-fact line is exactly the shape that invites a future edit adding "just the fact text, for context" next to an already-present `fact_id`, since a bare `fact_id` is admittedly not very informative on its own once the job document is gone (§4.4 confronts this directly rather than leaving it as an unstated temptation). (b) Signal-to-noise — a `present: false` on any *one* fact is weak evidence in isolation (near-chance, §1), so a wall of per-fact log lines each implying "this specific fact was dropped" overstates the confidence any single entry deserves. The aggregate, category-bucketed count is the right altitude: precise enough to be actionable (which categories, how often, out of how many) without implying single-fact-level certainty the underlying check does not have.
- **Always-on, not sampled.** This is one already-in-memory list turned into one `logger.info` call — no LLM call, no network call, no meaningful CPU cost. Sampling exists to control the *cost* of an expensive-per-instance signal; there is no cost here to control, and sampling would only reduce the population size available for computing a real, population-level omission rate — directly working against the stated goal (§1) of making the rate observable, not estimated. Resolved: always-on.
- **Naming, disambiguated from the existing `pipeline.py:498` warning.** `_sanitize_review_result`'s own `logger.warning("review: coverage omitted %d fact id(s); treating as not-present", ...)` is about a *different* event — the reviewer's raw response failing to answer for a fact_id at all (a protocol-compliance failure on the model's part, worth a `WARNING`). This PRD's `"review: coverage signal -- ..."` message is about the *substantive* content of the (already-sanitized) coverage answers — how many facts, after any such back-filling, ended up not marked present. Both use the word "coverage"; neither uses the word "omitted" in a way that lets one be `grep`ped for by mistake as the other — verified by using `"coverage omitted"` for the pre-existing line and `"coverage signal"` for the new one, distinct three-token substrings.

### 4.3 New whitelist entry: `Constants.Observability.LOG_EXTRA_KEYS`

`observability/logging_config.py`'s `StructuredJsonFormatter.format()` only copies an `extra` field into the emitted Cloud Logging JSON payload if its key name is listed in `Constants.Observability.LOG_EXTRA_KEYS` (`utils/constants.py:164-171`):

```python
for key in Constants.Observability.LOG_EXTRA_KEYS:
    val = getattr(record, key, _SENTINEL)
    if val is not _SENTINEL:
        log_entry[key] = val
```

Without an entry for it, `extra={"coverage_signal": {...}}` would be silently dropped from the structured JSON output in production (`K_SERVICE` set) — the dict would still be attached to the Python `LogRecord` object, but the formatter would never read it, so nothing would reach Cloud Logging's `jsonPayload`. (In local/dev mode, the plain-text formatter doesn't consult this list at all, so the field would appear to work in local testing and then silently vanish in the deployed structured-logging path — the kind of gap that is easy to miss without reading `logging_config.py` directly, which is why it's called out here as its own decision rather than assumed.) This PRD adds exactly one new entry:

```python
LOG_EXTRA_KEYS: list[str] = [
    "user_id", "function", "care_plan_version", "grading_version", "input_version",
    "operation", "metric", "metric_type", "duration_ms", "success", "outcome",
    "step_name", "status", "http_method", "http_path", "http_status",
    "http_status_code", "total_duration_ms", "saved_id", "input_chars",
    "error", "labels", "duration_ms_observed", "OpOutcome",
    "service", "environment",
    "coverage_signal",
]
```

One key, dict-valued — `StructuredJsonFormatter` passes the value straight to `json.dumps(log_entry, default=str)`, so a nested dict serializes correctly without needing to flatten `coverage_signal` into several top-level keys.

**Per-run correlation comes for free, without adding a job id to the log call.** `SessionIdFilter` (`observability/logging_config.py`) auto-injects `session_id` from Flask's `g` context into every log record — including this one, since `iter_steps` runs inside the worker's Flask request (`routes/worker.py`'s `execute_job`, itself wrapped by `app.py`'s `extract_session_id` before-request hook that sets `g.session_id` on every request). `StructuredJsonFormatter` additionally attaches the current OpenTelemetry `trace_id`/`span_id` to every record. Between `session_id` and `trace_id`, this log line is already attributable to one specific job/run in Cloud Logging without this PRD needing to thread a `job_id` through `_call`/`_log_coverage_summary` itself — see §4.5 for why this is also the load-bearing fact behind "logging alone is sufficient."

### 4.4 The PHI question: no fact text, category only — an explicit deviation from the source research's own suggestion

The comparison-drive research bundle's own text for R1 (§5) proposes, as its "minimum fix": *"log the `present=False` fact ids with their `text` and `category` at WARNING."* This PRD does **not** do that, and the deviation needs to be argued, not silently dropped.

**What `Fact.text` actually is.** Per `models/ledger.py`'s own docstring and `pipeline.py`'s `_verify_facts` (`pipeline.py:279`, `text=draft.text`), `Fact.text` is the grounding LLM's own paraphrase of one atomic clinical statement — not the raw verbatim quote (`draft.quote`, discarded after verification and never stored on `Fact` at all), but still a direct, clinical-content-bearing description derived from the patient's note ("started metformin 500mg twice daily," "denies chest pain"). It is exactly the kind of content `docs/data-and-privacy.md` addresses head-on: *"Not a HIPAA-covered service... **Do not upload real, identifiable patient health information (PHI).**"* — a posture that assumes uploaded content may nonetheless be real clinical information in practice, and treats it accordingly throughout the product's design.

**The established codebase posture already answers this question, and answers it consistently.** Grep across every log call in this file and its neighbors that touches fact-shaped data:

```
$ grep -n "logger\.\(warning\|info\|exception\)" backend/care_plan/pipeline.py
```

confirms every single one of them — the grounding drop-and-log warnings (`pipeline.py:254-268`, dropping a fact citing an unknown unit, a non-verbatim quote, or an uninformative quote), the assembly-time guards (`pipeline.py:379-435`, dropping unbacked items, hallucinated `source_fact_ids`, thin content fields), and the reviewer's own sanitizer (`pipeline.py:485-499`) — logs only `category`, `unit_id`, array index, field name, length (`len(value)`), or a list of bare integer ids. **None of them logs `fact.text`, `draft.quote`, or any other note-derived string value, anywhere, at any log level, for any reason** — including cases (thin-field detection, dropped-quote detection) where the fact's actual content would arguably be the single most useful piece of debugging context to have. That restraint is a deliberate, load-bearing pattern across the whole pipeline, not an oversight this PRD would be "completing" by adding text logging for the first time. `docs/data-and-privacy.md`'s Analytics section states the same rule explicitly for a different subsystem: every GA4 event parameter is "a fixed literal, a count, a category string... — never document content, filenames, extracted text, or generated care-plan text."

**The retention-posture mismatch this PRD must not create.** The product's whole data-lifecycle design (`docs/data-and-privacy.md`, "Every deletion path") is built around a job document that is deleted within roughly an hour to a day even in the worst case, with an explicit best-effort immediate delete on the common path (path 1, "the instant the result screen mounts"). `Fact` objects are already "[n]ever persisted to Firestore and never sent to the frontend" (`models/ledger.py`'s own docstring) — they exist only in the worker process's memory for the duration of one job. Writing `fact.text` into Cloud Logging would take content that currently has a maximum lifetime of one job run and give it Cloud Logging's own retention (project-configured log bucket retention, commonly 30 days by default and often longer) — a strictly longer and differently-governed retention posture than anything else this product does with note-derived content, introduced by an observability change whose entire stated value proposition is "at the cost of a log line" (§1). That trade is not worth it for a WEAK, near-chance signal (§4.2) — the log's value comes from the aggregate count and category breakdown, not from being able to eyeball which specific sentence a run flagged.

**Resolved:** the log record carries `fact_id` (via the aggregate's `omitted` count, not printed individually — §4.2 already decided against per-fact lines) and `category` only. No `fact.text`, no `draft.quote`, no excerpt, no "bounded prefix" of anything note-derived, at any log level. This is a direct, disclosed deviation from the source research bundle's own suggested minimum fix, made on the strength of (a) the codebase's own unbroken, cross-cutting precedent of never logging fact/quote text, (b) `docs/data-and-privacy.md`'s explicit product-level PHI posture, and (c) the retention-lifetime mismatch above — not a hand-wave, and not a compromise the aggregate approach forces on us for lack of a better idea: category-bucketed counts are independently the right altitude for a per-run trend signal (§4.2), regardless of the PHI question.

### 4.5 Logging alone is sufficient — nothing added to `PipelineRunResult` or the persisted job document

`PipelineRunResult` (`models/pipeline_events.py`) currently carries exactly `care_plan`, `term_data`, `raw_text`. This PRD does not add a fourth field.

**Why logging alone satisfies "observable across runs":**

- Per-run correlation is already free (§4.3) — `session_id` and `trace_id` land on every coverage-signal log line automatically, without this PRD adding a `job_id` field anywhere. "Observable across runs" in Cloud Logging means: filter by `jsonPayload.coverage_signal.rate > threshold`, group by `jsonPayload.coverage_signal.omitted_by_category`, correlate a specific run's line back to its `trace_id`/`session_id` if deeper investigation is warranted. All of that works from the log line alone.
- A log-based metric (Cloud Logging → Cloud Monitoring) can be built directly on `jsonPayload.coverage_signal.rate` or `.omitted` without any pipeline code change beyond this PRD's — this is exactly the mechanism `docs/data-and-privacy.md`'s own Analytics section relies on for other counters, and it is the natural next step for "make the rate observable" (flagged as manual follow-up, §8, since it's console/Terraform configuration, not code).
- Adding the aggregate to `PipelineRunResult` would mean threading it through `services/care_plan_pipeline.py`'s adapter into `AdapterResult`, then into `CarePlanInternal`'s envelope, then into `output_data` — at which point it becomes internal provenance riding on the same object `_strip_internal_provenance` (`routes/worker.py:36-54`) already exists specifically to scrub before persistence (it currently pops `raw`, `summary_fact_ids`, and every item's `source_fact_ids` for exactly this reason — PRD 06 §4.6). A `coverage_signal` field would need the identical treatment: pop it in `_strip_internal_provenance` before `complete_job` ever writes `output_data`, since `fact_id`-shaped internal identifiers are "exactly as internal as the ledger it cites into, regardless of size" (`_strip_internal_provenance`'s own docstring, quoted verbatim). That is real additional surface — a new field to add, a new field to strip, a new place a stripping bug could leak internal ids into a job document a patient's browser can read — for a value this PRD can already get from the log line's own structured fields, for free, with automatic per-run correlation already built into the logging pipeline.
- The job document's whole design point (`docs/data-and-privacy.md`) is a short-lived record deleted the instant `ResultScreen` mounts, purpose-built to hold exactly what the frontend needs and nothing else. An aggregate telemetry stat that no frontend code will ever read has no reason to pass through that document at all, let alone survive its scrubbing pass, merely to end up in the same place (Cloud Logging, via whatever log-based metric or export a later ops task builds) that this PRD's direct log line already reaches in one step.

**Resolved:** log-only stands. If a future need arises for the aggregate to be queryable per-job outside of Cloud Logging (e.g., a support tool that looks up one job's stats by id), that is a new, distinct requirement this PRD does not have evidence for today — see §9 for the recorded reasoning a future PRD can re-weigh against a concrete need.

## 5. API Change Summary

No route, request, or response shape changes. `iter_steps`'s public yield contract is unchanged: `StepEvent`, `PipelineRunResult`, `PipelineStepError` — same three types, same fields, same step count (six), same step numbers. `output_data` (the persisted/returned job document) gains no new key, per §4.5.

| Behavior | Before this PRD | After |
|---|---|---|
| `review_result.coverage` | Computed, sanitized, discarded | Computed, sanitized, and read once by `_log_coverage_summary` inside `iter_steps` |
| Cloud Logging output for a completed job | No signal about omission at all | One `INFO`-level `"review: coverage signal -- ..."` line per run with `review()` output, carrying `coverage_signal: {total, omitted, rate, omitted_by_category}` |
| `Constants.Observability.LOG_EXTRA_KEYS` | 18 entries | 19 entries (`coverage_signal` added) |
| Job document / `output_data` | No coverage-derived field | Unchanged — no coverage-derived field (§4.5) |
| A run where `review()` raised | `logger.exception(...)` only | Unchanged — still exactly that, and still nothing coverage-shaped logged for that run (§4.1) |

## 6. Frontend Change Summary

No change. `coverage` never reached `output_data`, the API response, or any `.tsx` file before this PRD, and does not after (§4.5, §5). Nothing here changes what `CarePlanView.tsx`, `ResultScreen.tsx`, or any other frontend file receives, reads, or renders.

## 7. Testing

New/changed tests live under `backend/tests/care_plan/`, following the existing files' conventions.

### 7.1 `backend/tests/care_plan/test_pipeline_review.py` (extend)

- `_log_coverage_summary` (new tests, alongside the existing `_sanitize_review_result` tests, same fixture helpers `_facts(n)`):
  - all facts covered (`coverage=[CoverageEntry(fact_id=i, present=True) for i in 1..3]`, `facts=_facts(3)`) → `omitted == 0`, `rate == 0.0`, `by_category == {}`, one `logger.info` call (assert via `caplog`, matching the pattern `tests/utils/test_llm.py:72`'s "Capture log messages from the named logger" already establishes in this codebase).
  - some facts omitted, mixed categories (e.g. 2 `medications` facts, 1 `warning_signs` fact; the `warning_signs` one and one `medications` one come back `present=False`) → `omitted == 2`, `rate == pytest.approx(2/3)`, `by_category == {"medications": 1, "warning_signs": 1}`.
  - `coverage=[]`, `facts=[]` → no `logger.info` call at all (the `if not facts: return` guard), asserted via `caplog` showing zero records, not just zero coverage-signal fields.
  - `coverage=[]`, `facts` non-empty (the raw-mock-shaped degenerate case, not reachable through a real `review()` call post-sanitization, but defensively covered): every fact counts as omitted (`omitted == len(facts)`), no `ZeroDivisionError`, no exception.
  - a `coverage` entry citing a `fact_id` not present in `facts` is ignored for `covered_ids` purposes (defensive; mirrors `_sanitize_review_result`'s own "drop unknown fact_id" policy at the read site, without needing `_sanitize_review_result` to have already run).
  - assert the log call's `extra["coverage_signal"]` dict has exactly the four documented keys (`total`, `omitted`, `rate`, `omitted_by_category`) — a schema-shape regression guard, since this is the one place a future edit might be tempted to add a fifth key (e.g. fact text) without revisiting §4.4's reasoning.
  - assert the log message text does not contain any fact's `category` string value passed positionally in a way that could be mistaken for fact content — not a strict requirement, but a sanity check that the human-readable message stays generic/aggregate-shaped (no per-fact interpolation into the message string itself, only into `extra`).

### 7.2 `backend/tests/care_plan/test_pipeline_streaming.py` (extend)

Existing fixture (`_make_pipeline`, `FACT_FIXTURE`, `CARE_PLAN_FIXTURE`) already mocks `p.review` directly, bypassing `_sanitize_review_result` — exactly the "coverage shorter than facts" case §4.2/§7.1 defensively covers, so these tests exercise the real integration path through `iter_steps`, not just the helper in isolation:

- `test_iter_steps_logs_coverage_summary_when_review_returns_coverage` — `p.review` returns `ReviewResult(verdict="pass", corrections=[], coverage=[CoverageEntry(fact_id=1, present=False)])` (matching `FACT_FIXTURE`'s single fact, `id=1`); assert (via `caplog` at `INFO`) that a `"review: coverage signal"` record is emitted with `omitted == 1`, `total == 1`.
- `test_iter_steps_does_not_log_coverage_summary_when_review_is_none` — `p.review = MagicMock(side_effect=RuntimeError("review failed"))` (the existing `test_iter_steps_review_failure_is_non_fatal` setup); assert no `"review: coverage signal"` record appears in `caplog` (only the existing `"pipeline: review failed"` exception log).
- `test_iter_steps_does_not_log_coverage_summary_when_coverage_is_empty` — `p.review` returns `ReviewResult(verdict="pass", corrections=[])` (the fixture's own default, `coverage=[]`) with `p.ground` returning `[FACT_FIXTURE]` as usual; per §4.1's stated behavior this should still log (facts is non-empty, coverage empty means "all omitted" per §4.2's degenerate-case handling) — **this test asserts that documented behavior explicitly** (`omitted == 1`, `total == 1`) rather than assuming coverage-empty means silence, so a future reader isn't left to infer the distinction between "coverage empty because facts is empty" (silent, §4.1) and "coverage empty because a mock/degenerate caller didn't populate it" (logged as 100% omitted, §4.2) from the helper's code alone.
- Assert the existing `test_iter_steps_yields_step_events_in_order` step-number sequence (`[(2,...),(3,...),(4,...),(5,...),(6,...)]`, ten events) is unchanged — this PRD adds no `StepEvent`.

### 7.3 `backend/tests/test_observability_logging.py` or `backend/tests/utils/test_logging_config.py` (extend, whichever already exists — confirmed present at `backend/tests/utils/test_logging_config.py`)

- `"coverage_signal"` is present in `Constants.Observability.LOG_EXTRA_KEYS`.
- `StructuredJsonFormatter.format()` on a record carrying `extra={"coverage_signal": {"total": 3, "omitted": 1, "rate": 0.333, "omitted_by_category": {"medications": 1}}}` includes that nested dict verbatim in the parsed JSON output — a direct regression guard for §4.3's "silently dropped if the key isn't whitelisted" failure mode, since that failure mode produces no error, only a quietly incomplete log line.

## 8. Manual Intervention Required From You

- **Confirm log volume and shape once wired into the live pipeline** (ngrok + pm2, `SERVICE_MODE=combined`): run a real note through the full pipeline and inspect the emitted `"review: coverage signal"` line directly (dev-mode plain-text formatter, so read the log line as printed) — confirm `total`/`omitted`/`rate`/`omitted_by_category` look sane against the note's actual fact count, and confirm the line appears exactly once per completed run with a successful `review()` call.
- **Decide whether/when to build a Cloud Logging-based metric or alerting policy on `jsonPayload.coverage_signal.rate`** once this has run in a live environment long enough to have a baseline. This is console/Terraform configuration, not code this PRD produces — genuinely out of scope here, but flagged as the natural next step §4.5 argues logging-alone enables.
- **No new environment variables, credentials, or console configuration required to land this PRD itself** — the `LOG_EXTRA_KEYS` addition is a pure code change; only the *optional* follow-up (a log-based metric) would need console/IaC work, and that is explicitly deferred, not required.
- **Sanity-check the omission rate against PRD 05 §7.5's injected-error catch-rate protocol, if/when that protocol is run.** They measure different things (this PRD's rate is the reviewer's own self-reported coverage on real, unperturbed runs; §7.5 measures catch rate against *known, injected* errors) but a wildly inconsistent picture between the two — e.g., a near-zero real-world omission rate alongside a low injected-error catch rate — would be worth a second look at whether real omissions in production notes look structurally different from the injected ones, rather than assuming the reviewer is simply accurate.

## 9. Open Questions & Decisions

- `[RESOLVED: coverage is consumed inside iter_steps's existing step 6 (_STEP.CORRECT) block, immediately after that step's "active" StepEvent and immediately before the "if review_result and review_result.corrections:" branch — not in its own step, not inside the corrections branch.]` — §4.1. Keeps the consumption visibly independent of `correct()`'s own success/failure, and avoids a seventh `PIPELINE_STEPS` member for something the patient never needs itemized.
- `[RESOLVED: when review_result is None (review failed/raised), nothing coverage-shaped is logged.]` — §4.1. The existing `pipeline.py:914` exception log already distinctly records "review didn't run"; logging a coverage summary in that branch would risk that case being misread as "review ran and found full coverage."
- `[RESOLVED: one aggregate log line per run (total, omitted, rate, omitted_by_category), not one line per omitted fact, and not both.]` — §4.2. A per-fact line multiplies a near-chance, per-item signal into many individually-overconfident lines, and is exactly the log shape most likely to invite adding fact text next to a bare, otherwise-useless `fact_id` later.
- `[RESOLVED: logger.info, not logger.warning.]` — §4.2. A nonzero omission rate is the expected, routine output of a documented near-chance check, not a code-level anomaly; `WARNING` in this file is reserved for the latter.
- `[RESOLVED: no fact text, no quote excerpt, no bounded text prefix of any kind in the log record — category and aggregate counts only. This is a direct, disclosed deviation from the source research bundle's own suggested "minimum fix" (log present=False fact ids with their text and category).]` — §4.4. Backed by (a) a grep-verified, unbroken, cross-cutting precedent of never logging `fact.text`/`draft.quote` anywhere else in this pipeline, even where it would be the most useful debugging context available; (b) `docs/data-and-privacy.md`'s explicit product-level "do not upload real PHI" posture and its Analytics section's identical rule for a different subsystem; (c) the retention-lifetime mismatch between a job document/in-memory `Fact` list with a maximum lifetime of one job run, and Cloud Logging's own, longer, differently-governed retention.
- `[RESOLVED: always-on, not sampled.]` — §4.2. One `logger.info` call over an already-in-memory list has no meaningful marginal cost to control via sampling, and sampling would only shrink the population available for a population-level rate estimate — directly working against this PRD's own stated goal.
- `[RESOLVED: log-only — nothing added to PipelineRunResult, AdapterResult, CarePlanInternal, or the persisted output_data job document.]` — §4.5. Per-run correlation (`session_id`, `trace_id`) is already automatic via the existing structured-logging pipeline; threading the aggregate through the job document would require giving it the same `_strip_internal_provenance` scrubbing `source_fact_ids`/`summary_fact_ids` already need (PRD 06 §4.6), for a value this PRD can already reach one step sooner, directly from the log line.
- `[RESOLVED: Constants.Observability.LOG_EXTRA_KEYS gains exactly one new entry, "coverage_signal", holding one nested dict — not four flat keys.]` — §4.3. `StructuredJsonFormatter` passes extra values through `json.dumps(..., default=str)` unmodified, so a single nested-dict key is sufficient and keeps the whitelist from growing by four entries for one logical unit of data.
- `[RESOLVED: whether the real-world omission rate, once observed, should feed back into a revisit of the soundness-over-completeness inversion itself, is out of scope for this PRD.]` — this PRD's job is to make the inversion falsifiable (§1), nothing more; it does not pre-judge what the evidence will show. A future decision needs future evidence, and no commitment is made here.
- `[DEFERRED: whether a Cloud Logging-based metric/alerting policy should be built on jsonPayload.coverage_signal, and if so, at what rate threshold.]` — console/IaC configuration, not code; already flagged in §8 as manual follow-up, to be thresholded once a real-world baseline exists. No threshold is guessed at with zero production data behind it.
- `[RESOLVED: log-only stands; no later, distinct requirement (e.g. a support tool querying one job's coverage stats by job id, outside Cloud Logging) is being anticipated or built for.]` — no such requirement exists today. §4.5's reasoning is recorded here so a future PRD can re-weigh it against a concrete need rather than re-derive it from scratch.
- `[DEFERRED: whether "not flagged present" should ever be surfaced more precisely than a per-run aggregate — e.g. a per-fact structured log line gated behind a stricter, non-content field set (fact_id, category, unit_id, char_start/char_end — offsets, not text) for deeper investigation of a single flagged run.]` — not built here; §4.2 already argues the aggregate is the right altitude for the stated goal, and even the offsets-only variant would need its own PHI review (an offset pair combined with other logged/available context could, in principle, be more reconstructable than a bare count) that this PRD has not done and is not scoped to do speculatively.
