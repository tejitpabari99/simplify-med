"""TDD tests for POST /internal/jobs/execute/<job_id>."""
import copy
from datetime import datetime, timedelta, timezone
import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from models.pipeline_events import AdapterStepEvent, AdapterResult, AdapterError
from models.grading import build_grading_with_before_after_score
from utils.scoring import score_text_safe


QUEUE_HEADER = {"X-CloudTasks-QueueName": "my-queue"}


@pytest.fixture(autouse=True)
def _disable_oidc_verification(monkeypatch):
    """Disable OIDC verification by default so the existing functional tests
    exercise job execution without a signed Cloud Tasks token. Tests that
    target the auth gate re-enable it explicitly via monkeypatch.
    """
    monkeypatch.setenv("WORKER_VERIFY_OIDC", "false")


@pytest.fixture
def app_worker():
    from routes.worker import worker_bp
    app = Flask(__name__)
    app.register_blueprint(worker_bp)
    return app


@pytest.fixture
def client_worker(app_worker):
    return app_worker.test_client()


def _make_job_doc(status="not_started", stage=None, batch_group_id=None, source_kind="text"):
    return {
        "uid": "user-1",
        "name": "Jan 15, 2026 10:00",
        "source_filename": "text_input",
        "created_at": datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        "status": status,
        "stage": stage,
        "batch_group_id": batch_group_id,
        "input_source_kind": source_kind,
        "input_text": "Patient has hypertension.",
        "input_doc_id": None,
        "input_version": "v1-2",
        "grading_enabled": False,
        "input_source_filename": "text_input",
        "batch_run_id": None,
    }


def test_missing_queue_header_returns_403(client_worker):
    resp = client_worker.post("/internal/jobs/execute/job-1")
    assert resp.status_code == 403


@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_happy_path_completes_job(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    client_worker
):
    mock_get_doc.return_value = _make_job_doc()

    # Mock Firestore client for status update
    mock_db = MagicMock()
    mock_fs_client.return_value = mock_db

    # Mock care_plan result
    care_plan_mock = MagicMock()
    care_plan_mock.to_dict.return_value = {"reason_for_visit": [{"reason": "Hypertension"}]}
    grading_mock = MagicMock()

    def fake_pipeline(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        yield AdapterStepEvent(step=2, status="active", label="Terms")
        yield AdapterStepEvent(step=2, status="done", label="Terms")
        yield AdapterResult(
            care_plan=care_plan_mock,
            grading=grading_mock,
            raw_text=text,
            clarified_text="clarified",
        )

    envelope_mock = MagicMock()
    envelope_mock.to_dict.return_value = {
        "care_plan": {"reason_for_visit": [{"reason": "Hypertension"}]},
        "metrics": {"saved_id": None},
    }

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline(*a, **kw)):
        with patch("routes.worker.CarePlanInternal", return_value=envelope_mock):
            resp = client_worker.post(
                "/internal/jobs/execute/job-1",
                headers=QUEUE_HEADER,
                content_type="application/json",
            )

    assert resp.status_code == 200
    mock_complete.assert_called_once()
    mock_fail.assert_not_called()


@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_pipeline_error_fails_job(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    client_worker
):
    mock_get_doc.return_value = _make_job_doc()
    mock_db = MagicMock()
    mock_fs_client.return_value = mock_db

    def fake_pipeline_error(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        yield AdapterError(error_data={
            "code": "PIPELINE_ERROR",
            "message": "Pipeline error",
            "details": "Pipeline exploded",
            "timestamp": "2026-06-22T00:00:00+00:00",
            "path": "/care_plan",
        })

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline_error(*a, **kw)):
        resp = client_worker.post(
            "/internal/jobs/execute/job-1",
            headers=QUEUE_HEADER,
        )

    assert resp.status_code == 200
    mock_fail.assert_called_once()
    fail_args = mock_fail.call_args
    error_data = fail_args.args[1]
    assert error_data["code"] == "PIPELINE_ERROR"
    assert error_data["details"] == "Pipeline exploded"
    mock_complete.assert_not_called()


@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_timeout_fails_job_with_job_timeout_code(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    client_worker
):
    mock_get_doc.return_value = _make_job_doc()
    mock_db = MagicMock()
    mock_fs_client.return_value = mock_db

    def fake_pipeline_slow(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        # Emit a stage transition so _check_timeout runs.
        yield AdapterStepEvent(step=2, status="active", label="Terms")

    # First monotonic() call records the start; the next (inside _check_timeout)
    # jumps far past the single-job deadline so the timeout triggers.
    from utils.constants import Constants
    deadline = Constants.Deadlines.SINGLE_JOB_INTERNAL_DEADLINE_S
    monotonic_values = iter([0.0, deadline + 100.0])

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline_slow(*a, **kw)):
        with patch("routes.worker.time.monotonic", side_effect=lambda: next(monotonic_values)):
            resp = client_worker.post(
                "/internal/jobs/execute/job-1",
                headers=QUEUE_HEADER,
            )

    assert resp.status_code == 200
    mock_fail.assert_called_once()
    error_data = mock_fail.call_args.args[1]
    assert error_data["code"] == "JOB_TIMEOUT"
    mock_complete.assert_not_called()


@patch("routes.worker.get_job_doc")
def test_idempotent_completed_job_returns_200(mock_get_doc, client_worker):
    mock_get_doc.return_value = _make_job_doc(status="completed")
    resp = client_worker.post(
        "/internal/jobs/execute/job-1",
        headers=QUEUE_HEADER,
    )
    assert resp.status_code == 200


@patch("routes.worker.get_job_doc")
def test_idempotent_error_job_returns_200(mock_get_doc, client_worker):
    mock_get_doc.return_value = _make_job_doc(status="error")
    resp = client_worker.post(
        "/internal/jobs/execute/job-1",
        headers=QUEUE_HEADER,
    )
    assert resp.status_code == 200


@patch("routes.worker.get_job_doc")
def test_missing_job_doc_returns_200(mock_get_doc, client_worker):
    mock_get_doc.return_value = None
    resp = client_worker.post(
        "/internal/jobs/execute/job-1",
        headers=QUEUE_HEADER,
    )
    assert resp.status_code == 200


@patch("routes.worker.get_job_doc", side_effect=Exception("DB error"))
def test_unexpected_exception_returns_500(mock_get_doc, client_worker):
    resp = client_worker.post(
        "/internal/jobs/execute/job-1",
        headers=QUEUE_HEADER,
    )
    assert resp.status_code == 500


# --- OIDC verification gate (verification ENABLED) ---


@patch("routes.worker.get_job_doc")
def test_oidc_enabled_missing_auth_header_returns_403(mock_get_doc, client_worker, monkeypatch):
    """With verification on, a request with no Authorization header is rejected
    at the auth gate (before any job lookup)."""
    monkeypatch.setenv("WORKER_VERIFY_OIDC", "true")
    resp = client_worker.post("/internal/jobs/execute/job-1", headers=QUEUE_HEADER)
    assert resp.status_code == 403
    mock_get_doc.assert_not_called()


@patch("routes.worker.get_job_doc")
def test_oidc_enabled_garbage_token_returns_403(mock_get_doc, client_worker, monkeypatch):
    """A malformed/garbage Bearer token fails google-auth verification → 403."""
    monkeypatch.setenv("WORKER_VERIFY_OIDC", "true")
    monkeypatch.delenv("WORKER_SERVICE_ACCOUNT", raising=False)
    headers = {**QUEUE_HEADER, "Authorization": "Bearer not-a-real-jwt"}
    resp = client_worker.post("/internal/jobs/execute/job-1", headers=headers)
    assert resp.status_code == 403
    mock_get_doc.assert_not_called()


@patch("routes.worker.get_job_doc")
def test_oidc_enabled_valid_claims_passes_auth_gate(mock_get_doc, client_worker, monkeypatch):
    """A token whose verified claims match the expected email and audience
    passes the auth gate (verified by reaching the job lookup, here a missing
    doc → 200)."""
    monkeypatch.setenv("WORKER_VERIFY_OIDC", "true")
    monkeypatch.setenv("WORKER_SERVICE_ACCOUNT", "worker@proj.iam.gserviceaccount.com")
    mock_get_doc.return_value = None  # missing doc → idempotent 200

    # The test client uses http on localhost; aud reconstruction honors
    # X-Forwarded-Proto, so set it to match what we return as the claim aud.
    headers = {
        **QUEUE_HEADER,
        "Authorization": "Bearer valid-token",
        "X-Forwarded-Proto": "https",
    }
    valid_claims = {
        "email_verified": True,
        "email": "worker@proj.iam.gserviceaccount.com",
        "aud": "https://localhost/internal/jobs/execute/job-1",
    }
    with patch(
        "google.oauth2.id_token.verify_oauth2_token", return_value=valid_claims
    ):
        resp = client_worker.post("/internal/jobs/execute/job-1", headers=headers)

    assert resp.status_code == 200
    mock_get_doc.assert_called_once()


@patch("routes.worker.get_job_doc")
def test_oidc_enabled_strips_extra_whitespace_in_bearer_header(mock_get_doc, client_worker, monkeypatch):
    """A Bearer header with extra internal whitespace (e.g. 'Bearer  <token>')
    must have the token stripped before verification, not passed through with
    a leading space (regression: _extract_bearer_token's split(" ", 1) used to
    leave the leading space in place, silently corrupting the token)."""
    monkeypatch.setenv("WORKER_VERIFY_OIDC", "true")
    monkeypatch.setenv("WORKER_SERVICE_ACCOUNT", "worker@proj.iam.gserviceaccount.com")
    mock_get_doc.return_value = None  # missing doc → idempotent 200

    headers = {
        **QUEUE_HEADER,
        "Authorization": "Bearer  valid-token",  # two spaces after "Bearer"
        "X-Forwarded-Proto": "https",
    }
    valid_claims = {
        "email_verified": True,
        "email": "worker@proj.iam.gserviceaccount.com",
        "aud": "https://localhost/internal/jobs/execute/job-1",
    }
    with patch(
        "google.oauth2.id_token.verify_oauth2_token", return_value=valid_claims
    ) as mock_verify:
        resp = client_worker.post("/internal/jobs/execute/job-1", headers=headers)

    assert resp.status_code == 200
    mock_get_doc.assert_called_once()
    # The token passed to google-auth must be stripped, not " valid-token".
    called_token = mock_verify.call_args[0][0]
    assert called_token == "valid-token"


# ---------------------------------------------------------------------------
# GCS cleanup for jobs with an uploaded PDF
# ---------------------------------------------------------------------------

def _make_job_doc_with_pdf_upload(status="not_started", input_pdf_gcs_uri="gs://b/p.pdf"):
    doc = _make_job_doc(status=status)
    doc["input_pdf_gcs_uri"] = input_pdf_gcs_uri
    return doc


@patch("routes.worker.delete_gcs_object")
@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_success_triggers_gcs_cleanup(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    mock_delete_gcs, client_worker,
):
    mock_get_doc.return_value = _make_job_doc_with_pdf_upload()
    mock_fs_client.return_value = MagicMock()

    care_plan_mock = MagicMock()
    care_plan_mock.to_dict.return_value = {"reason_for_visit": [{"reason": "Hypertension"}]}
    grading_mock = MagicMock()

    def fake_pipeline(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        yield AdapterResult(care_plan=care_plan_mock, grading=grading_mock, raw_text=text, clarified_text="c")

    envelope_mock = MagicMock()
    envelope_mock.to_dict.return_value = {"care_plan": {}, "metrics": {"saved_id": None}}

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline(*a, **kw)):
        with patch("routes.worker.CarePlanInternal", return_value=envelope_mock):
            resp = client_worker.post(
                "/internal/jobs/execute/job-1", headers=QUEUE_HEADER, content_type="application/json",
            )

    assert resp.status_code == 200
    mock_delete_gcs.assert_called_once_with("gs://b/p.pdf")


@patch("routes.worker.delete_gcs_object")
@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_pipeline_failure_still_triggers_gcs_cleanup(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    mock_delete_gcs, client_worker,
):
    mock_get_doc.return_value = _make_job_doc_with_pdf_upload()
    mock_fs_client.return_value = MagicMock()

    def fake_pipeline_error(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        yield AdapterError(error_data={"code": "PIPELINE_ERROR", "message": "boom"})

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline_error(*a, **kw)):
        resp = client_worker.post("/internal/jobs/execute/job-1", headers=QUEUE_HEADER)

    assert resp.status_code == 200
    mock_delete_gcs.assert_called_once_with("gs://b/p.pdf")


@patch("routes.worker.delete_gcs_object")
@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_without_pdf_upload_never_triggers_gcs_cleanup(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    mock_delete_gcs, client_worker,
):
    mock_get_doc.return_value = _make_job_doc()  # no input_pdf_gcs_uri key
    mock_fs_client.return_value = MagicMock()

    care_plan_mock = MagicMock()
    care_plan_mock.to_dict.return_value = {}
    grading_mock = MagicMock()

    def fake_pipeline(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        yield AdapterResult(care_plan=care_plan_mock, grading=grading_mock, raw_text=text, clarified_text="c")

    envelope_mock = MagicMock()
    envelope_mock.to_dict.return_value = {"care_plan": {}, "metrics": {"saved_id": None}}

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline(*a, **kw)):
        with patch("routes.worker.CarePlanInternal", return_value=envelope_mock):
            client_worker.post(
                "/internal/jobs/execute/job-1", headers=QUEUE_HEADER, content_type="application/json",
            )

    mock_delete_gcs.assert_not_called()


# ---------------------------------------------------------------------------
# Jobs drop `care_plan.raw` from the completed output (this change)
# ---------------------------------------------------------------------------

_RAW_TEXT_FIXTURE = {
    "text": "full document text " * 50,
    "simplified_text": "simplified document text " * 50,
    "clarified_text": "clarified document text " * 50,
}


@patch("routes.worker.delete_gcs_object")
@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_completed_output_has_no_raw(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    mock_delete_gcs, client_worker,
):
    """Jobs must not persist care_plan.raw (text/simplified_text/
    clarified_text each hold a full copy of the document) in the completed
    job's output_data."""
    mock_get_doc.return_value = _make_job_doc_with_pdf_upload()
    mock_fs_client.return_value = MagicMock()

    care_plan_mock = MagicMock()
    care_plan_mock.to_dict.return_value = {
        "reason_for_visit": [{"reason": "Hypertension"}],
        "raw": dict(_RAW_TEXT_FIXTURE),
    }
    grading_mock = MagicMock()

    def fake_pipeline(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        yield AdapterResult(care_plan=care_plan_mock, grading=grading_mock, raw_text=text, clarified_text="c")

    envelope_mock = MagicMock()
    envelope_mock.to_dict.return_value = {
        "care_plan": {
            "reason_for_visit": [{"reason": "Hypertension"}],
            "raw": dict(_RAW_TEXT_FIXTURE),
        },
        "metrics": {"saved_id": None},
    }

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline(*a, **kw)):
        with patch("routes.worker.CarePlanInternal", return_value=envelope_mock):
            resp = client_worker.post(
                "/internal/jobs/execute/job-1", headers=QUEUE_HEADER, content_type="application/json",
            )

    assert resp.status_code == 200
    mock_complete.assert_called_once()
    saved_output_data = mock_complete.call_args.args[1]
    assert "raw" not in saved_output_data["care_plan"]


# ---------------------------------------------------------------------------
# Jobs also drop the full document copy at `input.text` (this change)
# ---------------------------------------------------------------------------

_FULL_DOCUMENT_TEXT = "Patient has hypertension. Take your medicine daily. " * 50

# A real Grading, built the same way care_plan_pipeline.py builds it (from
# in-memory before/after text via score_text_safe + build_grading_with_before_
# after_score), so the regression test below asserts on real combined scores
# rather than a mocked stand-in.
_REAL_GRADING_DICT = build_grading_with_before_after_score(
    score_text_safe(_FULL_DOCUMENT_TEXT, "before"), _FULL_DOCUMENT_TEXT,
    score_text_safe("Your blood pressure is high. Take your pill daily. " * 50, "after"),
    "Your blood pressure is high. Take your pill daily. " * 50,
).to_dict()


@patch("routes.worker.delete_gcs_object")
@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_completed_output_strips_input_text(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    mock_delete_gcs, client_worker,
):
    """Jobs must not persist input.text (a second full copy of the
    document, alongside care_plan.raw) in the completed job's output_data."""
    mock_get_doc.return_value = _make_job_doc_with_pdf_upload()
    mock_fs_client.return_value = MagicMock()

    care_plan_mock = MagicMock()
    care_plan_mock.to_dict.return_value = {
        "reason_for_visit": [{"reason": "Hypertension"}],
        "raw": dict(_RAW_TEXT_FIXTURE),
    }
    grading_mock = MagicMock()

    def fake_pipeline(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        yield AdapterResult(care_plan=care_plan_mock, grading=grading_mock, raw_text=text, clarified_text="c")

    envelope_mock = MagicMock()
    envelope_mock.to_dict.return_value = {
        "input": {"mode": "text", "text": _FULL_DOCUMENT_TEXT},
        "care_plan": {
            "reason_for_visit": [{"reason": "Hypertension"}],
            "raw": dict(_RAW_TEXT_FIXTURE),
        },
        # Deep-copied so the in-place trim (`grading["entries"] = ...`)
        # in routes/worker.py never mutates the shared module-level fixture —
        # other tests in this file assert against the pristine, untrimmed
        # _REAL_GRADING_DICT and must not be affected by test execution order.
        "grading": copy.deepcopy(_REAL_GRADING_DICT),
        "metrics": {"saved_id": None},
    }

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline(*a, **kw)):
        with patch("routes.worker.CarePlanInternal", return_value=envelope_mock):
            resp = client_worker.post(
                "/internal/jobs/execute/job-1", headers=QUEUE_HEADER, content_type="application/json",
            )

    assert resp.status_code == 200
    mock_complete.assert_called_once()
    saved_output_data = mock_complete.call_args.args[1]

    # No full document text survives anywhere in the persisted output: neither
    # in input.text nor in care_plan.raw.
    assert "text" not in saved_output_data["input"]
    assert "raw" not in saved_output_data["care_plan"]
    dumped = str(saved_output_data)
    assert _FULL_DOCUMENT_TEXT not in dumped




@patch("routes.worker.delete_gcs_object")
@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_grading_trimmed_to_combined_after_input_and_raw_stripping(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    mock_delete_gcs, client_worker,
):
    """Regression guard for the input.text/care_plan.raw stripping above: the
    before/after 'combined' grading scores shown on the result screen
    (ResultScreen.tsx reads output_data.grading.entries) must survive, while
    the other 12 non-'combined' method entries (computed but never rendered
    in the frontend) are trimmed away, storage-side only."""
    mock_get_doc.return_value = _make_job_doc_with_pdf_upload()
    mock_fs_client.return_value = MagicMock()

    care_plan_mock = MagicMock()
    care_plan_mock.to_dict.return_value = {
        "reason_for_visit": [{"reason": "Hypertension"}],
        "raw": dict(_RAW_TEXT_FIXTURE),
    }
    grading_mock = MagicMock()

    def fake_pipeline(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        yield AdapterResult(care_plan=care_plan_mock, grading=grading_mock, raw_text=text, clarified_text="c")

    envelope_mock = MagicMock()
    envelope_mock.to_dict.return_value = {
        "input": {"mode": "text", "text": _FULL_DOCUMENT_TEXT},
        "care_plan": {
            "reason_for_visit": [{"reason": "Hypertension"}],
            "raw": dict(_RAW_TEXT_FIXTURE),
        },
        # Deep-copied so the in-place trim (`grading["entries"] = ...`)
        # in routes/worker.py never mutates the shared module-level fixture —
        # other tests in this file assert against the pristine, untrimmed
        # _REAL_GRADING_DICT and must not be affected by test execution order.
        "grading": copy.deepcopy(_REAL_GRADING_DICT),
        "metrics": {"saved_id": None},
    }

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline(*a, **kw)):
        with patch("routes.worker.CarePlanInternal", return_value=envelope_mock):
            resp = client_worker.post(
                "/internal/jobs/execute/job-1", headers=QUEUE_HEADER, content_type="application/json",
            )

    assert resp.status_code == 200
    mock_complete.assert_called_once()
    saved_output_data = mock_complete.call_args.args[1]

    entries = saved_output_data["grading"]["entries"]
    assert len(entries) == 2
    assert {e["name"] for e in entries} == {"combined"}
    assert {e["target"] for e in entries} == {"before", "after"}

    # Values, not just shape, must be unaffected by trimming: each surviving
    # entry's grade must match what the untrimmed pipeline output originally
    # computed for that (name, target) pair.
    original_combined = {
        (e["name"], e["target"]): e["grade"]
        for e in _REAL_GRADING_DICT["entries"] if e["name"] == "combined"
    }
    for e in entries:
        assert e["grade"] == original_combined[(e["name"], e["target"])]

    before = next(e for e in entries if e["target"] == "before")
    after = next(e for e in entries if e["target"] == "after")
    assert isinstance(before["grade"], (int, float))
    assert isinstance(after["grade"], (int, float))
    # Real, non-mocked scores from actual scoring logic — not zero/placeholder.
    assert before["grade"] > 0
    assert after["grade"] > 0


# ---------------------------------------------------------------------------
# Task 1 (06-job-optimizations): trim grading entries to combined-only
# ---------------------------------------------------------------------------



def _job_completes_with_grading(grading_value, has_grading_key, client_worker, mock_get_doc,
                                       mock_complete):
    mock_get_doc.return_value = _make_job_doc_with_pdf_upload()

    care_plan_mock = MagicMock()
    care_plan_mock.to_dict.return_value = {"reason_for_visit": [{"reason": "Hypertension"}]}
    grading_mock = MagicMock()

    def fake_pipeline(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        yield AdapterResult(care_plan=care_plan_mock, grading=grading_mock, raw_text=text, clarified_text="c")

    to_dict_value = {
        "input": {"mode": "text", "text": "some text"},
        "care_plan": {"reason_for_visit": [{"reason": "Hypertension"}]},
        "metrics": {"saved_id": None},
    }
    if has_grading_key:
        to_dict_value["grading"] = grading_value

    envelope_mock = MagicMock()
    envelope_mock.to_dict.return_value = to_dict_value

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline(*a, **kw)):
        with patch("routes.worker.CarePlanInternal", return_value=envelope_mock):
            resp = client_worker.post(
                "/internal/jobs/execute/job-1", headers=QUEUE_HEADER, content_type="application/json",
            )

    assert resp.status_code == 200
    mock_complete.assert_called_once()
    return mock_complete.call_args.args[1]


@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_completes_when_grading_key_missing(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    client_worker,
):
    """No `grading` key at all in envelope.to_dict() — must be a silent no-op,
    never a KeyError."""
    saved_output_data = _job_completes_with_grading(
        grading_value=None, has_grading_key=False,
        client_worker=client_worker, mock_get_doc=mock_get_doc, mock_complete=mock_complete,
    )
    assert "grading" not in saved_output_data


@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_completes_when_grading_is_none(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    client_worker,
):
    """`grading: None` — not a dict, so must be a silent no-op, never an
    AttributeError from calling .get on None."""
    saved_output_data = _job_completes_with_grading(
        grading_value=None, has_grading_key=True,
        client_worker=client_worker, mock_get_doc=mock_get_doc, mock_complete=mock_complete,
    )
    assert saved_output_data["grading"] is None


@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_completes_when_grading_dict_has_no_entries_key(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    client_worker,
):
    """`grading: {}` — dict present but no `entries` key — must be a silent
    no-op, never a KeyError."""
    saved_output_data = _job_completes_with_grading(
        grading_value={}, has_grading_key=True,
        client_worker=client_worker, mock_get_doc=mock_get_doc, mock_complete=mock_complete,
    )
    assert saved_output_data["grading"] == {}


@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_completes_when_entries_is_none(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    client_worker,
):
    """`grading: {"entries": None}` — entries present but not a list — must
    be a silent no-op, never a TypeError from iterating None."""
    saved_output_data = _job_completes_with_grading(
        grading_value={"entries": None}, has_grading_key=True,
        client_worker=client_worker, mock_get_doc=mock_get_doc, mock_complete=mock_complete,
    )
    assert saved_output_data["grading"]["entries"] is None


@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_drops_non_dict_entries_and_filters_valid_non_combined_ones(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    client_worker,
):
    """A mixed list of valid dict entries and non-dict junk: the non-dict
    entry must simply be dropped (not raise), and the one valid non-`combined`
    entry among them must still be filtered out."""
    saved_output_data = _job_completes_with_grading(
        grading_value={"entries": [
            {"name": "combined", "target": "before", "grade": 1},
            "not-a-dict",
            {"name": "smog", "target": "before", "grade": 2},
        ]},
        has_grading_key=True,
        client_worker=client_worker, mock_get_doc=mock_get_doc, mock_complete=mock_complete,
    )
    assert saved_output_data["grading"]["entries"] == [
        {"name": "combined", "target": "before", "grade": 1},
    ]


# ---------------------------------------------------------------------------
# total_duration_ms population (06-job-optimizations Task 2)
# ---------------------------------------------------------------------------

@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_completed_job_populates_total_duration_ms(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    client_worker, monkeypatch,
):
    mock_get_doc.return_value = _make_job_doc()
    mock_fs_client.return_value = MagicMock()

    # Two calls to time.monotonic() happen before this task's read-back:
    # once at worker.py:88 (`start`), once at this task's new line. Fake
    # a fixed 2.5s gap between them.
    clock = iter([100.0, 102.5])
    monkeypatch.setattr("routes.worker.time.monotonic", lambda: next(clock))

    care_plan_mock = MagicMock()
    care_plan_mock.to_dict.return_value = {}
    grading_mock = MagicMock()

    def fake_pipeline(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        yield AdapterResult(care_plan=care_plan_mock, grading=grading_mock, raw_text=text, clarified_text="c")

    envelope_mock = MagicMock()
    envelope_mock.to_dict.return_value = {"care_plan": {}, "metrics": {"saved_id": None}}

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline(*a, **kw)):
        with patch("routes.worker.CarePlanInternal") as mock_envelope_cls:
            mock_envelope_cls.return_value = envelope_mock
            resp = client_worker.post(
                "/internal/jobs/execute/job-1", headers=QUEUE_HEADER, content_type="application/json",
            )

    assert resp.status_code == 200
    # Assert on the Metrics instance passed into CarePlanInternal(...),
    # since envelope_mock.to_dict() is a fixed stub in this test.
    passed_metrics = mock_envelope_cls.call_args.kwargs["metrics"]
    assert passed_metrics.total_duration_ms == 2500.0


@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_with_pdf_upload_also_populates_total_duration_ms(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client,
    client_worker, monkeypatch,
):
    """Regression guard: Task 2 is unconditional, regardless of job shape."""
    mock_get_doc.return_value = _make_job_doc_with_pdf_upload()
    mock_fs_client.return_value = MagicMock()

    clock = iter([100.0, 102.5])
    monkeypatch.setattr("routes.worker.time.monotonic", lambda: next(clock))

    care_plan_mock = MagicMock()
    care_plan_mock.to_dict.return_value = {}
    grading_mock = MagicMock()

    def fake_pipeline(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        yield AdapterResult(care_plan=care_plan_mock, grading=grading_mock, raw_text=text, clarified_text="c")

    envelope_mock = MagicMock()
    envelope_mock.to_dict.return_value = {"care_plan": {}, "metrics": {"saved_id": None}}

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline(*a, **kw)):
        with patch("routes.worker.CarePlanInternal") as mock_envelope_cls:
            mock_envelope_cls.return_value = envelope_mock
            resp = client_worker.post(
                "/internal/jobs/execute/job-1", headers=QUEUE_HEADER, content_type="application/json",
            )

    assert resp.status_code == 200
    passed_metrics = mock_envelope_cls.call_args.kwargs["metrics"]
    assert passed_metrics.total_duration_ms == 2500.0


# ---------------------------------------------------------------------------
# Worker idempotency lease on "processing" redelivery (Finding 7)
# ---------------------------------------------------------------------------

@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_processing_job_within_lease_window_skips_redelivery(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client, client_worker
):
    """A redelivered task for a job that's still within its own timeout
    budget must be a no-op (no pipeline re-run, no Firestore writes) --
    otherwise Cloud Tasks' at-least-once redelivery re-runs the whole
    5-stage LLM pipeline a second time (double billing)."""
    doc = _make_job_doc(status="processing")
    doc["started_at"] = datetime.now(timezone.utc) - timedelta(seconds=5)
    mock_get_doc.return_value = doc

    resp = client_worker.post("/internal/jobs/execute/job-1", headers=QUEUE_HEADER)

    assert resp.status_code == 200
    mock_complete.assert_not_called()
    mock_fail.assert_not_called()
    mock_update_stage.assert_not_called()
    mock_fs_client.assert_not_called()


@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_processing_job_past_lease_window_is_retried_to_completion(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client, client_worker
):
    """A job stuck 'processing' well past its own deadline (crashed
    container, etc.) must still be retryable -- the lease check must not
    permanently strand a legitimately-failed job."""
    from utils.constants import Constants

    doc = _make_job_doc(status="processing")
    doc["started_at"] = datetime.now(timezone.utc) - timedelta(
        seconds=Constants.Deadlines.SINGLE_JOB_INTERNAL_DEADLINE_S + 10
    )
    mock_get_doc.return_value = doc
    mock_fs_client.return_value = MagicMock()

    care_plan_mock = MagicMock()
    care_plan_mock.to_dict.return_value = {"reason_for_visit": [{"reason": "Hypertension"}]}
    grading_mock = MagicMock()

    def fake_pipeline(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        yield AdapterResult(care_plan=care_plan_mock, grading=grading_mock, raw_text=text, clarified_text="c")

    envelope_mock = MagicMock()
    envelope_mock.to_dict.return_value = {"care_plan": {}, "metrics": {"saved_id": None}}

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline(*a, **kw)):
        with patch("routes.worker.CarePlanInternal", return_value=envelope_mock):
            resp = client_worker.post(
                "/internal/jobs/execute/job-1", headers=QUEUE_HEADER, content_type="application/json",
            )

    assert resp.status_code == 200
    mock_complete.assert_called_once()
    mock_fail.assert_not_called()


@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_processing_job_with_no_started_at_is_retried(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client, client_worker
):
    """Defensive fallback: 'processing' with no started_at (shouldn't happen
    in practice, but must fail open to retry rather than strand the job)."""
    doc = _make_job_doc(status="processing")  # started_at defaults to None
    mock_get_doc.return_value = doc
    mock_fs_client.return_value = MagicMock()

    care_plan_mock = MagicMock()
    care_plan_mock.to_dict.return_value = {}
    grading_mock = MagicMock()

    def fake_pipeline(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        yield AdapterResult(care_plan=care_plan_mock, grading=grading_mock, raw_text=text, clarified_text="c")

    envelope_mock = MagicMock()
    envelope_mock.to_dict.return_value = {"care_plan": {}, "metrics": {"saved_id": None}}

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline(*a, **kw)):
        with patch("routes.worker.CarePlanInternal", return_value=envelope_mock):
            resp = client_worker.post(
                "/internal/jobs/execute/job-1", headers=QUEUE_HEADER, content_type="application/json",
            )

    assert resp.status_code == 200
    mock_complete.assert_called_once()


# ---------------------------------------------------------------------------
# Defensive minimum-content guard (Finding 2)
# ---------------------------------------------------------------------------

@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_worker_rejects_text_below_min_meaningful_content_as_empty_document(
    mock_get_doc, mock_fail, mock_complete, mock_fs_client, client_worker
):
    """Belt-and-suspenders alongside the resolve_uploaded_files-level check:
    even if some other path put near-nothing into job.input_text, the worker
    itself must never let it reach the LLM pipeline."""
    doc = _make_job_doc()
    doc["input_text"] = "short"  # < MIN_MEANINGFUL_CONTENT_CHARS (20)
    mock_get_doc.return_value = doc
    mock_fs_client.return_value = MagicMock()

    resp = client_worker.post("/internal/jobs/execute/job-1", headers=QUEUE_HEADER)

    assert resp.status_code == 200
    mock_fail.assert_called_once()
    error_data = mock_fail.call_args.args[1]
    assert error_data["code"] == "EMPTY_DOCUMENT"
    mock_complete.assert_not_called()


# ---------------------------------------------------------------------------
# Top-level input_text cleared on terminal state (Finding 4)
# ---------------------------------------------------------------------------

@patch("utils.firebase.firestore.client")
@patch("routes.worker.complete_job")
@patch("routes.worker.update_job_stage")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_completion_clears_top_level_input_text(
    mock_get_doc, mock_fail, mock_update_stage, mock_complete, mock_fs_client, client_worker
):
    mock_get_doc.return_value = _make_job_doc_with_pdf_upload()
    mock_fs_client.return_value = MagicMock()

    care_plan_mock = MagicMock()
    care_plan_mock.to_dict.return_value = {}
    grading_mock = MagicMock()

    def fake_pipeline(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        yield AdapterResult(care_plan=care_plan_mock, grading=grading_mock, raw_text=text, clarified_text="c")

    envelope_mock = MagicMock()
    envelope_mock.to_dict.return_value = {"care_plan": {}, "metrics": {"saved_id": None}}

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline(*a, **kw)):
        with patch("routes.worker.CarePlanInternal", return_value=envelope_mock):
            resp = client_worker.post(
                "/internal/jobs/execute/job-1", headers=QUEUE_HEADER, content_type="application/json",
            )

    assert resp.status_code == 200
    mock_complete.assert_called_once()

@patch("utils.firebase.firestore.client")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_failure_also_clears_top_level_input_text(
    mock_get_doc, mock_fail, mock_fs_client, client_worker
):
    doc = _make_job_doc_with_pdf_upload()
    doc["input_text"] = "short"  # triggers the MIN_MEANINGFUL_CONTENT_CHARS EMPTY_DOCUMENT path
    mock_get_doc.return_value = doc
    mock_fs_client.return_value = MagicMock()

    resp = client_worker.post("/internal/jobs/execute/job-1", headers=QUEUE_HEADER)

    assert resp.status_code == 200
    mock_fail.assert_called_once()


@patch("utils.firebase.firestore.client")
@patch("routes.worker.fail_job")
@patch("routes.worker.get_job_doc")
def test_job_unexpected_exception_clears_top_level_input_text(
    mock_get_doc, mock_fail, mock_fs_client, client_worker
):
    """The bottom except-Exception handler must also call fail_job (which
    unconditionally clears input_text), not just the "clean" fail paths."""
    mock_get_doc.return_value = _make_job_doc_with_pdf_upload()
    mock_fs_client.return_value = MagicMock()

    def fake_pipeline_raises(text, metrics, grading_enabled, source_kind="text", is_batch=False):
        raise RuntimeError("boom")
        yield  # pragma: no cover -- keeps this a generator function

    with patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline_raises(*a, **kw)):
        resp = client_worker.post("/internal/jobs/execute/job-1", headers=QUEUE_HEADER)

    assert resp.status_code == 500
    mock_fail.assert_called_once()
