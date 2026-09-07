"""Tests for services/retention.py — anonymous Firebase Auth account cleanup.

Mocks `services.retention.auth` throughout — this suite must never touch a real
Firebase Auth user pool (mirrors the mocking style in tests/utils/test_gcs.py).
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from services.retention import (
    _is_anonymous,
    _older_than,
    cleanup_anonymous_users,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def make_user(uid, provider_ids, creation_timestamp_ms):
    """Build a fake ExportedUserRecord-shaped object.

    provider_ids: list of provider_id strings (empty list => anonymous).
    creation_timestamp_ms: int, ms since epoch.
    """
    return SimpleNamespace(
        uid=uid,
        provider_data=[SimpleNamespace(provider_id=pid) for pid in provider_ids],
        user_metadata=SimpleNamespace(creation_timestamp=creation_timestamp_ms),
    )


def make_page(users, next_page=None):
    """Build a fake ListUsersPage-shaped object."""
    page = SimpleNamespace(users=users)
    page.get_next_page = MagicMock(return_value=next_page)
    return page


NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)
ONE_HOUR_MS = 60 * 60 * 1000

OLD_MS = NOW_MS - (25 * ONE_HOUR_MS)   # older than 24h cutoff
NEW_MS = NOW_MS - (1 * ONE_HOUR_MS)    # younger than 24h cutoff


# ---------------------------------------------------------------------------
# _is_anonymous
# ---------------------------------------------------------------------------

def test_is_anonymous_true_for_empty_provider_data():
    user = make_user("u1", [], OLD_MS)
    assert _is_anonymous(user) is True


def test_is_anonymous_false_for_password_provider():
    user = make_user("u2", ["password"], OLD_MS)
    assert _is_anonymous(user) is False


def test_is_anonymous_false_for_multiple_providers():
    user = make_user("u3", ["password", "google.com"], OLD_MS)
    assert _is_anonymous(user) is False


# ---------------------------------------------------------------------------
# _older_than
# ---------------------------------------------------------------------------

def test_older_than_true_when_before_cutoff():
    user = make_user("u1", [], OLD_MS)
    cutoff_ms = NOW_MS - (24 * ONE_HOUR_MS)
    assert _older_than(user, cutoff_ms) is True


def test_older_than_false_when_after_cutoff():
    user = make_user("u1", [], NEW_MS)
    cutoff_ms = NOW_MS - (24 * ONE_HOUR_MS)
    assert _older_than(user, cutoff_ms) is False


# ---------------------------------------------------------------------------
# cleanup_anonymous_users — dry_run=True
# ---------------------------------------------------------------------------

def test_dry_run_counts_only_anonymous_and_old(monkeypatch):
    mock_auth = MagicMock()
    monkeypatch.setattr("services.retention.auth", mock_auth)

    users = [
        make_user("anon-old", [], OLD_MS),
        make_user("anon-new", [], NEW_MS),
        make_user("real-old", ["password"], OLD_MS),
        make_user("real-new", ["password"], NEW_MS),
    ]
    page = make_page(users, next_page=None)
    mock_auth.list_users.return_value = page

    summary = cleanup_anonymous_users(dry_run=True, now=NOW)

    assert summary.matched == 1
    assert summary.deleted == 1
    assert summary.dry_run is True
    mock_auth.delete_users.assert_not_called()


# ---------------------------------------------------------------------------
# cleanup_anonymous_users — dry_run=False
# ---------------------------------------------------------------------------

def test_live_run_deletes_only_matched_uids(monkeypatch):
    mock_auth = MagicMock()
    monkeypatch.setattr("services.retention.auth", mock_auth)

    users = [
        make_user("anon-old", [], OLD_MS),
        make_user("anon-new", [], NEW_MS),
        make_user("real-old", ["password"], OLD_MS),
        make_user("real-new", ["password"], NEW_MS),
    ]
    page = make_page(users, next_page=None)
    mock_auth.list_users.return_value = page
    mock_auth.delete_users.return_value = SimpleNamespace(errors=[])

    summary = cleanup_anonymous_users(dry_run=False, now=NOW)

    mock_auth.delete_users.assert_called_once_with(["anon-old"])
    assert summary.matched == 1
    assert summary.deleted == 1
    assert summary.delete_errors == 0


def test_live_run_records_delete_errors_without_raising(monkeypatch):
    mock_auth = MagicMock()
    monkeypatch.setattr("services.retention.auth", mock_auth)

    users = [
        make_user("anon-old", [], OLD_MS),
    ]
    page = make_page(users, next_page=None)
    mock_auth.list_users.return_value = page
    mock_auth.delete_users.return_value = SimpleNamespace(
        errors=[SimpleNamespace(index=0, reason="internal-error")]
    )

    summary = cleanup_anonymous_users(dry_run=False, now=NOW)

    assert summary.delete_errors == 1
    assert summary.error_uids == ["anon-old"]
    assert summary.deleted == 0


# ---------------------------------------------------------------------------
# Real-account safety — explicit regression guard
# ---------------------------------------------------------------------------

def test_real_users_never_matched_regardless_of_age(monkeypatch):
    mock_auth = MagicMock()
    monkeypatch.setattr("services.retention.auth", mock_auth)

    users = [
        make_user("real-1", ["password"], OLD_MS),
        make_user("real-2", ["password"], OLD_MS - (1000 * ONE_HOUR_MS)),
        make_user("real-3", ["google.com"], OLD_MS),
    ]
    page = make_page(users, next_page=None)
    mock_auth.list_users.return_value = page

    summary = cleanup_anonymous_users(dry_run=True, now=NOW)

    assert summary.matched == 0
    assert summary.deleted == 0
    mock_auth.delete_users.assert_not_called()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def test_pagination_calls_delete_per_page_with_matches(monkeypatch):
    mock_auth = MagicMock()
    monkeypatch.setattr("services.retention.auth", mock_auth)

    page2_users = [
        make_user("anon-old-2", [], OLD_MS),
        make_user("real-2", ["password"], OLD_MS),
    ]
    page2 = make_page(page2_users, next_page=None)

    page1_users = [
        make_user("anon-old-1", [], OLD_MS),
        make_user("real-1", ["password"], NEW_MS),
    ]
    page1 = make_page(page1_users, next_page=page2)

    mock_auth.list_users.return_value = page1
    mock_auth.delete_users.return_value = SimpleNamespace(errors=[])

    summary = cleanup_anonymous_users(dry_run=False, now=NOW)

    assert mock_auth.delete_users.call_count == 2
    mock_auth.delete_users.assert_any_call(["anon-old-1"])
    mock_auth.delete_users.assert_any_call(["anon-old-2"])
    assert summary.scanned == 4
    assert summary.matched == 2
    assert summary.deleted == 2
    assert summary.pages == 2


# ---------------------------------------------------------------------------
# Empty result set
# ---------------------------------------------------------------------------

def test_empty_result_set(monkeypatch):
    mock_auth = MagicMock()
    monkeypatch.setattr("services.retention.auth", mock_auth)

    page = make_page([], next_page=None)
    mock_auth.list_users.return_value = page

    summary = cleanup_anonymous_users(dry_run=True, now=NOW)

    assert summary.scanned == 0
    assert summary.matched == 0
    assert summary.deleted == 0
