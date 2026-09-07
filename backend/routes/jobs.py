"""backend/routes/jobs.py — POST /jobs, DELETE /jobs/<job_id>.

The only job-submission surface in this app: resolves the request's text or
uploaded files, creates a Firestore job doc, and enqueues a Cloud Task for the
worker — forks nothing from the pipeline itself. Rate-limited and
retention-scoped; auth uses the verify_firebase_token decorator with
allow_anonymous=True opted in explicitly — every caller of this app is
anonymous by design (see utils/firebase.py).
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import HTTPException

from models.job import JobDoc
from utils.firebase import create_job_doc, verify_firebase_token, firestore_client
from utils.cloud_tasks import enqueue_job_safe, require_env, MissingJobConfigError
from utils.rate_limit import rate_limit
from utils.gcs import delete_gcs_object
from utils.constants import Constants
from services.care_plan_input import (
    resolve_uploaded_files,
    upload_combined_pdf,
    validate_extracted_text_length,
)
from utils.markers.markers import Markers
from utils.markers.marker import Scope
from errors import make_error_response, ErrorCode, SimplifyError

logger = logging.getLogger(__name__)
jobs_bp = Blueprint("jobs", __name__)


def _resolve_job_input(user_id: str) -> dict:
    """Resolve the request body into job input fields: pasted text, or <=5
    uploaded files. grading_enabled/version are pinned, never client-settable."""
    json_data = request.get_json(silent=True) or {}
    text_input = (request.form.get("text") or json_data.get("text") or "").strip()
    if text_input:
        # Enforces the char cap, the UTF-8 byte cap (Finding 1), and rejects
        # unstorable text such as a lone UTF-16 surrogate (Finding 5).
        validate_extracted_text_length(text_input)
        return {
            "input_source_kind": "text",
            "input_text": text_input,
            "input_source_filename": "text_input",
            "input_pdf_gcs_uri": None,
            "input_version": Constants.Pipeline.PIPELINE_VERSION,
            "grading_enabled": True,
        }

    uploads = request.files.getlist("files")
    if not uploads:
        raise ValueError("Request must include 'files' or 'text'")

    # Upload limits (explicit product decision): max 5 files, max 10 MB
    # TOTAL across all files, and NO per-file size limit -- deliberately more
    # permissive per file, tighter in aggregate.
    # tolerate_unusable_files=True: a single unusable file (blank scan,
    # corrupt/encrypted PDF, unsupported type, etc.) is skipped rather than
    # aborting the whole multi-file submission (Finding 8); the request only
    # fails if none of the files yield usable content (then EMPTY_DOCUMENT).
    resolved, raw_pdf_bytes = resolve_uploaded_files(
        uploads,
        max_file_count=Constants.Limits.MAX_FILE_COUNT,
        max_aggregate_bytes=Constants.Limits.MAX_AGGREGATE_FILE_BYTES,
        tolerate_unusable_files=True,
    )
    pdf_gcs_uri = upload_combined_pdf(raw_pdf_bytes, user_id) if raw_pdf_bytes else None
    return {
        "input_source_kind": "upload",
        "input_text": resolved.text,
        "input_source_filename": resolved.source_filename,
        "input_pdf_gcs_uri": pdf_gcs_uri,
        "input_version": Constants.Pipeline.PIPELINE_VERSION,
        "grading_enabled": True,
        # Surface which files (if any) were tolerated-skipped as unusable
        # (Finding 8) -- computed by resolve_uploaded_files but previously
        # discarded here, never reaching the job doc or the client at all.
        "skipped_files": resolved.skipped_files,
    }


@jobs_bp.route("/jobs", methods=["POST"])
@rate_limit          # outermost: runs before auth, keyed on IP only
@verify_firebase_token(allow_anonymous=True)   # every caller of this app is anonymous by design
def create_job(user_id: str):
    def _handler(scope: Scope):
        try:
            try:
                input_fields = _resolve_job_input(user_id)
            except (ValueError, FileNotFoundError) as exc:
                return make_error_response(
                    ErrorCode.INPUT_VALIDATION_ERROR, request.path,
                    {"field": "input", "reason": str(exc)},
                ).to_dict(), 400
            except SimplifyError as exc:
                # e.g. EMPTY_DOCUMENT from image OCR finding no text — a known,
                # already-classified failure. Use its own error_code/http_status
                # rather than letting it fall through to the generic 500 below.
                return make_error_response(exc.error_code, request.path).to_dict(), exc.info.http_status

            # Validate Cloud Tasks config BEFORE writing anything to Firestore —
            # this route never orphans a doc.
            try:
                queue_name = require_env("CLOUD_TASKS_QUEUE")
                worker_url = require_env("WORKER_URL")
                service_account = require_env("WORKER_SERVICE_ACCOUNT")
            except MissingJobConfigError:
                logger.exception("jobs: missing Cloud Tasks config; refusing job")
                return make_error_response(ErrorCode.INTERNAL_ERROR, request.path).to_dict(), 500

            job_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            job_doc = JobDoc.for_single(
                user_id=user_id, now=now, trace_id=None, input_fields=input_fields,
                expires_at=now + timedelta(hours=Constants.Limits.JOB_TTL_HOURS),
            )
            create_job_doc(user_id=user_id, job_id=job_id, payload=job_doc.to_firestore())

            if err := enqueue_job_safe(
                job_id, queue_name=queue_name, worker_url=worker_url,
                service_account=service_account,
                deadline_seconds=Constants.Deadlines.JOB_TIMEOUT_SECONDS_SINGLE,
                path=request.path,
            ):
                return err

            return jsonify({"job_id": job_id}), 202
        except HTTPException:
            # e.g. werkzeug.exceptions.RequestEntityTooLarge raised lazily by
            # request.form/request.get_json() the first time the body is read,
            # once it exceeds app.config["MAX_CONTENT_LENGTH"] -- a bare
            # `except Exception` below would swallow this and misreport it as
            # a generic 500 instead of letting Flask's own @app.errorhandler
            # (413, 404, etc.) produce the correct, standard JSON envelope.
            raise
        except Exception:
            logger.exception("create_job: unexpected error")
            return make_error_response(ErrorCode.INTERNAL_ERROR, request.path).to_dict(), 500

    return Markers.Jobs.CreateJob.execute(_handler)


@jobs_bp.route("/jobs/<job_id>", methods=["DELETE"])
@verify_firebase_token(allow_anonymous=True)      # NOT rate-limited (deliberate); every caller of this app is anonymous by design
def delete_job(job_id: str, user_id: str):
    def _handler(scope: Scope):
        try:
            db = firestore_client()
            ref = db.collection("care_plan_outputs").document(job_id)
            doc = ref.get()
            if not doc.exists:
                return make_error_response(
                    ErrorCode.RESOURCE_NOT_FOUND, request.path,
                    {"collection": "care_plan_outputs", "doc_id": job_id},
                ).to_dict(), 404

            data = doc.to_dict()
            # Ownership check: only the job's own creator may delete it.
            if data.get("uid") != user_id:
                return make_error_response(
                    ErrorCode.RESOURCE_FORBIDDEN, request.path,
                    {"collection": "care_plan_outputs", "doc_id": job_id},
                ).to_dict(), 403

            gcs_uri = data.get("input_pdf_gcs_uri")
            if gcs_uri:
                delete_gcs_object(gcs_uri)  # best-effort; logs+swallows, never raises

            ref.delete()
            return "", 204
        except Exception:
            logger.exception("delete_job: unexpected error for job_id=%s", job_id)
            return make_error_response(ErrorCode.INTERNAL_ERROR, request.path).to_dict(), 500

    return Markers.Jobs.DeleteJob.execute(_handler)
