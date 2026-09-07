"""Cloud Tasks enqueue helper for simplify-worker dispatch."""
import json
import logging
import os

from google.cloud import tasks_v2
from google.protobuf import duration_pb2

from errors import SimplifyError, ErrorCode, make_error_response

logger = logging.getLogger(__name__)


class MissingJobConfigError(SimplifyError):
    """Raised when a required Cloud Tasks env var is unset/empty."""

    def __init__(self, var_name: str) -> None:
        super().__init__(
            ErrorCode.INTERNAL_ERROR,
            detail=f"Required environment variable '{var_name}' is not set.",
        )


def require_env(name: str) -> str:
    """Return the value of a required env var, or raise a clear error.

    Unlike ``os.environ[name]`` (which raises a bare ``KeyError`` that gives no
    indication of which variable is missing), this names the offending variable
    and treats empty strings as missing too.
    """
    value = os.environ.get(name)
    if not value:
        raise MissingJobConfigError(name)
    return value


def enqueue_job(
    job_id: str,
    *,
    queue_name: str,
    worker_url: str,
    service_account: str,
    deadline_seconds: int,
) -> None:
    client = tasks_v2.CloudTasksClient()
    url = f"{worker_url.rstrip('/')}/internal/jobs/execute/{job_id}"
    payload = json.dumps({"job_id": job_id}).encode()

    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": url,
            "headers": {"Content-Type": "application/json"},
            "body": payload,
            "oidc_token": {
                "service_account_email": service_account,
                "audience": url,
            },
        },
        "dispatch_deadline": duration_pb2.Duration(seconds=deadline_seconds),
    }
    client.create_task(request={"parent": queue_name, "task": task})


def enqueue_job_safe(
    job_id: str,
    *,
    queue_name: str,
    worker_url: str,
    service_account: str,
    deadline_seconds: int,
    path: str | None = None,
) -> tuple[dict, int] | None:
    """Enqueue a job; return (error_response_dict, status) on failure, None on success."""
    try:
        enqueue_job(
            job_id,
            queue_name=queue_name,
            worker_url=worker_url,
            service_account=service_account,
            deadline_seconds=deadline_seconds,
        )
        return None
    except MissingJobConfigError:
        logger.exception("enqueue_job_safe: missing Cloud Tasks config for job_id=%s", job_id)
        return make_error_response(ErrorCode.INTERNAL_ERROR, path).to_dict(), 500
    except Exception:
        logger.exception("enqueue_job_safe: failed to enqueue Cloud Task for job_id=%s", job_id)
        return make_error_response(ErrorCode.INTERNAL_ERROR, path).to_dict(), 500
