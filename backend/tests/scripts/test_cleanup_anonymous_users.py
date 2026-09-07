"""Tests for scripts/cleanup_anonymous_users.py — Cloud Run Job entrypoint.

Mocks initialize_firebase and services.retention.cleanup_anonymous_users
throughout — this suite must never touch real Firebase Auth/Admin SDKs.
"""
import logging

import pytest

from services.retention import CleanupSummary
from scripts.cleanup_anonymous_users import _dry_run_from_env, main


# ---------------------------------------------------------------------------
# _dry_run_from_env
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "env_value, expected",
    [
        (None, True),
        ("true", True),
        ("TRUE", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("1", True),
    ],
)
def test_dry_run_from_env(monkeypatch, env_value, expected):
    if env_value is None:
        monkeypatch.delenv("RETENTION_DRY_RUN", raising=False)
    else:
        monkeypatch.setenv("RETENTION_DRY_RUN", env_value)

    assert _dry_run_from_env() is expected


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_returns_zero_even_with_delete_errors(monkeypatch):
    monkeypatch.setattr(
        "scripts.cleanup_anonymous_users.initialize_firebase", lambda: None
    )
    monkeypatch.setattr(
        "scripts.cleanup_anonymous_users.cleanup_anonymous_users",
        lambda dry_run: CleanupSummary(dry_run=dry_run, delete_errors=2),
    )

    assert main() == 0


def test_main_logs_warning_when_delete_errors(monkeypatch, caplog):
    monkeypatch.setattr(
        "scripts.cleanup_anonymous_users.initialize_firebase", lambda: None
    )
    monkeypatch.setattr(
        "scripts.cleanup_anonymous_users.cleanup_anonymous_users",
        lambda dry_run: CleanupSummary(dry_run=dry_run, delete_errors=2),
    )

    with caplog.at_level(logging.WARNING, logger="scripts.cleanup_anonymous_users"):
        main()

    assert any(
        record.levelno == logging.WARNING for record in caplog.records
    )


def test_main_does_not_log_warning_when_no_delete_errors(monkeypatch, caplog):
    monkeypatch.setattr(
        "scripts.cleanup_anonymous_users.initialize_firebase", lambda: None
    )
    monkeypatch.setattr(
        "scripts.cleanup_anonymous_users.cleanup_anonymous_users",
        lambda dry_run: CleanupSummary(dry_run=dry_run, delete_errors=0),
    )

    with caplog.at_level(logging.WARNING, logger="scripts.cleanup_anonymous_users"):
        main()

    assert not any(
        record.levelno == logging.WARNING for record in caplog.records
    )
