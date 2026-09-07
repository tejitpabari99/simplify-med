"""TDD tests for POST /jobs and DELETE /jobs/<job_id>."""
import pytest
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import patch, MagicMock
from flask import Flask

from errors import ErrorCode, SimplifyError


JOBS_ENV = {
    "CLOUD_TASKS_QUEUE": "test-queue",
    "WORKER_URL": "https://worker.run.app",
    "WORKER_SERVICE_ACCOUNT": "sa@proj.iam",
}


@pytest.fixture
def app_jobs():
    from routes.jobs import jobs_bp
    app = Flask(__name__)
    app.register_blueprint(jobs_bp)
    return app


@pytest.fixture
def client_jobs(app_jobs):
    return app_jobs.test_client()


@pytest.fixture
def auth_ok(monkeypatch):
    monkeypatch.setattr("utils.firebase.auth.verify_id_token", lambda *a, **k: {"uid": "user-1"})
    return {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def _allow_rate_limit(monkeypatch):
    """Most tests aren't testing the rate limiter itself — always allow."""
    monkeypatch.setattr("routes.jobs.rate_limit", lambda f: f)


# ---------------------------------------------------------------------------
# POST /jobs
# ---------------------------------------------------------------------------

@patch.dict("os.environ", JOBS_ENV)
@patch("routes.jobs.enqueue_job_safe", return_value=None)
@patch("routes.jobs.create_job_doc")
def test_post_text_returns_202_with_job_fields(mock_create_doc, mock_enqueue, client_jobs, auth_ok):
    resp = client_jobs.post("/jobs", json={"text": "Patient has hypertension."}, headers=auth_ok)
    assert resp.status_code == 202
    assert "job_id" in resp.get_json()

    payload = mock_create_doc.call_args.kwargs["payload"]
    assert payload["expires_at"] > datetime.now(timezone.utc)
    assert payload["grading_enabled"] is True
    assert payload["input_version"] == "v1-2"

    enqueue_kwargs = mock_enqueue.call_args.kwargs
    assert enqueue_kwargs["queue_name"] == "test-queue"


@patch.dict("os.environ", {**JOBS_ENV, "GCP_BUCKET_NAME": "test-bucket"})
@patch("services.care_plan_input.get_gcs_bucket")
@patch("routes.jobs.enqueue_job_safe", return_value=None)
@patch("routes.jobs.create_job_doc")
def test_post_multipart_upload_within_limit_returns_202(
    mock_create_doc, mock_enqueue, mock_get_gcs_bucket, client_jobs, auth_ok
):
    # "note.txt" is mergeable into a combined PDF by resolve_uploaded_files
    # (real, unmocked pdf-merge logic), so the route's upload_combined_pdf
    # call reaches real GCS bucket access; mock only that boundary, not the
    # merge/text-extraction logic.
    bucket = mock_get_gcs_bucket.return_value
    bucket.blob.return_value = MagicMock()

    # Content must clear MIN_MEANINGFUL_CONTENT_CHARS (20) -- "hello world"
    # alone (11 chars) would now be treated as not-really-a-document (Finding 2).
    data = {"files": (BytesIO(b"hello world, this is a real clinical note"), "note.txt")}
    resp = client_jobs.post(
        "/jobs", data=data, content_type="multipart/form-data", headers=auth_ok,
    )
    assert resp.status_code == 202
    mock_create_doc.assert_called_once()
    payload = mock_create_doc.call_args.kwargs["payload"]
    assert payload["input_pdf_gcs_uri"].startswith("gs://test-bucket/care_plan_inputs/")


@patch.dict("os.environ", {**JOBS_ENV, "GCP_BUCKET_NAME": "test-bucket"})
@patch("services.care_plan_input.get_gcs_bucket")
@patch("routes.jobs.enqueue_job_safe", return_value=None)
@patch("routes.jobs.create_job_doc")
def test_post_multipart_one_blank_file_among_several_still_succeeds(
    mock_create_doc, mock_enqueue, mock_get_gcs_bucket, client_jobs, auth_ok
):
    """Regression for Finding 8: one unusable file (here, a blank txt) among
    several must NOT abort the whole submission -- the good file's
    text is used and the request still succeeds."""
    bucket = mock_get_gcs_bucket.return_value
    bucket.blob.return_value = MagicMock()

    data = {
        "files": [
            (BytesIO(b"This is a perfectly good clinical note about hypertension."), "good.txt"),
            (BytesIO(b"   "), "blank.txt"),
        ]
    }
    resp = client_jobs.post(
        "/jobs", data=data, content_type="multipart/form-data", headers=auth_ok,
    )
    assert resp.status_code == 202
    mock_create_doc.assert_called_once()
    payload = mock_create_doc.call_args.kwargs["payload"]
    assert "perfectly good clinical note" in payload["input_text"]


@patch.dict("os.environ", {**JOBS_ENV, "GCP_BUCKET_NAME": "test-bucket"})
@patch("services.care_plan_input.get_gcs_bucket")
@patch("routes.jobs.enqueue_job_safe", return_value=None)
@patch("routes.jobs.create_job_doc")
def test_post_multipart_all_files_blank_returns_422_empty_document(
    mock_create_doc, mock_enqueue, mock_get_gcs_bucket, client_jobs, auth_ok
):
    """Only when NO file yields usable content does the request fail
    (Finding 8's flip side -- tolerance must not silently accept an
    all-unusable batch)."""
    data = {
        "files": [
            (BytesIO(b"   "), "blank1.txt"),
            (BytesIO(b""), "blank2.txt"),
        ]
    }
    resp = client_jobs.post(
        "/jobs", data=data, content_type="multipart/form-data", headers=auth_ok,
    )
    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "EMPTY_DOCUMENT"
    mock_create_doc.assert_not_called()


@patch.dict("os.environ", {**JOBS_ENV, "GCP_BUCKET_NAME": "test-bucket"})
@patch("services.care_plan_input.get_gcs_bucket")
@patch("routes.jobs.enqueue_job_safe", return_value=None)
@patch("routes.jobs.create_job_doc")
@patch(
    "services.care_plan_input.extract_text_from_image",
    side_effect=SimplifyError(
        ErrorCode.EMPTY_DOCUMENT,
        detail="Image contained no readable text (model returned NO_TEXT_FOUND).",
    ),
)
def test_post_blurry_image_returns_422_empty_document(
    mock_extract_image, mock_create_doc, mock_enqueue, mock_get_gcs_bucket, client_jobs, auth_ok
):
    """Regression test: extract_text_from_image raising SimplifyError(EMPTY_DOCUMENT)
    for an unreadable/blurry image must surface as 422 EMPTY_DOCUMENT, not fall
    through the generic `except Exception` to a 500 INTERNAL_ERROR."""
    data = {"files": (BytesIO(b"fake-jpeg-bytes"), "photo.jpg")}
    resp = client_jobs.post(
        "/jobs", data=data, content_type="multipart/form-data", headers=auth_ok,
    )
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"]["code"] == "EMPTY_DOCUMENT"
    mock_create_doc.assert_not_called()
    mock_enqueue.assert_not_called()


@patch.dict("os.environ", JOBS_ENV)
@patch("routes.jobs.enqueue_job_safe", return_value=None)
@patch("routes.jobs.create_job_doc")
def test_post_more_than_5_files_returns_400(mock_create_doc, mock_enqueue, client_jobs, auth_ok):
    data = {"files": [(BytesIO(b"x"), f"f{i}.txt") for i in range(6)]}
    resp = client_jobs.post(
        "/jobs", data=data, content_type="multipart/form-data", headers=auth_ok,
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "INPUT_VALIDATION_ERROR"
    mock_create_doc.assert_not_called()


@patch.dict("os.environ", JOBS_ENV)
@patch("routes.jobs.create_job_doc")
def test_post_no_input_returns_400(mock_create_doc, client_jobs, auth_ok):
    resp = client_jobs.post("/jobs", json={}, headers=auth_ok)
    assert resp.status_code == 400
    mock_create_doc.assert_not_called()


def test_post_unauthenticated_returns_401(client_jobs):
    resp = client_jobs.post("/jobs", json={"text": "hi"})
    assert resp.status_code == 401


@patch.dict("os.environ", {}, clear=True)
@patch("routes.jobs.create_job_doc")
def test_post_missing_cloud_tasks_config_returns_500_and_no_doc_created(mock_create_doc, client_jobs, auth_ok):
    resp = client_jobs.post("/jobs", json={"text": "hi"}, headers=auth_ok)
    assert resp.status_code == 500
    # Regression guard: this route validates Cloud Tasks config BEFORE
    # writing to Firestore, so a missing config never orphans a doc.
    mock_create_doc.assert_not_called()


@patch.dict("os.environ", JOBS_ENV)
@patch("routes.jobs.create_job_doc")
def test_post_ignores_client_supplied_grading_and_version_and_doc_id(mock_create_doc, client_jobs, auth_ok):
    with patch("routes.jobs.enqueue_job_safe", return_value=None):
        resp = client_jobs.post(
            "/jobs",
            json={"text": "hi", "grading_enabled": False, "version": "v9-9", "doc_id": "some-doc"},
            headers=auth_ok,
        )
    assert resp.status_code == 202
    payload = mock_create_doc.call_args.kwargs["payload"]
    assert payload["grading_enabled"] is True
    assert payload["input_version"] == "v1-2"


def test_rate_limit_429_blocks_before_auth(client_jobs, monkeypatch):
    """With the real (non-bypassed) rate_limit decorator, a blocked IP
    gets 429 even with no Authorization header at all.

    Deviation from TASKS.md's verbatim test: the autouse `_allow_rate_limit`
    fixture monkeypatches the module-level name `routes.jobs.rate_limit`,
    but `create_job` was already wrapped by the *real* `rate_limit`
    at import/decoration time (decorators bind once, at module load) — so that
    monkeypatch never actually reaches the already-decorated route. What makes
    every other POST test in this file pass regardless is that the real
    `rate_limit` fails OPEN whenever `check_rate_limit()` raises (no
    Firebase app initialized in this unit-test process), not the autouse
    fixture. This test exercises that same real, still-attached decorator
    directly: patch `check_rate_limit` at its home module
    (`utils.rate_limit`, where `rate_limit`'s wrapper looks it up at
    call time) rather than a `routes.jobs.check_rate_limit` name that was
    never imported there in the first place.
    """
    monkeypatch.setattr("utils.rate_limit.check_rate_limit", lambda: False)
    resp = client_jobs.post("/jobs", json={"text": "hi"})
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# DELETE /jobs/<job_id>
# ---------------------------------------------------------------------------

def _mock_doc(exists, data=None):
    doc = MagicMock()
    doc.exists = exists
    doc.to_dict.return_value = data or {}
    return doc


@patch("routes.jobs.delete_gcs_object")
@patch("routes.jobs.firestore_client")
def test_delete_owned_job_returns_204_and_deletes_gcs(mock_fs, mock_delete_gcs, client_jobs, auth_ok):
    doc = _mock_doc(True, {"uid": "user-1", "input_pdf_gcs_uri": "gs://b/p.pdf"})
    ref = MagicMock()
    ref.get.return_value = doc
    mock_fs.return_value.collection.return_value.document.return_value = ref

    resp = client_jobs.delete("/jobs/job-1", headers=auth_ok)
    assert resp.status_code == 204
    mock_delete_gcs.assert_called_once_with("gs://b/p.pdf")
    ref.delete.assert_called_once()


@patch("routes.jobs.firestore_client")
def test_delete_nonexistent_job_returns_404(mock_fs, client_jobs, auth_ok):
    ref = MagicMock()
    ref.get.return_value = _mock_doc(False)
    mock_fs.return_value.collection.return_value.document.return_value = ref

    resp = client_jobs.delete("/jobs/nope", headers=auth_ok)
    assert resp.status_code == 404


@patch("routes.jobs.firestore_client")
def test_delete_wrong_uid_returns_403(mock_fs, client_jobs, auth_ok):
    """Ownership/trust-boundary check: a caller may only delete their own
    job, regardless of who else's uid happens to be on the doc."""
    doc = _mock_doc(True, {"uid": "someone-else"})
    ref = MagicMock()
    ref.get.return_value = doc
    mock_fs.return_value.collection.return_value.document.return_value = ref

    resp = client_jobs.delete("/jobs/job-1", headers=auth_ok)
    assert resp.status_code == 403
    ref.delete.assert_not_called()


def test_delete_unauthenticated_returns_401(client_jobs):
    resp = client_jobs.delete("/jobs/job-1")
    assert resp.status_code == 401


@patch("routes.jobs.firestore_client")
def test_delete_is_not_rate_limited(mock_fs, client_jobs, auth_ok):
    """DELETE has no rate_limit decorator at all — calling it many times in
    a row never returns 429."""
    doc = _mock_doc(True, {"uid": "user-1", "input_pdf_gcs_uri": None})
    ref = MagicMock()
    ref.get.return_value = doc
    mock_fs.return_value.collection.return_value.document.return_value = ref

    for _ in range(10):
        resp = client_jobs.delete("/jobs/job-1", headers=auth_ok)
        assert resp.status_code in (204, 404)  # never 429


# ---------------------------------------------------------------------------
# Anonymous callers (Finding 1) — /jobs routes must keep working for them
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_anonymous(monkeypatch):
    monkeypatch.setattr(
        "utils.firebase.auth.verify_id_token",
        lambda *a, **k: {"uid": "anon-1", "firebase": {"sign_in_provider": "anonymous", "identities": {}}},
    )
    return {"Authorization": "Bearer anon-token"}


@patch.dict("os.environ", JOBS_ENV)
@patch("routes.jobs.enqueue_job_safe", return_value=None)
@patch("routes.jobs.create_job_doc")
def test_post_anonymous_token_accepted_on_jobs(mock_create_doc, mock_enqueue, client_jobs, auth_anonymous):
    resp = client_jobs.post("/jobs", json={"text": "Patient has hypertension."}, headers=auth_anonymous)
    assert resp.status_code == 202
    assert "job_id" in resp.get_json()
    mock_create_doc.assert_called_once()
    assert mock_create_doc.call_args.kwargs["user_id"] == "anon-1"


# ---------------------------------------------------------------------------
# Server-side max text length (Finding 2)
# ---------------------------------------------------------------------------

@patch.dict("os.environ", JOBS_ENV)
@patch("routes.jobs.enqueue_job_safe", return_value=None)
@patch("routes.jobs.create_job_doc")
def test_post_text_at_max_length_is_accepted(mock_create_doc, mock_enqueue, client_jobs, auth_ok):
    from utils.constants import Constants
    # MAX_TEXT_BYTES (not MAX_TEXT_LENGTH) is the binding cap for ASCII text
    # (1 byte/char) -- see Finding 1.
    text = "a" * Constants.Uploads.MAX_TEXT_BYTES
    resp = client_jobs.post("/jobs", json={"text": text}, headers=auth_ok)
    assert resp.status_code == 202
    mock_create_doc.assert_called_once()


@patch.dict("os.environ", JOBS_ENV)
@patch("routes.jobs.enqueue_job_safe", return_value=None)
@patch("routes.jobs.create_job_doc")
def test_post_text_over_max_length_returns_400(mock_create_doc, mock_enqueue, client_jobs, auth_ok):
    from utils.constants import Constants
    text = "a" * (Constants.Uploads.MAX_TEXT_BYTES + 1)
    resp = client_jobs.post("/jobs", json={"text": text}, headers=auth_ok)
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "INPUT_VALIDATION_ERROR"
    mock_create_doc.assert_not_called()
    mock_enqueue.assert_not_called()


@patch.dict("os.environ", JOBS_ENV)
@patch("routes.jobs.enqueue_job_safe", return_value=None)
@patch("routes.jobs.create_job_doc")
def test_post_cjk_text_under_char_cap_but_over_byte_cap_returns_400(
    mock_create_doc, mock_enqueue, client_jobs, auth_ok
):
    """Regression for edge-case review Finding 1: CJK text well under the
    500,000-character cap (so the old char-only check would have let it
    through) is 3 bytes/char in UTF-8 and so can exceed MAX_TEXT_BYTES --
    must now be rejected with a clean 400, not an uncaught Firestore write
    failure surfacing as an opaque 500."""
    from utils.constants import Constants
    char_count = (Constants.Uploads.MAX_TEXT_BYTES // 3) + 100
    assert char_count < Constants.Uploads.MAX_TEXT_LENGTH
    text = "中" * char_count
    resp = client_jobs.post("/jobs", json={"text": text}, headers=auth_ok)
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "INPUT_VALIDATION_ERROR"
    mock_create_doc.assert_not_called()
    mock_enqueue.assert_not_called()


@patch.dict("os.environ", JOBS_ENV)
@patch("routes.jobs.enqueue_job_safe", return_value=None)
@patch("routes.jobs.create_job_doc")
def test_post_uploaded_file_extracted_text_over_max_length_returns_400(
    mock_create_doc, mock_enqueue, client_jobs, auth_ok
):
    """Regression: the uploaded-file path never checked extracted text length
    (only the pasted-text path did), so an over-limit uploaded document used
    to sail through every pipeline step before failing late with a
    misleading MAX_TOKENS error. Must now be rejected up front, before any
    job is created or enqueued -- the whole point of the fix."""
    from utils.constants import Constants
    oversized_text = "a" * (Constants.Uploads.MAX_TEXT_BYTES + 1)
    data = {"files": (BytesIO(oversized_text.encode("utf-8")), "note.txt")}
    resp = client_jobs.post(
        "/jobs", data=data, content_type="multipart/form-data", headers=auth_ok,
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "INPUT_VALIDATION_ERROR"
    mock_create_doc.assert_not_called()
    mock_enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# Lone UTF-16 surrogate in pasted text (Finding 5)
# ---------------------------------------------------------------------------

@patch.dict("os.environ", JOBS_ENV)
@patch("routes.jobs.enqueue_job_safe", return_value=None)
@patch("routes.jobs.create_job_doc")
def test_post_text_with_lone_surrogate_returns_400_not_500(mock_create_doc, mock_enqueue, client_jobs, auth_ok):
    """Regression for Finding 5: {"text": "...\\ud800..."} decodes via
    json.loads into a Python str containing an unpaired surrogate, which
    can't be UTF-8 encoded. Must be rejected with a clean 400 before ever
    reaching create_job_doc, not an uncaught UnicodeEncodeError -> 500."""
    resp = client_jobs.post(
        "/jobs",
        data='{"text": "hello \\ud800 world"}',
        headers={**auth_ok, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "INPUT_VALIDATION_ERROR"
    mock_create_doc.assert_not_called()
    mock_enqueue.assert_not_called()
