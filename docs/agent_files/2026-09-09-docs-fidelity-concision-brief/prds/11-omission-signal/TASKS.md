# Tasks: Omission Signal

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01 (`backend/models/ledger.py` — `Fact`, including `category`), 03 (`ground()` producing the verified `list[Fact]` ledger), 05 (`backend/models/review.py` — `CoverageEntry`/`ReviewResult`; `backend/care_plan/pipeline.py` — `review()`, `_sanitize_review_result`, both read-only here), 06 (`iter_steps`'s step 5/6 wiring — the exact block this PRD edits). All four are already landed in this repo (verified by reading the real code at authoring time — see the line-number note below). Depended on by: none — this is a leaf sub-project, a consumption-only change to an already-computed value.

**Conventions**

- Backend tests: from `backend/`, run `python -m pytest tests/ -q` (matches CI). Single file/test: `python -m pytest tests/care_plan/test_pipeline_review.py -q` or `...::test_name -q`.
- Lint: `ruff check .` from `backend/`.
- No frontend changes in this PRD (§6, §3 Non-Goals) — no frontend test commands needed here.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given.
- Every task traces to PRD `## 4. Architecture Decisions`; do not add fields, files, or behavior beyond what's cited.
- **Line-number note**: verified against the real, current `backend/care_plan/pipeline.py` (972 lines) at authoring time: `_sanitize_review_result` spans lines 471-505; `_format_corrections_for_prompt` begins at line 508 (one blank line at 506, one at 507, between them); `review()` is at lines 767-789; `iter_steps`'s step 5 block is lines 907-916 (`yield StepEvent(..., status="active", ...)` at 909, `review_result = _call(...)` at 911-912, `yield StepEvent(..., status="done", ...)` at 916); step 6 begins at line 918 with `yield StepEvent(step=_STEP.CORRECT.number, status="active", ...)` at line 921 immediately followed by `if review_result and review_result.corrections:` at line 922. `CoverageEntry` and `FactCategory` are already imported at the top of `pipeline.py` (`from models.review import Correction, CoverageEntry, ReviewResult`; `from models.ledger import Fact, FactCategory, Unit`) — no new imports needed for those. `_STEP = Constants.Pipeline.PIPELINE_STEPS` (line 53). Locate everything below by symbol/content, not by these line numbers alone — they are for orientation only, confirmed accurate as of this writing but not guaranteed to survive an unrelated edit.
- **Verified match between PRD snippets and real code**: `CoverageEntry(fact_id: int, present: bool)` and `ReviewResult(verdict, corrections, coverage)` in `backend/models/review.py` match the PRD's snippets verbatim. `Fact(id, category, unit_id, char_start, char_end, text)` in `backend/models/ledger.py` matches. `Constants.Observability.LOG_EXTRA_KEYS` in `backend/utils/constants.py` matches the PRD §4.3 snippet verbatim, **except the PRD's §5 summary table says the list has "18 entries" before this change / "19" after — the real list has 26 entries today, so it will have 27 after Task 3.** This is a miscount inside the PRD's own prose (the code snippet itself is byte-for-byte correct), not a code mismatch; Task 3's acceptance criteria below use the real count (26 → 27), not the PRD table's stated count.

---

### Task 1 — `_log_coverage_summary`: new aggregation helper in `pipeline.py`

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: none (first task; touches only a new, self-contained function).
   - Changes (PRD §4.2): Insert the following function directly below `_sanitize_review_result` (i.e. after line 505's `return result.model_copy(...)`, in the existing blank space before `_format_corrections_for_prompt` at line 508) — same neighborhood as the `CoverageEntry`-handling code it reads:
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
     Carried verbatim from PRD §4.2 — do not paraphrase the docstring or the log message text; §7.1's tests assert on the exact `extra["coverage_signal"]` key set and PRD §4.2's naming-disambiguation note (below) relies on the exact three-token substrings `"coverage omitted"` (pre-existing, `pipeline.py:502`) vs. `"coverage signal"` (this one) staying distinct.
     `logger`, `CoverageEntry`, and `Fact` are already in scope in this module — no new imports.
   - Acceptance criteria:
     - `python -c "from care_plan.pipeline import _log_coverage_summary"` (from `backend/`) succeeds.
     - `grep -n "^def _log_coverage_summary" backend/care_plan/pipeline.py` shows it between `_sanitize_review_result` and `_format_corrections_for_prompt`.
     - `_log_coverage_summary([], [])` returns `None` and calls no `logger.info` (empty `facts` short-circuits before touching `coverage`).
     - `_log_coverage_summary([CoverageEntry(fact_id=1, present=True)], [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="x")])` computes `omitted=0`, `total=1`, `rate=0.0`.
     - `grep -c "coverage signal" backend/care_plan/pipeline.py` returns exactly 1, and `grep -n "coverage omitted" backend/care_plan/pipeline.py` (the pre-existing `_sanitize_review_result` warning at line 502) is unaffected — the two substrings do not collide under a single `grep "coverage"`.
     - Every existing test in `backend/tests/care_plan/` still passes unchanged (`python -m pytest tests/care_plan/ -q`) — this task is purely additive.
     - Permanent test coverage lands in Task 4 (`test_pipeline_review.py`).

### Task 2 — Wire `_log_coverage_summary` into `iter_steps`'s step 6 block

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: land after Task 1 (needs `_log_coverage_summary` to exist).
   - Changes (PRD §4.1): In `iter_steps`, insert exactly two new lines immediately after the step 6 `StepEvent(..., status="active", ...)` yield (line 921) and immediately *before* `if review_result and review_result.corrections:` (line 922) — no other line in this block changes:
     ```python
     # Step 6: correct (LLM, NON-FATAL) + the deterministic close.
     # Bundled under one progress-bar step deliberately (PRD §4.1) — none of
     # what happens here is something a patient needs itemized.
     yield StepEvent(step=_STEP.CORRECT.number, status="active", label=_STEP.CORRECT.label)

     if review_result and review_result.coverage:
         _log_coverage_summary(review_result.coverage, facts)

     if review_result and review_result.corrections:
         try:
             care_plan = _call(
     ```
     (Only the blank line and the new two-line `if` block are additions; the surrounding lines shown are for placement context, not edits.)
     Do not touch step 4/5, `_verify_assembly`, or anything named in PRD 10's territory — this is the entire edit for this task.
   - Acceptance criteria:
     - `sed -n '918,930p' backend/care_plan/pipeline.py` shows the new `if review_result and review_result.coverage:` / `_log_coverage_summary(review_result.coverage, facts)` block positioned strictly between the step 6 "active" `StepEvent` and the `if review_result and review_result.corrections:` line.
     - `test_iter_steps_yields_step_events_in_order` (existing, `backend/tests/care_plan/test_pipeline_streaming.py`) still asserts exactly `[(2,...),(3,...),(4,...),(5,...),(6,...)]` (ten events) and passes unmodified — this task adds no `StepEvent`.
     - `test_iter_steps_review_failure_is_non_fatal` (existing) still passes: when `review_result` is `None`, `_log_coverage_summary` is never called (the `if review_result and ...` guard short-circuits on `None`).
     - `python -m pytest tests/care_plan/test_pipeline_streaming.py -q` (from `backend/`) passes in full with the existing fixture (`p.review` returns `ReviewResult(verdict="pass", corrections=[])`, i.e. `coverage=[]`) — note this means `_log_coverage_summary` is *not* called for the default fixture today (`coverage=[]` is falsy), which Task 5 adds a dedicated test to pin down explicitly.
     - Permanent integration test coverage lands in Task 5 (`test_pipeline_streaming.py`).

### Task 3 — `Constants.Observability.LOG_EXTRA_KEYS`: add `coverage_signal`

   - Files: `backend/utils/constants.py`
   - Dependency: independent of Tasks 1-2; can land in any order relative to them, but is listed here so Task 6's tests have everything they need once Tasks 1-3 are all in.
   - Changes (PRD §4.3): Add exactly one new entry, `"coverage_signal"`, to the end of the existing `LOG_EXTRA_KEYS` list (`backend/utils/constants.py`, currently 26 entries — see the header note above on the PRD's own "18/19" miscount):
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
     Do not reorder or otherwise touch the existing 26 entries. This is the whole edit — one key, dict-valued; `StructuredJsonFormatter` passes it straight to `json.dumps(log_entry, default=str)`, so no flattening of `coverage_signal`'s four sub-keys is needed.
     **Shared-file seam with PRD 12 (extraction-provenance)**: PRD 12 also adds one or more entries to this same `LOG_EXTRA_KEYS` list. Both PRDs only *append* a new string to the list — neither reorders nor removes an existing entry — so the two edits are structurally non-conflicting (a textual merge conflict is possible if both land in the same list-literal region without rebasing, but there is no semantic collision: whichever PR lands second only needs to append its own key next to this one, not resolve any shared logic).
   - Acceptance criteria:
     - `python -c "from utils.constants import Constants; assert 'coverage_signal' in Constants.Observability.LOG_EXTRA_KEYS; assert len(Constants.Observability.LOG_EXTRA_KEYS) == 27"` (from `backend/`) succeeds.
     - `grep -c '"coverage_signal"' backend/utils/constants.py` returns 1.
     - Every existing entry in `LOG_EXTRA_KEYS` is still present, in its original relative order (diff should show only one line added, at the end).
     - Permanent test coverage lands in Task 6 (`test_logging_config.py`).

### Task 4 — Extend `backend/tests/care_plan/test_pipeline_review.py`: `_log_coverage_summary` unit tests

   - Files: `backend/tests/care_plan/test_pipeline_review.py`
   - Dependency: land after Task 1.
   - Changes (PRD §7.1): Add tests alongside the existing `_sanitize_review_result` tests, reusing the file's existing `_facts(n)` helper (line 36-40: `Fact(id=i, category="medications", unit_id=1, char_start=0, char_end=1, text=f"fact {i}")` for `i in 1..n`) and importing `_log_coverage_summary` and `logging` (for `caplog.at_level`) at the top. Use the `caplog` fixture, matching this codebase's established convention (`backend/tests/care_plan/test_pipeline_assembly.py`'s `caplog.at_level(logging.WARNING)` / `caplog.records` pattern; here the level is `INFO`, e.g. `caplog.at_level(logging.INFO, logger="care_plan.pipeline")`). Cover every case below:
     - `test_log_coverage_summary_all_facts_covered` — `coverage=[CoverageEntry(fact_id=i, present=True) for i in (1,2,3)]`, `facts=_facts(3)` → exactly one `logger.info` record; its `record.coverage_signal` (the `extra` dict lands as a plain attribute on the `LogRecord`) equals `{"total": 3, "omitted": 0, "rate": 0.0, "omitted_by_category": {}}`.
     - `test_log_coverage_summary_some_facts_omitted_mixed_categories` — 3 facts: two `category="medications"` (ids 1, 2), one `category="warning_signs"` (id 3); `coverage=[CoverageEntry(fact_id=1, present=False), CoverageEntry(fact_id=2, present=True), CoverageEntry(fact_id=3, present=False)]` → `record.coverage_signal == {"total": 3, "omitted": 2, "rate": pytest.approx(2/3), "omitted_by_category": {"medications": 1, "warning_signs": 1}}`.
     - `test_log_coverage_summary_empty_coverage_and_empty_facts_logs_nothing` — `_log_coverage_summary([], [])`; assert `caplog.records == []` (zero records total, not just zero coverage-signal fields).
     - `test_log_coverage_summary_empty_coverage_with_nonempty_facts_treats_all_as_omitted` — `_log_coverage_summary([], _facts(2))` (the raw-mock-shaped degenerate case, not reachable through a real `review()` call post-sanitization, but defensively covered per PRD §4.2); assert no exception, `record.coverage_signal["omitted"] == 2 == record.coverage_signal["total"]`, `rate == 1.0`.
     - `test_log_coverage_summary_ignores_coverage_entry_for_unknown_fact_id` — `coverage=[CoverageEntry(fact_id=1, present=True), CoverageEntry(fact_id=999, present=True)]`, `facts=_facts(1)` → `omitted == 0`, `total == 1` (the unknown id contributes nothing to `covered_ids` or the omitted count; mirrors `_sanitize_review_result`'s own "drop unknown fact_id" policy at the read site, without needing `_sanitize_review_result` to have already run).
     - `test_log_coverage_summary_extra_dict_has_exactly_four_keys` — assert `set(record.coverage_signal.keys()) == {"total", "omitted", "rate", "omitted_by_category"}` — a schema-shape regression guard, since this is the one place a future edit might be tempted to add a fifth key (e.g. fact text) without revisiting PRD §4.4's reasoning.
     - `test_log_coverage_summary_message_has_no_per_fact_category_interpolation` — a sanity check, not a strict requirement: assert the human-readable `record.getMessage()` string does not contain any of the input facts' `category` values as a substring beyond the generic message text itself (the message stays generic/aggregate-shaped; per-fact detail only ever goes into `extra`, never into the message string).
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_review.py -q` (from `backend/`) passes in full, including all existing `_sanitize_review_result`/`review()`/`_resolve_path`/`_targets_removed_item` tests (untouched) plus the new `_log_coverage_summary` tests above.

### Task 5 — Extend `backend/tests/care_plan/test_pipeline_streaming.py`: `iter_steps` integration tests

   - Files: `backend/tests/care_plan/test_pipeline_streaming.py`
   - Dependency: land after Task 2.
   - Changes (PRD §7.2): The existing fixture (`_make_pipeline`, `FACT_FIXTURE` — single `Fact(id=1, category="medications", ...)`, `CARE_PLAN_FIXTURE`) already mocks `p.review` directly, bypassing `_sanitize_review_result` entirely — this is exactly the "coverage shorter than facts" / "coverage empty" case PRD §4.2/§7.1 defensively covers, so these tests exercise the real integration path through `iter_steps`, not just the helper in isolation. Add, importing `CoverageEntry` from `models.review` and `logging` at the top:
     - `test_iter_steps_logs_coverage_summary_when_review_returns_coverage` — `p.review = MagicMock(return_value=ReviewResult(verdict="pass", corrections=[], coverage=[CoverageEntry(fact_id=1, present=False)]))` (matching `FACT_FIXTURE`'s single fact, `id=1`); with `caplog.at_level(logging.INFO, logger="care_plan.pipeline")`, run `list(p.iter_steps("input text", []))`; assert a record with message starting `"review: coverage signal"` is present and its `coverage_signal["omitted"] == 1` and `["total"] == 1`.
     - `test_iter_steps_does_not_log_coverage_summary_when_review_is_none` — reuse the existing `test_iter_steps_review_failure_is_non_fatal` setup (`p.review = MagicMock(side_effect=RuntimeError("review failed"))`); with `caplog.at_level(logging.INFO, logger="care_plan.pipeline")`, assert no record's message starts with `"review: coverage signal"` (only the existing `"pipeline: review failed"` exception log fires).
     - `test_iter_steps_does_not_log_coverage_summary_when_coverage_is_empty_list` — use the fixture's own default `p.review` return (`ReviewResult(verdict="pass", corrections=[])`, i.e. `coverage=[]`) with `p.ground` returning `[FACT_FIXTURE]` as usual. Per PRD §4.1, `coverage=[]` with non-empty `facts` is the raw-mock-shaped degenerate case — the `if review_result and review_result.coverage:` guard in `iter_steps` is `False` when `coverage` is the empty list (falsy), so **no log is emitted here, matching the guard's truthiness, not `_log_coverage_summary`'s own internal "empty coverage but non-empty facts = 100% omitted" handling** (that internal handling only matters for a *direct* call to `_log_coverage_summary`, as in Task 4's tests — it is never reached via `iter_steps` when `coverage` itself is empty, because the `if ... review_result.coverage:` guard filters it out first). Assert no record's message starts with `"review: coverage signal"`. This distinction (guard-level emptiness vs. helper-level degenerate-case handling) is worth stating explicitly in the test's docstring so a future reader isn't confused by `_log_coverage_summary`'s own defensive branch never firing through this path.
     - Assert the existing `test_iter_steps_yields_step_events_in_order` step-number sequence (`[(2,...),(3,...),(4,...),(5,...),(6,...)]`, ten events) is unchanged — already covered by Task 2's acceptance criteria; no new assertion needed here beyond confirming the existing test still passes.
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_streaming.py -q` (from `backend/`) passes in full, including all pre-existing tests plus the three new ones above.

### Task 6 — Extend `backend/tests/utils/test_logging_config.py`: `LOG_EXTRA_KEYS` whitelist regression test

   - Files: `backend/tests/utils/test_logging_config.py`
   - Dependency: land after Task 3.
   - Changes (PRD §7.3): This file is confirmed present (100 lines) and already tests `StructuredJsonFormatter.format()`'s whitelist pass-through (`test_extra_fields_serialized`, `test_unknown_extra_not_leaked`, etc., using its `make_record`/`fmt` helpers). Add:
     - `test_coverage_signal_key_is_whitelisted` — `from utils.constants import Constants; assert "coverage_signal" in Constants.Observability.LOG_EXTRA_KEYS`.
     - `test_coverage_signal_dict_serialized_verbatim` — using this file's existing `make_record`/`fmt` helpers: `result = fmt(make_record(extra={"coverage_signal": {"total": 3, "omitted": 1, "rate": 0.333, "omitted_by_category": {"medications": 1}}}))`; assert `result["coverage_signal"] == {"total": 3, "omitted": 1, "rate": 0.333, "omitted_by_category": {"medications": 1}}` — a direct regression guard for §4.3's "silently dropped if the key isn't whitelisted" failure mode, since that failure mode produces no error, only a quietly incomplete log line.
   - Acceptance criteria: `python -m pytest tests/utils/test_logging_config.py -q` (from `backend/`) passes in full, including the two new tests plus all pre-existing ones.

### Task 7 — Full-suite verification and lint

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-6.
   - Changes (confirms PRD §4.5's "no other file changes" and §5/§6's "no API/frontend change" hold): no edit in this task; it only runs checks.
   - Acceptance criteria:
     - From `backend/`, `python -m pytest tests/ -q` passes with zero failures and zero errors.
     - `ruff check .` (from `backend/`) is clean for `backend/care_plan/pipeline.py`, `backend/utils/constants.py`, and every test file this PRD touched.
     - `grep -rn "PipelineRunResult" backend/models/pipeline_events.py` still shows exactly the pre-existing three fields (`care_plan`, `term_data`, `raw_text`) — no fourth field added, confirming PRD §4.5's resolution held.
     - `git diff --stat` (or equivalent) for this PRD's full change set touches only: `backend/care_plan/pipeline.py`, `backend/utils/constants.py`, `backend/tests/care_plan/test_pipeline_review.py`, `backend/tests/care_plan/test_pipeline_streaming.py`, `backend/tests/utils/test_logging_config.py` — no route file, no frontend file, no `docs/data-and-privacy.md` edit (see note below on why that doc is not touched).
     - `grep -rn "review.txt\b" backend/care_plan/pipeline.py backend/care_plan/prompts/review.txt` shows no edit was made to the reviewer prompt (PRD §3 Non-Goals) — a byte-identical file if diffed against the pre-PRD version.

---

## Note: `docs/data-and-privacy.md` requires no edit

PRD context instructed checking whether §4.4's PHI decision (category only, never fact text) requires a documentation edit. It does not, and no task above touches that file. Reasoning: `docs/data-and-privacy.md` has no section enumerating backend Cloud Logging fields or internal pipeline log lines — its "Analytics" section is scoped specifically to the optional GA4 frontend integration (event parameters), and its "What is stored, and where" / "Every deletion path" tables describe Firestore/Cloud Storage/GCS objects, not `logger.info`/`logger.warning` call sites. This PRD's `coverage_signal` payload (an aggregate count plus a fixed 8-member category vocabulary, never `fact.text`) is fully consistent with the document's existing "do not upload real PHI" posture and its analytics section's identical "never document content" rule for GA4 — it does not contradict, extend, or make stale anything currently written there. No new fact is being asserted about data handling that the document doesn't already generally cover.

## Summary of what requires you (not a dev agent)

Per PRD §8, these are session-local, judgement-based checks against real infrastructure that cannot be automated by a dev agent:

1. **Confirm log volume and shape once wired into the live pipeline** (ngrok + pm2, `SERVICE_MODE=combined`): run a real note through the full pipeline and inspect the emitted `"review: coverage signal"` line directly (dev-mode plain-text formatter, so read the line as printed) — confirm `total`/`omitted`/`rate`/`omitted_by_category` look sane against the note's actual fact count, and confirm the line appears exactly once per completed run with a successful `review()` call.
2. **Decide whether/when to build a Cloud Logging-based metric or alerting policy** on `jsonPayload.coverage_signal.rate`, once this has run in a live environment long enough to have a baseline. This is console/Terraform configuration, not code — out of scope for any task above, flagged only as the natural next step §4.5 argues logging-alone enables. No threshold should be guessed at with zero production data.
3. **No new environment variables, credentials, or console configuration are required to land the tasks above** — the `LOG_EXTRA_KEYS` addition is a pure code change; only the optional follow-up (item 2) would ever need console/IaC work, and that is explicitly deferred.
4. **Sanity-check the omission rate against PRD 05 §7.5's injected-error catch-rate protocol, if/when that protocol is run.** They measure different things (this PRD's rate is the reviewer's own self-reported coverage on real, unperturbed runs; §7.5 measures catch rate against known, injected errors) but a wildly inconsistent picture between the two would be worth a second look.

No PRD §9 items are `[OPEN]` — the gate was clear (verified: every item in §9 is `[RESOLVED: ...]` or explicitly `[DEFERRED: ...]` to a documented, non-blocking future decision); all 7 tasks above derive from `[RESOLVED]` decisions only.
