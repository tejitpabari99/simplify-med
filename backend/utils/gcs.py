"""utils/gcs.py — GCS client construction and generic bucket access."""

import logging
import os

from google.cloud import storage as gcs

logger = logging.getLogger(__name__)

_DEFAULT_BUCKET = os.environ.get("GCP_BUCKET_NAME", "")

# Lazily-constructed, process-wide GCS client. Populated on first use by
# _gcs_client(); see that function for details. Tests reset this to None
# (via monkeypatch) so each test gets a fresh mocked client.
_client: gcs.Client | None = None


def _gcs_client() -> gcs.Client:
    """Single construction point for the GCS client (project from GCP_PROJECT_ID env).

    Lazily constructs the client on first call and caches it at module level,
    so subsequent calls reuse the same instance instead of re-paying ADC
    credential-resolution cost on every call.
    """
    global _client
    if _client is None:
        _client = gcs.Client(project=os.environ.get("GCP_PROJECT_ID") or None)
    return _client


# ---------------------------------------------------------------------------
# Generic bucket access
# ---------------------------------------------------------------------------

def get_gcs_bucket(bucket_name: str | None = None):
    """Return a GCS Bucket for the given name (default: GCP_BUCKET_NAME env)."""
    name = bucket_name or _DEFAULT_BUCKET
    return _gcs_client().bucket(name)


def delete_gcs_object(gcs_uri: str) -> None:
    """Best-effort delete of a gs:// object. Swallows NotFound and logs any
    other failure — GCS cleanup failing must never fail the caller (job
    completion or the DELETE route); the expires_at TTL is the safety net."""
    if not gcs_uri.startswith("gs://"):
        logger.warning("gcs: delete_gcs_object called with non-gs:// uri=%s", gcs_uri)
        return
    _, _, rest = gcs_uri.partition("gs://")
    bucket_name, _, blob_name = rest.partition("/")
    try:
        _gcs_client().bucket(bucket_name).blob(blob_name).delete()
    except Exception as exc:
        from google.api_core.exceptions import NotFound
        if isinstance(exc, NotFound):
            return
        logger.exception("gcs: delete_gcs_object failed for uri=%s", gcs_uri)
