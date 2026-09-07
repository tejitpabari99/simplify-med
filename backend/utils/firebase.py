"""Firebase utilities: initialization, Firestore client, auth, and persistence."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from functools import wraps

import firebase_admin
from firebase_admin import auth, credentials, firestore
from flask import g, request
from errors import make_error_response, ErrorCode

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class FirestoreError(RuntimeError):
    """Raised when a Firestore operation fails in a firebase wrapper function."""


# ---------------------------------------------------------------------------
# Firebase / Firestore initialization
# ---------------------------------------------------------------------------

def initialize_firebase():
    """Initialize Firebase Admin SDK"""
    if not firebase_admin._apps:
        # Prefer JSON string from env (Cloud Run / CI via Secret Manager)
        sa_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
        if sa_json:
            cred = credentials.Certificate(json.loads(sa_json))
            firebase_admin.initialize_app(cred)
        else:
            service_account_path = os.getenv('FIREBASE_SERVICE_ACCOUNT_PATH')
            if service_account_path and os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
                firebase_admin.initialize_app(cred)
            else:
                # For production, use default credentials
                firebase_admin.initialize_app()

    # Get the Firestore database ID from environment variable
    database_id = os.getenv('FIRESTORE_DATABASE_ID', '(default)')

    # Return Firestore client with specific database
    return firestore.client(database_id=database_id)


def firestore_client():
    """Return a Firestore client using FIRESTORE_DATABASE_ID env (default: '(default)')."""
    db_id = os.environ.get("FIRESTORE_DATABASE_ID", "(default)")
    return firestore.client(database_id=db_id)


# ---------------------------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------------------------

def _extract_bearer_token(auth_header: str | None) -> tuple[str | None, tuple | None]:
    """Parse 'Bearer <token>'. Returns (token, None) or (None, (error_dict, status))."""
    if not auth_header:
        return None, (make_error_response(ErrorCode.MISSING_AUTH_HEADER, None).to_dict(), 401)
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        return None, (make_error_response(ErrorCode.MALFORMED_AUTH_HEADER, None).to_dict(), 401)
    token = parts[1].strip()
    if not token:
        return None, (make_error_response(ErrorCode.MALFORMED_AUTH_HEADER, None).to_dict(), 401)
    return token, None


def _is_anonymous_token(decoded_token: dict) -> bool:
    """True iff a decoded Firebase ID token belongs to an anonymous sign-in.

    Uses the token's own ``firebase.sign_in_provider`` claim rather than an
    Admin SDK lookup (e.g. ``auth.get_user(uid).provider_data``) — that claim
    is exactly what Firebase stamps onto every anonymous ID token, and reading
    it costs nothing extra per request. A token with no ``firebase`` claim at
    all (e.g. a minimal test double) is treated as non-anonymous.
    """
    return decoded_token.get('firebase', {}).get('sign_in_provider') == 'anonymous'


def verify_firebase_token(f=None, *, allow_anonymous: bool = False):
    """Decorator to verify Firebase ID token from Authorization header.

    Deny-by-default for anonymous callers: a Firebase ID token minted by
    ``signInAnonymously()`` on this public site is a valid credential
    against this same backend/Firebase project, so any route that requires a
    non-anonymous account must reject it (403) or it becomes an unthrottled,
    unbounded-cost backdoor around the per-IP rate limit. Only the
    /jobs routes are meant to accept anonymous callers, and must opt in
    explicitly via ``@verify_firebase_token(allow_anonymous=True)``.

    Usable either bare (``@verify_firebase_token``) or as a factory
    (``@verify_firebase_token(allow_anonymous=True)``).
    """
    def decorator(func):
        @wraps(func)
        def decorated_function(*args, **kwargs):
            # OPTIONS preflight must pass through so flask-cors can attach CORS headers
            if request.method == 'OPTIONS':
                return '', 204

            token, err = _extract_bearer_token(request.headers.get("Authorization"))
            if err:
                return err

            try:
                # Verify the token
                decoded_token = auth.verify_id_token(token)
                user_id = decoded_token['uid']
                is_anonymous = _is_anonymous_token(decoded_token)

                # Store on flask.g so structured logging / SessionIdFilter pick it up
                # automatically on every structured log call in this request.
                g.user_id = user_id
                g.is_anonymous = is_anonymous

                # Also pass as a kwarg for route handlers that need it explicitly
                kwargs['user_id'] = user_id

            except Exception as e:
                return make_error_response(ErrorCode.UNAUTHORIZED, request.path, {"detail": str(e)}).to_dict(), 401

            if is_anonymous and not allow_anonymous:
                return make_error_response(ErrorCode.ANONYMOUS_ACCESS_FORBIDDEN, request.path).to_dict(), 403

            return func(*args, **kwargs)

        return decorated_function

    # Support both @verify_firebase_token and @verify_firebase_token(allow_anonymous=True)
    if f is not None:
        return decorator(f)
    return decorator


def verify_oidc_token() -> bool:
    """Verify the Google-signed OIDC token Cloud Tasks attaches to worker requests.

    Cloud Tasks signs each dispatch with an OIDC JWT issued for the worker service
    account, using the full execute URL as the token audience (see
    ``utils/cloud_tasks.enqueue_job``). This validates that signed token so the
    publicly-reachable worker route cannot be invoked by arbitrary callers.

    Returns True if the request is authorized, False otherwise. Callers should
    translate a False result into an HTTP 403. Never logs token contents.

    Behavior:
      - Kill-switch: if ``WORKER_VERIFY_OIDC`` is false/0/no, verification is
        skipped (for local/dev/tests). Verification is ENABLED by default.
      - Requires an ``Authorization: Bearer <token>`` header.
      - Verifies the JWT signature/issuer/expiry via google-auth.
      - Requires ``email_verified`` to be truthy.
      - If ``WORKER_SERVICE_ACCOUNT`` is set, requires the token ``email`` to match.
      - Requires the token ``aud`` to equal the (proxy-aware) request URL.
    """
    if os.environ.get("WORKER_VERIFY_OIDC", "true").lower() in ("false", "0", "no"):
        return True

    token, err = _extract_bearer_token(request.headers.get("Authorization"))
    if err:
        logger.warning("worker: rejected request without a valid Bearer Authorization header")
        return False

    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_requests

    try:
        claims = google_id_token.verify_oauth2_token(token, google_requests.Request())
    except Exception as exc:
        logger.warning("worker: OIDC token verification failed: %s", type(exc).__name__)
        return False

    if not claims.get("email_verified"):
        logger.warning("worker: rejected OIDC token with unverified email")
        return False

    expected_email = os.environ.get("WORKER_SERVICE_ACCOUNT")
    if expected_email and claims.get("email") != expected_email:
        logger.warning(
            "worker: rejected OIDC token with service-account email mismatch "
            "(got=%s expected=%s)", claims.get("email"), expected_email
        )
        return False

    proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    expected_aud = f"{proto}://{request.host}{request.path}"
    if claims.get("aud") != expected_aud:
        logger.warning(
            "worker: rejected OIDC token with audience mismatch (got=%s expected=%s)",
            claims.get("aud"), expected_aud
        )
        return False

    return True


# ---------------------------------------------------------------------------
# Persistence: job lifecycle wrappers
# ---------------------------------------------------------------------------

def create_job_doc(*, user_id: str, job_id: str, payload: dict) -> None:
    try:
        db = firestore_client()
        db.collection("care_plan_outputs").document(job_id).set(payload)
    except Exception as exc:
        logger.exception("firebase: create_job_doc failed for job_id=%s", job_id)
        raise FirestoreError(f"create_job_doc failed: {exc}") from exc


def update_job_stage(job_id: str, stage: int) -> None:
    try:
        db = firestore_client()
        db.collection("care_plan_outputs").document(job_id).update({
            "stage": stage,
            "updated_at": datetime.now(timezone.utc),
        })
    except Exception as exc:
        logger.exception("firebase: update_job_stage failed for job_id=%s stage=%d", job_id, stage)
        raise FirestoreError(f"update_job_stage failed: {exc}") from exc


def complete_job(job_id: str, output_data: dict, name: str) -> None:
    """Mark a job completed. Always deletes the top-level input_text field in
    the SAME update -- the raw pasted/extracted document text is write-once
    (by create_job_doc) and read-once (by resolve_input_from_job_doc at
    worker start), never needed again after this point. This is a *separate*
    field from output_data["input"]["text"] (already popped by the caller,
    see routes/worker.py) -- without also clearing this one, the full-length
    top-level copy survives untouched for the entire job TTL, undermining
    the "stay under 1 MiB" intent and compounding the byte-vs-char cap bug
    (edge-case review Finding 4)."""
    try:
        now = datetime.now(timezone.utc)
        db = firestore_client()
        update_fields: dict = {
            "status": "completed",
            "stage": 5,
            "output_data": output_data,
            "name": name,
            "completed_at": now,
            "updated_at": now,
            "input_text": firestore.DELETE_FIELD,
        }
        db.collection("care_plan_outputs").document(job_id).update(update_fields)
    except Exception as exc:
        logger.exception("firebase: complete_job failed for job_id=%s", job_id)
        raise FirestoreError(f"complete_job failed: {exc}") from exc


def fail_job(job_id: str, error_data: dict) -> None:
    """Mark a job failed. Always clears input_text -- see complete_job's
    docstring; applies equally on the failure path since the raw text is no
    longer needed once the job has reached ANY terminal state."""
    try:
        now = datetime.now(timezone.utc)
        db = firestore_client()
        update_fields: dict = {
            "status": "error",
            "error_data": error_data,
            "completed_at": now,
            "updated_at": now,
            "input_text": firestore.DELETE_FIELD,
        }
        db.collection("care_plan_outputs").document(job_id).update(update_fields)
    except Exception as exc:
        logger.exception("firebase: fail_job failed for job_id=%s", job_id)
        raise FirestoreError(f"fail_job failed: {exc}") from exc


def get_job_doc(job_id: str) -> dict | None:
    try:
        db = firestore_client()
        doc = db.collection("care_plan_outputs").document(job_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as exc:
        logger.exception("firebase: get_job_doc failed for job_id=%s", job_id)
        raise FirestoreError(f"get_job_doc failed: {exc}") from exc
