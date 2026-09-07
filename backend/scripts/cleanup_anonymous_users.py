"""scripts/cleanup_anonymous_users.py — Cloud Run Job entrypoint.

Invoked daily by Cloud Scheduler via the Cloud Run Jobs `:run` API.
Reads DRY_RUN from the environment so the job can be deployed once in
dry-run mode and flipped to live later without a code change (mirrors the
WORKER_VERIFY_OIDC kill-switch pattern in utils/firebase.py).
"""
import logging
import os
import sys

from utils.firebase import initialize_firebase
from observability import setup_logging
from utils.markers.markers import Markers
from services.retention import cleanup_anonymous_users

setup_logging()
logger = logging.getLogger(__name__)


def _dry_run_from_env() -> bool:
    return os.environ.get("RETENTION_DRY_RUN", "true").lower() not in ("false", "0", "no")


def main() -> int:
    initialize_firebase()
    dry_run = _dry_run_from_env()

    def _run(scope):
        summary = cleanup_anonymous_users(dry_run=dry_run)
        scope.add_many({
            "scanned": summary.scanned,
            "matched": summary.matched,
            "deleted": summary.deleted,
            "delete_errors": summary.delete_errors,
            "dry_run": summary.dry_run,
        })
        return summary

    summary = Markers.Retention.AnonUserCleanup.execute(_run)
    if summary.delete_errors:
        logger.warning("retention: completed with %d delete errors — see prior warnings", summary.delete_errors)
    return 0  # non-zero would trigger a Cloud Run Job retry; partial failure is not fatal


if __name__ == "__main__":
    sys.exit(main())
