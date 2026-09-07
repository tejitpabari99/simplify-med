"""Tests for utils/rate_limit.py — the POST /jobs route's per-IP Firestore counter."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from utils.rate_limit import get_client_ip, _hash_ip, check_rate_limit, rate_limit
from utils.constants import Constants


# ---------------------------------------------------------------------------
# get_client_ip
#
# Topology (see utils.rate_limit.get_client_ip docstring for the full
# citation): simplify-api is reached directly on its `*.run.app` URL. There is no
# External Application Load Balancer / Cloud Armor / CDN in front of it
# (Compute Engine API -- required for any of those -- is disabled on the GCP
# project; confirmed live via `gcloud compute url-maps list`). Cloud Run's own
# front end is therefore the ONLY trusted proxy hop, so it appends exactly ONE
# IP -- the real client's -- to the right of X-Forwarded-For. That makes
# Constants.Limits.TRUSTED_PROXY_HOPS == 1 correct *for this topology*, and the
# rightmost XFF value is the one Google appended. If this deployment is ever
# put behind a GCLB (which appends TWO values --
# "<existing>,<client-ip>,<lb-ip>" per Google's Cloud Load Balancing docs),
# TRUSTED_PROXY_HOPS must become 2 -- via TRUSTED_PROXY_HOPS, no code
# change required.
# ---------------------------------------------------------------------------

def test_get_client_ip_uses_rightmost_xff_value_for_single_trusted_hop(app):
    """With TRUSTED_PROXY_HOPS=1 (this deployment's topology), the single
    Google-appended value is the last one -- not necessarily 'the last two
    values ago' as it would be behind an additional LB hop."""
    with app.test_request_context(headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}):
        assert get_client_ip() == "5.6.7.8"


def test_get_client_ip_ignores_spoofed_leading_values():
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context(headers={"X-Forwarded-For": "attacker-spoofed, also-fake, 9.9.9.9"}):
        assert get_client_ip() == "9.9.9.9"


def test_get_client_ip_single_value_header(app):
    """No existing header from the client; Cloud Run appended exactly one
    value -- the common case for most requests."""
    with app.test_request_context(headers={"X-Forwarded-For": "203.0.113.7"}):
        assert get_client_ip() == "203.0.113.7"


def test_get_client_ip_tolerates_irregular_whitespace(app):
    with app.test_request_context(headers={"X-Forwarded-For": "1.2.3.4 ,   5.6.7.8  "}):
        assert get_client_ip() == "5.6.7.8"


def test_get_client_ip_falls_back_to_remote_addr_when_header_absent():
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context(environ_base={"REMOTE_ADDR": "10.0.0.1"}):
        assert get_client_ip() == "10.0.0.1"


def test_get_client_ip_falls_back_to_unknown_when_nothing_available():
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context(environ_base={"REMOTE_ADDR": ""}):
        assert get_client_ip() == "unknown"


def test_get_client_ip_falls_back_when_header_present_but_empty():
    """An XFF header that is present but empty/whitespace-only must not be
    treated as a zero-length, always-satisfied list -- fall back safely."""
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context(headers={"X-Forwarded-For": "   "}, environ_base={"REMOTE_ADDR": "10.0.0.2"}):
        assert get_client_ip() == "10.0.0.2"


def test_get_client_ip_handles_bracketed_ipv6_with_port(app):
    with app.test_request_context(headers={"X-Forwarded-For": "1.2.3.4, [2001:db8::1]:54321"}):
        assert get_client_ip() == "2001:db8::1"


def test_get_client_ip_handles_bracketed_ipv6_without_port(app):
    with app.test_request_context(headers={"X-Forwarded-For": "1.2.3.4, [2001:db8::1]"}):
        assert get_client_ip() == "2001:db8::1"


def test_get_client_ip_leaves_bare_ipv6_untouched(app):
    """A bare (unbracketed) IPv6 address is indistinguishable from an
    unbracketed 'IPv6:port' form -- stripping would corrupt the address, so
    it must be passed through as-is."""
    with app.test_request_context(headers={"X-Forwarded-For": "1.2.3.4, 2001:db8::1"}):
        assert get_client_ip() == "2001:db8::1"


def test_get_client_ip_strips_ipv4_port(app):
    with app.test_request_context(headers={"X-Forwarded-For": "1.2.3.4:8080"}):
        assert get_client_ip() == "1.2.3.4"


def test_get_client_ip_honors_trusted_hops_env_override(monkeypatch):
    """If this deployment is later put behind an additional trusted proxy
    (e.g. a GCLB), bumping TRUSTED_PROXY_HOPS to 2 must select the
    second-to-last value instead of the last, with no code change."""
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context(headers={"X-Forwarded-For": "attacker-value, 9.9.9.9, 203.0.113.55"}):
        assert get_client_ip() == "9.9.9.9"


def test_get_client_ip_falls_back_when_header_shorter_than_trusted_hops(monkeypatch):
    """A header with fewer comma-separated values than the configured trusted
    hop count is malformed/truncated for this topology -- none of its values
    can be trusted, so fall back rather than guessing which one is real."""
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context(headers={"X-Forwarded-For": "9.9.9.9"}, environ_base={"REMOTE_ADDR": "10.0.0.3"}):
        assert get_client_ip() == "10.0.0.3"


def test_get_client_ip_ignores_non_numeric_env_override(monkeypatch):
    """A garbage TRUSTED_PROXY_HOPS value must not crash request
    handling -- fall back to the documented default for this topology."""
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "not-a-number")
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context(headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}):
        assert get_client_ip() == "5.6.7.8"


# ---------------------------------------------------------------------------
# _hash_ip
# ---------------------------------------------------------------------------

def test_hash_ip_deterministic_same_ip_and_salt(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_SALT", "salt-a")
    assert _hash_ip("1.2.3.4") == _hash_ip("1.2.3.4")


def test_hash_ip_differs_across_ips(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_SALT", "salt-a")
    assert _hash_ip("1.2.3.4") != _hash_ip("5.6.7.8")


def test_hash_ip_differs_across_salts(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_SALT", "salt-a")
    h1 = _hash_ip("1.2.3.4")
    monkeypatch.setenv("RATE_LIMIT_SALT", "salt-b")
    h2 = _hash_ip("1.2.3.4")
    assert h1 != h2


# ---------------------------------------------------------------------------
# _hash_ip fallback salt when RATE_LIMIT_SALT is unset (Finding 9)
# ---------------------------------------------------------------------------

def test_hash_ip_missing_salt_does_not_equal_unsalted_sha256(monkeypatch):
    """Regression: previously, a missing salt fell back to an EMPTY HMAC key
    (hmac.new(b"", ...)), which is trivially reversible against the small
    IPv4 address space. It must no longer produce that exact unsalted value."""
    import hashlib
    import hmac as hmac_module

    monkeypatch.delenv("RATE_LIMIT_SALT", raising=False)
    unsalted = hmac_module.new(b"", b"1.2.3.4", hashlib.sha256).hexdigest()[:20]
    assert _hash_ip("1.2.3.4") != unsalted


def test_hash_ip_missing_salt_still_deterministic_within_process(monkeypatch):
    """The process-local fallback salt must be stable across calls within
    the same process (so rate-limit buckets are at least self-consistent
    for the lifetime of one instance)."""
    monkeypatch.delenv("RATE_LIMIT_SALT", raising=False)
    assert _hash_ip("1.2.3.4") == _hash_ip("1.2.3.4")


def test_hash_ip_missing_salt_logs_error(monkeypatch, caplog):
    import logging
    monkeypatch.delenv("RATE_LIMIT_SALT", raising=False)
    with caplog.at_level(logging.ERROR, logger="utils.rate_limit"):
        _hash_ip("1.2.3.4")
    assert any("RATE_LIMIT_SALT" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# check_rate_limit — uses fake_firestore-style in-memory counter, not the
# emulator (no emulator is configured in this test suite's CI setup).
# ---------------------------------------------------------------------------

class _FakeSnapshot:
    def __init__(self, count):
        self._count = count
        self.exists = count is not None

    def get(self, field):
        return self._count if field == "count" else None


class _FakeRef:
    """Minimal Firestore doc-ref stand-in with an in-memory count."""
    def __init__(self, store, key):
        self._store = store
        self._key = key

    def get(self, transaction=None):
        return _FakeSnapshot(self._store.get(self._key))


class _FakeTransaction:
    """Minimal Firestore-transaction stand-in. Besides the in-memory `.set()`
    the real code path exercises, this also carries the small attribute/method
    surface the installed google-cloud-firestore's `@firestore.transactional`
    decorator's retry/commit protocol touches (`_read_only`, `_max_attempts`,
    `_clean_up`, `_begin`, `_commit`, `_rollback`, `_id`) so it can drive this
    fake as a single-attempt, always-succeeds transaction."""
    _read_only = False
    _max_attempts = 1

    def __init__(self):
        self._id = b"fake-transaction-id"

    def _clean_up(self):
        pass

    def _begin(self, retry_id=None):
        pass

    def _commit(self):
        return []

    def _rollback(self):
        pass

    def set(self, ref, data, merge=True):
        ref._store[ref._key] = data["count"]


@pytest.fixture
def fake_rate_limit_firestore(monkeypatch):
    """Patch firestore_client() so check_rate_limit() operates on an
    in-memory dict keyed by doc_id, simulating Firestore's transactional
    read-then-write without needing a real emulator."""
    store: dict[str, int] = {}

    def _fake_client():
        db = MagicMock()

        def _doc(doc_id):
            return _FakeRef(store, doc_id)

        db.collection.return_value.document.side_effect = _doc
        db.transaction.return_value = _FakeTransaction()
        return db

    monkeypatch.setattr("utils.rate_limit.firestore_client", _fake_client)
    return store


def test_check_rate_limit_allows_up_to_limit_and_blocks_the_next(fake_rate_limit_firestore, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_SALT", "salt")
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context(environ_base={"REMOTE_ADDR": "1.1.1.1"}):
        results = [check_rate_limit() for _ in range(Constants.Limits.RATE_LIMIT_PER_IP_PER_HOUR + 1)]
    assert results == [True] * Constants.Limits.RATE_LIMIT_PER_IP_PER_HOUR + [False]


def test_check_rate_limit_resets_in_next_hour_window(fake_rate_limit_firestore, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_SALT", "salt")
    from flask import Flask
    app = Flask(__name__)

    with app.test_request_context(environ_base={"REMOTE_ADDR": "2.2.2.2"}):
        for _ in range(Constants.Limits.RATE_LIMIT_PER_IP_PER_HOUR):
            assert check_rate_limit() is True
        assert check_rate_limit() is False

    # Simulate the next hour-aligned window by freezing datetime.now().
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
            return base if tz is None else base.astimezone(tz)

    with patch("utils.rate_limit.datetime", _FrozenDatetime):
        with app.test_request_context(environ_base={"REMOTE_ADDR": "2.2.2.2"}):
            assert check_rate_limit() is True


# ---------------------------------------------------------------------------
# rate_limit decorator
# ---------------------------------------------------------------------------

def test_rate_limit_fails_open_on_exception(monkeypatch):
    monkeypatch.setattr("utils.rate_limit.check_rate_limit", MagicMock(side_effect=RuntimeError("firestore down")))

    @rate_limit
    def _handler():
        return "ok", 200

    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context("/jobs", method="POST"):
        body, status = _handler()
    assert status == 200
    assert body == "ok"


def test_rate_limit_returns_429_when_blocked(monkeypatch):
    monkeypatch.setattr("utils.rate_limit.check_rate_limit", MagicMock(return_value=False))

    @rate_limit
    def _handler():
        return "ok", 200

    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context("/jobs", method="POST"):
        body, status = _handler()
    assert status == 429
