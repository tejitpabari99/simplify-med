"""POST /internal/jobs/execute/<job_id> — worker endpoint for Cloud Tasks."""

# ── Imports & blueprint setup ──────────────────────────────────────────────────
import logging
import time
from datetime import datetime, timezone

from flask import Blueprint, request

from utils.firebase import (
    get_job_doc,
    update_job_stage,
    complete_job,
    fail_job,
    verify_oidc_token,
)
from services.care_plan_pipeline import run_care_plan_pipeline
from services.care_plan_input import resolve_input_from_job_doc
from models.pipeline_events import AdapterStepEvent, AdapterResult, AdapterError
from models.care_plan.envelope import CarePlanInternal
from models.job import JobDoc
from models.input import TextInput
from models.metrics import Metrics
from utils.constants import Constants
from utils.misc import derive_output_name
from utils.markers import Markers, SimplifyContext
from utils.job_helpers import canonical_input_type
from utils.gcs import delete_gcs_object
from errors import ErrorCode, build_error_data, build_error_data_from_exc

logger = logging.getLogger(__name__)
worker_bp = Blueprint("worker", __name__)


# ── Job execution handler ──────────────────────────────────────────────────────
@worker_bp.route("/internal/jobs/execute/<job_id>", methods=["POST"])
def execute_job(job_id: str):
    queue_name_header = request.headers.get("X-CloudTasks-QueueName", "").strip()
    if not queue_name_header:
        logger.warning("worker: rejected request without X-CloudTasks-QueueName")
        return "", 403

    if not verify_oidc_token():
        return "", 403

    def _run(scope):
        SimplifyContext.from_g(function="execute_job").apply(scope)
        scope.add("job_id", job_id)

        job: JobDoc | None = None

        try:
            job_doc = get_job_doc(job_id)
            if job_doc is None:
                logger.warning("worker: job doc not found for job_id=%s — skipping", job_id)
                return "", 200

            job = JobDoc.from_firestore(job_doc)

            if job.status in ("completed", "error"):
                logger.info("worker: job %s already in terminal state %s — idempotent return", job_id, job.status)
                return "", 200

            deadline_s = Constants.Deadlines.SINGLE_JOB_INTERNAL_DEADLINE_S

            if job.status == "processing" and job.started_at is not None:
                lease_elapsed_s = (datetime.now(timezone.utc) - job.started_at).total_seconds()
                if lease_elapsed_s < deadline_s:
                    # A prior attempt is still within its own timeout budget --
                    # Cloud Tasks' at-least-once delivery redelivered this task
                    # while that attempt may still legitimately be in flight
                    # (or may have crashed without reaching a terminal state).
                    # Re-running the pipeline here would re-execute the whole
                    # 5-stage LLM pipeline a second time, double-billing every
                    # Vertex AI call it already made (edge-case review Finding
                    # 7). Treat this delivery as a no-op: the original attempt
                    # (or its own _check_timeout below) will reach a terminal
                    # state on its own. Returning 200 tells Cloud Tasks not to
                    # retry again.
                    logger.info(
                        "worker: job %s already processing (leased %.1fs ago, "
                        "budget %ds) — skipping redelivery", job_id, lease_elapsed_s, deadline_s,
                    )
                    return "", 200
                # Lease expired: the original attempt almost certainly crashed
                # or was killed before reaching a terminal state (a healthy
                # attempt would have hit its own _check_timeout well before
                # this). Deliberately does NOT give up on the job -- it's
                # allowed to run again, exactly like a first attempt, so a
                # transient crash doesn't permanently strand it.
                logger.warning(
                    "worker: job %s stuck in processing since %s (%.1fs, exceeds "
                    "%ds budget) — treating as abandoned and allowing retry",
                    job_id, job.started_at.isoformat(), lease_elapsed_s, deadline_s,
                )

            uid = job.uid

            from utils.firebase import firestore_client
            now = datetime.now(timezone.utc)
            firestore_client().collection("care_plan_outputs").document(job_id).update({
                "status": "processing",
                "started_at": now,
                "stage": 1,
                "updated_at": now,
            })

            start = time.monotonic()

            def _check_timeout(stage: int) -> bool:
                elapsed = time.monotonic() - start
                if elapsed > deadline_s:
                    fail_job(job_id, build_error_data(ErrorCode.JOB_TIMEOUT, f"Job timed out at stage {stage}"))
                    logger.warning("worker: job %s timed out at stage %d after %.1fs", job_id, stage, elapsed)
                    return True
                return False

            source_kind = job.input_source_kind
            text = resolve_input_from_job_doc(job)

            # Defensive floor (belt-and-suspenders alongside the per-file check
            # in services.care_plan_input.resolve_uploaded_files): reject not
            # just an empty string but anything below a sane minimum of real
            # content, so a document that is technically non-empty but is
            # really just separator scaffolding around a scanned/no-text-layer
            # file can never silently reach the LLM pipeline (edge-case review
            # Finding 2).
            if len(text.strip()) < Constants.Uploads.MIN_MEANINGFUL_CONTENT_CHARS:
                fail_job(job_id, build_error_data(ErrorCode.EMPTY_DOCUMENT))
                return "", 200

            grading_enabled = job.grading_enabled

            metrics = Metrics.start(
                session_id=job_id,
                pipeline_version=job.input_version,
                input_type=canonical_input_type(source_kind),
            )

            current_stage = 1
            pipeline_result = None
            pipeline_error_data: dict | None = None

            for event in run_care_plan_pipeline(text, metrics, grading_enabled, source_kind=source_kind):
                if isinstance(event, AdapterResult):
                    pipeline_result = event
                elif isinstance(event, AdapterError):
                    pipeline_error_data = event.error_data
                    break
                elif isinstance(event, AdapterStepEvent):
                    if event.status == "active" and event.step != current_stage:
                        current_stage = event.step
                        if _check_timeout(current_stage):
                            return "", 200
                        update_job_stage(job_id, current_stage)

            if pipeline_error_data is not None:
                # Defensive: fall back to a generic error if error_data is
                # unexpectedly missing both code and message.
                if pipeline_error_data.get("code") or pipeline_error_data.get("message"):
                    fail_job(job_id, pipeline_error_data)
                else:
                    fail_job(job_id, build_error_data(
                        ErrorCode.UNKNOWN_ERROR, "Pipeline failed without an error message"
                    ))
                return "", 200

            if pipeline_result is None:
                fail_job(job_id, build_error_data(
                    ErrorCode.UNKNOWN_ERROR, "Pipeline returned no result"
                ))
                return "", 200

            care_plan = pipeline_result.care_plan
            grading   = pipeline_result.grading

            input_model = TextInput(text=text)

            # Read back the timeout-check timer (started at `start = time.monotonic()`
            # above) into the field that already exists on Metrics but was never
            # populated anywhere.
            metrics.total_duration_ms = (time.monotonic() - start) * 1000.0

            envelope = CarePlanInternal(
                metrics=metrics,
                input=input_model,
                grading=grading,
                care_plan=care_plan,
            )
            output_data = envelope.to_dict()

            name = derive_output_name(output_data.get("care_plan", {}), job.input_source_filename)
            output_data["metrics"]["saved_id"] = job_id

            # Jobs are short-lived and the UI never reads raw text/simplified_text/
            # clarified_text, nor the original input text — drop the whole (optional) `raw`
            # key and the (optional) `input.text` key so completed docs stay well
            # under Firestore's 1 MiB doc limit and don't risk the ~1500-byte auto-indexed
            # field limit on these full-document-length strings. `input.text` is popped
            # rather than replacing the whole `input` dict so it round-trips cleanly back
            # into TextInput (text: str | None = None) with no model or frontend change.
            output_data.get("care_plan", {}).pop("raw", None)
            output_data.get("input", {}).pop("text", None)

            # UI (ResultScreen.tsx) reads only the two `combined` grading entries
            # (before/after); the other 12 non-`combined` method entries are
            # computed (grading supports a per-method breakdown) but never
            # rendered anywhere in the frontend. Dropping them here, storage-side
            # only, cuts ~38% off output_data (Finding 1).
            grading_dict = output_data.get("grading")
            if isinstance(grading_dict, dict):
                entries = grading_dict.get("entries")
                if isinstance(entries, list):
                    grading_dict["entries"] = [
                        e for e in entries
                        if isinstance(e, dict) and e.get("name") == "combined"
                    ]

            complete_job(job_id, output_data, name)
            logger.info("worker: job %s completed", job_id, extra={"job_id": job_id, "uid": uid, "stage": 5})
            return "", 200

        except Exception as exc:
            scope.mark_failed()
            logger.exception("worker: unexpected error for job %s", job_id, extra={"job_id": job_id})
            # Best-effort: mark the job as failed so the frontend doesn't show it as stuck.
            try:
                fail_job(job_id, build_error_data_from_exc(exc))
            except Exception:
                pass
            return "", 500
        finally:
            if job is not None and job.input_pdf_gcs_uri:
                delete_gcs_object(job.input_pdf_gcs_uri)

    return Markers.Worker.JobExecute.execute(_run)
