# dashboard/api_kepler_heatmap.py
"""
Replacement for kepler_heatmap_data in api_kepler.py.

Drop-in: same URL, same response schema, reads from ThreatEventGrid
instead of running live aggregation against ThreatEvent.

Wire up in urls.py:
    from .api_kepler_heatmap import kepler_heatmap_data
    path("api/threats/kepler/heatmap/", kepler_heatmap_data),
"""
import logging
from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET

from core.auth import api_auth_required
from .models import ThreatEventGrid

logger = logging.getLogger("obsidian.api.heatmap")

HEATMAP_FIELDS = [
    {"name": "lat",         "format": "", "type": "real"},
    {"name": "lon",         "format": "", "type": "real"},
    {"name": "weight",      "format": "", "type": "real"},
    {"name": "severity",    "format": "", "type": "string"},
    {"name": "country",     "format": "", "type": "string"},
    {"name": "actor",       "format": "", "type": "string"},
    {"name": "event_count", "format": "", "type": "integer"},
]


def _parse_hours(request, default=720, max_hours=8760):
    try:
        return min(max(int(request.GET.get("hours", default)), 1), max_hours)
    except (ValueError, TypeError):
        return default


@api_auth_required
@require_GET
@cache_page(60 * 5)  # 5-minute HTTP cache layer; grid itself refreshes every 10 min
def kepler_heatmap_data(request):
    """
    Serve pre-aggregated heatmap data from ThreatEventGrid.

    Query params:
        hours     int     Time window in hours (default 720 = 30 days)
        severity  str     Comma-separated severity filter
        actor     str     Actor name substring

    Falls back gracefully if grid is empty (e.g. first deploy before first
    Celery run) — returns empty rows with correct schema rather than 500.
    """
    hours    = _parse_hours(request)
    severity = request.GET.get("severity", "").strip()
    actor_q  = request.GET.get("actor", "").strip()

    since = timezone.now() - timedelta(hours=hours)

    qs = ThreatEventGrid.objects.filter(bucket_hour__gte=since)

    if severity:
        sev_list = [s.strip() for s in severity.split(",") if s.strip()]
        qs = qs.filter(severity__in=sev_list)

    if actor_q:
        qs = qs.filter(actor_name__icontains=actor_q)

    # Collapse grid cells that share (lat, lon, severity) across multiple hours
    # into a single heatmap point by summing event_count and taking max weight.
    # This reduces the payload to KeplerGL without losing density signal.
    from django.db.models import Sum
    collapsed = (
        qs
        .values("grid_lat", "grid_lon", "severity", "actor_name", "country")
        .annotate(
            total_events=Sum("event_count"),
            total_weight=Sum("weight"),
        )
        .order_by("-total_weight")
        [:5000]  # cap at 5000 heatmap cells — KeplerGL renders comfortably
    )

    rows = []
    for cell in collapsed:
        rows.append([
            float(cell["grid_lat"]),
            float(cell["grid_lon"]),
            float(cell["total_weight"]),
            cell["severity"],
            cell["country"] or "",
            cell["actor_name"] or "Unknown",
            cell["total_events"],
        ])

    # Warn operators if grid appears stale (no data at all)
    if not rows:
        logger.warning(
            "heatmap_grid_empty",
            extra={"hours": hours, "note": "Grid may not have been populated yet"},
        )

    return JsonResponse({
        "fields": HEATMAP_FIELDS,
        "rows":   rows,
        "count":  len(rows),
        "meta": {
            "hours":        hours,
            "severity":     severity,
            "actor":        actor_q,
            "source":       "pre_aggregated_grid",
            "grid_size":    "1 degree (~111km)",
            "generated_at": timezone.now().isoformat(),
        },
    })
