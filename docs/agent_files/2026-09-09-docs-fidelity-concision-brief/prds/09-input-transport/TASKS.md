# Tasks: Input Transport

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01 (schema-and-config — `JobDoc` shape, `shared` field removal), 02 (unitization-and-provenance — `SourceSpan`, `models/provenance.py`, `services.unitizer.unitize`, `resolve_uploaded_files`'s `provenance` output, `JobDoc.input_provenance`, `resolve_input_from_job_doc`/`resolve_units_from_job_doc`), 06 (pipeline-orchestration — `routes/worker.py`'s `units` wiring, `_strip_internal_provenance`, and `complete_job`'s `stage` field). **This PRD lands only after PRDs 01, 02, and 06 have landed exactly as written on this branch** (PRD §3, §9's `[RESOLVED: ordering]` entry) — every task below is written against that post-01/02/06 code state, not the code currently checked out on `docs/fidelity-concision-brief` (01/02/06 haven't landed yet as of this writing). Where a task's "old" snippet differs from what you'd see by reading the repo today, that's expected — it's what 01/02/06 leave behind, not a mistake in this file. Depended on by: none (leaf, PRD §"Depended on by").

**Conventions**

- Backend tests: from `backend/`, run `python -m pytest tests/ -q` (matches CI). To run a single file/test: `python -m pytest tests/services/test_care_plan_input.py -q` or `...::test_name -q`. `pyproject.toml`'s `addopts` already adds `--cov=. --cov-report=term-missing`; no extra flags needed.
- Frontend tests: from `frontend/`, run `npm test` (or the project's configured vitest command) — only `frontend/src/utils/validateFiles.ts` and its test file are touched (PRD §6, §4.12).
- Lint (optional but matches repo config): `ruff check .` from `backend/`.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given (later tasks depend on earlier ones landing first — see each task's dependency note).
- Every task traces to PRD `## 4. Architecture Decisions`; do not add fields, files, or behavior beyond what's cited.
- **Prerequisite check before starting Task 1**: confirm `python -c "from models.job import JobDoc; JobDoc.model_fields['input_provenance']"` (from `backend/`) succeeds and `python -c "from services.care_plan_input import resolve_input_from_job_doc, resolve_units_from_job_doc"` succeeds — both confirm 01/02/06 have actually landed on this branch. If either fails, stop: those PRDs' own task lists must land first.

---

### Task 1 — `backend/models/provenance.py`: add `JobInputPayload`

   - Files: `backend/models/provenance.py` (existing file, created by 02's Task 1 — home of `SourceSpan`)
   - Changes (PRD §4.1, §4.2):
     - Add `from pydantic import Field` to the file's imports if not already present (02's Task 1 snippet does not import `Field`; confirm at implementation time and add only if missing).
     - Add the new model, using the exact docstring from PRD §4.1 (it documents why this model is persisted to a GCS object rather than Firestore, and how it differs from both `SourceSpan` and `Unit`/`Fact`):
       ```python
       class JobInputPayload(JsonModel):
           """Wire shape of the GCS object services.care_plan_input.upload_job_input
           writes and load_job_input reads back -- the whole reason this object
           exists is to carry input_text and input_provenance from the API to the
           worker as one payload (PRD 09 §4.1), since the one function that ever
           consumes either (services.unitizer.unitize) always consumes both.

           Like SourceSpan, this model IS written to a persistence layer (a GCS
           object, not Firestore) -- unlike Unit/Fact, which never touch storage
           at all. Unlike SourceSpan, it never appears as a JobDoc field; it is
           the object input_payload_gcs_uri points AT, not a value stored inline.
           """

           text: str
           provenance: list[SourceSpan] = Field(default_factory=list)
       ```
     - Do not place `JobInputPayload` in `models/ledger.py`, `models/job.py`, or a new file (PRD §4.1's "Rejected: two objects" reasoning and §4.2's placement rationale — same module as `SourceSpan`, the persistence-layer half of the provenance design).
   - Acceptance criteria:
     - `python -c "from models.provenance import JobInputPayload, SourceSpan"` (from `backend/`) succeeds.
     - `JobInputPayload(text="hello", provenance=[])` constructs; round-trips through `.to_dict()`/`.from_dict()`.
     - `JobInputPayload(text="x", provenance=[], extra="y")` raises `ValidationError` (inherited `extra="forbid"` from `JsonModel`).
     - Covered permanently by the new tests added to `test_provenance.py` in Task 9.

### Task 2 — `backend/utils/gcs.py`: add `download_gcs_string`

   - Files: `backend/utils/gcs.py`
   - Changes (PRD §4.3): Add the new function below the existing `delete_gcs_object` (leave `get_gcs_bucket`, `delete_gcs_object`, `_gcs_client` byte-for-byte unchanged):
     ```python
     def download_gcs_string(gcs_uri: str) -> str:
         """Download and return the text contents of a gs:// object.

         Unlike delete_gcs_object, this does NOT swallow failures -- a caller
         that needs this content cannot proceed without it (see
         services.care_plan_input.load_job_input, PRD 09 §4.9, which is this
         function's only caller). Raises google.api_core.exceptions.NotFound if
         the object doesn't exist, or whatever the underlying client raises for
         any other failure (permission denied, network error, etc.) -- the
         caller is responsible for classifying and handling these, not this
         function.
         """
         if not gcs_uri.startswith("gs://"):
             raise ValueError(f"download_gcs_string called with non-gs:// uri={gcs_uri}")
         _, _, rest = gcs_uri.partition("gs://")
         bucket_name, _, blob_name = rest.partition("/")
         return _gcs_client().bucket(bucket_name).blob(blob_name).download_as_text()
     ```
     Note the URI-parsing logic (`partition("gs://")`/`partition("/")`) is deliberately duplicated from `delete_gcs_object` rather than extracted into a shared helper — PRD §4.3 is explicit this is intentional (two three-line `partition` calls aren't worth a shared helper, and keeping them textually identical means a reader auditing one can trust the other matches).
   - Acceptance criteria:
     - `python -c "from utils.gcs import download_gcs_string"` (from `backend/`) succeeds.
     - `download_gcs_string("not-a-gs-uri")` raises `ValueError`.
     - Covered permanently by the new `test_gcs.py` tests in Task 10.

### Task 3 — `backend/services/care_plan_input.py`: add `upload_job_input`

   - Files: `backend/services/care_plan_input.py`
   - Dependency: land after Tasks 1, 2.
   - Changes (PRD §4.5):
     - Update imports: `from models.provenance import SourceSpan` (already present per 02) gains `JobInputPayload` alongside it — `from models.provenance import SourceSpan, JobInputPayload`. Add `import json` (not currently imported in this file). Change `from utils.gcs import get_gcs_bucket` to `from utils.gcs import get_gcs_bucket, download_gcs_string`.
     - Add the new function, placed beside `upload_combined_pdf` (both are "resolve input → GCS" functions called from `routes/jobs.py::_resolve_job_input`):
       ```python
       def upload_job_input(text: str, provenance: list[SourceSpan], user_id: str) -> str:
           """Upload the (text, provenance) pair services.unitizer.unitize will
           later need, as one JSON object, to GCS -- the transport this PRD (09)
           chose over persisting either field on the Firestore job doc (PRD 02's
           original design). Mirrors upload_combined_pdf's bucket/prefix/naming
           convention exactly (same care_plan_inputs/{user_id}/inputs/ prefix,
           same fresh-uuid object naming -- see PRD 09 §4.4 for why the path is
           NOT derived from a job id), but writes a JSON payload instead of PDF
           bytes, and unlike the merged PDF, this write is NOT optional -- see
           PRD 09 §4.6 for why a failure here must propagate, not degrade.

           Unlike validate_extracted_text_length (called on `text` by every caller
           of this function before it's ever reached), this function does not
           re-validate text storability -- the UTF-8-encode this function's JSON
           serialization performs can still fail on a lone surrogate exactly as a
           Firestore write could, but validate_text_storable has already ruled
           that out upstream (PRD 09 §4.12's third bullet)."""
           bucket_name = os.environ.get(Constants.Storage.GCS_BUCKET_ENV_VAR, "")
           if not bucket_name:
               raise RuntimeError("GCP_BUCKET_NAME is not configured")

           object_id = str(uuid.uuid4())
           blob_name = f"care_plan_inputs/{user_id}/inputs/{object_id}.json"

           payload = JobInputPayload(text=text, provenance=provenance)
           bucket = get_gcs_bucket(bucket_name)
           blob = bucket.blob(blob_name)
           blob.upload_from_string(json.dumps(payload.to_dict()), content_type="application/json")
           return f"gs://{bucket_name}/{blob_name}"
       ```
       This reuses the module's existing `os`, `uuid`, and `Constants` imports (already present for `upload_combined_pdf`) — no new imports needed for those.
   - Acceptance criteria:
     - `python -c "from services.care_plan_input import upload_job_input"` (from `backend/`) succeeds.
     - `upload_job_input` with `GCP_BUCKET_NAME` unset raises `RuntimeError` (mirrors `upload_combined_pdf`'s existing guard).
     - Covered permanently by the new tests in Task 11.

### Task 4 — `backend/services/care_plan_input.py`: replace `resolve_input_from_job_doc`/`resolve_units_from_job_doc` with `load_job_input`

   - Files: `backend/services/care_plan_input.py`
   - Dependency: land after Task 3 (same file, builds on its imports).
   - Changes (PRD §4.9, §9's `[RESOLVED: deleted outright, not resigned]`):
     - Delete `resolve_input_from_job_doc` and `resolve_units_from_job_doc` outright (both currently defined in this file per 02's Task 8) — not kept as wrappers.
     - Add `load_job_input` in their place:
       ```python
       def load_job_input(job) -> tuple[str, list[SourceSpan]]:  # job: models.job.JobDoc
           """Download and parse the (text, provenance) pair the API wrote to GCS
           at job-creation time (upload_job_input, §4.5) -- the one GCS read this
           performs per job, spent once at the start of the worker's run
           (routes/worker.py). Supersedes resolve_input_from_job_doc and
           resolve_units_from_job_doc (PRD 02 §4.7), which read job.input_text/
           job.input_provenance directly off the job doc; neither field exists on
           JobDoc any more (PRD 09 §4.11).

           Raises SimplifyError(ErrorCode.PIPELINE_ERROR) -- never a bare
           exception -- if the job has no input_payload_gcs_uri at all, the
           object is missing, or its contents fail to parse as a JobInputPayload.
           This is an expected failure mode, not just a theoretical one: see PRD
           09 §4.10 for a concrete, code-derivable race that produces it."""
           if not job.input_payload_gcs_uri:
               raise SimplifyError(ErrorCode.PIPELINE_ERROR, detail="job has no input_payload_gcs_uri")
           try:
               raw = download_gcs_string(job.input_payload_gcs_uri)
               payload = JobInputPayload.from_dict(json.loads(raw))
           except SimplifyError:
               raise
           except Exception as exc:
               raise SimplifyError(
                   ErrorCode.PIPELINE_ERROR,
                   detail=f"failed to load job input from GCS: {type(exc).__name__}",
                   original=exc,
               ) from exc
           return payload.text, payload.provenance
       ```
       `ErrorCode`/`SimplifyError` are already imported in this file (`from errors import ErrorCode, SimplifyError`) — no new import needed for them.
   - Acceptance criteria:
     - `grep -n "def resolve_input_from_job_doc\|def resolve_units_from_job_doc" backend/services/care_plan_input.py` returns zero hits.
     - `python -c "from services.care_plan_input import load_job_input"` (from `backend/`) succeeds.
     - `load_job_input(job)` with `job.input_payload_gcs_uri = None` raises `SimplifyError` with `error_code == ErrorCode.PIPELINE_ERROR`.
     - Fully covered by the new tests in Task 11.

### Task 5 — `backend/routes/jobs.py::_resolve_job_input`: replace `input_text`/`input_provenance` with `upload_job_input`'s URI

   - Files: `backend/routes/jobs.py`
   - Dependency: land after Task 3.
   - Changes (PRD §4.6, §4.7):
     - Add the import: `from services.care_plan_input import upload_job_input` (alongside the existing `resolve_uploaded_files`, `upload_combined_pdf`, `validate_extracted_text_length` import).
     - Pasted-text branch — replace:
       ```python
       if text_input:
           validate_extracted_text_length(text_input)
           return {
               "input_source_kind": "text",
               "input_text": text_input,
               "input_source_filename": "text_input",
               "input_pdf_gcs_uri": None,
               "input_provenance": provenance_for_pasted_text(text_input),
               "input_version": Constants.Pipeline.PIPELINE_VERSION,
               "grading_enabled": True,
           }
       ```
       with:
       ```python
       if text_input:
           validate_extracted_text_length(text_input)
           provenance = provenance_for_pasted_text(text_input)
           input_payload_gcs_uri = upload_job_input(text_input, provenance, user_id)
           return {
               "input_source_kind": "text",
               "input_payload_gcs_uri": input_payload_gcs_uri,
               "input_source_filename": "text_input",
               "input_pdf_gcs_uri": None,
               "input_version": Constants.Pipeline.PIPELINE_VERSION,
               "grading_enabled": True,
           }
       ```
     - Upload branch — replace:
       ```python
       resolved, raw_pdf_bytes = resolve_uploaded_files(...)
       pdf_gcs_uri = upload_combined_pdf(raw_pdf_bytes, user_id) if raw_pdf_bytes else None
       return {
           "input_source_kind": "upload",
           "input_text": resolved.text,
           "input_source_filename": resolved.source_filename,
           "input_pdf_gcs_uri": pdf_gcs_uri,
           "input_provenance": resolved.provenance,
           "input_version": Constants.Pipeline.PIPELINE_VERSION,
           "grading_enabled": True,
           "skipped_files": resolved.skipped_files,
       }
       ```
       with:
       ```python
       resolved, raw_pdf_bytes = resolve_uploaded_files(...)
       pdf_gcs_uri = upload_combined_pdf(raw_pdf_bytes, user_id) if raw_pdf_bytes else None
       input_payload_gcs_uri = upload_job_input(resolved.text, resolved.provenance, user_id)
       return {
           "input_source_kind": "upload",
           "input_payload_gcs_uri": input_payload_gcs_uri,
           "input_source_filename": resolved.source_filename,
           "input_pdf_gcs_uri": pdf_gcs_uri,
           "input_version": Constants.Pipeline.PIPELINE_VERSION,
           "grading_enabled": True,
           "skipped_files": resolved.skipped_files,
       }
       ```
     - **`upload_job_input`'s success is not optional** (PRD §4.6): if it raises (missing bucket config, a transient GCS error, anything), let it propagate uncaught out of `_resolve_job_input` — do not wrap it in a `try/except`. It is not caught by `create_job`'s inner `except (ValueError, FileNotFoundError)`/`except SimplifyError` blocks, so an uncaught raise here falls through to `create_job`'s outer `except Exception: ... return INTERNAL_ERROR, 500` unchanged — no new exception handling needs to be added anywhere in `create_job` for this task.
     - **Ordering** (PRD §4.7): the `upload_job_input` call must land inside `_resolve_job_input` (step 1 of `create_job`'s existing sequence), at the same point `upload_combined_pdf` already runs — i.e. before the Cloud Tasks config validation (`require_env` calls) and before `job_id`/the Firestore doc are created. Do not move it later and do not change `create_job`'s existing ordering of Cloud-Tasks-check-before-Firestore-write.
   - Acceptance criteria:
     - `grep -n '"input_text"\|"input_provenance"' backend/routes/jobs.py` returns zero hits.
     - `POST /jobs` with `{"text": "line one\nline two"}`: the created `JobDoc`'s `input_payload_gcs_uri` is a `gs://` URI; no `input_text`/`input_provenance` key is ever passed to `create_job_doc`.
     - `POST /jobs` with a multi-file upload: same — `input_payload_gcs_uri` set, no `input_text`/`input_provenance` keys.
     - If `upload_job_input` is mocked to raise, `POST /jobs` returns 500 and `create_job_doc` is never called (proves the "never orphans a Firestore doc" property extends to this new failure point — the request fails before `create_job_doc` is ever reached, since `upload_job_input` runs inside `_resolve_job_input`, which runs before the Firestore write).
     - Fully covered by the new/rewritten tests in Task 14.

### Task 6 — `backend/models/job.py`: replace `input_text`/`input_provenance` with `input_payload_gcs_uri`

   - Files: `backend/models/job.py`
   - Dependency: land after Task 5 (so the field this task removes is no longer referenced by `_resolve_job_input`'s dict by the time this lands — though field removal on the model itself doesn't strictly require this ordering, landing after keeps the repo importable/consistent at every commit).
   - Changes (PRD §4.11):
     - Replace the "Input provenance" section:
       ```python
       # ── Input provenance ──────────────────────────────────────────────────
       input_source_kind: SourceKind
       input_text: Optional[str] = None
       input_source_filename: str
       input_pdf_gcs_uri: Optional[str] = None
       input_provenance: list[SourceSpan] = Field(default_factory=list)
       input_version: str = "v1-2"
       grading_enabled: bool = False
       ```
       with:
       ```python
       # ── Input provenance ──────────────────────────────────────────────────
       # input_text and input_provenance no longer live here -- both moved to a
       # GCS object referenced by input_payload_gcs_uri (PRD 09). Firestore
       # holds only what the frontend renders or what routing/cleanup needs;
       # the raw input text and its provenance map are neither.
       input_source_kind: SourceKind
       input_source_filename: str
       input_pdf_gcs_uri: Optional[str] = None
       input_payload_gcs_uri: Optional[str] = None
       input_version: str = "v1-2"
       grading_enabled: bool = False
       ```
     - Remove the now-unused `from .provenance import SourceSpan` import (added by 02's Task 7) — nothing in `job.py` references `SourceSpan` any more.
     - Update `for_single`'s docstring from:
       ```
       input_fields dict must contain:
         input_source_kind, input_text, input_source_filename,
         input_pdf_gcs_uri, input_provenance, input_version, grading_enabled
       ```
       to:
       ```
       input_fields dict must contain:
         input_source_kind, input_payload_gcs_uri, input_source_filename,
         input_pdf_gcs_uri, input_version, grading_enabled
       ```
       No other change to `for_single` — it already forwards `**input_fields` directly.
   - Acceptance criteria:
     - `grep -n "input_text\|input_provenance\|SourceSpan" backend/models/job.py` returns zero hits.
     - `python -c "from models.job import JobDoc; JobDoc.model_fields['input_payload_gcs_uri']"` (from `backend/`) succeeds.
     - `JobDoc.for_single(...)` with an `input_fields` dict containing `input_payload_gcs_uri` (no `input_text`/`input_provenance` keys) constructs successfully.

### Task 7 — Cleanup: `backend/utils/firebase.py`, `backend/routes/worker.py`, `backend/routes/jobs.py::delete_job`

   - Files: `backend/utils/firebase.py`, `backend/routes/worker.py`, `backend/routes/jobs.py`
   - Dependency: land after Task 6 (removes the fields these cleanup sites currently reference).
   - Changes (PRD §4.8):
     - **`backend/utils/firebase.py`**: in `complete_job`'s `update_fields`, delete the line `"input_text": firestore.DELETE_FIELD,`. Do the identical removal in `fail_job`'s `update_fields`. Do not touch `complete_job`'s `"stage": Constants.Pipeline.PIPELINE_STEPS.CORRECT.number,` line (set by 06's Task 7) or any other field. Update both functions' docstrings: drop the "Always clears input_text [and input_provenance]" language, replacing it with a short note that the job's raw input now lives in GCS (`input_payload_gcs_uri`), not on this document, and is cleaned up by `routes/worker.py`'s `finally` block and the `DELETE /jobs/<job_id>` route instead (both below) — not by `complete_job`/`fail_job`.
       - **The Firestore field `input_payload_gcs_uri` itself is never `DELETE_FIELD`'d** (PRD §4.8, §9's `[RESOLVED]` entry) — this is a deliberate departure from `input_text`/`input_provenance`'s treatment (which were `DELETE_FIELD`'d because they held PHI text inline). Do not add a `DELETE_FIELD` entry for it anywhere.
     - **`backend/routes/worker.py`**: in `execute_job`'s `finally` block, change:
       ```python
       finally:
           if job is not None and job.input_pdf_gcs_uri:
               delete_gcs_object(job.input_pdf_gcs_uri)
       ```
       to:
       ```python
       finally:
           if job is not None:
               if job.input_pdf_gcs_uri:
                   delete_gcs_object(job.input_pdf_gcs_uri)
               if job.input_payload_gcs_uri:
                   delete_gcs_object(job.input_payload_gcs_uri)
       ```
       This `finally` block already runs on every path out of `_run` once `job` is bound (success, every `fail_job` early-return, the timeout path, the outer `except Exception` handler) — no new control flow needed. `delete_gcs_object` is already idempotent-safe (swallows `NotFound`), so this is harmless even when the object is already gone (the §4.10 race).
     - **`backend/routes/jobs.py::delete_job`**: change:
       ```python
       gcs_uri = data.get("input_pdf_gcs_uri")
       if gcs_uri:
           delete_gcs_object(gcs_uri)  # best-effort; logs+swallows, never raises
       ref.delete()
       ```
       to:
       ```python
       gcs_uri = data.get("input_pdf_gcs_uri")
       if gcs_uri:
           delete_gcs_object(gcs_uri)  # best-effort; logs+swallows, never raises
       payload_gcs_uri = data.get("input_payload_gcs_uri")
       if payload_gcs_uri:
           delete_gcs_object(payload_gcs_uri)  # best-effort; same as above
       ref.delete()
       ```
   - Acceptance criteria:
     - `grep -n "input_text\|input_provenance" backend/utils/firebase.py backend/routes/worker.py backend/routes/jobs.py` returns zero hits (this file set only — other files are handled by their own tasks).
     - `grep -n "input_payload_gcs_uri" backend/routes/worker.py backend/routes/jobs.py` returns at least one hit each.
     - Fully covered by the new/updated tests in Tasks 13-15.

### Task 8 — `backend/routes/worker.py`: replace the `resolve_input_from_job_doc`/`resolve_units_from_job_doc` call site with `load_job_input`

   - Files: `backend/routes/worker.py`
   - Dependency: land after Task 4 and Task 7 (same file as Task 7 — land together or immediately after; needs `load_job_input` to exist).
   - Changes (PRD §4.10): This edits `execute_job`'s post-06 call site (06's Task 6 already changed the old single-line `text = resolve_input_from_job_doc(job)` into a two-line block adding `units = resolve_units_from_job_doc(job)`, and changed the pipeline call to pass `units`). Starting from that post-06 shape:
       ```python
       from services.care_plan_input import resolve_input_from_job_doc, resolve_units_from_job_doc
       ...
       source_kind = job.input_source_kind
       text = resolve_input_from_job_doc(job)
       units = resolve_units_from_job_doc(job)     # PRD 02 §4.7's reconstruction, spent here

       if len(text.strip()) < Constants.Uploads.MIN_MEANINGFUL_CONTENT_CHARS:
           fail_job(job_id, build_error_data(ErrorCode.EMPTY_DOCUMENT))
           return "", 200
       ```
     replace with:
       ```python
       from services.care_plan_input import load_job_input
       from services.unitizer import unitize
       ...
       source_kind = job.input_source_kind
       try:
           text, provenance = load_job_input(job)
       except SimplifyError as exc:
           fail_job(job_id, build_error_data(exc.error_code, exc.detail))
           return "", 200
       units = unitize(text, provenance)

       if len(text.strip()) < Constants.Uploads.MIN_MEANINGFUL_CONTENT_CHARS:
           fail_job(job_id, build_error_data(ErrorCode.EMPTY_DOCUMENT))
           return "", 200
       ```
     Add `SimplifyError` to `routes/worker.py`'s existing `from errors import ErrorCode, build_error_data, build_error_data_from_exc` import line (becomes `from errors import ErrorCode, SimplifyError, build_error_data, build_error_data_from_exc`). The pipeline call site itself (`for event in run_care_plan_pipeline(text, units, metrics, grading_enabled, source_kind=source_kind):`, wired by 06's Task 6) is unchanged — `units` still flows into it, just built via `unitize(text, provenance)` directly instead of via the now-deleted `resolve_units_from_job_doc`.

     **Why `ErrorCode.PIPELINE_ERROR` and why a 200, not a 500** (PRD §4.10, no code change needed beyond what's shown above — noted here so the reason for this exact shape is on record): `PIPELINE_ERROR` is `errors/codes.py`'s existing generic "something went wrong before/during processing that isn't the document's fault" bucket (`retryable=True`, `http_status=500`), reused rather than inventing a new code, for the concrete lease-expiry race PRD §4.10 documents (a crashed first attempt whose `finally` block already deleted `input_payload_gcs_uri` before its own terminal Firestore write landed, followed by a redelivered retry that finds the object gone). The worker still returns `("", 200)` to Cloud Tasks on this failure — matching the existing `EMPTY_DOCUMENT`/`JOB_TIMEOUT` pattern exactly — because `retryable=True` is a client-facing hint ("resubmit a fresh job"), not an instruction to redeliver the identical Cloud Task; redelivering cannot help since the object is permanently gone (no resumption machinery, PRD §3 Non-Goals).
   - Acceptance criteria:
     - `python -c "import routes.worker"` (from `backend/`) succeeds with no `ImportError`.
     - `grep -n "resolve_input_from_job_doc\|resolve_units_from_job_doc" backend/routes/worker.py` returns zero hits.
     - `grep -n "load_job_input\|unitize" backend/routes/worker.py` returns at least one hit each.
     - With `load_job_input` mocked to raise `SimplifyError(ErrorCode.PIPELINE_ERROR, "job has no input_payload_gcs_uri")`, a worker run against that job ends with `status == "error"`, `error_data["code"] == "PIPELINE_ERROR"`, and the worker route returns HTTP 200 (not 500) — proving Cloud Tasks is told not to redeliver.
     - Fully covered by the new tests in Task 15.

### Task 9 — `backend/tests/models/test_provenance.py`: add `JobInputPayload` tests

   - Files: `backend/tests/models/test_provenance.py`
   - Dependency: land after Task 1.
   - Changes (PRD §7.3): Add:
     - `test_job_input_payload_round_trips_through_to_dict_from_dict` — construct a `JobInputPayload` with a non-trivial `text` and a two-element `provenance` list, round-trip through `to_dict()`/`from_dict()`, assert equality.
     - `test_job_input_payload_rejects_unknown_key` — `extra="forbid"` guard, same pattern as `SourceSpan`'s own test in this file: assert constructing `JobInputPayload(text="x", provenance=[], extra="y")` raises `ValidationError`.
   - Acceptance criteria: `python -m pytest tests/models/test_provenance.py -q` (from `backend/`) passes, including the existing `SourceSpan` tests (untouched) and the two new ones.

### Task 10 — New `backend/tests/utils/test_gcs.py`: `download_gcs_string`

   - Files: `backend/tests/utils/test_gcs.py` (new file, or additions if `delete_gcs_object` already has tests there by the time you implement this — confirm at implementation time and add alongside rather than duplicating fixtures)
   - Dependency: land after Task 2.
   - Changes (PRD §7.3): Add:
     - `test_download_gcs_string_returns_decoded_text` — mock the GCS client/bucket/blob chain, assert the returned string matches a mocked `download_as_text()` return value.
     - `test_download_gcs_string_raises_not_found_for_missing_object` — mock `download_as_text` to raise `google.api_core.exceptions.NotFound`, assert it propagates uncaught (this function does NOT swallow, unlike `delete_gcs_object`).
     - `test_download_gcs_string_rejects_non_gs_uri` — `download_gcs_string("not-a-gs-uri")` raises `ValueError`.
   - Acceptance criteria: `python -m pytest tests/utils/test_gcs.py -q` (from `backend/`) passes; all three cases present.

### Task 11 — `backend/tests/services/test_care_plan_input.py`: `upload_job_input`/`load_job_input` tests

   - Files: `backend/tests/services/test_care_plan_input.py`
   - Dependency: land after Tasks 3, 4.
   - Changes (PRD §7.1 row 2 concept, §7.3 — this task both rewrites 02's `resolve_units_from_job_doc` test and adds the new coverage this PRD calls for):
     - Delete `test_resolve_units_from_job_doc_round_trips_through_a_job_doc_shaped_object` (02's Task 12 test — tests a function this PRD deletes).
     - Add:
       - `test_upload_job_input_writes_json_with_text_and_provenance` — mock `get_gcs_bucket` (the same pattern the file's existing `upload_combined_pdf` tests already use), call `upload_job_input(text, provenance, "user-1")`, capture the `upload_from_string` call, `json.loads` it, assert `["text"] == text` and `["provenance"]` matches the input spans' serialized form; assert the returned URI matches `gs://<bucket>/care_plan_inputs/user-1/inputs/<uuid>.json` (regex on the `<uuid>` segment, exact match on the rest — mirrors how `test_jobs.py` already asserts `payload["input_pdf_gcs_uri"].startswith("gs://test-bucket/care_plan_inputs/")` for the PDF path).
       - `test_upload_job_input_raises_if_bucket_env_var_missing` — clear `GCP_BUCKET_NAME`, assert `RuntimeError` (mirrors `upload_combined_pdf`'s identical existing guard/test in this same file).
       - `test_load_job_input_happy_path` — mock `download_gcs_string` to return a `JobInputPayload(text="hello", provenance=[...]).to_dict()`-shaped JSON string; assert `load_job_input(fake_job)` returns the matching `(text, provenance)` tuple.
       - `test_load_job_input_raises_pipeline_error_when_gcs_uri_is_missing` — `fake_job.input_payload_gcs_uri = None`; assert `SimplifyError` with `error_code == ErrorCode.PIPELINE_ERROR`.
       - `test_load_job_input_raises_pipeline_error_on_not_found` — mock `download_gcs_string` to raise `google.api_core.exceptions.NotFound`; assert the same `SimplifyError`/`PIPELINE_ERROR` mapping — this is the test that directly proves §4.10's lease-expiry race is handled cleanly.
       - `test_load_job_input_raises_pipeline_error_on_malformed_json` — mock `download_gcs_string` to return `"not json"`; assert the same mapping.
       - `test_load_job_input_raises_pipeline_error_on_schema_mismatch` — mock `download_gcs_string` to return valid JSON missing the required `text` key; assert the same mapping (proves `JobInputPayload.from_dict`'s `ValidationError` is caught by the broad `except Exception`, not left to propagate raw).
   - Acceptance criteria:
     - `python -m pytest tests/services/test_care_plan_input.py -q` (from `backend/`) passes in full, including all 6 new tests.
     - `grep -n "resolve_units_from_job_doc\|resolve_input_from_job_doc" backend/tests/services/test_care_plan_input.py` returns zero hits.

### Task 12 — `backend/tests/utils/test_constants.py` and `backend/tests/services/test_care_plan_input.py`: remove `MAX_TEXT_BYTES` assertions; `backend/utils/constants.py` and `services/care_plan_input.py::validate_extracted_text_length`: delete the byte cap

   - Files: `backend/utils/constants.py`, `backend/services/care_plan_input.py`, `backend/tests/utils/test_constants.py`, `backend/tests/services/test_care_plan_input.py`, `backend/tests/routes/test_jobs.py`
   - Dependency: independent of Tasks 1-11 (this is the `MAX_TEXT_BYTES` removal, PRD §4.12 — a separate concern from the GCS transport change; can land any time, but grouped here as its own commit since it touches different files).
   - Changes (PRD §4.12, §9's `[RESOLVED: deleted outright]`):
     - **`backend/utils/constants.py`**: delete `Constants.Uploads.MAX_TEXT_BYTES` entirely. Update the surviving `MAX_TEXT_LENGTH` constant's comment to note it is now the *only* input-length cap, and why no substitute byte cap is needed (GCS has no comparable size ceiling at these scales; the char cap alone already bounds worst-case UTF-8 size to ~2 MB):
       ```python
       # Upper bound on extracted/pasted document text, enforced up front
       # (routes/jobs.py, services.care_plan_input) before any job is
       # enqueued. Not a practical limit on real clinical documents (even a
       # long chart is well under 100K chars) -- exists only to fail fast on
       # a pathological input, with enormous headroom below the model's
       # input context. The output ceiling is Llm.MAX_TOKENS_LONG_FORM, not
       # this.
       #
       # This is now the ONLY input-length cap (PRD 09 removed the sibling
       # MAX_TEXT_BYTES byte cap that used to sit here). MAX_TEXT_BYTES
       # existed purely to keep this text under Firestore's 1,048,576-byte
       # document limit; input_text no longer touches Firestore at all
       # (it moves to a GCS object -- see services.care_plan_input.
       # upload_job_input/load_job_input), so that limit no longer applies,
       # and no substitute byte cap was needed in its place: a GCS object
       # has no comparable size ceiling at these scales, and this char cap
       # alone already bounds worst-case UTF-8 size to 4 * MAX_TEXT_LENGTH
       # bytes (~2 MB even for 4-byte-per-char text) -- a non-issue for a
       # GCS write/read or for this pipeline's existing LLM token budgets.
       MAX_TEXT_LENGTH: int = 500_000
       ```
     - **`backend/services/care_plan_input.py::validate_extracted_text_length`**: delete the byte-length check block (the `byte_length = len(text.encode("utf-8")); if byte_length > Constants.Uploads.MAX_TEXT_BYTES: raise ValueError(...)` branch), leaving only the `char_length`/`MAX_TEXT_LENGTH` check and the preceding `validate_text_storable` call. Update the function's docstring to describe one length check instead of two:
       ```python
       def validate_extracted_text_length(text: str) -> None:
           """Raise ValueError if extracted or pasted document text is unsafe to
           store, or exceeds the configured maximum length.

           One length check: MAX_TEXT_LENGTH, a Python character (codepoint)
           count. PRD 09 removed the sibling UTF-8-byte check this function used
           to also run (MAX_TEXT_BYTES) -- it existed only to keep this text under
           Firestore's 1 MiB document limit, and this text no longer goes to
           Firestore at all (see Constants.Uploads.MAX_TEXT_LENGTH's comment for
           the full accounting of why no substitute byte cap was needed).
           """
           validate_text_storable(text, field="Extracted document text")

           char_length = len(text)
           if char_length > Constants.Uploads.MAX_TEXT_LENGTH:
               raise ValueError(
                   f"Extracted document text is too long to process "
                   f"({char_length:,} characters; limit is {Constants.Uploads.MAX_TEXT_LENGTH:,} characters). "
                   "Try uploading a shorter document or splitting it into smaller sections."
               )
       ```
       `validate_text_storable`'s own NUL/lone-surrogate checks are unchanged — leave that function untouched (PRD §4.12's third bullet, §9's `[RESOLVED]` entry: the failure it protects against — a string that can't be UTF-8-encoded — is unrelated to the byte-count cap and is unaffected by this task).
     - **`backend/tests/utils/test_constants.py`**: in `test_uploads_namespace`, delete the two lines `assert Constants.Uploads.MAX_TEXT_BYTES == 350_000` and `assert Constants.Uploads.MAX_TEXT_BYTES < Constants.Uploads.MAX_TEXT_LENGTH`. No replacement assertion needed — `MAX_TEXT_LENGTH`'s own value is unchanged.
     - **`backend/tests/services/test_care_plan_input.py`**: rewrite the four tests referencing `Constants.Uploads.MAX_TEXT_BYTES` as char-count-boundary tests, or delete where the case no longer has anything to assert:
       - `test_validate_extracted_text_length_accepts_text_at_char_limit` — change `text = "a" * Constants.Uploads.MAX_TEXT_BYTES` to `text = "a" * Constants.Uploads.MAX_TEXT_LENGTH`; assert `validate_extracted_text_length(text)` does not raise.
       - `test_validate_extracted_text_length_rejects_text_over_byte_limit` — delete outright (its case — a multibyte string over the byte cap but under the char cap — no longer has anything to assert now that the byte cap is gone). `test_validate_extracted_text_length_rejects_text_over_char_limit` (the char-cap test) already covers the surviving cap and needs no change.
       - `test_validate_extracted_text_length_rejects_cjk_text_under_char_cap_but_over_byte_cap` — delete outright (same reason: the byte cap it tested no longer exists).
       - `test_resolve_uploaded_files_rejects_extracted_text_over_limit` — change `oversized_text = "a" * (Constants.Uploads.MAX_TEXT_BYTES + 1)` to `oversized_text = "a" * (Constants.Uploads.MAX_TEXT_LENGTH + 1)`.
     - **`backend/tests/routes/test_jobs.py`**: rewrite the four tests referencing `Constants.Uploads.MAX_TEXT_BYTES` at the route level (char-count boundary instead of byte-count boundary):
       - `test_post_text_at_max_length_is_accepted` — change `text = "a" * Constants.Uploads.MAX_TEXT_BYTES` to `text = "a" * Constants.Uploads.MAX_TEXT_LENGTH`; assert 202 as before.
       - `test_post_text_over_max_length_returns_400` — change `text = "a" * (Constants.Uploads.MAX_TEXT_BYTES + 1)` to `text = "a" * (Constants.Uploads.MAX_TEXT_LENGTH + 1)`; assert 400/`INPUT_VALIDATION_ERROR` as before.
       - `test_post_cjk_text_under_char_cap_but_over_byte_cap_returns_400` — delete outright (the byte-cap boundary this test exercised no longer exists; there is no longer a case where CJK text is under the char cap but over some other cap).
       - `test_post_uploaded_file_extracted_text_over_max_length_returns_400` — change `oversized_text = "a" * (Constants.Uploads.MAX_TEXT_BYTES + 1)` to `oversized_text = "a" * (Constants.Uploads.MAX_TEXT_LENGTH + 1)`.
   - Acceptance criteria:
     - `grep -rn "MAX_TEXT_BYTES" backend --include=*.py` returns zero hits anywhere in the codebase.
     - `python -c "from utils.constants import Constants; Constants.Uploads.MAX_TEXT_BYTES"` (from `backend/`) raises `AttributeError`.
     - `python -m pytest tests/utils/test_constants.py tests/services/test_care_plan_input.py tests/routes/test_jobs.py -q` (from `backend/`) passes in full.

### Task 13 — `frontend/src/utils/validateFiles.ts` and its test: remove `MAX_TEXT_BYTES`

   - Files: `frontend/src/utils/validateFiles.ts`, `frontend/src/tests/utils/validateFiles.test.ts`
   - Dependency: independent of the backend tasks; land any time, but must land in the same overall change as Task 12 (leaving the frontend `MAX_TEXT_BYTES` mirror in place once the backend constant is gone would make the frontend client-side-reject a pasted-text submission the backend would now accept — PRD §4.12, §6).
   - Changes (PRD §4.12, §6):
     - Remove the `MAX_TEXT_BYTES` export (line 18) and the `MAX_TEXT_BYTES_CHECK_THRESHOLD` const (line 22), and their preceding comment blocks.
     - In `validateText()`, remove the entire byte-check block:
       ```typescript
       // Cheap pre-check (see MAX_TEXT_BYTES_CHECK_THRESHOLD above) before paying for a
       // full UTF-8 encode of a possibly very large string.
       if (text.length > MAX_TEXT_BYTES_CHECK_THRESHOLD) {
         const byteLength = new TextEncoder().encode(text).length;
         if (byteLength > MAX_TEXT_BYTES) {
           // ...
           return 'This text is too long to process. Try shortening it or uploading a file instead.';
         }
       }
       ```
       leaving only the preceding `MAX_TEXT_LENGTH` check (unchanged) followed by `return null;`.
     - In `frontend/src/tests/utils/validateFiles.test.ts`: remove the `MAX_TEXT_BYTES` import from the top-of-file import list; remove the tests asserting `validateText('a'.repeat(MAX_TEXT_BYTES))`/`validateText('a'.repeat(MAX_TEXT_BYTES + 1))` boundary behavior and the multibyte-padding `MAX_TEXT_BYTES` case. The surviving `MAX_TEXT_LENGTH`-boundary tests need no change.
   - Acceptance criteria:
     - `grep -n "MAX_TEXT_BYTES" frontend/src/utils/validateFiles.ts frontend/src/tests/utils/validateFiles.test.ts` returns zero hits.
     - `validateText('a'.repeat(500_000))` (at `MAX_TEXT_LENGTH`) returns `null`; `validateText('a'.repeat(500_001))` returns the "too long" message.
     - The frontend test suite for this file passes in full.

### Task 14 — `backend/tests/routes/test_jobs.py`: rewrite the payload-shape assertions this PRD's transport change breaks; add new tests

   - Files: `backend/tests/routes/test_jobs.py`
   - Dependency: land after Task 5.
   - Changes (PRD §7.1 row 3):
     - `test_post_multipart_one_blank_file_among_several_still_succeeds`: replace `assert "perfectly good clinical note" in payload["input_text"]` with a check against the mocked GCS write instead — the test already mocks `services.care_plan_input.get_gcs_bucket` and sets `bucket.blob.return_value = MagicMock()`; capture `bucket.blob.return_value.upload_from_string.call_args.args[0]` (this is the *last* `upload_from_string` call on the shared mock, which is `upload_job_input`'s JSON write — it runs after `upload_combined_pdf`'s PDF write in the upload branch per Task 5's ordering), `json.loads` it, and assert `"perfectly good clinical note" in captured["text"]`. This mirrors how `test_unicode_emoji_filename_accepted_and_isolated_from_gcs_path` (in `test_jobs_e2e_scenarios.py`) already asserts against mocked `blob()` call args for the PDF path.
     - Add `test_post_text_job_uploads_payload_and_stores_uri` — pasted-text submission; capture the mocked `upload_from_string` call, assert the uploaded JSON's `"text"` matches the posted text and `"provenance"` is a single span covering the whole string (via `provenance_for_pasted_text`'s existing contract); assert `payload["input_payload_gcs_uri"]` is set (where `payload` is `mock_create_doc.call_args.kwargs["payload"]`, matching the file's existing pattern) and `"input_text" not in payload` / `"input_provenance" not in payload`.
     - Add `test_post_job_returns_500_when_upload_job_input_raises` — mock `services.care_plan_input.upload_job_input` to raise; assert `resp.status_code == 500`, `mock_create_doc.assert_not_called()` (proves Task 5's "never orphans a Firestore doc" property holds for this new failure point too).
   - Acceptance criteria: `python -m pytest tests/routes/test_jobs.py -q` (from `backend/`) passes in full, including the 2 new tests and the rewritten `test_post_multipart_one_blank_file_among_several_still_succeeds`.

### Task 15 — `backend/tests/routes/test_worker.py`: mock `load_job_input` in place of `resolve_input_from_job_doc`/`resolve_units_from_job_doc`; add failure-mode and cleanup tests

   - Files: `backend/tests/routes/test_worker.py`
   - Dependency: land after Task 8.
   - Changes (PRD §7.1 row 8, §7.3): by the time this PRD lands, 06's own Task 11 has already added a `monkeypatch.setattr("routes.worker.resolve_units_from_job_doc", lambda job: [])` (or equivalent) to every test in this file that reaches the pipeline call, alongside `job.input_text` already being set directly on the mocked/stub `JobDoc` for `resolve_input_from_job_doc` to read.
     - Replace every such `resolve_units_from_job_doc` mock (and rely on no separate `resolve_input_from_job_doc` mock existing, since it needed none before) with a single `load_job_input` mock, e.g.:
       ```python
       monkeypatch.setattr("routes.worker.load_job_input", lambda job: ("some text", []))
       ```
       (or `patch("services.care_plan_input.load_job_input", ...)`, matching whichever import style — `monkeypatch` fixture vs. `@patch` decorator — that specific test already uses for its other worker-boundary mocks). Where a test's stub job doc set `input_text` directly to control the pipeline's input text, move that string into the `load_job_input` mock's return value instead (`("<that string>", [])`) — `job.input_text` is no longer a field these stubs need to set (Task 6 removed it from `JobDoc`).
     - Add `test_execute_job_fails_cleanly_with_pipeline_error_when_input_payload_missing` — full route-level test: post a job (or construct a pending doc directly), monkeypatch `load_job_input` (or the `download_gcs_string` it calls) to raise `SimplifyError(ErrorCode.PIPELINE_ERROR, ...)`; call `_run_worker`; assert `worker_resp.status_code == 200`, `doc["status"] == "error"`, `doc["error_data"]["code"] == "PIPELINE_ERROR"` — the route-level proof that §4.10's handling actually reaches Firestore correctly, mirroring the existing `test_llm_429_quota_exceeded_surfaces_as_safe_terminal_error` pattern in `test_jobs_e2e_scenarios.py`.
     - Add `test_execute_job_finally_block_deletes_both_gcs_objects_on_success` — a full happy-path run with both `input_pdf_gcs_uri` and `input_payload_gcs_uri` set on the job doc; assert `delete_gcs_object` (mocked) is called with both URIs.
     - Add `test_execute_job_finally_block_deletes_both_gcs_objects_on_failure` — same, but the pipeline itself raises; assert both deletes still happen (proves the `finally` block's placement, not just the happy path).
   - Acceptance criteria:
     - `python -m pytest tests/routes/test_worker.py -q` (from `backend/`) passes in full, including the 3 new tests.
     - `grep -n "resolve_input_from_job_doc\|resolve_units_from_job_doc" backend/tests/routes/test_worker.py` returns zero hits.

### Task 16 — `backend/tests/routes/test_jobs_e2e_scenarios.py`: rewrite every breaking assertion for the new transport

   - Files: `backend/tests/routes/test_jobs_e2e_scenarios.py`
   - Dependency: land after Tasks 5, 6, 7, 8.
   - Changes (PRD §7.1 rows 4-7):
     - `TestScenario2PhonePhotosOCR::test_three_jpegs_via_ocr_completes` — replace `for t in ocr_texts: assert t in doc["input_text"]` (reads the processing-state doc, which no longer has `input_text`): inspect the mocked GCS `upload_from_string` call captured by the test's existing `mock_gcs`/`get_gcs_bucket` patching instead, `json.loads` it, and assert each OCR string is `in captured["text"]`.
     - `TestScenario1TypicalDischargeSummary::test_full_chain_completes_and_final_doc_is_safe_and_small` and `TestScenario4MultibyteNearLimits::test_mixed_multibyte_just_under_both_caps_completes_and_stays_under_1mib` — both currently assert `assert "input_text" not in doc` and (per 02's Task 16) `assert "input_provenance" not in doc` on the completed doc. Keep both assertions as residual regression guards (cheap insurance against either field ever being reintroduced) — they still pass, just vacuously, since neither field exists on any doc state any more. Add, alongside them in each test, `assert "input_payload_gcs_uri" in doc` (the field is never cleared at completion, per Task 7 — it should still be present and non-null on the completed doc, unlike `input_pdf_gcs_uri`'s and `input_payload_gcs_uri`'s underlying *objects*, which are deleted, not the *field*).
     - Find the "processing-state doc contains a non-empty `input_provenance`" test 02's own tasks added (e.g. `test_multi_file_upload_processing_doc_has_non_empty_input_provenance`, per 02's Task 16) and invert it: assert `"input_provenance" not in doc` and `"input_text" not in doc` on the **processing**-state doc (read immediately after `POST /jobs`, before the worker runs), and assert `doc["input_payload_gcs_uri"].startswith("gs://")` instead.
     - `TestScenario8LifecycleRaces::test_delete_mid_worker_write_does_not_resurrect_doc_and_gcs_not_orphaned` — its fixture doc currently sets only `input_pdf_gcs_uri`; add `"input_payload_gcs_uri": "gs://test-bucket/care_plan_inputs/anon-1/inputs/xyz.json"` to the fixture doc, and change `mock_delete_gcs.assert_called_once_with(...)` (which currently checks only one URI) to assert `delete_gcs_object` was called with **both** URIs (`assert_any_call` for each, or assert `call_count == 2`) — proving Task 7's sibling delete actually lands in the same code path this test already exercises.
     - Every raw job-doc literal in this file that currently sets `"input_text": text` / `"input_provenance": ...` directly — the redelivery tests (`test_redelivery_of_fresh_lease_is_noop_llm_not_called_twice`, `test_redelivery_after_lease_expired_retries_and_completes`), `TestScenario9FailureSurfaces`'s `_make_pending_job`-style fixtures and the LLM-error tests, `TestScenario11AccessControl`'s two delete tests — replace `"input_text": text` (and remove any `"input_provenance": ...` key) with `"input_payload_gcs_uri": "gs://test-bucket/care_plan_inputs/anon-1/inputs/fixture.json"` in each, and add a `patch("services.care_plan_input.download_gcs_string", return_value=json.dumps({"text": text, "provenance": []}))` (or monkeypatch `services.care_plan_input.load_job_input` directly, returning `(text, [])`) around the `_run_worker`/worker-invocation call in each affected test — mirroring how these same tests already patch `routes.worker.run_care_plan_pipeline`.
     - `TestScenario6PartialFailureBatch::test_two_of_five_unusable_succeeds_with_skipped_files_reported` — currently asserts `"Good clinical note number one" in doc["input_text"]` (and the two siblings) on a **completed** doc; since `input_text` never existed on any doc state after this PRD, and the completed doc's `output_data` doesn't carry the raw input either, this specific assertion has nothing left to check post-transport — delete these three assertions from this test (the file's earlier upload-branch coverage, rewritten per this task's first bullet's pattern, already proves the text reached the GCS payload correctly for the OCR scenario; this test's own purpose — proving `skipped_files` is reported — is unaffected and its other assertions stay).
     - `test_firestore_rules_static_review_note` — untouched by this PRD (its `shared`-clause rewrite is 01's job, already landed).
     - Do **not** touch the doc-size-budget thresholds (`_doc_size_bytes`, `_max_leaf_string_bytes`, `< 1_048_576`, `< 1500`) or `_build_care_plan` — both are out of scope for this PRD.
   - Acceptance criteria:
     - `python -m pytest tests/routes/test_jobs_e2e_scenarios.py -q` (from `backend/`) passes in full for every test this task touches.
     - `grep -n '"input_text"\|"input_provenance"' backend/tests/routes/test_jobs_e2e_scenarios.py` returns zero hits as dict-literal keys (residual `assert "input_text" not in doc` / `assert "input_provenance" not in doc` string-membership assertions are fine and expected to remain, per this task's second bullet).

### Task 17 — Full-suite verification

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-16.
   - Acceptance criteria:
     - From `backend/`, `python -m pytest tests/ -q` passes with zero failures and zero errors.
     - From `frontend/`, the test suite passes with zero failures and zero errors.
     - `grep -rn "input_text\|input_provenance\|resolve_input_from_job_doc\|resolve_units_from_job_doc\|MAX_TEXT_BYTES" backend/ --include=*.py | grep -v "^backend/tests/routes/test_jobs_e2e_scenarios.py:.*assert \"input_text\" not in doc\|^backend/tests/routes/test_jobs_e2e_scenarios.py:.*assert \"input_provenance\" not in doc"` returns zero hits outside the two residual regression-guard assertion patterns just excluded (confirms every renamed/deleted symbol is fully gone from production and test code alike, matching PRD §9's own closing grep).
     - `python -c "from models.provenance import SourceSpan, JobInputPayload; from utils.gcs import get_gcs_bucket, delete_gcs_object, download_gcs_string; from services.care_plan_input import upload_job_input, load_job_input; from models.job import JobDoc; assert 'input_payload_gcs_uri' in JobDoc.model_fields and 'input_text' not in JobDoc.model_fields and 'input_provenance' not in JobDoc.model_fields"` (from `backend/`) succeeds — a single smoke import proving every new/renamed symbol this PRD introduces is wired together correctly and the two retired `JobDoc` fields are actually gone.
     - `grep -n "MAX_TEXT_BYTES" frontend/src --include=*.ts -r` returns zero hits.

---

## Summary of what requires you (not a dev agent)

Per PRD §8, all three items are manual/infrastructure checks tied to real GCP access and cannot be automated by a dev agent:

1. **Confirm the `juno-worker` Cloud Run service's runtime service account can read (`storage.objects.get`), not just delete, objects in `GCP_BUCKET_NAME`.** This is a genuinely new requirement: today the worker only ever calls `delete_gcs_object`, never reads GCS object content. `download_gcs_string` (Task 2) is the first time the worker's runtime identity needs `storage.objects.get` on this bucket — check via `gcloud storage buckets get-iam-policy gs://$GCP_BUCKET_NAME` against the worker's runtime SA before this lands in a deployed environment (this branch is never deployed until the whole PRD set lands, per the project-wide locked decisions, but the check itself needs your GCP access).
2. **No new GCS lifecycle rule or `deploy.yml` change is needed** (noted so it isn't mistaken for a missed step): the new payload object reuses the existing `care_plan_inputs/` prefix, already covered by the "Apply GCS lifecycle rules" deploy step's `age:1`/`matchesPrefix: ["care_plan_inputs/"]` rule. Nothing to do here.
3. **Smoke-test the new failure path once deployed**: deliberately delete a `care_plan_inputs/.../inputs/*.json` object for a job stuck in `processing` (simulating the crash-before-terminal-write race Task 8 handles) and confirm a redelivered/retried execution produces a clean `error_data.code == "PIPELINE_ERROR"` doc rather than an uncaught 500 — exercises real Cloud Tasks redelivery timing and real IAM that unit/integration tests can approximate but not fully replace.

No PRD §9 items are `[OPEN]` — the gate was clear; all 17 tasks above derive from `[RESOLVED]` decisions only.
