"""backend/utils/rate_limit.py — Firestore-backed per-IP rate limiter for the
POST /jobs route. In-memory counters are unreliable across Cloud Run's autoscaled,
non-shared-memory instances; this is deliberately the only place in the
codebase that hashes a client IP."""
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import request
from google.cloud import firestore

from utils.firebase import firestore_client
from utils.constants import Constants
from errors import make_error_response, ErrorCode

# Process-local fallback HMAC key, used ONLY if RATE_LIMIT_SALT is
# unset -- see _hash_ip. Generated once per process at import time (not
# module-level None + lazy-init) so it's stable for the life of this
# instance but never written anywhere or derivable from outside the
# process.
_FALLBACK_IP_HASH_SALT = secrets.token_bytes(32)

logger = logging.getLogger(__name__)


def _trusted_proxy_hops() -> int:
    """Number of trusted reverse-proxy hops between the public internet and
    this container -- i.e. how many IP addresses Google appends to the RIGHT
    end of X-Forwarded-For before the request reaches Flask.

    Deployment topology this value assumes (verified against the original
    deployment, not assumed on faith): the API service is reached directly on
    its `*.run.app` URL -- deployed with a bare `gcloud run services update`,
    with the frontend pointing straight at that `*.run.app` host. There is no
    External Application/Classic Load Balancer, Cloud Armor, or CDN in front
    of it: all of those require the Compute Engine API, which a live `gcloud
    compute url-maps list` confirmed was disabled on that project (PERMISSION_
    DENIED / SERVICE_DISABLED). So Cloud Run's own front end is the ONLY
    proxy hop, and per Google's documented behavior it appends exactly ONE
    IP -- the real client's -- to the right of whatever X-Forwarded-For value
    (if any) the client sent in. That makes 1 the correct hop count for that
    topology -- verify this against your own deployment before relying on it.

    Contrast with a Global External Application Load Balancer, which Google's
    own docs (cloud.google.com/load-balancing/docs/https) describe as
    appending TWO values in the form "<existing>,<client-ip>,<lb-ip>" -- if
    this deployment is ever put behind a GCLB (or any other additional
    trusted proxy), this must become 2, selecting the second-to-last value
    instead of the last. Rather than hard-code a magic index, that knob is
    exposed as TRUSTED_PROXY_HOPS so the topology can be corrected
    without a code change.
    """
    override = os.environ.get(Constants.EnvVars.TRUSTED_PROXY_HOPS)
    if override:
        try:
            hops = int(override)
        except ValueError:
            hops = None
        if hops is not None and hops >= 1:
            return hops
        logger.warning(
            "rate_limit: ignoring invalid %s=%r; using default %d",
            Constants.EnvVars.TRUSTED_PROXY_HOPS, override, Constants.Limits.TRUSTED_PROXY_HOPS,
        )
    return Constants.Limits.TRUSTED_PROXY_HOPS


def _strip_port(value: str) -> str:
    """Best-effort removal of a trailing ':port' from a single X-Forwarded-For
    entry. Handles bracketed IPv6 ('[::1]:8080' -> '::1', '[::1]' -> '::1')
    and IPv4:port ('1.2.3.4:8080' -> '1.2.3.4'). Deliberately leaves a bare,
    unbracketed IPv6 address ('2001:db8::1') untouched: it is indistinguishable
    from an unbracketed 'IPv6:port' form, and guessing wrong would corrupt a
    valid address, so only the unambiguous single-colon (IPv4:port) and
    bracketed-IPv6 forms are stripped."""
    if value.startswith("["):
        closing = value.find("]")
        return value[1:closing] if closing != -1 else value
    if value.count(":") == 1:
        host, _, port = value.rpartition(":")
        if port.isdigit():
            return host
    return value


def get_client_ip() -> str:
    """Real client IP for this deployment's topology (see
    _trusted_proxy_hops for the full citation): direct Cloud Run, one trusted
    proxy hop, so the value TRUSTED_PROXY_HOPS positions from the right of
    X-Forwarded-For is Google-appended and trustworthy -- values to its left
    (including position 0, the traditional "first XFF value") are
    client-supplied and spoofable, never trusted.

    Falls back to request.remote_addr -- deliberately, not a shared constant
    that would merge all callers into one rate-limit bucket -- when the
    header is absent, empty, or has fewer values than the configured trusted
    hop count (a malformed/truncated header we can't safely trust any part
    of). remote_addr itself only reaches "unknown" if neither is available
    (e.g. some non-HTTP test contexts), which intentionally is NOT a shared
    bucket in production: Cloud Run always sets X-Forwarded-For for real
    internet traffic, so that branch is not expected to be hit there.
    """
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        parts = [_strip_port(p.strip()) for p in xff.split(",") if p.strip()]
        hops = _trusted_proxy_hops()
        if len(parts) >= hops:
            return parts[-hops]
        logger.warning(
            "rate_limit: X-Forwarded-For has fewer values (%d) than trusted proxy hops (%d); "
            "falling back to remote_addr rather than trusting an unverified hop",
            len(parts), hops,
        )
    return request.remote_addr or "unknown"


def _hash_ip(ip: str) -> str:
    """HMAC-SHA256 the client IP, truncated to 20 hex chars, for use as (part
    of) a Firestore document ID.

    If RATE_LIMIT_SALT is unset, this used to silently fall back to an
    empty HMAC key -- i.e. unsalted SHA-256 over the IP. That's trivially
    reversible against the small IPv4 address space (rainbow-table/brute-
    force), turning rate_limits' document IDs into an effectively
    plaintext IP log (edge-case review Finding 9). Rather than fail the
    whole feature closed on a missing env var (rate_limit's own
    design deliberately fails OPEN on any check_rate_limit() error --
    availability over strict enforcement for a free-feature abuse guard, not
    a security boundary), fall back to a random, process-local salt: it
    still isn't guessable/reversible externally, at the cost of not being
    stable across process restarts/instances (a known, accepted limitation
    of this fallback -- rate-limit buckets for the same IP may not match
    between instances until the env var is set). Logs at ERROR (not WARNING)
    since this is a misconfiguration that must be fixed in production, not a
    routine/expected condition.
    """
    secret = os.environ.get("RATE_LIMIT_SALT", "")
    if secret:
        key = secret.encode()
    else:
        logger.error(
            "rate_limit: RATE_LIMIT_SALT is not set in this environment -- "
            "falling back to a random, process-local salt so IP hashes are not a "
            "trivially reversible unsalted SHA-256. Set RATE_LIMIT_SALT in "
            "production; until then, rate-limit buckets for the same IP will not "
            "necessarily match across process restarts/instances."
        )
        key = _FALLBACK_IP_HASH_SALT
    return hmac.new(key, ip.encode(), hashlib.sha256).hexdigest()[:20]


@firestore.transactional
def _check_and_increment(transaction, ref, limit: int, now, expires_at) -> bool:
    snapshot = ref.get(transaction=transaction)
    count = snapshot.get("count") if snapshot.exists else 0
    if count >= limit:
        return False
    transaction.set(ref, {"count": count + 1, "updated_at": now, "expires_at": expires_at}, merge=True)
    return True


def check_rate_limit() -> bool:
    """Returns True if this request is within budget (and has been counted),
    False if the caller's IP is over the hourly limit.

    Known, accepted limitation: this is a fixed wall-clock-hour window (keyed
    by `window_start`), not a sliding one. An IP that sends 5 requests just
    before :00 and 5 more just after can get 10 requests through within
    seconds of an hour boundary. A true sliding window would need either a
    second Firestore read per request (a previous-window lookup, doubling
    read cost) or additional fields on this document (a storage-shape
    change) -- both outside this fix's scope, which is to keep the existing
    single-document-per-window shape and read/write cost profile unchanged.
    Reviewed and deliberately deferred rather than fixed here."""
    ip_hash = _hash_ip(get_client_ip())
    now = datetime.now(timezone.utc)
    window_start = now.replace(minute=0, second=0, microsecond=0)
    window_end = window_start + timedelta(hours=1)
    # Counter TTL buffer: always in the future relative to window_end, so the
    # doc survives long enough for Firestore's TTL policy to reliably clean it up.
    doc_expires_at = window_end + timedelta(hours=Constants.Limits.RATE_LIMIT_COUNTER_TTL_HOURS)
    doc_id = f"{ip_hash}_{window_start.strftime('%Y%m%d%H')}"

    db = firestore_client()
    ref = db.collection(Constants.Limits.RATE_LIMIT_COLLECTION).document(doc_id)
    transaction = db.transaction()
    return _check_and_increment(transaction, ref, Constants.Limits.RATE_LIMIT_PER_IP_PER_HOUR, now, doc_expires_at)


def rate_limit(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method == "OPTIONS":     # let flask-cors attach preflight headers
            return "", 204
        try:
            allowed = check_rate_limit()
        except Exception:
            # Fail OPEN: a transient Firestore hiccup should not take down the
            # app for everyone. Availability > strict enforcement here —
            # this is abuse prevention on a free feature, not a security boundary.
            logger.exception("rate_limit: check_rate_limit failed; allowing request")
            allowed = True
        if not allowed:
            return make_error_response(ErrorCode.RATE_LIMIT_EXCEEDED, request.path).to_dict(), 429
        return f(*args, **kwargs)
    return wrapper
