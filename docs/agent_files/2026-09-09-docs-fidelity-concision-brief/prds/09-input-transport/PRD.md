# PRD 09 — Input Transport

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here). This sub-project itself was not part of the original brief — it is the owner's separately-raised follow-on, recorded verbatim in `../README.md`'s "Deferred follow-on — not in this PRD set" section when PRDs 01-08 were settled.

Branch: `docs/fidelity-concision-brief`.

Depends on: 01 (schema-and-config — `JobDoc` shape), 02 (unitization-and-provenance — `SourceSpan`, `services.unitizer.unitize`, `resolve_uploaded_files`'s `provenance` output; this PRD supersedes 02's transport decision, §4.14, but not its provenance design), 06 (pipeline-orchestration — this PRD replaces the `resolve_input_from_job_doc`/`resolve_units_from_job_doc` call site 06 wired into `routes/worker.py`).

Depended on by: none. Leaf; a follow-on. Nothing in 01-08 depends on this landing, and this PRD depends on all of them having already landed exactly as written — see the ordering note in §3.

**Everything in this PRD is written against the POST-01-08 codebase** (i.e. `JobDoc.input_text`/`input_provenance` exist, `services/unitizer.py` and `models/provenance.py` exist, `routes/worker.py` calls `resolve_input_from_job_doc`/`resolve_units_from_job_doc`), not against the pre-01-08 code currently checked out on this branch. Every "old" code block below is what 01-08 leave behind; every "new" block is this PRD's change on top of that.

## 1. Problem

`JobDoc.input_text` (and, as of 02, `JobDoc.input_provenance`) are persisted to Firestore not because either is state worth keeping, but because the API and worker are two separate Cloud Run services joined only by a Cloud Tasks queue whose task payload carries nothing but the job id (`utils/cloud_tasks.py`'s `enqueue_job_safe`/`enqueue_job`). The Firestore job document is the *only* channel through which the text the API extracted, and the provenance map 02 computes alongside it, ever reach the worker process that actually needs them. Concretely, verified against the post-02 code:

- `routes/jobs.py::_resolve_job_input` runs in the **API** process, computes `input_text: str` (up to `Constants.Uploads.MAX_TEXT_LENGTH` = 500,000 chars, further capped in bytes by `Constants.Uploads.MAX_TEXT_BYTES` = 350,000) and, as of 02, `input_provenance: list[SourceSpan]`, and writes both directly onto the `JobDoc` Firestore document via `create_job_doc`.
- `routes/worker.py::execute_job` runs in a **different** process (`juno-worker`, a separate Cloud Run service per `.github/workflows/deploy.yml`) and reads them back with `resolve_input_from_job_doc(job) -> job.input_text or ""` and `resolve_units_from_job_doc(job) -> unitize(job.input_text or "", job.input_provenance)` (02 §4.7). Both calls just read attributes off the same `JobDoc` object `get_job_doc`/`JobDoc.from_firestore` already loaded — no second Firestore read, because both fields already live on the one document the worker fetches.

The consequences of routing clinical text through Firestore this way, all verified directly against the current code and constants:

- **PHI sits in a Firestore document for the duration of every job.** `input_text` is the patient's own note/discharge-summary/lab-result text, `input_provenance` is a structural map of exactly which file and page every line of it came from — both are as sensitive as anything this app ever handles, and both live as plain Firestore fields, readable by anything with Firestore read access to `care_plan_outputs`, for as long as the job takes to run (bounded by `Constants.Deadlines.SINGLE_JOB_INTERNAL_DEADLINE_S` = 270s in the healthy case, but see §4.10 for a real path where they outlive that).
- **`MAX_TEXT_BYTES` (350,000 bytes) exists solely to keep the job document under Firestore's 1,048,576-byte (1 MiB) hard per-document limit.** Its own comment in `utils/constants.py` says so explicitly: "sized to keep the full `care_plan_outputs` Firestore doc under the 1,048,576 byte (1 MiB) hard document limit... do not raise this without re-deriving that budget." It is an input-size cap driven entirely by a storage-layer choice — nothing about the product, the clinical documents this app processes, or the model's context window motivates 350,000 bytes specifically. `Constants.Uploads.MAX_TEXT_LENGTH` (500,000 chars) is the one cap that *is* independently justified ("not a practical limit on real clinical documents... exists only to fail fast on a pathological input, with enormous headroom below the model's input context").
- **02's provenance map competes for the same byte budget**, and 02 spends real, explicit design effort justifying its size against it (02 §4.1's Option 1/Option 2 analysis, and §4.13's quantitative accounting of the ~546,576 bytes of headroom left after `input_text`). That effort was the right call *given* the Firestore-transport constraint — but the constraint itself is the thing this PRD removes.

**The fix**: Firestore should hold only what the frontend renders. Move `input_text` and `input_provenance` off the job document entirely, into a GCS object keyed to the job, written by the API at job-creation time and read once by the worker at the start of its run — the same pattern `input_pdf_gcs_uri` (the merged-PDF audit copy) already establishes for exactly this API→worker/GCS relationship, just for a field the worker actually needs to run the pipeline rather than one it only ever deletes.

## 2. Goals

- Remove `input_text` and `input_provenance` from `JobDoc` (Firestore) entirely. Neither field is ever written to Firestore again, in any job state — not "written then deleted at completion" (02's existing lifecycle), but never written at all.
- Replace them with one new GCS object per job, containing both fields together, referenced from the job doc by a single new URI field (`input_data_gcs_uri` — no, see §4.4 for the actual chosen name, `input_payload_gcs_uri`) — written by the API in `_resolve_job_input`, read once by the worker at the start of `execute_job`, and deleted alongside the job's existing `input_pdf_gcs_uri` cleanup (worker's own terminal-state `finally` block, and the user-initiated `DELETE /jobs/<job_id>` route).
- Revisit `MAX_TEXT_BYTES` now that its stated justification (Firestore's 1 MiB document limit) no longer applies to this field at all, and decide its fate honestly (§4.12) — including its exact mirror on the frontend, `frontend/src/utils/validateFiles.ts`'s own `MAX_TEXT_BYTES`, which the file's own comment says exists only to "mirror" this one.
- Give the worker a clean, already-classified failure mode (reusing an existing `ErrorCode`, not inventing one) for the one new way this design can fail that today's design cannot: the referenced GCS object is missing or unreadable when the worker goes to read it (§4.10) — a failure mode with a concrete, code-derivable trigger (the existing lease-expiry retry path), not a hypothetical.
- Preserve the "never orphan a Firestore doc" property `create_job` already protects today (§4.6), and be explicit about the different, already-accepted property it does *not* try to protect (a GCS object can be orphaned by an aborted job-creation request — true today for `input_pdf_gcs_uri` already, and the lifecycle-rule backstop that already exists for that prefix, `.github/workflows/deploy.yml`'s "Apply GCS lifecycle rules" step, covers the new object too, for free, because it lands under the same `care_plan_inputs/` prefix — §4.4).
- Retire `resolve_input_from_job_doc` and `resolve_units_from_job_doc` (02 §4.7) as job-doc-shaped functions and specify exactly what the worker calls instead (§4.9, §4.14).
- Full test specification (§7): every existing test that constructs a raw job doc with an `input_text` key, or asserts `"input_text" not in doc` / `"input_provenance" not in doc`, or reads `payload["input_text"]` off a mocked `create_job_doc` call.

## 3. Non-Goals

- **Ordering: this PRD lands after 01-08, not alongside or before them.** PRDs 01-08 land exactly as written, with `input_text`/`input_provenance` on `JobDoc` exactly as 02 specifies, `resolve_units_from_job_doc(job)` wired into the pipeline exactly as 06 specifies. This PRD is a follow-on that then changes the transport underneath an already-landed, already-working design — it is not a prerequisite for 01-08 and does not block them. It is implementable independently of the fidelity/concision work itself: nothing in this PRD touches `care_plan/pipeline.py`, any prompt, `CarePlan`, `Fact`, or `Unit`'s own shape.
- **No durability, retry, or resumption machinery for a job whose input object goes missing mid-run.** If a job dies partway through — the worker crashes, the machine goes down, the GCS object is deleted out from under a still-running attempt — losing the input is an acceptable outcome. The user re-uploads and starts a new job. This PRD's only job on the failure side is to turn "input object gone" into a clean, classified job failure (§4.10) instead of an uncaught exception; it does not try to make the input recoverable, re-fetchable, or re-derivable from anything else.
- **No change to 02's provenance design.** `SourceSpan`, `services/unitizer.py::unitize`/`provenance_for_pasted_text`, and `resolve_uploaded_files`'s per-(file,page) span computation are all taken as given and untouched. This PRD changes only *where the pair `(input_text, input_provenance)` lives between the API computing it and the worker consuming it* — not how either half is computed, not the `Unit`/`SourceSpan` contracts, not `unitize`'s own logic. See §4.14 for exactly what carries over from 02 unchanged versus what this PRD supersedes.
- **No change to `input_pdf_gcs_uri`'s own purpose or lifecycle.** It remains the merged/re-rendered audit-copy PDF, still optional (`None` when `resolve_uploaded_files` produces no merge candidates, or when `merge_pdfs` itself fails — an already-tolerated failure, see §4.6), still deleted the same two places it is today. This PRD adds a sibling field and sibling cleanup calls; it does not touch `input_pdf_gcs_uri`'s own semantics.
- **No pipeline, prompt, or `CarePlan`/`Fact`/`Unit` schema changes.** Everything downstream of the worker having `(text, units)` in hand is unchanged; this PRD only changes how the worker gets there.
- **No versioning, no migration code, no dual-read path.** Per the project-wide locked decision (`../README.md`'s "Locked decisions" section): mutate in place. There is no live population of `JobDoc` documents that need to keep working mid-migration — jobs are short-lived (`Constants.Limits.JOB_TTL_HOURS` = 1) and this branch is never deployed until the whole set lands, so there is no window where old-shape and new-shape job docs coexist in production.
- **No per-PR backend preview environment, no clinical-fidelity evaluation.** Out of scope everywhere, per the project-wide Non-Goals.
- **No change to the frontend's job-polling/rendering behavior.** The frontend never reads `input_text`/`input_provenance`/`input_payload_gcs_uri` today and won't after this PRD either (§6). The one frontend file this PRD does touch, `frontend/src/utils/validateFiles.ts`, is touched only for the `MAX_TEXT_BYTES` constant-sync consequence of §4.12 — not for anything about how a job is displayed.

## 4. Architecture Decisions

### 4.1 Object shape — one JSON blob, not two objects

**Decision: one GCS object per job, a single JSON document holding both `text` and `provenance` together.**

The worker consumes the pair as a pair: `resolve_units_from_job_doc` (02 §4.7) is `unitize(job.input_text or "", job.input_provenance)` — both arguments are required by the one function that ever needs either of them, and they are needed at the same moment, once, at the start of the worker's run. There is no scenario in this codebase where the worker wants `input_text` without `input_provenance` (both feed into `unitize`) or `input_provenance` without `input_text` (a provenance map with no text to slice is meaningless). Splitting them into two objects would mean:

- Two GCS writes on the API side instead of one (inside `_resolve_job_input`, which already does a synchronous GCS write for `upload_combined_pdf` — a second, unrelated write adds request latency for no benefit).
- Two GCS reads on the worker side instead of one, at the exact same point in the code, for values that are always consumed together.
- Two objects to delete instead of one at every cleanup site (§4.8), doubling the number of `delete_gcs_object` calls and the number of ways cleanup can partially fail (one delete succeeds, one doesn't — a new, avoidable partial-cleanup state).
- Two `gs://` URIs to carry on the job doc instead of one, for no product-visible benefit (neither is ever read independently).

**Rejected: two objects (e.g. `<id>.txt` for text, `<id>.json` for provenance).** The only argument for splitting them is if a future consumer wanted one without the other — no such consumer exists today, and inventing the split now for a hypothetical future reader would be exactly the kind of speculative surface the parent brief argues against elsewhere (e.g. 01 §9's identical reasoning for not persisting the ledger "for a consumer that doesn't exist yet"). One object, one write, one read, one delete.

The blob's shape is a new small model, `JobInputPayload`, added to `backend/models/provenance.py` (02's home for `SourceSpan` — see §4.2 for why it belongs in the same file):

```python
class JobInputPayload(JsonModel):
    """Wire shape of the GCS object services.care_plan_input.upload_job_input
    writes and load_job_input reads back -- the whole reason this object
    exists is to carry input_text and input_provenance from the API to the
    worker as one payload (PRD 09 SS4.1), since the one function that ever
    consumes either (services.unitizer.unitize) always consumes both.

    Like SourceSpan, this model IS written to a persistence layer (a GCS
    object, not Firestore) -- unlike Unit/Fact, which never touch storage
    at all. Unlike SourceSpan, it never appears as a JobDoc field; it is
    the object input_payload_gcs_uri points AT, not a value stored inline.
    """

    text: str
    provenance: list[SourceSpan] = Field(default_factory=list)
```

### 4.2 Where `JobInputPayload` lives

`backend/models/provenance.py` (not a new file) — the same module 02 created for `SourceSpan`, for the same reason 02 gave for keeping `SourceSpan` out of `models/ledger.py`: this is the persisted half of the provenance design, and `JobInputPayload` is even more directly a persistence-layer model than `SourceSpan` is (it's the literal on-disk shape of a GCS object, where `SourceSpan` is merely one Firestore field's element type). Add `from pydantic import Field` to the file's existing imports (already needed for `SourceSpan`'s own sibling fields if 02 didn't already import it — confirm at implementation time; `provenance.py` as shown in 02 §4.3 does not yet import `Field`, so this PRD adds it).

### 4.3 `backend/utils/gcs.py` — a new, non-swallowing download helper

`utils/gcs.py` today has `get_gcs_bucket` (generic bucket handle) and `delete_gcs_object` (best-effort, swallows `NotFound`, logs and swallows everything else — "GCS cleanup failing must never fail the caller"). Reading the input payload back needs the opposite failure posture: a caller that cannot get the content cannot proceed, so nothing should be swallowed.

New function, same URI-parsing logic as `delete_gcs_object` (kept identical rather than refactored into a shared parser — two three-line `partition` calls is not worth a shared helper, and keeping them textually identical means a reader auditing one can trust the other matches):

```python
def download_gcs_string(gcs_uri: str) -> str:
    """Download and return the text contents of a gs:// object.

    Unlike delete_gcs_object, this does NOT swallow failures -- a caller
    that needs this content cannot proceed without it (see
    services.care_plan_input.load_job_input, PRD 09 SS4.9, which is this
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

`delete_gcs_object` itself is unchanged.

### 4.4 Naming and location — reuse `care_plan_inputs/`, a full URI field, a fresh object id

**Prefix: `care_plan_inputs/{user_id}/inputs/`, the exact prefix `upload_combined_pdf` already writes into** — not a new prefix. Two consequences fall out of this, both wins:

1. **No new GCS lifecycle rule needed, and no change to `.github/workflows/deploy.yml`.** That file's "Apply GCS lifecycle rules (both apps' upload prefixes)" deploy step already applies, on every deploy, `{"action":{"type":"Delete"},"condition":{"age":1,"matchesPrefix":["care_plan_inputs/"]}}` to `GCP_BUCKET_NAME`. Any object under `care_plan_inputs/` — the merged-PDF audit copy today, this PRD's new payload object tomorrow — is deleted after 1 day regardless of whether application-level cleanup (the worker's `finally` block, the `DELETE /jobs/<job_id>` route) ever ran. This is exactly the "obvious backstop" the task brief for this PRD anticipated needing a manual step for — except it already exists, already covers this prefix, and needs no owner action. (Confirmed by reading `upload_combined_pdf`'s own docstring: "Uses a visually distinct prefix (`care_plan_inputs/`) so a GCS lifecycle rule can safely target these uploads for retention" — this PRD's object gets that same property for free by choosing the same prefix.)
2. **This PRD reads as "add a sibling artifact next to the one that's already there," not "stand up new input-artifact infrastructure."** Both objects are per-user, per-job-creation-attempt uploads serving the same "this job's raw input, kept only as long as the job needs it" purpose — one for pipeline consumption (this PRD's), one for retention/audit (already existing). Same bucket, same top-level prefix, same per-user subpath, same lifecycle coverage. This is also the honest answer to "does this actually reduce PHI exposure or just relocate it" (§4.13): it puts the pipeline's raw-text transport in the *same* place, under the *same* retention policy, as an artifact this app already accepted the same exposure profile for.

**Object naming: `care_plan_inputs/{user_id}/inputs/{object_id}.json`, `object_id = str(uuid.uuid4())`** — a fresh random id, generated at write time, exactly mirroring `upload_combined_pdf`'s own `object_id = str(uuid.uuid4())` / `blob_name = f"care_plan_inputs/{user_id}/inputs/{object_id}.pdf"`. Same directory, same random-id convention, different extension.

**The job doc stores the full `gs://` URI in a new field, `input_payload_gcs_uri: Optional[str]`, not a derived path.** This mirrors `input_pdf_gcs_uri`'s own existing shape exactly. The alternative — derive the object's path from the job id alone (`care_plan_inputs/{user_id}/inputs/{job_id}.json`, no field needed at all, since any code holding a `JobDoc` already has its own job id) — was considered and rejected:

**Rejected: job-id-derived path, no new field.** This would save exactly one `Optional[str]` field on `JobDoc` (a handful of bytes) at the cost of a real structural problem: **`_resolve_job_input` runs, and therefore would need to write this object, *before* `job_id` exists.** Read `routes/jobs.py::create_job` in order: `input_fields = _resolve_job_input(user_id)` runs first; `job_id = str(uuid.uuid4())` is generated only after the Cloud Tasks config validation that follows it. `upload_combined_pdf` already faces this exact problem today and already solves it the same way this PRD does — by minting its own random id rather than waiting for a job id that doesn't exist yet at that point in the request. Deriving the new object's path from `job_id` would require either (a) moving `job_id` generation to the top of `create_job` and threading it into `_resolve_job_input` as a new parameter neither the pasted-text nor upload branch currently needs, reordering a function this PRD would otherwise leave untouched in that respect, or (b) writing the object *after* `job_id` exists but *before* the Firestore write, which is a different point in the function than where `upload_combined_pdf` already runs today, needlessly splitting "resolve input" from "write input" across two separate blocks of `create_job` for a field-count saving. Either path is a larger, more invasive change than storing one string, and (per the task's own framing of this tradeoff) introduces a hidden coupling: any future reordering of `create_job` (e.g. 06's own future changes, or a refactor that moves the Cloud Tasks check earlier) could silently break a path convention with no compiler- or model-level signal that it broke, whereas a stored full URI is self-describing and cannot go stale by construction — it is written once, alongside the object, in the same function call.

Decision: full URI field, `input_payload_gcs_uri`, one extra field on `JobDoc`, mirroring the one precedent (`input_pdf_gcs_uri`) this codebase already has for exactly this relationship.

### 4.5 `backend/services/care_plan_input.py` — `upload_job_input`

New function, placed beside `upload_combined_pdf` (both are "resolve input → GCS" functions called from `_resolve_job_input`):

```python
def upload_job_input(text: str, provenance: list[SourceSpan], user_id: str) -> str:
    """Upload the (text, provenance) pair services.unitizer.unitize will
    later need, as one JSON object, to GCS -- the transport this PRD (09)
    chose over persisting either field on the Firestore job doc (PRD 02's
    original design). Mirrors upload_combined_pdf's bucket/prefix/naming
    convention exactly (same care_plan_inputs/{user_id}/inputs/ prefix,
    same fresh-uuid object naming -- see PRD 09 SS4.4 for why the path is
    NOT derived from a job id), but writes a JSON payload instead of PDF
    bytes, and unlike the merged PDF, this write is NOT optional -- see
    PRD 09 SS4.6 for why a failure here must propagate, not degrade.

    Unlike validate_extracted_text_length (called on `text` by every caller
    of this function before it's ever reached), this function does not
    re-validate text storability -- the UTF-8-encode this function's JSON
    serialization performs can still fail on a lone surrogate exactly as a
    Firestore write could, but validate_text_storable has already ruled
    that out upstream (PRD 09 SS4.12's third bullet)."""
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

New imports needed in this file: `import json` (not currently imported), `from models.provenance import SourceSpan, JobInputPayload` (`SourceSpan` is already imported per 02 §4.7; add `JobInputPayload`), `from utils.gcs import get_gcs_bucket, download_gcs_string` (add `download_gcs_string` to the existing `get_gcs_bucket` import).

### 4.6 `backend/routes/jobs.py::_resolve_job_input` — call sites and why this write is not optional

Both branches call `upload_job_input` after their existing validation, replacing the `input_text`/`input_provenance` dict keys with one `input_payload_gcs_uri` key.

Pasted-text branch — old (post-02):
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
New:
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

Upload branch — old (post-02):
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
New:
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

New import: `from services.care_plan_input import upload_job_input` alongside the existing `resolve_uploaded_files`, `upload_combined_pdf`, `validate_extracted_text_length` import.

**`upload_job_input`'s success is not optional, unlike `upload_combined_pdf`'s.** Look at how `resolve_uploaded_files` already treats `merge_pdfs` failing: `try: combined_pdf_bytes = merge_pdfs(merge_candidates) except Exception: logger.exception(...); # continuing without combined PDF` — the merged PDF is a best-effort audit artifact; a job runs fine with `input_pdf_gcs_uri = None`. There is no equivalent fallback for `upload_job_input`: it carries the only copy of the text the pipeline will ever run on, and per the governing principle for this whole PRD ("do not push state to Firestore unless absolutely necessary"), there is no Firestore fallback to degrade to either. If `upload_job_input` raises (missing bucket config, a transient GCS error, anything), `_resolve_job_input` lets it propagate uncaught. It is not wrapped in `create_job`'s inner `try/except (ValueError, FileNotFoundError)`/`except SimplifyError` blocks (§4.6's ordering below), so it falls through to `create_job`'s outer `except Exception: ... return INTERNAL_ERROR, 500` — the same generic-failure path any other unexpected exception in this function already takes. This is deliberate, not an oversight: a job that cannot get its own input into GCS should fail the request outright, exactly as if `resolve_uploaded_files` itself had raised.

### 4.7 Ordering — where the GCS write lands relative to the Cloud Tasks config check

`create_job`'s existing comment is explicit about what it protects: "Validate Cloud Tasks config BEFORE writing anything to Firestore — this route never orphans a doc." That is a **Firestore-doc** guarantee, not a **GCS-object** guarantee — and the code already only protects the former. Read the existing order:

1. `_resolve_job_input(user_id)` — calls `resolve_uploaded_files` (which may call `merge_pdfs`) and `upload_combined_pdf` (a real, synchronous GCS write) if there are merge candidates.
2. Cloud Tasks config validated (`require_env` calls); a `MissingJobConfigError` here returns 500 with **no Firestore doc ever written** — but any GCS object `upload_combined_pdf` already wrote in step 1 is *not* rolled back. It is already an accepted, existing orphan case, backstopped only by the `care_plan_inputs/` lifecycle rule (§4.4).
3. `job_id` generated.
4. `JobDoc.for_single(...)` built; `create_job_doc` writes it to Firestore.
5. `enqueue_job_safe` enqueues the Cloud Task.

**This PRD's `upload_job_input` call lands inside step 1**, at the same point `upload_combined_pdf` already runs, for the same reason: it needs `resolved.text`/`resolved.provenance` (or `text_input`/`provenance_for_pasted_text(text_input)`), which only exist once `_resolve_job_input` has done its own work, and `job_id` does not exist yet at this point regardless (§4.4). This preserves the *actual* invariant the existing comment protects — no Firestore doc is ever written for a request that fails Cloud Tasks validation — while accepting the *same*, already-existing tradeoff `upload_combined_pdf` accepts today: a request that fails after step 1 but before step 4 can leave one or two orphaned `care_plan_inputs/` objects (the merged PDF, and now this PRD's payload object) with no Firestore doc ever pointing at them. That tradeoff is not new; this PRD's object just becomes the second thing it already applies to, and the same lifecycle rule already cleans up both (§4.4) — nothing about this ordering needs to change, and nothing new needs to be added to protect it.

### 4.8 Cleanup — mirroring `input_pdf_gcs_uri`'s two existing delete sites

**The Firestore field itself is never `DELETE_FIELD`'d.** This is a deliberate departure from 02's own treatment of `input_text`/`input_provenance` (which *were* `DELETE_FIELD`'d at `complete_job`/`fail_job`, because they held the actual PHI text inline). `input_payload_gcs_uri` is a short pointer string, structurally identical to `input_pdf_gcs_uri` — which today is *not* cleared from the completed/failed doc; it stays as a (by then dangling, once the object is deleted) reference. This is safe because nothing ever reads `input_payload_gcs_uri` again after the one point each of the two cleanup call sites below deletes the object it points at, and — unlike a text field — a `gs://.../<uuid>.json` string carries no PHI of its own. Mirroring `input_pdf_gcs_uri`'s existing (accepted, working) treatment exactly is simpler than inventing a new Firestore-cleanup step for a field that was designed from the start not to need one.

**`backend/utils/firebase.py`: `complete_job`/`fail_job` lose their `input_text`/`input_provenance` `DELETE_FIELD` entries.** These fields no longer exist anywhere on `JobDoc` (§4.11), so there is nothing left to delete. Old (post-02):
```python
update_fields: dict = {
    "status": "completed",
    "stage": 5,
    "output_data": output_data,
    "name": name,
    "completed_at": now,
    "updated_at": now,
    "input_text": firestore.DELETE_FIELD,
    "input_provenance": firestore.DELETE_FIELD,
}
```
New:
```python
update_fields: dict = {
    "status": "completed",
    "stage": 5,
    "output_data": output_data,
    "name": name,
    "completed_at": now,
    "updated_at": now,
}
```
(Same removal in `fail_job`, whose `update_fields` dict is otherwise unchanged.) Update both functions' docstrings to drop the "Always clears input_text and input_provenance" language — replace with a short note that the job's raw input now lives in GCS, not on this document, and is cleaned up by `routes/worker.py`'s `finally` block and the `DELETE /jobs/<job_id>` route instead (both below), not by this function.

**`backend/routes/worker.py`'s existing `finally` block gains a sibling delete.** Old:
```python
finally:
    if job is not None and job.input_pdf_gcs_uri:
        delete_gcs_object(job.input_pdf_gcs_uri)
```
New:
```python
finally:
    if job is not None:
        if job.input_pdf_gcs_uri:
            delete_gcs_object(job.input_pdf_gcs_uri)
        if job.input_payload_gcs_uri:
            delete_gcs_object(job.input_payload_gcs_uri)
```
This `finally` block already runs on every path out of `_run` once `job` is bound — success, every `fail_job` early-return, the timeout path, and the outer `except Exception` handler — so the input payload object is deleted exactly when `input_pdf_gcs_uri`'s object already is, with no new control flow. `delete_gcs_object` is already idempotent-safe (swallows `NotFound`), so this is harmless even in the §4.10 case where the object is already gone.

**`backend/routes/jobs.py::delete_job` gains the same sibling delete**, for a user who deletes a job while it is still processing (before the worker's own `finally` ever ran). Old:
```python
gcs_uri = data.get("input_pdf_gcs_uri")
if gcs_uri:
    delete_gcs_object(gcs_uri)  # best-effort; logs+swallows, never raises
ref.delete()
```
New:
```python
gcs_uri = data.get("input_pdf_gcs_uri")
if gcs_uri:
    delete_gcs_object(gcs_uri)  # best-effort; logs+swallows, never raises
payload_gcs_uri = data.get("input_payload_gcs_uri")
if payload_gcs_uri:
    delete_gcs_object(payload_gcs_uri)  # best-effort; same as above
ref.delete()
```

**What happens if neither cleanup site ever runs** (a worker that crashes before reaching its `finally`, or a job nobody ever deletes): the object is orphaned in `care_plan_inputs/` until the existing 1-day lifecycle rule removes it (§4.4) — no new backstop needed, since it's already the backstop for `input_pdf_gcs_uri` today and this object shares its prefix.

### 4.9 `backend/services/care_plan_input.py` — `load_job_input` replaces the two job-doc-shaped readers

Old (post-02), both in `care_plan_input.py`:
```python
def resolve_input_from_job_doc(job) -> str:  # job: models.job.JobDoc
    return job.input_text or ""


def resolve_units_from_job_doc(job) -> list[Unit]:  # job: models.job.JobDoc
    return unitize(job.input_text or "", job.input_provenance)
```

Both are **deleted outright**, not kept as wrappers — see §9 and §4.14 for why, and see §4.10 for what replaces their one call site. New function in their place:

```python
def load_job_input(job) -> tuple[str, list[SourceSpan]]:  # job: models.job.JobDoc
    """Download and parse the (text, provenance) pair the API wrote to GCS
    at job-creation time (upload_job_input, SS4.5) -- the one GCS read this
    performs per job, spent once at the start of the worker's run
    (routes/worker.py). Supersedes resolve_input_from_job_doc and
    resolve_units_from_job_doc (PRD 02 SS4.7), which read job.input_text/
    job.input_provenance directly off the job doc; neither field exists on
    JobDoc any more (PRD 09 SS4.11).

    Raises SimplifyError(ErrorCode.PIPELINE_ERROR) -- never a bare
    exception -- if the job has no input_payload_gcs_uri at all, the
    object is missing, or its contents fail to parse as a JobInputPayload.
    This is an expected failure mode, not just a theoretical one: see PRD
    09 SS4.10 for a concrete, code-derivable race that produces it."""
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

### 4.10 `backend/routes/worker.py` — the new call site, and the failure mode

Old (post-06, per 06 §4.6's wiring):
```python
from services.care_plan_input import resolve_input_from_job_doc, resolve_units_from_job_doc
...
source_kind = job.input_source_kind
text = resolve_input_from_job_doc(job)
units = resolve_units_from_job_doc(job)     # PRD 02 SS4.7's reconstruction, spent here

if len(text.strip()) < Constants.Uploads.MIN_MEANINGFUL_CONTENT_CHARS:
    fail_job(job_id, build_error_data(ErrorCode.EMPTY_DOCUMENT))
    return "", 200
```
New:
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
`SimplifyError` is added to `routes/worker.py`'s existing `from errors import ErrorCode, build_error_data, build_error_data_from_exc` import line.

**Why `ErrorCode.PIPELINE_ERROR`, reused rather than invented** (matching how 03 §4.5 reused two existing codes rather than adding one, per this task's own instruction to prefer reuse): `errors/codes.py`'s `PIPELINE_ERROR` is defined exactly for this shape of failure — `message="Pipeline error"`, `details_template="Unexpected error during processing: {detail}"`, `http_status=500`, `retryable=True` — a generic, already-classified "something went wrong before/during processing that isn't the document's fault" bucket, distinct from `EMPTY_DOCUMENT` (a *content* problem: real bytes were read, they just had no usable text) and from `FILE_PARSE_FAILED` (a *format* problem: an uploaded file's bytes couldn't be decoded as its claimed type). A missing or corrupt GCS transport object is neither of those — it is an internal-infrastructure failure the user's document had nothing to do with, which is exactly `PIPELINE_ERROR`'s stated purpose.

**Why this needs an explicit, catchable failure mode at all — a concrete race, not a hypothetical.** Re-read `execute_job`'s existing lease-expiry logic: when a job is redelivered by Cloud Tasks while its Firestore doc still says `status == "processing"`, the worker checks `lease_elapsed_s` against `Constants.Deadlines.SINGLE_JOB_INTERNAL_DEADLINE_S` (270s). If the lease expired, "the original attempt almost certainly crashed... allowed to run again, exactly like a first attempt" — the existing code's own comment. Now trace what a crashed *first* attempt may have already done before dying: reach its `finally` block (which runs on `except Exception` too, and now deletes `input_payload_gcs_uri`, §4.8) and successfully delete the GCS object, but then fail (crash, OOM-kill, deploy-time restart) *before or during* its own `fail_job`/`complete_job` Firestore write — leaving the doc stuck at `status == "processing"` with `input_payload_gcs_uri` already deleted. The next delivery, after the lease expires, is explicitly *allowed to retry* by this codebase's own existing design (`backend/tests/routes/test_jobs_e2e_scenarios.py::test_redelivery_after_lease_expired_retries_and_completes` already exercises exactly this "stuck processing, past its budget, gets retried" scenario) — and that retry now finds a job doc whose `input_payload_gcs_uri` points at an object that is genuinely, permanently gone. `load_job_input` turning that into a clean `SimplifyError(PIPELINE_ERROR)` rather than an uncaught `NotFound` bubbling into the generic `except Exception` handler (which would still produce a correct, if less specifically labeled, outcome — `build_error_data_from_exc` classifies unrecognized exceptions as `UNKNOWN_ERROR`) is the entire point of this section: a *known*, *named* failure mode gets a *known*, *named* error code, exactly as `EMPTY_DOCUMENT`/`JOB_TIMEOUT` already do for their own known failure modes.

**Why the worker returns `("", 200)`, not a 500, on this failure** (Cloud Tasks semantics: 200 = don't redeliver): matching the existing `EMPTY_DOCUMENT`/`JOB_TIMEOUT` pattern exactly, not a new policy. `ErrorInfo.retryable=True` on `PIPELINE_ERROR` is a **client-facing** hint ("resubmitting a fresh job is worth trying") — it does not mean "Cloud Tasks should redeliver this exact task." Redelivering the identical task cannot help here: the object is gone for good (§2's Non-Goal — no resumption machinery), so nothing about trying the same `job_id` again would ever succeed. This is the same distinction the existing code already draws for `JOB_TIMEOUT` (also presumably client-retryable, also still a 200-to-Cloud-Tasks terminal outcome) — this PRD introduces no new interpretation of that split, just one more code path that lands in the same "cleanly fail, tell Cloud Tasks to stop" bucket.

### 4.11 `backend/models/job.py` — `JobDoc` field changes

Old (post-02):
```python
class JobDoc(JsonModel):
    ...
    # ── Input provenance ──────────────────────────────────────────────────
    input_source_kind: SourceKind
    input_text: Optional[str] = None
    input_source_filename: str
    input_pdf_gcs_uri: Optional[str] = None
    input_provenance: list[SourceSpan] = Field(default_factory=list)
    input_version: str = "v1-2"
    grading_enabled: bool = False
```
New:
```python
class JobDoc(JsonModel):
    ...
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
Remove the now-unused `from .provenance import SourceSpan` import 02 added to this file (nothing in `job.py` references `SourceSpan` any more).

`for_single`'s docstring, old:
```python
"""input_fields dict must contain:
  input_source_kind, input_text, input_source_filename,
  input_pdf_gcs_uri, input_provenance, input_version, grading_enabled
"""
```
New:
```python
"""input_fields dict must contain:
  input_source_kind, input_payload_gcs_uri, input_source_filename,
  input_pdf_gcs_uri, input_version, grading_enabled
"""
```
No other change to `for_single` — it already forwards `**input_fields` directly.

### 4.12 `MAX_TEXT_BYTES` — removed, on both sides of the mirror

**Decision: delete `Constants.Uploads.MAX_TEXT_BYTES` and the byte-length branch of `validate_extracted_text_length` entirely. `Constants.Uploads.MAX_TEXT_LENGTH` (500,000 chars) is unchanged and is now the only input-length cap.**

Being honest about the three possible outcomes the task asked for (raise / remove / retain-for-a-different-real-reason):

- **Its stated reason is gone.** `MAX_TEXT_BYTES`'s own comment says it exists to keep `input_text` "under the 1,048,576 byte (1 MiB) hard document limit." `input_text` no longer touches Firestore at all after this PRD — there is no document for it to be a byte inside of any more. The reason doesn't shrink or change scope; it fully stops applying.
- **No new, real, independent reason survives to retain a distinct byte cap.** Checked each candidate honestly:
  - *GCS object size*: a GCS object's practical size ceiling (5 TiB) is not a realistic constraint at any size this app produces. Worst case under the still-unchanged `MAX_TEXT_LENGTH` = 500,000 chars is 4 bytes/char (the UTF-8 worst case) ≈ 2 MB — trivial to write and read.
  - *LLM input cost/latency*: `MAX_TEXT_LENGTH`'s own comment already establishes "enormous headroom below the model's input context" at the *character*-count level, and this app's actual documents are, per that same comment, "well under 100K chars" in practice — nowhere near either cap. A separate *byte*-denominated ceiling on top of an already-generous *character* ceiling adds no additional real protection against cost or latency that the character cap doesn't already provide.
  - *Firestore's other per-field limits* (e.g. the ~1,500-byte auto-indexed-field truncation risk `test_jobs_e2e_scenarios.py`'s `_max_leaf_string_bytes` check guards against): irrelevant now, since `input_text` is never a Firestore field of any size.
  - *OCR/Vertex request-size limits*: already independently governed by `Constants.Limits.MAX_AGGREGATE_FILE_BYTES` (10 MB, upload-time) and the image OCR downscale ceiling (02 §4.5) — neither is about *extracted text* byte size, and neither needs a companion here.
  - Nothing else in this codebase reads `MAX_TEXT_BYTES` for a reason unrelated to the Firestore limit (confirmed by the grep in §9).
- **`validate_text_storable`'s NUL/lone-surrogate check is unaffected and stays** — it protects a different failure than the byte-count cap does, and that failure is not Firestore-specific: `upload_job_input`'s `json.dumps(...)` can still produce a Python string containing an escaped lone surrogate (JSON's `\uXXXX` escape permits encoding one even though it isn't a valid Unicode scalar value), and the eventual UTF-8 encode `blob.upload_from_string` performs against that string would raise `UnicodeEncodeError` for the same underlying reason a Firestore gRPC write would have. `validate_text_storable` already runs upstream of `upload_job_input` on every path (inside `resolve_uploaded_files`, per-page, and in `_resolve_job_input`'s pasted-text branch, both via `validate_extracted_text_length`), so this failure is still caught before it would ever reach the GCS write — just for a different underlying write target than before.

`utils/constants.py`, old:
```python
        # Upper bound on extracted/pasted document text, enforced up front
        # (routes/jobs.py, services.care_plan_input) before any job is
        # enqueued. Not a practical limit on real clinical documents (even a
        # long chart is well under 100K chars) -- exists only to fail fast on
        # a pathological input, with enormous headroom below the model's
        # input context. The output ceiling is Llm.MAX_TOKENS_LONG_FORM, not this.
        MAX_TEXT_LENGTH: int = 500_000

        # UTF-8-encoded BYTE budget, enforced alongside MAX_TEXT_LENGTH (char
        # count alone doesn't bound bytes for non-ASCII text). HAZARD: sized
        # to keep the full care_plan_outputs Firestore doc under the 1,048,576
        # byte (1 MiB) hard document limit -- Firestore measures size in
        # UTF-8 bytes, not codepoints, so e.g. 500K CJK chars is ~1.5 MB.
        # Exceeding this previously caused an uncaught Firestore write
        # failure (500) instead of a clean 400 (edge-case review Finding 1).
        # 350,000 B leaves a large safety margin below the ~896,576 B
        # actually available for input_text once job metadata and the
        # trimmed output_data reserve are accounted for -- do not raise this
        # without re-deriving that budget.
        MAX_TEXT_BYTES: int = 350_000
```
New:
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

`services/care_plan_input.py::validate_extracted_text_length`, old:
```python
def validate_extracted_text_length(text: str) -> None:
    """Raise ValueError if extracted or pasted document text is unsafe to
    store, or exceeds the configured maximum length.
    ...
    Two independent length checks, both must pass:
    - MAX_TEXT_LENGTH: a Python character (codepoint) count. The original
      check; kept as-is so ASCII-only input's allowed length is unchanged.
    - MAX_TEXT_BYTES: a UTF-8-encoded byte count. Added because Firestore's
      1,048,576-byte (1 MiB) per-document hard limit is a *byte* limit, and
      the char count alone doesn't bound it for non-ASCII text -- 500,000
      chars of CJK/emoji is 1.5-2 MB in UTF-8, well past the char check
      failing to catch it (see Constants.Uploads.MAX_TEXT_BYTES for the full
      accounting, and edge-case review Finding 1).
    """
    validate_text_storable(text, field="Extracted document text")

    char_length = len(text)
    if char_length > Constants.Uploads.MAX_TEXT_LENGTH:
        raise ValueError(...)

    byte_length = len(text.encode("utf-8"))
    if byte_length > Constants.Uploads.MAX_TEXT_BYTES:
        raise ValueError(...)
```
New:
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

**Frontend mirror: `frontend/src/utils/validateFiles.ts` loses its own `MAX_TEXT_BYTES` for the same reason.** That file's `MAX_TEXT_BYTES` export exists, per its own comment, only to "Mirror[] backend `Constants.Uploads.MAX_TEXT_BYTES`... keep these two values in sync." Leaving it in place once the backend constant is gone would be worse than doing nothing: the frontend would then client-side-reject a pasted-text submission (any UTF-8-heavy text between ~350,000 and 500,000 bytes) that the backend would now happily accept — a real, user-visible regression this PRD would have introduced, not a merely-stale comment. `validateText()`'s `MAX_TEXT_LENGTH` check (its own mirror of the backend's surviving cap) is unchanged. Concretely: remove the `MAX_TEXT_BYTES` and `MAX_TEXT_BYTES_CHECK_THRESHOLD` exports/consts, and the `if (text.length > MAX_TEXT_BYTES_CHECK_THRESHOLD) { ... }` block inside `validateText()`, leaving only the `MAX_TEXT_LENGTH` check that already precedes it. `frontend/src/tests/utils/validateFiles.test.ts`'s `MAX_TEXT_BYTES`-specific tests (the byte-boundary and multibyte-padding cases) are removed alongside it (§7.4). This is the one frontend file this PRD's design touches — noted here rather than as a silent aside, since the task scope for writing this document is backend-first but a design that leaves a known, self-inflicted product regression undocumented is not a complete design.

### 4.13 PHI exposure — an honest comparison, not an automatic privacy win

What this PRD **actually improves**:
- Firestore's `care_plan_outputs` document shrinks by exactly `input_text` + `input_provenance`'s combined size for the entire duration of every job (previously up to ~350,000 + provenance-map bytes, present on every `not_started`/`processing` doc; now zero, always).
- `MAX_TEXT_BYTES`'s Firestore-driven input-size cap is gone, with no product-facing cost (§4.12).
- Both of this app's per-job raw-input artifacts (the merged-PDF audit copy and now the pipeline's own text transport) live under one bucket, one prefix, one lifecycle policy, one mental model for "where does a job's raw input go and when does it disappear" — rather than one artifact's lifecycle being "a GCS object with a lifecycle rule" and the other's being "a Firestore field with a `DELETE_FIELD` write."

What this PRD **does not improve, stated plainly**:
- **This is not a privacy win by default — it is a lateral move in exposure, made honest.** The same PHI (raw clinical text, plus a structural map of which file/page it came from) still exists in plaintext, in the same GCP project, under the same `GCP_BUCKET_NAME`, for a comparable window (from job creation until the worker's `finally` block runs, typically well under the 270-second internal deadline — the same window `input_text` already lived in Firestore for today). Moving the *storage product* does not by itself shrink *who can read it* or *for how long it exists* — both are governed by IAM/lifecycle policy on the new home, which must be at least as tight as Firestore's security rules were, not assumed to be tighter (§8's IAM item is exactly this check).
- **GCS and Firestore are both already encrypted at rest by default on GCP** — this move is not "moving PHI from an unencrypted store to an encrypted one." There is no encryption-posture improvement to claim here.
- **The access-control *mechanism* changes, which is a real difference in kind, not just degree, but not automatically a hardening.** Firestore security rules and GCS bucket IAM are different systems with different default postures and different audit surfaces; this PRD does not audit or tighten either beyond what already exists for `input_pdf_gcs_uri` (whose bucket/IAM this new object reuses exactly, §4.4) — it inherits that artifact's existing security posture rather than establishing a new, more scrutinized one for itself.

The honest framing: this PRD's primary, unambiguous win is architectural (Firestore holds only render-relevant state, matching the governing principle) and removes one artificial input-size constraint (`MAX_TEXT_BYTES`) with no compensating downside. It is not, by itself, a demonstrated reduction in PHI exposure risk — that would require an IAM/retention audit of the GCS bucket this PRD reuses, which is exactly what §8 asks the owner to do, since it's the one part of this design this PRD cannot verify from inside the repo.

### 4.14 Relationship to PRD 02 — what supersedes, what stands

**Superseded by this PRD:**
- 02 §4.1's "Option 2 (recommended)" conclusion, specifically the *persistence* half of it: "It is persisted as a new `JobDoc.input_provenance: list[SourceSpan]` field" — no longer true. `input_provenance` is never a `JobDoc` field; it lives inside the `JobInputPayload` GCS object (§4.1).
- 02 §4.10's `JobDoc.input_text`/`input_provenance` fields — both removed (§4.11).
- 02 §4.11's `_resolve_job_input` diffs — superseded by this PRD's own §4.6 diffs (which build on 02's structure — `provenance_for_pasted_text`, `resolved.provenance` — but change what gets written where).
- 02 §4.12's `complete_job`/`fail_job` `DELETE_FIELD` additions — removed again by this PRD (§4.8), since the fields they clean up no longer exist.
- 02 §4.13's Firestore size-budget accounting — moot. There is no longer a shared byte budget between `input_text` and `input_provenance` to account for, because neither is on the document being budgeted.
- 02 §4.7's `resolve_input_from_job_doc`/`resolve_units_from_job_doc` — both deleted (§4.9); `resolve_units_from_job_doc`'s signature question the task asked about is answered by deleting the function entirely rather than resigning it: once `job.input_text`/`job.input_provenance` don't exist, a function whose entire body was "read those two attributes and call `unitize`" has nothing left to do that its caller (`routes/worker.py`, which already has to call `load_job_input` to get `(text, provenance)` in the first place) can't do itself in one line — `unitize(text, provenance)`, called directly, with `unitize` imported from `services.unitizer` exactly as it already is inside the function this PRD deletes. Keeping a one-line pass-through wrapper around a call the worker can make directly would be exactly the kind of vestigial indirection the parent brief argues against elsewhere.

**Left standing, unchanged, by this PRD:**
- `models/provenance.py::SourceSpan` — same fields, same 0-indexed convention, same role as the compact per-(file,page) line-range map. This PRD adds `JobInputPayload` to the same file; it does not touch `SourceSpan` itself.
- `services/unitizer.py::unitize`/`provenance_for_pasted_text` — both unchanged. `unitize(text, provenance)` is called from a different place (`routes/worker.py` directly, instead of from inside `resolve_units_from_job_doc`) but with the identical two arguments, in the identical order, doing the identical work.
- `services/care_plan_input.py::resolve_uploaded_files`'s provenance computation (02 §4.7) — unchanged. It still returns `ResolvedInput.provenance: list[SourceSpan]`; this PRD's `upload_job_input` is simply a new consumer of that same return value, called from `_resolve_job_input` at the same point `resolved.text`/`resolved.provenance` first become available.
- `models/input.py::ResolvedInput.provenance` — unchanged.
- 02's unit-granularity table (§4.2), OCR downscale ceiling change (§4.5), `source_separator` retirement (§4.6), and `extract_pages_from_pdf`/`extract_pages_from_bytes` rewrites (§4.4/§4.7) — none of these are about the API→worker transport; all stand exactly as 02 specifies.

A short pointer recording this is added to `02-unitization-and-provenance/PRD.md` §9 (not restructuring 02, not rewriting its §4.11-§4.13) — see the companion edit accompanying this PRD.

## 5. API Change Summary

`JobDoc`'s Firestore wire shape, relative to the post-02 shape:

| Key | Post-02 | Post-09 |
|---|---|---|
| `input_text` | present while `status in {"not_started", "processing"}`; `list[str]`-sized blob up to `MAX_TEXT_BYTES` (350,000 B); deleted via `DELETE_FIELD` at completion/failure | **removed entirely** — never a `JobDoc` field, in any state |
| `input_provenance` | present while processing (per 02 §4.10-§4.12); deleted at completion/failure | **removed entirely** — never a `JobDoc` field, in any state |
| `input_payload_gcs_uri` | did not exist | **new**: `Optional[str]`, a `gs://` URI, present from job creation onward, never deleted from the doc (the underlying object is deleted, not this field — §4.8) |

No route signature, HTTP status code, or error-response shape changes (the one new failure mode, §4.10, reuses `ErrorCode.PIPELINE_ERROR`'s already-existing HTTP mapping via the same `fail_job`/`error_data` path every other worker-side failure already uses — nothing about the `GET`/poll response shape a client sees changes). `output_data`/`CarePlanInternal` is completely unaffected, exactly as it was for 02 — `input_text`/`input_provenance`/`input_payload_gcs_uri` never appear there.

## 6. Frontend Change Summary

**Effectively N/A for job handling** — the frontend never read `input_text`/`input_provenance` before this PRD and doesn't read `input_payload_gcs_uri` after it; job polling and rendering are both unaffected. The one real frontend change is the `MAX_TEXT_BYTES` removal from `frontend/src/utils/validateFiles.ts` specified in §4.12, needed to keep the client-side pasted-text length check from being stricter than the backend it's supposed to mirror.

## 7. Testing

### 7.1 Files with breaking changes

| File | What breaks | What it should assert instead |
|---|---|---|
| `backend/tests/utils/test_constants.py` | `test_...` asserting `Constants.Uploads.MAX_TEXT_BYTES == 350_000` and `MAX_TEXT_BYTES < MAX_TEXT_LENGTH` | Delete both assertions (the constant no longer exists); no replacement needed — `MAX_TEXT_LENGTH`'s own value is unchanged and needs no new test. |
| `backend/tests/services/test_care_plan_input.py` (four tests referencing `Constants.Uploads.MAX_TEXT_BYTES`, per the grep in §9) | Reference a deleted constant | Rewrite each as a `MAX_TEXT_LENGTH`-only boundary test (char-count boundary instead of byte-count boundary), or delete if the case they covered (a multibyte string that's under the char cap but over the byte cap) no longer has anything to assert now that the byte cap is gone. |
| `backend/tests/routes/test_jobs.py` (four tests referencing `MAX_TEXT_BYTES`, same grep) | Same | Same treatment as above, applied at the route level (submit text, assert 400 `INPUT_VALIDATION_ERROR` at the char boundary; delete the byte-specific multibyte-boundary test). |
| `backend/tests/routes/test_jobs.py::test_post_multipart_one_blank_file_among_several_still_succeeds` | `assert "perfectly good clinical note" in payload["input_text"]` — `payload` (the dict passed to `create_job_doc`) no longer has an `input_text` key | Capture the JSON `upload_job_input` uploads instead: the test already mocks `services.care_plan_input.get_gcs_bucket` and sets `bucket.blob.return_value = MagicMock()`; capture `bucket.blob.return_value.upload_from_string.call_args.args[0]`, `json.loads` it, and assert `"perfectly good clinical note" in captured["text"]`. Mirrors how `test_unicode_emoji_filename_accepted_and_isolated_from_gcs_path` (same file) already asserts against mocked `blob()` call args for the PDF path. |
| `backend/tests/routes/test_jobs_e2e_scenarios.py`'s Scenario 2 test (phone-photo OCR path) | `for t in ocr_texts: assert t in doc["input_text"]` reads the processing-state doc's `input_text`, which no longer exists | Same fix as above: inspect the mocked GCS `upload_from_string` call captured by `_post_job`'s `mock_gcs` patching, parse the JSON, assert each OCR string is `in captured["text"]`. |
| `backend/tests/routes/test_jobs_e2e_scenarios.py` — the four `assert "input_text" not in doc` lines (Scenarios 1, 2, 4, and the LLM-quota-error test) | Still pass, but now vacuously — `input_text` never exists on any doc, processing or completed, so this no longer tests the completion-time cleanup it used to test | Keep each as a residual regression guard (cheap insurance against the field ever being reintroduced), but it is no longer this PRD's load-bearing assertion — see the new test below for what replaces it as the actually-meaningful check. |
| `backend/tests/routes/test_jobs_e2e_scenarios.py::TestScenario3...`'s (or wherever 02 §7.3 landed it) "processing-state doc contains a non-empty `input_provenance`" test | Directly contradicts this PRD — the processing-state doc must **not** contain `input_provenance` | Invert it: assert `"input_provenance" not in doc` and `"input_text" not in doc` on the **processing**-state doc (read immediately after `POST /jobs`, before the worker runs), and assert `doc["input_payload_gcs_uri"].startswith("gs://")` instead. |
| `backend/tests/routes/test_jobs_e2e_scenarios.py::test_delete_mid_worker_write_does_not_resurrect_doc_and_gcs_not_orphaned` | Its fixture doc only sets `input_pdf_gcs_uri`; `mock_delete_gcs.assert_called_once_with(...)` only checks one URI | Add `"input_payload_gcs_uri": "gs://test-bucket/care_plan_inputs/anon-1/inputs/xyz.json"` to the fixture doc, and assert `delete_gcs_object` was called with **both** URIs (`assert_any_call` for each, or assert `call_count == 2`) — proving §4.8's sibling delete actually lands in the same code path this test already exercises. |
| Every raw job-doc literal in `test_jobs_e2e_scenarios.py` that sets `"input_text": text` / `"input_provenance": ...` directly (the redelivery tests, `_make_pending_job`, the LLM-error tests around line 960-1050) | These construct a `JobDoc`-shaped Firestore doc by hand, bypassing `create_job`, to test worker behavior in isolation — the literal keys no longer match `JobDoc`'s fields | Replace `"input_text": text` with `"input_payload_gcs_uri": "gs://test-bucket/care_plan_inputs/anon-1/inputs/fixture.json"` in each, and add a `patch("services.care_plan_input.download_gcs_string", return_value=json.dumps({"text": text, "provenance": []}))` (or monkeypatch `services.care_plan_input.load_job_input` directly, returning `(text, [])`) around the `_run_worker` call in each affected test — mirroring how these same tests already patch `routes.worker.run_care_plan_pipeline`. |
| `backend/tests/routes/test_worker.py` (per 01 §7.3/06's own test-migration notes, wherever `resolve_input_from_job_doc`/`resolve_units_from_job_doc` are mocked per-test) | Mocks a function this PRD deletes | Replace with `monkeypatch.setattr("routes.worker.load_job_input", lambda job: ("some text", []))` (or `patch("services.care_plan_input.load_job_input", ...)`, matching whichever import style the test file already uses for its other worker-boundary mocks). |
| `backend/tests/services/test_care_plan_input.py::test_resolve_units_from_job_doc_round_trips_through_a_job_doc_shaped_object` (02 §7.3's own new test) | Tests a function this PRD deletes | Delete. Its property (round-tripping `(text, provenance)` through to `unitize`'s output) is still worth having — replace with a `test_load_job_input_round_trips_through_a_mocked_gcs_object` that mocks `download_gcs_string` to return a `JobInputPayload(...).to_dict()`-shaped JSON string, calls `load_job_input(fake_job)`, and asserts the returned `(text, provenance)` matches what was uploaded. |

### 7.2 Files checked and confirmed unaffected

- `backend/tests/models/test_ledger.py`, `test_unitizer.py` (02's) — `Unit`, `Fact`, `unitize`, `provenance_for_pasted_text` are all untouched by this PRD (§4.14); none of their tests reference `JobDoc`, `input_text`, or `input_provenance`.
- `backend/care_plan/pipeline.py` and every `backend/tests/care_plan/*` file — this PRD does not touch the pipeline, any prompt, or `CarePlan`/`Fact` in any way; `units`/`text` reach `run_care_plan_pipeline` with the identical values they had before, just sourced from `load_job_input` + `unitize` instead of `resolve_input_from_job_doc` + `resolve_units_from_job_doc`.
- `backend/tests/models/test_job.py` (if one exists testing `JobDoc` construction generically) — confirmed no test asserts full-dict equality including `input_text`/`input_provenance` as a blanket snapshot; spot-check at implementation time, but the pattern (per 02 §7.1's identical finding for `test_jobs.py`) is per-key lookups, not whole-payload equality, so most call sites tolerate the field rename without change.

### 7.3 New tests this PRD should add

- **`backend/tests/models/test_provenance.py`** additions: `test_job_input_payload_round_trips_through_to_dict_from_dict` — construct a `JobInputPayload` with a non-trivial `text` and a two-element `provenance` list, round-trip through `to_dict()`/`from_dict()`, assert equality; `test_job_input_payload_rejects_unknown_key` — `extra="forbid"` guard, same pattern as `SourceSpan`'s own test.
- **`backend/tests/utils/test_gcs.py`** (new, or additions to an existing one if `delete_gcs_object` already has tests there — confirm at implementation time): `test_download_gcs_string_returns_decoded_text` (mock the GCS client, assert the returned string matches a mocked `download_as_text()`); `test_download_gcs_string_raises_not_found_for_missing_object` (mock `download_as_text` to raise `google.api_core.exceptions.NotFound`, assert it propagates uncaught — this function does NOT swallow, unlike `delete_gcs_object`); `test_download_gcs_string_rejects_non_gs_uri`.
- **`backend/tests/services/test_care_plan_input.py`** additions:
  - `test_upload_job_input_writes_json_with_text_and_provenance` — mock `get_gcs_bucket`, call `upload_job_input(text, provenance, "user-1")`, capture the `upload_from_string` call, `json.loads` it, assert `["text"] == text` and `["provenance"]` matches the input spans' serialized form; assert the returned URI matches `gs://<bucket>/care_plan_inputs/user-1/inputs/<uuid>.json` (regex on the `<uuid>` segment, exact match on the rest — mirrors how `test_jobs.py` already asserts `payload["input_pdf_gcs_uri"].startswith("gs://test-bucket/care_plan_inputs/")` for the PDF path).
  - `test_upload_job_input_raises_if_bucket_env_var_missing` — clear `GCP_BUCKET_NAME`, assert `RuntimeError` (mirrors `upload_combined_pdf`'s identical existing guard/test).
  - `test_load_job_input_happy_path` — mock `download_gcs_string` to return a `JobInputPayload(text="hello", provenance=[...]).to_dict()`-shaped JSON string; assert `load_job_input(fake_job)` returns the matching `(text, provenance)` tuple.
  - `test_load_job_input_raises_pipeline_error_when_gcs_uri_is_missing` — `fake_job.input_payload_gcs_uri = None`; assert `SimplifyError` with `error_code == ErrorCode.PIPELINE_ERROR`.
  - `test_load_job_input_raises_pipeline_error_on_not_found` — mock `download_gcs_string` to raise `google.api_core.exceptions.NotFound`; assert the same `SimplifyError`/`PIPELINE_ERROR` mapping — this is the test that directly proves §4.10's lease-expiry race is handled cleanly.
  - `test_load_job_input_raises_pipeline_error_on_malformed_json` — mock `download_gcs_string` to return `"not json"`; assert the same mapping.
  - `test_load_job_input_raises_pipeline_error_on_schema_mismatch` — mock `download_gcs_string` to return valid JSON missing the required `text` key; assert the same mapping (proves `JobInputPayload.from_dict`'s `ValidationError` is caught by the broad `except Exception`, not left to propagate raw).
- **`backend/tests/routes/test_worker.py`** additions:
  - `test_execute_job_fails_cleanly_with_pipeline_error_when_input_payload_missing` — full route-level test: post a job (or construct a pending doc directly), monkeypatch `load_job_input` (or the `download_gcs_string` it calls) to raise `SimplifyError(ErrorCode.PIPELINE_ERROR, ...)`; call `_run_worker`; assert `worker_resp.status_code == 200`, `doc["status"] == "error"`, `doc["error_data"]["code"] == "PIPELINE_ERROR"` — the route-level proof that §4.10's handling actually reaches Firestore correctly, mirroring the existing `test_llm_429_quota_exceeded_surfaces_as_safe_terminal_error` pattern in `test_jobs_e2e_scenarios.py` exactly.
  - `test_execute_job_finally_block_deletes_both_gcs_objects_on_success` — a full happy-path run with both `input_pdf_gcs_uri` and `input_payload_gcs_uri` set on the job doc; assert `delete_gcs_object` (mocked) is called with both URIs.
  - `test_execute_job_finally_block_deletes_both_gcs_objects_on_failure` — same, but the pipeline itself raises; assert both deletes still happen (proves the `finally` block's placement, not just the happy path).
- **`backend/tests/routes/test_jobs.py`** additions:
  - `test_post_text_job_uploads_payload_and_stores_uri` — pasted-text submission; capture the mocked `upload_from_string` call, assert the uploaded JSON's `"text"` matches the posted text and `"provenance"` is a single span covering the whole string (via `provenance_for_pasted_text`'s existing contract); assert `payload["input_payload_gcs_uri"]` is set and `"input_text" not in payload` / `"input_provenance" not in payload`.
  - `test_post_job_returns_500_when_upload_job_input_raises` — mock `services.care_plan_input.upload_job_input` to raise; assert `resp.status_code == 500`, `mock_create_doc.assert_not_called()` (proves §4.6/§4.7's "never orphans a Firestore doc" property holds for this new failure point too — the request fails before `create_job_doc` is ever reached, since `upload_job_input` runs inside `_resolve_job_input`, which runs before the Firestore write).

### 7.4 Frontend tests

- `frontend/src/tests/utils/validateFiles.test.ts` — remove the tests asserting `validateText('a'.repeat(MAX_TEXT_BYTES))` boundary behavior and the multibyte-padding `MAX_TEXT_BYTES` case (§4.12); the surviving `MAX_TEXT_LENGTH`-boundary tests are unaffected and need no change.

## 8. Manual Intervention Required From You

- **Confirm the `juno-worker` Cloud Run service's runtime service account can read (`storage.objects.get`), not just delete, objects in `GCP_BUCKET_NAME`.** This is a genuinely new requirement this PRD introduces: today, the worker only ever calls `delete_gcs_object` on `input_pdf_gcs_uri` — it has never needed to *read the contents* of a GCS object, only delete-by-URI. `download_gcs_string` (§4.3) is the first time the worker's own runtime identity (not `juno-worker-invoker`, which per `.github/workflows/deploy.yml`'s top-of-file comment is only the OIDC *invoke* identity Cloud Tasks uses to call the worker's HTTP endpoint — a different thing from the container's own runtime service account) needs `storage.objects.get` on this bucket. Its existing delete permission proves it already has *some* GCS role on the bucket, but "can delete" and "can read content" are distinct IAM permissions that are not guaranteed to travel together depending on which predefined role was granted — this is not verifiable from inside this repo and needs a one-time IAM check (`gcloud storage buckets get-iam-policy gs://$GCP_BUCKET_NAME`, checked against the worker's runtime SA) before this PRD is deployed.
- **No new GCS lifecycle rule or `deploy.yml` change is needed** (noted here so it isn't mistaken for an oversight): the new object reuses the existing `care_plan_inputs/` prefix, already covered by the "Apply GCS lifecycle rules" step's `age:1`/`matchesPrefix: ["care_plan_inputs/"]` rule, applied automatically on every deploy (§4.4). This is a deliberate design choice specifically to avoid adding a manual/infra step here.
- **Smoke-test the new failure path once deployed**: deliberately delete a `care_plan_inputs/.../inputs/*.json` object for a job stuck in `processing` (simulating §4.10's crash-before-terminal-write race) and confirm a redelivered/retried execution produces a clean `error_data.code == "PIPELINE_ERROR"` doc rather than an uncaught 500 — this exercises the one genuinely new runtime behavior this PRD adds that unit/integration tests can approximate but not fully replace (real Cloud Tasks redelivery timing, real IAM).

## 9. Open Questions & Decisions

- `[RESOLVED: one GCS object per job holding both input_text and input_provenance as a single JSON payload (models.provenance.JobInputPayload), not two separate objects.]` — see §4.1. The one consumer (`unitize`) always needs both together; splitting them would double every write/read/delete site for no consumer that exists.
- `[RESOLVED: the object lives under the existing care_plan_inputs/{user_id}/inputs/ prefix, named with a fresh uuid4 (not derived from job_id), and its full gs:// URI is stored on JobDoc as a new field, input_payload_gcs_uri.]` — see §4.4. Reusing the prefix means the existing GCS lifecycle rule already covers it with zero infra change; a job-id-derived path was rejected because job_id doesn't exist yet at the point in `create_job` where this object must be written (the same reason `upload_combined_pdf` already mints its own uuid rather than waiting for one).
- `[RESOLVED: the GCS write (upload_job_input) lands inside _resolve_job_input, at the same point upload_combined_pdf already runs -- i.e. before the Cloud Tasks config check and before job_id/Firestore-doc creation.]` — see §4.7. This preserves the actual invariant `create_job`'s existing comment protects (no orphaned Firestore doc) while accepting the same already-existing GCS-orphan-on-abort tradeoff `upload_combined_pdf` already accepts today, backstopped by the same lifecycle rule.
- `[RESOLVED: unlike upload_combined_pdf (best-effort, tolerated failure, job proceeds with input_pdf_gcs_uri=None), upload_job_input's failure is NOT tolerated -- it propagates uncaught, falling through to create_job's existing generic 500 handler, and no Firestore doc is written.]` — see §4.6. There is no fallback transport for the pipeline's actual input once Firestore is no longer an option by design.
- `[RESOLVED: MAX_TEXT_BYTES is deleted outright (constant, its check in validate_extracted_text_length, and its frontend mirror in validateFiles.ts) -- not raised, not retained under a new justification.]` — see §4.12 for the point-by-point elimination of every candidate real reason to keep a distinct byte cap once its only stated reason (Firestore's 1 MiB limit) stops applying. `MAX_TEXT_LENGTH` (500,000 chars) is unchanged and was already independently justified.
- `[RESOLVED: the worker's one new failure mode -- input_payload_gcs_uri missing, unreadable, or unparseable -- is classified as ErrorCode.PIPELINE_ERROR (existing code, not a new one), raised as SimplifyError from a new load_job_input function, caught explicitly in routes/worker.py, and results in fail_job + a 200 response to Cloud Tasks (no redelivery).]` — see §4.10, including the concrete lease-expiry race (already covered by an existing test, `test_redelivery_after_lease_expired_retries_and_completes`) that makes this a real, not hypothetical, failure mode.
- `[RESOLVED: resolve_input_from_job_doc and resolve_units_from_job_doc (PRD 02 SS4.7) are both deleted outright, not resigned to take (text, provenance) instead of job. The worker calls the new load_job_input(job) -> (text, provenance) once, then calls services.unitizer.unitize(text, provenance) directly.]` — see §4.9/§4.14. Once neither field lives on `job`, a wrapper function whose entire body was "read two job attributes and call `unitize`" has nothing left to add over calling `unitize` directly at the one call site that needs it.
- `[RESOLVED: input_payload_gcs_uri is never DELETE_FIELD'd from the Firestore doc at job completion/failure -- only the underlying GCS object is deleted (worker's finally block, and the DELETE /jobs/<job_id> route). This reverses PRD 02's own treatment of input_text/input_provenance (which WERE DELETE_FIELD'd, because they held the PHI text inline); input_payload_gcs_uri holds no PHI itself and is treated identically to the pre-existing input_pdf_gcs_uri, which is also never DELETE_FIELD'd.]` — see §4.8.
- `[RESOLVED: validate_text_storable's NUL/lone-surrogate checks are unchanged and remain necessary -- they now protect upload_job_input's JSON-then-UTF-8-encode write path instead of a Firestore write, but the underlying failure (a string that cannot be UTF-8-encoded) is identical either way.]` — see §4.12.
- `[RESOLVED: this PRD's PHI-exposure claim is narrow and stated honestly -- it shrinks the Firestore document and removes an artificial size cap, and does NOT by itself claim a reduced exposure window, tighter access control, or an encryption-posture improvement, since both Firestore and GCS are encrypted at rest by default and the new object inherits input_pdf_gcs_uri's existing, unaudited-by-this-PRD bucket IAM posture rather than a newly-hardened one.]` — see §4.13. The one piece of this that needs owner verification (worker SA read permission) is in §8, not asserted as already-true here.
- `[RESOLVED: PRDs 01-08 land first, exactly as written (including 02's now-superseded input_text/input_provenance Firestore fields and 06's now-superseded resolve_input_from_job_doc/resolve_units_from_job_doc wiring); this PRD lands after, as an independent follow-on, not a prerequisite or a modification bundled into any of the eight.]` — see §3 and the header's Depends-on/Depended-on-by lines.
- `[RESOLVED: a short forward-pointer is added to 02-unitization-and-provenance/PRD.md SS9 recording that this PRD supersedes 02's transport decision while leaving its provenance design (SourceSpan, unitize, provenance_for_pasted_text, the unit-granularity table, the OCR ceiling change) standing -- 02 itself is not restructured or rewritten.]` — see the companion edit to 02 §9, made alongside this PRD.
- Grep performed to confirm no other consumer of the deleted symbols survives this PRD: `grep -rn "MAX_TEXT_BYTES\|resolve_input_from_job_doc\|resolve_units_from_job_doc\|job\.input_text\|job\.input_provenance" backend/ frontend/` — every hit outside this PRD's own touched files is a test file already enumerated in §7.1, or `frontend/src/utils/validateFiles.ts`/its test file, both handled in §4.12/§7.4.
- `[OPEN]` — none remaining that block `dev-tasks` from generating tasks for this sub-project deterministically. The two items in §8 are a manual IAM verification and a post-deploy smoke test, not decisions this PRD left unmade.
