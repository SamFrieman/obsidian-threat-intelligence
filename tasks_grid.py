# dashboard/tasks_grid.py
"""
Heatmap grid refresh tasks.

Two tasks:
  - refresh_heatmap_grid_incremental : runs every 10 min, covers last 2 hours
  - refresh_heatmap_grid_full        : runs weekly, rebuilds entire table

Locking strategy:
  Redis-based distributed lock (via cache.add — atomic on Redis).
  Prevents concurrent runs without requiring a separate advisory lock library.
  Lock is released in finally block and has a hard TTL of 5 minutes as a
  dead-lock guard in case the worker is killed mid-task.

Bulk upsert strategy:
  Uses Django 4.1+ bulk_create(update_conflicts=True) which maps to
  PostgreSQL's INSERT ... ON CONFLICT DO UPDATE.
  This is ~10× faster than N individual update_or_create() calls at scale.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, F, Max
from django.db.models.functions import Round, TruncHour
from django.utils import timezone

from .models import ThreatEvent, ThreatEventGrid

logger = logging.getLogger("obsidian.tasks.grid")

_LOCK_KEY = "lock:heatmap_grid_refresh"
_LOCK_TTL = 300  # 5 minutes — hard TTL prevents dead lock if worker dies

SEV_SCORE = {
    "critical": 4,
    "high":     3,
    "medium":   2,
    "low":      1,
    "info":     0,
}


def _acquire_lock() -> bool:
    """
    Atomic lock acquisition using cache.add (returns False if key exists).
    Redis SETNX semantics: only one caller wins.
    """
    return cache.add(_LOCK_KEY, "1", timeout=_LOCK_TTL)


def _release_lock():
    cache.delete(_LOCK_KEY)


def _aggregate_window(since, actor_filter: str = "") -> list[ThreatEventGrid]:
    """
    Aggregate ThreatEvent rows in the given time window into grid objects.
    Does NOT write to DB — returns a list of unsaved ThreatEventGrid instances.
    """
    qs = (
        ThreatEvent.objects
        .filter(
            event_date__gte=since,
            latitude__isnull=False,
            longitude__isnull=False,
        )
        .annotate(
            grid_lat=Round(F("latitude"),  0),
            grid_lon=Round(F("longitude"), 0),
            bucket_hour=TruncHour("event_date"),
        )
        .values("grid_lat", "grid_lon", "bucket_hour", "severity", "actor__name", "country")
        .annotate(
            event_count=Count("id"),
            max_sev=Max("severity_score"),
        )
        .order_by()  # Remove default ordering to avoid GROUP BY overhead
    )

    grid_objects = []
    for cell in qs.iterator(chunk_size=2000):
        sev = cell["severity"] or "info"
        max_sev = cell["max_sev"] or SEV_SCORE.get(sev, 0)
        grid_objects.append(ThreatEventGrid(
            grid_lat=cell["grid_lat"],
            grid_lon=cell["grid_lon"],
            bucket_hour=cell["bucket_hour"],
            severity=sev,
            actor_name=cell["actor__name"] or "",
            country=cell["country"] or "",
            event_count=cell["event_count"],
            max_sev_score=max_sev,
            weight=float(cell["event_count"]) * max_sev,
        ))

    return grid_objects


def _bulk_upsert_grid(objects: list[ThreatEventGrid]) -> dict:
    """
    Bulk upsert using PostgreSQL ON CONFLICT DO UPDATE.
    Batched in chunks of 500 to bound transaction size and memory.

    Returns: {"upserted": int, "batches": int, "errors": int}
    """
    if not objects:
        return {"upserted": 0, "batches": 0, "errors": 0}

    batch_size = 500
    total_upserted = 0
    total_errors = 0
    batches = 0

    update_fields = ["event_count", "max_sev_score", "weight", "country"]
    unique_fields = ["grid_lat", "grid_lon", "bucket_hour", "severity", "actor_name"]

    for i in range(0, len(objects), batch_size):
        batch = objects[i : i + batch_size]
        try:
            with transaction.atomic():
                ThreatEventGrid.objects.bulk_create(
                    batch,
                    update_conflicts=True,
                    update_fields=update_fields,
                    unique_fields=unique_fields,
                )
            total_upserted += len(batch)
            batches += 1
        except Exception as exc:
            logger.error(
                "grid_upsert_batch_failed",
                extra={"batch_index": i // batch_size, "error": str(exc)},
            )
            total_errors += 1

    return {"upserted": total_upserted, "batches": batches, "errors": total_errors}


@shared_task(
    name="dashboard.refresh_heatmap_grid_incremental",
    ignore_result=True,
    soft_time_limit=120,   # 2 min soft limit
    time_limit=180,        # 3 min hard kill
)
def refresh_heatmap_grid_incremental():
    """
    Incremental refresh: last 2 hours of data.
    Safe to run every 10 minutes.
    """
    if not _acquire_lock():
        logger.info("grid_refresh_skipped: lock held by another worker")
        return

    try:
        since = timezone.now() - timedelta(hours=2)
        objects = _aggregate_window(since)
        result = _bulk_upsert_grid(objects)
        logger.info(
            "grid_refresh_incremental_done",
            extra={"since_hours": 2, **result},
        )
    except Exception as exc:
        logger.exception("grid_refresh_incremental_failed: %s", exc)
    finally:
        _release_lock()


@shared_task(
    name="dashboard.refresh_heatmap_grid_full",
    ignore_result=True,
    soft_time_limit=600,   # 10 min soft limit
    time_limit=720,        # 12 min hard kill
)
def refresh_heatmap_grid_full():
    """
    Full rebuild: all retained data.
    Runs weekly. Clears stale grid cells first.
    Do NOT run this concurrently with incremental.
    """
    if not _acquire_lock():
        logger.info("grid_full_refresh_skipped: lock held")
        return

    try:
        logger.info("grid_full_refresh_started")
        start = timezone.now()

        # Delete all existing grid data before rebuild
        # Use batched delete to avoid a single long-running DELETE
        deleted = 0
        while True:
            ids = list(
                ThreatEventGrid.objects.values_list("id", flat=True)[:5000]
            )
            if not ids:
                break
            ThreatEventGrid.objects.filter(id__in=ids).delete()
            deleted += len(ids)

        # Rebuild from scratch
        since = timezone.now() - timedelta(days=365)
        objects = _aggregate_window(since)
        result = _bulk_upsert_grid(objects)

        elapsed = (timezone.now() - start).total_seconds()
        logger.info(
            "grid_full_refresh_done",
            extra={
                "deleted_cells": deleted,
                "elapsed_s": round(elapsed, 1),
                **result,
            },
        )
    except Exception as exc:
        logger.exception("grid_full_refresh_failed: %s", exc)
    finally:
        _release_lock()


# ── Celery Beat schedule — add to core/celery.py ─────────────────────
#
# from celery.schedules import crontab
#
# app.conf.beat_schedule = {
#     ...
#     "heatmap-grid-incremental": {
#         "task": "dashboard.refresh_heatmap_grid_incremental",
#         "schedule": 600,   # every 10 minutes
#     },
#     "heatmap-grid-full": {
#         "task": "dashboard.refresh_heatmap_grid_full",
#         "schedule": crontab(day_of_week="sunday", hour=2, minute=0),
#     },
# }
