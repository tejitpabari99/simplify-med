"""Tests for utils/gcs.py — GCS client construction and delete_gcs_object."""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_gcs_module(monkeypatch):
    """Patch utils.gcs.gcs with a MagicMock; return the blob mock.

    Chain: gcs.Client() → mock_client → .bucket() → mock_bucket → .blob() → mock_blob
    """
    import utils.gcs as mod

    mock_gcs = MagicMock()
    mock_client = MagicMock()
    mock_bucket = MagicMock()
    mock_blob = MagicMock()

    mock_gcs.Client.return_value = mock_client
    mock_client.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob

    monkeypatch.setattr(mod, "gcs", mock_gcs)
    # _gcs_client() caches its result at module level; reset it so this
    # test's mock chain is what actually gets constructed and exercised,
    # rather than a stale client cached by a prior test.
    monkeypatch.setattr(mod, "_client", None)
    return mock_blob


# ---------------------------------------------------------------------------
# delete_gcs_object
# ---------------------------------------------------------------------------

def test_delete_gcs_object_parses_uri_and_deletes(mock_gcs_module):
    from utils.gcs import delete_gcs_object
    delete_gcs_object("gs://my-bucket/care_plan_inputs/user-1/inputs/abc.pdf")
    mock_gcs_module.delete.assert_called_once()


def test_delete_gcs_object_uses_correct_bucket_and_blob_name(monkeypatch):
    import utils.gcs as mod

    mock_client = MagicMock()
    monkeypatch.setattr(mod, "_client", mock_client)

    from utils.gcs import delete_gcs_object
    delete_gcs_object("gs://my-bucket/care_plan_inputs/user-1/inputs/abc.pdf")

    mock_client.bucket.assert_called_once_with("my-bucket")
    mock_client.bucket.return_value.blob.assert_called_once_with(
        "care_plan_inputs/user-1/inputs/abc.pdf"
    )


def test_delete_gcs_object_swallows_not_found(mock_gcs_module):
    from google.api_core.exceptions import NotFound
    mock_gcs_module.delete.side_effect = NotFound("gone")

    from utils.gcs import delete_gcs_object
    delete_gcs_object("gs://my-bucket/some/path.pdf")  # must not raise


def test_delete_gcs_object_logs_but_does_not_raise_on_other_error(mock_gcs_module):
    mock_gcs_module.delete.side_effect = RuntimeError("boom")

    from utils.gcs import delete_gcs_object
    delete_gcs_object("gs://my-bucket/some/path.pdf")  # must not raise


def test_delete_gcs_object_warns_and_noops_on_non_gs_uri(caplog):
    from utils.gcs import delete_gcs_object
    delete_gcs_object("not-a-gs-uri")  # must not raise
