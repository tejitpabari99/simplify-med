"""Tests for utils/cloud_tasks.py — TDD: write tests first, then create the module."""

import json
from unittest.mock import MagicMock, patch


@patch("utils.cloud_tasks.tasks_v2.CloudTasksClient")
def test_enqueue_job_calls_create_task(mock_client_class):
    from utils.cloud_tasks import enqueue_job

    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    enqueue_job(
        "abc",
        queue_name="q",
        worker_url="https://w.run.app",
        service_account="sa@p.iam",
        deadline_seconds=300,
    )

    mock_client.create_task.assert_called_once()
    call_kwargs = mock_client.create_task.call_args
    request_arg = call_kwargs.kwargs.get("request") or call_kwargs.args[0]
    assert request_arg["parent"] == "q"

    task = request_arg["task"]
    assert task["http_request"]["url"].endswith("/internal/jobs/execute/abc")
    assert task["http_request"]["oidc_token"]["service_account_email"] == "sa@p.iam"
    assert task["dispatch_deadline"].seconds == 300

    payload = json.loads(task["http_request"]["body"].decode())
    assert payload == {"job_id": "abc"}


@patch("utils.cloud_tasks.tasks_v2.CloudTasksClient")
def test_enqueue_job_strips_trailing_slash_from_url(mock_client_class):
    from utils.cloud_tasks import enqueue_job

    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    enqueue_job(
        "abc",
        queue_name="q",
        worker_url="https://w.run.app/",
        service_account="sa@p.iam",
        deadline_seconds=300,
    )

    call_kwargs = mock_client.create_task.call_args
    request_arg = call_kwargs.kwargs.get("request") or call_kwargs.args[0]
    task = request_arg["task"]
    url = task["http_request"]["url"]
    assert url == "https://w.run.app/internal/jobs/execute/abc"


def test_enqueue_job_safe_returns_none_on_success():
    from utils.cloud_tasks import enqueue_job_safe
    from unittest.mock import patch
    with patch("utils.cloud_tasks.enqueue_job") as mock_enqueue:
        mock_enqueue.return_value = None
        result = enqueue_job_safe(
            "job123",
            queue_name="q",
            worker_url="https://w.run.app",
            service_account="sa@p.iam",
            deadline_seconds=300,
        )
        assert result is None


def test_enqueue_job_safe_returns_500_on_missing_config():
    from utils.cloud_tasks import enqueue_job_safe, MissingJobConfigError
    from unittest.mock import patch
    with patch("utils.cloud_tasks.enqueue_job", side_effect=MissingJobConfigError("CLOUD_TASKS_QUEUE")):
        result = enqueue_job_safe(
            "job123",
            queue_name="q",
            worker_url="https://w.run.app",
            service_account="sa@p.iam",
            deadline_seconds=300,
        )
        assert result is not None
        resp_dict, status = result
        assert status == 500
        assert resp_dict["error"]["code"] == "INTERNAL_ERROR"


def test_enqueue_job_safe_returns_500_on_exception():
    from utils.cloud_tasks import enqueue_job_safe
    from unittest.mock import patch
    with patch("utils.cloud_tasks.enqueue_job", side_effect=Exception("network error")):
        result = enqueue_job_safe(
            "job123",
            queue_name="q",
            worker_url="https://w.run.app",
            service_account="sa@p.iam",
            deadline_seconds=300,
        )
        assert result is not None
        resp_dict, status = result
        assert status == 500
        assert resp_dict["error"]["code"] == "INTERNAL_ERROR"
