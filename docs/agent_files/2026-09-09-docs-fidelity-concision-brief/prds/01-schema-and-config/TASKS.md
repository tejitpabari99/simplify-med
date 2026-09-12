# Tasks: Schema and Config

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on nothing (root of the decomposition). Depended on by: 02, 03, 04, 05, 06, 07, 08.

**Conventions**

- Backend tests: from `backend/`, run `python -m pytest tests/ -q` (matches CI, `.github/workflows/*.yml`). To run a single file/test: `python -m pytest tests/models/test_care_plan.py -q` or `python -m pytest tests/models/test_care_plan.py::test_name -q`. `pyproject.toml`'s `addopts` already adds `--cov=. --cov-report=term-missing`; no extra flags needed.
- Lint (optional but matches repo config): `ruff check .` from `backend/` (`pyproject.toml`'s `[tool.ruff]`, `select = ["F"]`).
- No frontend changes in this PRD (see PRD §6, §3 Non-Goals) — no frontend test commands needed here.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given (later tasks depend on earlier ones landing first — see each task's dependency note).
- Every task traces to PRD `## 4. Architecture Decisions`; do not add fields, files, or behavior beyond what's cited.

---

### Task 1 — Delete fabrication-risk and dead fields from `CarePlan`/`Diagnosis`/the five item models; retire `RawArtifacts`

   - Files: `backend/models/care_plan/care_plan.py`
   - Changes (PRD §4.1, "Full old → new field table" + "`RawArtifacts` retirement"):
     - On `CarePlan`: delete the `urgency` field (`Literal["normal","caution","concern","urgent"] = "normal"`) and the `additional_info` field (`list[str] = Field(default_factory=list)`).
     - On `CarePlan`: delete the `raw: RawArtifacts | None = None` field. Delete the `RawArtifacts` class entirely (currently lines 101-104). Nothing replaces `raw` on `CarePlan` — see PRD §4.1's "RawArtifacts retirement" subsection; the ledger this PRD adds in Task 4 is a separate, non-`CarePlan` module and must NOT be attached here.
     - On `Diagnosis`: delete `main_conclusion: str = ""`.
     - On `Medication`, `Test`, `Procedure`, `OtherInstruction`, `WarningSign` (all five): delete `importance: Constants.Enums.IMPORTANCE = Constants.Enums.IMPORTANCE.LOW` and `source: Constants.Enums.SOURCE | None = None`.
     - Do not touch `Constants.Enums` itself yet (Task 3 does that, after these usages are gone) or anything under §4.1's "new field" changes (Task 2 does those, in the same file).
   - Acceptance criteria:
     - `backend/models/care_plan/care_plan.py` has no remaining reference to `Constants.Enums`, `RawArtifacts`, `urgency`, `additional_info`, or `main_conclusion`.
     - The module still imports (`python -c "from models.care_plan.care_plan import CarePlan"` from `backend/`) — it will still fail at this point only if Task 2's additions aren't done yet in the same edit pass; if you land Task 1 and Task 2 as separate commits, expect this file to be transiently invalid mid-way (that's fine — land Tasks 1+2 as a single commit if you prefer, since they're the same file and the PRD treats them as one field table). Either way, after Task 2 is also done, `python -m pytest tests/models/test_care_plan.py -q` and `python -m pytest tests/models/test_readpath_tolerance.py -q` are the tests that exercise this file (they will still show fixture-drift failures until Tasks 8-11 land — that's expected and tracked there, not a regression in this task).

### Task 2 — Add `status`, `source_fact_ids`, `summary_fact_ids`; make `WarningSign.urgency` nullable; fold `Medication.change`/`change_description`

   - Files: `backend/models/care_plan/care_plan.py` (same file as Task 1 — land together or immediately after)
   - Changes (PRD §4.1):
     - On `CarePlan`, add a sibling field next to `summary`:
       ```python
       summary_fact_ids: list[int] = Field(default_factory=list)
       ```
     - On `Medication`, `Test`, `Procedure`, `OtherInstruction`, `FollowUp` (all five — `FollowUp` included per PRD §4.1's explicit call-out), add a required field with no default:
       ```python
       status: Literal["to_do", "done"]
       ```
     - On `Medication`, `Test`, `Procedure`, `OtherInstruction`, `FollowUp`, `WarningSign` (all six), add:
       ```python
       source_fact_ids: list[int] = Field(default_factory=list)
       ```
     - On `WarningSign`, change:
       ```python
       urgency: Literal["emergency", "call_doctor", "monitor", "normal_side_effect"] = "monitor"
       ```
       to:
       ```python
       urgency: Literal["emergency", "call_doctor", "monitor", "normal_side_effect"] | None
       ```
       No default — the field must always be present in a payload, but its value may be `null`. Do not write `= None` after the type (that would make it optional-with-default, i.e. omittable — the PRD is explicit this must stay required-but-nullable).
     - On `Medication`, replace:
       ```python
       change: bool = False
       change_description: str = ""
       ```
       with the single field:
       ```python
       change: str = ""
       ```
   - Acceptance criteria:
     - `CarePlan` has `summary_fact_ids: list[int]` defaulting to `[]`.
     - `Medication`, `Test`, `Procedure`, `OtherInstruction`, `FollowUp` each require `status` (constructing one without `status=` raises `pydantic.ValidationError`); `Medication`, `Test`, `Procedure`, `OtherInstruction`, `FollowUp`, `WarningSign` each default `source_fact_ids` to `[]` when omitted.
     - `WarningSign(...)` without `urgency=` raises `ValidationError`; `WarningSign(urgency=None, ...)` (with all other required fields, if any) validates successfully.
     - `Medication` has exactly one `change: str` field (no `change_description`, no boolean `change`).
     - These behaviors get their permanent regression tests in Task 9 below (this task is just the schema edit).

### Task 3 — Delete `Constants.Enums` (`SOURCE`, `IMPORTANCE`) from `backend/utils/constants.py`

   - Files: `backend/utils/constants.py`
   - Changes (PRD §4.2): Delete the entire `class Enums:` block (currently lines 139-147), including both nested enums `SOURCE` and `IMPORTANCE`. Do not touch `class Pipeline: / PIPELINE_STEPS` (same file, unrelated, explicitly out of scope per PRD §3 Non-Goals and §4.2's "Confirm no accidental collateral" note).
   - Dependency: land after Tasks 1+2 (which remove every usage of `Constants.Enums.*` from `care_plan.py` — the only consumer, per PRD §4.2's grep).
   - Acceptance criteria:
     - `grep -rn "Constants.Enums" backend --include=*.py` returns zero hits anywhere in the repo.
     - `python -c "from utils.constants import Constants; Constants.Enums"` (run from `backend/`) raises `AttributeError`.
     - `python -c "from utils.constants import Constants; Constants.Pipeline.PIPELINE_STEPS.READ_NOTE"` (run from `backend/`) still works unchanged.

### Task 4 — New module `backend/models/ledger.py`: `Unit`, `Fact`, `FactCategory`, `quote_for`

   - Files: `backend/models/ledger.py` (new file)
   - Changes (PRD §4.3): Create the file with exactly the contract specified in PRD §4.3 — module docstring, `FactCategory` (the eight-value `Literal`, spelled identically to `CarePlan`'s top-level field names: `reason_for_visit`, `diagnosis`, `medications`, `tests`, `procedures`, `other`, `follow_up`, `warning_signs`), `Unit(JsonModel)` with fields `id: int`, `file: str`, `page: int`, `line: int`, `text: str`, `Fact(JsonModel)` with fields `id: int`, `category: FactCategory`, `unit_id: int`, `char_start: int`, `char_end: int`, `text: str` (no `quote` field — deliberately dropped per PRD §9's resolved decision), and the module-level function:
     ```python
     def quote_for(fact: Fact, units_by_id: dict[int, Unit]) -> str:
         return units_by_id[fact.unit_id].text[fact.char_start:fact.char_end]
     ```
     Import `JsonModel` from `.base` (same pattern as `backend/models/job.py`, `backend/models/grading.py`). Do not place this under `models/care_plan/` (PRD §4.3's explicit "why not" rationale — the ledger is deliberately not part of the `CarePlan` family). Do not modify `backend/models/pipeline_events.py` — that's explicitly out of scope for this PRD (§4.1's "Where the ledger actually lives" note; flagged for 06).
   - Acceptance criteria:
     - `python -c "from models.ledger import Unit, Fact, FactCategory, quote_for"` (from `backend/`) succeeds.
     - `Fact` has no `quote` attribute; constructing `Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="x", quote="y")` raises `ValidationError` (extra key forbidden, inherited from `JsonModel`).
     - Covered permanently by the new `test_ledger.py` in Task 10.

### Task 5 — Close the dead `firestore.rules` clause; delete `JobDoc.shared`

   - Files: `firestore.rules`, `backend/models/job.py`
   - Changes (PRD §4.4):
     - In `firestore.rules`, in the `match /care_plan_outputs/{docId}` block, change:
       ```
       allow get: if resource == null
                   || (request.auth != null && request.auth.uid == resource.data.uid)
                   || resource.data.shared == true;
       ```
       to:
       ```
       allow get: if resource == null
                   || (request.auth != null && request.auth.uid == resource.data.uid);
       ```
       (Delete the `|| resource.data.shared == true` line only. Leave `allow list` and `allow write` and the `rate_limits` block untouched.)
     - In `backend/models/job.py`, delete the field declaration `shared: Optional[bool] = None` (currently line 55, in the "Single-job-only extras" section) and delete the `shared=False,` kwarg from the `for_single` factory (currently line 94).
   - Acceptance criteria:
     - `firestore.rules` no longer contains the string `shared`.
     - `python -c "from models.job import JobDoc; JobDoc.for_single(user_id='u', now=__import__('datetime').datetime.now(), trace_id=None, input_fields={'input_source_kind':'text','input_text':'x','input_source_filename':'f','input_pdf_gcs_uri':None,'input_version':'v1-2','grading_enabled':False})"` (from `backend/`) succeeds and the resulting object has no `shared` attribute.
     - `backend/tests/models/test_job.py` still fails at this point until Task 12 fixes its `shared` assertion — expected, tracked there.

### Task 6 — Configurable CORS origins via `CORS_ALLOWED_ORIGINS`

   - Files: `backend/app.py`, `backend/utils/constants.py`
   - Changes (PRD §4.5):
     - In `backend/app.py`, replace the current inline `CORS(app, origins=[...], ...)` call (currently lines 38-50) with a resolver function plus the same `CORS(...)` call reading from it:
       ```python
       _DEFAULT_CORS_ORIGINS = [
           "https://juno-medical-clarity.web.app",        # production Firebase Hosting site
           "https://juno-medical-clarity.firebaseapp.com",  # Firebase Hosting's alternate default domain
           "http://localhost:5173",                       # frontend dev server
       ]


       def _cors_allowed_origins() -> list[str]:
           """CORS_ALLOWED_ORIGINS is a comma-separated list, e.g.
           "https://abcd1234.ngrok-free.app,http://localhost:5173". Falls back to
           the hardcoded production + local-dev origins when unset or empty, so
           production behavior is unchanged with no env var configured."""
           raw = _os.environ.get("CORS_ALLOWED_ORIGINS", "")
           origins = [o.strip() for o in raw.split(",") if o.strip()]
           return origins or _DEFAULT_CORS_ORIGINS


       CORS(
           app,
           origins=_cors_allowed_origins(),
           methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
           allow_headers=["Content-Type", "Authorization", "X-Session-Id"],
           expose_headers=["X-Session-Id", "X-Trace-Id"],
           supports_credentials=False,
           max_age=600,
       )
       ```
       `app.py` already imports `os as _os` at the top (line 9) — reuse it, don't add a second import. Place `_DEFAULT_CORS_ORIGINS`/`_cors_allowed_origins` immediately above the `CORS(...)` call, keeping `methods`/`allow_headers`/`expose_headers`/`supports_credentials`/`max_age` byte-for-byte unchanged (only `origins` becomes dynamic).
     - In `backend/utils/constants.py`, add one line to `class EnvVars:` (alongside the existing `SERVICE_MODE`, `K_SERVICE`, etc.): `CORS_ALLOWED_ORIGINS: str = "CORS_ALLOWED_ORIGINS"`. This is documentation only — `app.py` still reads the raw string literal `"CORS_ALLOWED_ORIGINS"` directly (matching the file's existing inconsistent style, per PRD §4.5), it does not need to reference `Constants.EnvVars.CORS_ALLOWED_ORIGINS`.
   - Acceptance criteria:
     - With no `CORS_ALLOWED_ORIGINS` env var set, `_cors_allowed_origins()` returns the same 3-element list as the old hardcoded `origins=[...]` — production behavior is unchanged.
     - With `CORS_ALLOWED_ORIGINS=https://foo.ngrok-free.app,http://localhost:5173` set, `_cors_allowed_origins()` returns `["https://foo.ngrok-free.app", "http://localhost:5173"]`.
     - With `CORS_ALLOWED_ORIGINS=` (empty string) set, `_cors_allowed_origins()` falls back to the default 3-element list.
     - `Constants.EnvVars.CORS_ALLOWED_ORIGINS == "CORS_ALLOWED_ORIGINS"`.
     - No existing test currently covers `app.py`'s CORS setup (confirmed: no `test_app.py` exists) — this task does not need to add one; manual verification via the criteria above is sufficient, per PRD scope (no new test is specified for this in §7.3).

### Task 7 — Fix `derive_output_name`'s dead priority-2 fallback

   - Files: `backend/utils/misc.py`
   - Changes (PRD §4.6): In `derive_output_name` (currently lines 14-52), replace the `main_conclusion`-based fallback:
     ```python
     diagnosis = care_plan_data.get("diagnosis") or {}
     main = (diagnosis.get("main_conclusion") or "").strip()
     if main:
         first_sentence = main.split(".")[0].strip()
         if first_sentence:
             return first_sentence[:60]
     ```
     with:
     ```python
     diagnosis = care_plan_data.get("diagnosis") or {}
     details = diagnosis.get("details") or []
     if details:
         label = (details[0].get("plain_name") or details[0].get("title") or "").strip()
         if label:
             return label[:60]
     ```
     Also update the function's docstring line `2. diagnosis.main_conclusion first sentence` to `2. diagnosis.details[0].plain_name (or .title)`, since the docstring documents the priority order. No other part of the function (the `reason_for_visit` priority-1 branch, filename/group/appointment fallbacks, the `except Exception: pass` wrapper) changes.
   - Dependency: land after Task 1 (which deletes `main_conclusion` from the schema — this is that deletion's direct consequence, per PRD §4.6).
   - Acceptance criteria:
     - `derive_output_name({"reason_for_visit": [], "diagnosis": {"details": [{"plain_name": "Hypertension"}]}})` returns `"Hypertension"`.
     - `derive_output_name({"reason_for_visit": [], "diagnosis": {"details": [{"title": "Hypertension Diagnosis"}]}})` (no `plain_name`) returns `"Hypertension Diagnosis"`.
     - Permanent regression test updated in Task 14 below.

### Task 8 — Rewrite `backend/tests/fixtures/care_plan.json` to the new schema shape

   - Files: `backend/tests/fixtures/care_plan.json`
   - Changes (PRD §7.1, row 1): Rewrite the fixture so it round-trips through the `CarePlan` model produced by Tasks 1-2:
     - Delete top-level `urgency`, `additional_info`, and `raw`.
     - Delete `diagnosis.main_conclusion`.
     - Delete `importance` and `source` from every item in `medications`, `tests`, `procedures`, `other`, `warning_signs`.
     - Add `"status": "to_do"` (or `"done"` for variety — pick one non-default value on at least one entry to prove both values round-trip) to the single entries in `medications`, `tests`, `procedures`, `other`, and `follow_up`.
     - Fold `medications[0].change`/`.change_description` (`true` / `"This medicine was started today."`) into one field: `"change": "This medicine was started today."`.
     - Add `"summary_fact_ids": [1, 2, 3]` at the top level (sibling of `summary`).
     - Add a small non-empty `"source_fact_ids"` (e.g. `[1]`) to the single entry in each of the six item lists (`medications`, `tests`, `procedures`, `other`, `follow_up`, `warning_signs`).
     - Leave `warning_signs[0].urgency` as `"emergency"` (a valid non-null value) — the fixture doesn't need to exercise the null case (that's covered by the new unit tests in Task 9); it does need to still be present since the field remains required.
     - Leave everything else (`doc_type`, `version`, `summary`, `reason_for_visit`, `diagnosis.changed_since_last_visit`, `diagnosis.details`, `questions`, `low_priority`, `note`, `terms`) unchanged.
   - Dependency: land after Tasks 1-2 (defines the shape this fixture must match).
   - Acceptance criteria:
     - The rewritten JSON is valid JSON and contains none of: `urgency`, `additional_info`, `raw`, `main_conclusion`, `importance`, `source` (as item-model field names — note `terms.Hypertension.source` is `GlossaryTerm.source`, an unrelated untouched field per PRD §4.2's grep, and must stay), `change_description`.
     - Every entry in `medications`/`tests`/`procedures`/`other`/`follow_up` has a `status` key with value `"to_do"` or `"done"`.
     - `python -m pytest tests/models/test_care_plan.py::test_care_plan_round_trips_full_fixture -q` (from `backend/`) passes once Task 9's companion fixes land (this test itself needs no code change per PRD §7.1 — it just round-trips whatever the fixture contains).

### Task 9 — Update `backend/tests/models/test_care_plan.py`: fix drifted assertions, add new required-field/nullability/default tests

   - Files: `backend/tests/models/test_care_plan.py`
   - Changes (PRD §7.1 row 3, §7.3):
     - In `test_care_plan_minimal_payload_uses_pipeline_defaults`, delete the line `assert model.urgency == "normal"` and the line `assert model.raw is None`. Every other assertion in that test is unaffected (an empty `medications`/`tests`/etc. list never triggers the new `status`-required validation, since there are no items to validate).
     - Add a new test asserting `WarningSign(...)` constructed without `urgency=` raises `ValidationError` (proves "no default" took):
       ```python
       def test_warning_sign_requires_urgency():
           with pytest.raises(ValidationError):
               WarningSign(symptom="x", what_to_do="y", source_fact_ids=[])
       ```
       (Import `WarningSign` from `models.care_plan.care_plan` alongside the existing `Diagnosis` import.)
     - Add a new test asserting `WarningSign(urgency=None, ...)` validates successfully (proves nullable took):
       ```python
       def test_warning_sign_accepts_null_urgency():
           sign = WarningSign(symptom="x", what_to_do="y", urgency=None)
           assert sign.urgency is None
       ```
     - Add a new test asserting one of the five `status`-bearing models raises `ValidationError` when `status=` is omitted:
       ```python
       def test_medication_requires_status():
           from models.care_plan.care_plan import Medication
           with pytest.raises(ValidationError):
               Medication(title="x")
       ```
     - Add a new test asserting `source_fact_ids` defaults to `[]` when omitted, on one of the six item models:
       ```python
       def test_medication_source_fact_ids_defaults_empty():
           from models.care_plan.care_plan import Medication
           med = Medication(title="x", status="to_do")
           assert med.source_fact_ids == []
       ```
   - Dependency: land after Tasks 1-2 and Task 8 (fixture).
   - Acceptance criteria: `python -m pytest tests/models/test_care_plan.py -q` (from `backend/`) passes in full, including the four new tests above and the two pre-existing "rejects extra key" tests (unaffected, PRD §7.1 row 2).

### Task 10 — New `backend/tests/models/test_ledger.py`

   - Files: `backend/tests/models/test_ledger.py` (new file)
   - Changes (PRD §7.3): Create tests covering `Unit`/`Fact`/`quote_for` from Task 4:
     - Round-trip: construct a `Unit` and a `Fact`, call `.to_dict()` then `.from_dict()`, assert equality.
     - `extra="forbid"` regression guard: assert constructing `Fact(..., quote="some text")` (a valid `Fact` plus the deleted `quote` key) raises `ValidationError` — this is the specific "don't reintroduce the old field by habit" guard the PRD calls for.
     - `Fact.category` rejects a value outside the eight-item `FactCategory` `Literal` (e.g. `category="not_a_category"` raises `ValidationError`).
     - `Fact` requires `id`, `category`, `unit_id`, `char_start`, `char_end`, `text` — omitting any one raises `ValidationError` (a single parametrized test or one assertion per field is fine).
     - `test_quote_for_returns_unit_text_slice`: construct `Unit(id=1, file="f.pdf", page=1, line=1, text="Continue metoprolol 25 mg twice daily")`, a `Fact` citing it with `char_start`/`char_end` matching the substring `"metoprolol 25 mg"`, call `quote_for(fact, {1: unit})`, assert the result equals `"metoprolol 25 mg"` exactly (byte-for-byte).
     - `test_quote_for_raises_key_error_on_unknown_unit_id`: build `units_by_id` missing the fact's `unit_id`, assert `quote_for(fact, units_by_id)` raises `KeyError`.
   - Dependency: land after Task 4.
   - Acceptance criteria: `python -m pytest tests/models/test_ledger.py -q` (from `backend/`) passes; all listed cases present.

### Task 11 — Repoint `backend/tests/models/test_readpath_tolerance.py` to `CarePlan.note`

   - Files: `backend/tests/models/test_readpath_tolerance.py`
   - Changes (PRD §7.1 row 4): Rename `test_care_plan_without_raw_validates_for_free_read_tolerance` to `test_care_plan_without_note_validates_for_free_read_tolerance`, and change its body from popping `"raw"` to popping `"note"`:
     ```python
     def test_care_plan_without_note_validates_for_free_read_tolerance():
         data = json.loads(FIXTURE_PATH.read_text())
         data.pop("note")

         # No migration or legacy-handling code; this is only free read tolerance.
         model = CarePlan.model_validate(data)

         assert model.note is None
     ```
     Do not delete the test — the PRD is explicit this preserves the regression-guard pattern (documents that an optional field may legitimately be absent from an older stored doc) for the next optional field someone adds, rather than losing the coverage `raw`'s retirement would otherwise take with it.
   - Dependency: land after Task 8 (fixture no longer has `raw`; still has `note: null`, unaffected by Task 8).
   - Acceptance criteria: `python -m pytest tests/models/test_readpath_tolerance.py -q` (from `backend/`) passes with the new test name and body; `grep -n "raw" backend/tests/models/test_readpath_tolerance.py` returns no hits.

### Task 12 — Fix `backend/tests/models/test_job.py`'s `shared` assertion

   - Files: `backend/tests/models/test_job.py`
   - Changes (PRD §7.1 row 6): In `test_for_single_sets_shared_trace`, delete the line `assert job.shared is False`. Keep `assert job.trace_id == "abc123"` and `assert job.status == StatusEnum.not_started`. Rename the test to `test_for_single_sets_trace` (PRD's suggestion, since "shared" is no longer part of what it verifies).
   - Dependency: land after Task 5 (`JobDoc.shared` deleted).
   - Acceptance criteria: `python -m pytest tests/models/test_job.py -q` (from `backend/`) passes in full; `grep -n "shared" backend/tests/models/test_job.py` returns no hits.

### Task 13 — Fix `backend/tests/routes/test_jobs_e2e_scenarios.py`: rules docstring + `_build_care_plan` helper

   - Files: `backend/tests/routes/test_jobs_e2e_scenarios.py`
   - Changes (PRD §7.1 rows 7-9):
     - In `test_firestore_rules_static_review_note` (currently ~line 1272), update the docstring's quoted rule to the new 2-clause form (delete the `|| resource.data.shared == true` line from the quoted rule block) and delete the sentence "so `get`/`list`... fails BOTH the uid check and the shared check for user A's doc" — replace with the equivalent uid-only explanation: an anonymous user B's token (`uid != resource.data.uid`) fails the uid check, so `get`/`list` are denied. The rest of the docstring (write always denied, Admin SDK bypasses rules, "not independently verified against a live emulator") stays.
     - In `_build_care_plan` (currently lines 251-334):
       - Remove the `RawArtifacts` import from the `from models.care_plan.care_plan import (...)` line (currently line 256), and delete the `raw = RawArtifacts(text="x" * 3000, simplified_text="y" * 3000, clarified_text="z" * 3000)` line (currently line 309) and the `raw=raw,` kwarg on the final `CarePlan(...)` call.
       - Remove `importance="high",` / `importance="low",` from all four call sites: the `Medication(...)` comprehension (line 267), the `Test(...)` comprehension (line 277), the `Procedure(...)` comprehension (line 287), and the `WarningSign(...)` comprehension (line 298).
       - Remove `main_conclusion="Your blood pressure remains elevated and needs medication adjustment.",` from the `Diagnosis(...)` call (line 316).
       - Add required `status="to_do"` to the `Medication(...)` comprehension and the `Test(...)` comprehension; add `status="done"` to the `Procedure(...)` comprehension (mix values per PRD §7.1's "for variety" guidance elsewhere in this pass — any valid literal is acceptable, just make sure every `Medication`/`Test`/`Procedure` instance gets one, since `status` has no default). `WarningSign` does not get `status` (it's not one of the five `status`-bearing models). The `FollowUp(time_frame="2 weeks", description="Return for a blood pressure check.")` call on line 328 also needs `status="to_do"` added (it's one of the five).
     - Do **not** change any of the numeric size-budget assertions elsewhere in this file (`_doc_size_bytes`, `_max_leaf_string_bytes`, the `< 1_048_576` / `< 1500` thresholds, or the `size`/`n` scaling logic) — recalibrating those now that `RawArtifacts`'s 9000-char padding is gone is explicitly deferred to 06 (PRD §7.1 row 9, `[RESOLVED: division of labor]` in §9). This task's job is only to make every test in this file construct valid models again.
   - Dependency: land after Tasks 1, 2, and 5.
   - Acceptance criteria:
     - `python -m pytest tests/routes/test_jobs_e2e_scenarios.py -q` (from `backend/`) — every test in the file at least constructs its fixtures without `TypeError`/`ValidationError` from `_build_care_plan`. (Some size-budget assertions may now pass or fail differently than before purely because `RawArtifacts`'s padding is gone — per the division-of-labor resolution, that recalibration is 06's job, not this task's; do not edit thresholds to force green here. If a threshold assertion fails only because of the missing padding, leave it — flag it in your task-completion notes so 06 knows this file needs threshold recalibration, but do not change the numbers yourself.)
     - `grep -n "RawArtifacts\|main_conclusion\|importance=" backend/tests/routes/test_jobs_e2e_scenarios.py` returns no hits.
     - `test_firestore_rules_static_review_note`'s docstring no longer contains the string `shared`.

### Task 14 — Fix `backend/tests/utils/test_misc.py::test_diagnosis_fallback`

   - Files: `backend/tests/utils/test_misc.py`
   - Changes (PRD §7.1 row 10): Replace:
     ```python
     def test_diagnosis_fallback():
         data = {"reason_for_visit": [], "diagnosis": {"main_conclusion": "Hypertension. More details."}}
         result = derive_output_name(data)
         assert result == "Hypertension"
     ```
     with:
     ```python
     def test_diagnosis_fallback():
         data = {"reason_for_visit": [], "diagnosis": {"details": [{"plain_name": "Hypertension"}]}}
         result = derive_output_name(data)
         assert result == "Hypertension"
     ```
   - Dependency: land after Task 7.
   - Acceptance criteria: `python -m pytest tests/utils/test_misc.py -q` (from `backend/`) passes in full, including this updated test and all pre-existing ones (`test_rfv_reason_title_cased`, `test_filename_fallback`, `test_group_fallback`, `test_appointment_fallback`, `test_max_60_chars`, `test_text_input_filename_skipped`, and the `extract_text_from_html` tests — none of which reference `main_conclusion` and are unaffected).

### Task 15 — Full-suite verification

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-14.
   - Acceptance criteria: from `backend/`, `python -m pytest tests/ -q` passes with zero failures and zero errors, **except** any pre-existing size-budget assertions in `test_jobs_e2e_scenarios.py` that Task 13 explicitly flagged as deferred-to-06 (if any such failures remain, list exactly which test functions and why, referencing Task 13's note — do not silently mark this task done if unrelated tests fail). Confirm via `grep -rn "Constants.Enums\|RawArtifacts\|additional_info\|main_conclusion" backend --include=*.py` that all four are fully gone from the codebase (zero hits).

---

## Handed off to PRD 06 (specified here, not implemented here — do not action as part of this task list)

Per PRD §3 Non-Goals and §4.1.4/§4.1's explicit "flagged for 06" notes, the following are **out of scope for this PRD's tasks** even though this PRD specifies exactly what they must do. Do not implement these against this TASKS.md — they're recorded here only so whoever picks up 06 has the pointer, per the PRD's own cross-references:

- **Strip `summary_fact_ids`/`source_fact_ids` before persistence** (PRD §4.1's "internal provenance fields" note): a `_strip_internal_provenance(care_plan_dict)` helper (or equivalent) added at `routes/worker.py:195-203`, alongside the existing `.pop("raw", None)` / `.pop("input.text", None)` calls, popping `care_plan.summary_fact_ids` and `source_fact_ids` off every item in `medications`/`tests`/`procedures`/`other`/`follow_up`/`warning_signs`. Must land in the same change that makes 04 actually populate these fields (an unpopulated field has nothing to leak; a populated, un-stripped one is a live provenance leak).
- **Two new tests** proving the above: `test_job_completed_output_has_no_summary_fact_ids` and `test_job_completed_output_has_no_source_fact_ids` in `backend/tests/routes/test_worker.py`, mirroring the existing `test_job_completed_output_has_no_raw` (currently `test_worker.py:425-463`) pattern exactly.
- **Delete the now-dead `.pop("raw", None)`** at `routes/worker.py:198` (a no-op once `CarePlan.raw` no longer exists — harmless but confusing to leave forever).
- **Clean up `_STRUCTURING_SCHEMA`'s exclude set** at `care_plan/pipeline.py:61` (currently `exclude={"terms", "raw", "note"}`) — `"raw"` no longer needs to be named there once the field doesn't exist on `CarePlan` at all. Harmless to leave (confirmed: `_llm_schema`'s `.pop(field, None)` makes this a no-op either way, and `test_care_plan.py::test_structured_llm_schema_properties_match_care_plan_structured_fields` passes unchanged regardless).
- **Recalibrate `test_jobs_e2e_scenarios.py`'s doc-size-budget thresholds** now that `RawArtifacts`'s ~9000-char padding is gone from `_build_care_plan` (Task 13 above only makes the file construct valid models; it does not touch the size assertions themselves).
- Not from this PRD's own file scope, but flagged by the PRD for whoever consumes it: **`frontend/src/tests/fixtures/realCarePlanOutput.fixture.json`** needs regenerating against the new backend contract (§6) — this is sub-project 08's dependency, not touched here.

## Summary of what requires you (not a dev agent)

Per PRD §8, both items are session-local console/environment actions tied to your own accounts and cannot be automated by a dev agent:

1. **Firebase Auth authorized domains**: each time you start an ngrok tunnel for local `SERVICE_MODE=combined` testing, add that session's ngrok domain to Firebase Auth's authorized domains list yourself (Firebase Console → Authentication → Settings → Authorized domains).
2. **Set `CORS_ALLOWED_ORIGINS` locally per session**: once Task 6 lands, set `CORS_ALLOWED_ORIGINS=https://<your-ngrok-domain>.ngrok-free.app,http://localhost:5173` in your local environment before starting the backend each time you tunnel (free ngrok domains rotate on restart, so this is a recurring manual step even though the code change makes it possible instead of requiring a source edit).

No PRD §9 items are `[OPEN]` — the gate was clear; all 15 tasks above derive from `[RESOLVED]` decisions only.
