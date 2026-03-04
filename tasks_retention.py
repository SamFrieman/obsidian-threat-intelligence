# dashboard/tasks_retention.py
"""
Data retention enforcement task.

Deletes ThreatEvent rows older than THREAT_RETENTION_DAYS.
Also cleans stale ThreatEventGrid cells (bucket_hour beyond retention window).

Deletion strategy:
  Batched by primary key to avoid a single long-running DELETE that would
  hold row locks and block concurrent reads/writes.

  Batch size of 2000 is a safe default:
    - Each batch takes ~50–200ms on a healthy PG instance with the index
    - Short enough to not impact concurrent readers
    - Large enough to make progress quickly even at 1M row scale

Safety guards:
  1. Minimum retention floor (MIN_RETENTION_DAYS=7) prevents accidental
     total deletion from a misconfigured env var.
  2. dry_run=True mode logs what would be deleted without touching DB.
  3. Task logs before and after with counts — provides an audit trail.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

logger = logging.getLogger("obsidian.tasks.retention")

_MIN_RETENTION_DAYS = 7     # hard floor — never delete less than a week
_DEFAULT_RETENTION_DAYS = 365
_BATCH_SIZE = 2000


def _get_retention_days() -> int:
    raw = getattr(settings, "THREAT_RETENTION_DAYS", _DEFAULT_RETENTION_DAYS)
    try:
        days = int(raw)
    except (ValueError, TypeError):
        logger.error(
            "retention_config_invalid",
            extra={"raw_value": raw, "fallback": _DEFAULT_RETENTION_DAYS},
        )
        return _DEFAULT_RETENTION_DAYS

    if days < _MIN_RETENTION_DAYS:
        logger.warning(
            "retention_days_below_floor",
            extra={"configured": days, "enforced": _MIN_RETENTION_DAYS},
        )
        return _MIN_RETENTION_DAYS

    return days


@shared_task(
    name="dashboard.enforce_retention",
    ignore_result=True,
    soft_time_limit=900,   # 15 minutes soft
    time_limit=1080,       # 18 minutes hard kill
)
def enforce_retention(dry_run: bool = False):
    """
    Delete ThreatEvent and ThreatEventGrid rows beyond retention window.

    Args:
        dry_run: If True, count rows that would be deleted but do not delete.
                 Useful for testing config before first production run.

    Scheduled: daily at 03:00 UTC (off-peak).
    """
    retention_days = _get_retention_days()
    cutoff = timezone.now() - timedelta(days=retention_days)

    logger.info(
        "retention_task_started",
        extra={
            "retention_days": retention_days,
            "cutoff":         cutoff.isoformat(),
            "dry_run":        dry_run,
        },
    )

    event_deleted   = _delete_threat_events(cutoff, dry_run)
    grid_deleted    = _delete_grid_cells(cutoff, dry_run)

    logger.info(
        "retention_task_complete",
        extra={
            "events_deleted":    event_deleted,
            "grid_cells_deleted": grid_deleted,
            "retention_days":    retention_days,
            "dry_run":           dry_run,
        },
    )

    return {
        "events_deleted":    event_deleted,
        "grid_cells_deleted": grid_deleted,
        "cutoff":            cutoff.isoformat(),
        "dry_run":           dry_run,
    }


def _delete_threat_events(cutoff, dry_run: bool) -> int:
    """Batched deletion of ThreatEvent rows older than cutoff."""
    from .models import ThreatEvent

    if dry_run:
        count = ThreatEvent.objects.filter(event_date__lt=cutoff).count()
        logger.info(
            "retention_dry_run_events",
            extra={"would_delete": count, "cutoff": cutoff.isoformat()},
        )
        return count

    deleted_total = 0
    while True:
        # Fetch IDs first — avoids full table scan in DELETE on tables with
        # many retained rows. The PK lookup is O(log n) with the PK index.
        ids = list(
            ThreatEvent.objects
            .filter(event_date__lt=cutoff)
            .values_list("id", flat=True)
            .order_by("id")          # consistent ordering prevents thrashing
            [:_BATCH_SIZE]
        )
        if not ids:
            break

        with transaction.atomic():
            deleted, _ = ThreatEvent.objects.filter(id__in=ids).delete()

        deleted_total += deleted
        logger.debug(
            "retention_batch_deleted",
            extra={"model": "ThreatEvent", "batch_size": deleted, "total": deleted_total},
        )

    return deleted_total


def _delete_grid_cells(cutoff, dry_run: bool) -> int:
    """Delete ThreatEventGrid cells whose bucket_hour is beyond retention."""
    from .models import ThreatEventGrid

    if dry_run:
        count = ThreatEventGrid.objects.filter(bucket_hour__lt=cutoff).count()
        logger.info(
            "retention_dry_run_grid",
            extra={"would_delete": count},
        )
        return count

    deleted_total = 0
    while True:
        ids = list(
            ThreatEventGrid.objects
            .filter(bucket_hour__lt=cutoff)
            .values_list("id", flat=True)
            .order_by("id")
            [:_BATCH_SIZE]
        )
        if not ids:
            break

        with transaction.atomic():
            deleted, _ = ThreatEventGrid.objects.filter(id__in=ids).delete()

        deleted_total += deleted

    return deleted_total


# ── Celery Beat schedule — add to core/celery.py ─────────────────────
#
# "enforce-retention": {
#     "task":     "dashboard.enforce_retention",
#     "schedule": crontab(hour=3, minute=0),  # 03:00 UTC daily
#     "kwargs":   {"dry_run": False},
# },
