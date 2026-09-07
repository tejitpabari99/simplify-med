"""services/retention.py — anonymous Firebase Auth account cleanup.

Deletes anonymous Auth accounts older than a configurable age. Safety-critical:
the predicate below must never match a real (password/other-provider) account.
Called by scripts/cleanup_anonymous_users.py, which is the Cloud Run Job's
entrypoint; kept here (not in scripts/) so it's importable and mockable from
backend/tests/services/ like every other service module.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from firebase_admin import auth

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_HOURS = 24
DEFAULT_PAGE_SIZE = 1000          # auth.list_users' own page-size ceiling


@dataclass
class CleanupSummary:
    scanned: int = 0
    matched: int = 0
    deleted: int = 0
    delete_errors: int = 0
    pages: int = 0
    dry_run: bool = False
    error_uids: list[str] = field(default_factory=list)


def _is_anonymous(user: "auth.ExportedUserRecord") -> bool:
    """True only if the account has no linked sign-in providers. Anonymous
    accounts (signInAnonymously — this app's only auth method) have
    provider_data == [] by Firebase's own design. A real account with every
    provider manually unlinked via the Admin SDK would false-positive here;
    there's no other signal to distinguish that case. Accepted risk, no
    additional guard (decided 2026-09-05)."""
    return len(user.provider_data) == 0


def _older_than(user: "auth.ExportedUserRecord", cutoff_ms: int) -> bool:
    return user.user_metadata.creation_timestamp < cutoff_ms


def cleanup_anonymous_users(
    *,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    dry_run: bool = True,
    now: datetime | None = None,
) -> CleanupSummary:
    """Delete (or, if dry_run, just count) anonymous accounts older than
    max_age_hours. Paginates list_users at 1000/page; batches delete_users at
    <=1000 uids/call (one call per page, since a page is already <=1000). No
    persisted cursor -- a full re-sweep each run is simpler than tracking
    resumption state and pagination naturally bounds the cost."""
    now = now or datetime.now(timezone.utc)
    cutoff_ms = int((now - timedelta(hours=max_age_hours)).timestamp() * 1000)
    summary = CleanupSummary(dry_run=dry_run)

    page = auth.list_users(max_results=DEFAULT_PAGE_SIZE)
    while page:
        summary.pages += 1
        summary.scanned += len(page.users)
        matched_uids = [
            u.uid for u in page.users
            if _is_anonymous(u) and _older_than(u, cutoff_ms)
        ]
        summary.matched += len(matched_uids)

        if matched_uids and not dry_run:
            result = auth.delete_users(matched_uids)
            summary.deleted += len(matched_uids) - len(result.errors)
            summary.delete_errors += len(result.errors)
            for err in result.errors:
                summary.error_uids.append(matched_uids[err.index])
                logger.warning(
                    "retention: failed to delete anon user index=%d reason=%s",
                    err.index, err.reason,
                )
        elif matched_uids:
            summary.deleted += len(matched_uids)  # dry-run: "would delete"

        page = page.get_next_page()

    logger.info(
        "retention: anon user cleanup complete scanned=%d matched=%d deleted=%d "
        "errors=%d pages=%d dry_run=%s",
        summary.scanned, summary.matched, summary.deleted,
        summary.delete_errors, summary.pages, summary.dry_run,
    )
    return summary
