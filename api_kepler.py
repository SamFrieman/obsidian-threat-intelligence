# dashboard/api_kepler.py
"""
KeplerGL-optimized data endpoints.

Separate from api.py to keep concerns isolated. These endpoints return
KeplerGL's native tabular format (fields[] + rows[][]) rather than the
GeoJSON/dict format used by the existing Leaflet map.

Routes (add to dashboard/urls.py):
    path('api/threats/kepler/',   api_kepler.kepler_threat_data,   name='api-kepler-threats'),
    path('api/threats/kepler/heatmap/', api_kepler.kepler_heatmap_data, name='api-kepler-heatmap'),
    path('api/actors/kepler/',    api_kepler.kepler_actor_density,  name='api-kepler-actors'),
"""
import logging
from datetime import timedelta

from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.views.decorators.cache import cache_page
from django.utils import timezone

from .models import ThreatEvent, IOC, ThreatActor

logger = logging.getLogger(__name__)

# ── Severity mapping ────────────────────────────────────────────────
SEV_SCORE = {
    'critical': 4,
    'high':     3,
    'medium':   2,
    'low':      1,
    'info':     0,
}

# Neutral intelligence-palette colors (matches new design system)
SEV_COLOR_HEX = {
    'critical': '#ef4444',
    'high':     '#f97316',
    'medium':   '#eab308',
    'low':      '#22c55e',
    'info':     '#3b82f6',
}

# KeplerGL expects colors as [R, G, B] arrays for colorRange
SEV_COLOR_RGB = {
    'critical': [239, 68,  68],
    'high':     [249, 115, 22],
    'medium':   [234, 179,  8],
    'low':      [ 34, 197, 94],
    'info':     [ 59, 130, 246],
}

# ── Field schema ────────────────────────────────────────────────────
THREAT_FIELDS = [
    {'name': 'id',             'format': '',                      'type': 'integer'},
    {'name': 'lat',            'format': '',                      'type': 'real'},
    {'name': 'lon',            'format': '',                      'type': 'real'},
    {'name': 'severity',       'format': '',                      'type': 'string'},
    {'name': 'severity_score', 'format': '',                      'type': 'integer'},
    {'name': 'title',          'format': '',                      'type': 'string'},
    {'name': 'description',    'format': '',                      'type': 'string'},
    {'name': 'country',        'format': '',                      'type': 'string'},
    {'name': 'city',           'format': '',                      'type': 'string'},
    {'name': 'source',         'format': '',                      'type': 'string'},
    {'name': 'actor',          'format': '',                      'type': 'string'},
    # timestamp field enables KeplerGL's time animation layer
    {'name': 'timestamp',      'format': 'YYYY-MM-DDTHH:mm:ssZ', 'type': 'timestamp'},
    {'name': 'epoch_ms',       'format': '',                      'type': 'integer'},
]

HEATMAP_FIELDS = [
    {'name': 'lat',            'format': '', 'type': 'real'},
    {'name': 'lon',            'format': '', 'type': 'real'},
    {'name': 'weight',         'format': '', 'type': 'real'},
    {'name': 'severity',       'format': '', 'type': 'string'},
    {'name': 'country',        'format': '', 'type': 'string'},
    {'name': 'actor',          'format': '', 'type': 'string'},
    {'name': 'event_count',    'format': '', 'type': 'integer'},
]


def _parse_hours(request, default=168, max_hours=8760):
    """Parse ?hours= param safely. Default 7 days, max 1 year."""
    try:
        return min(max(int(request.GET.get('hours', default)), 1), max_hours)
    except (ValueError, TypeError):
        return default


def _parse_limit(request, default=10000, maximum=50000):
    """Parse ?limit= param safely."""
    try:
        return min(max(int(request.GET.get('limit', default)), 1), maximum)
    except (ValueError, TypeError):
        return default


def _parse_bbox(request):
    """
    Parse ?bbox=minLon,minLat,maxLon,maxLat for spatial filtering.
    Returns None if not provided or malformed.
    """
    bbox_str = request.GET.get('bbox', '')
    if not bbox_str:
        return None
    try:
        parts = [float(x) for x in bbox_str.split(',')]
        if len(parts) != 4:
            return None
        min_lon, min_lat, max_lon, max_lat = parts
        return min_lon, min_lat, max_lon, max_lat
    except (ValueError, TypeError):
        return None


@require_GET
def kepler_threat_data(request):
    """
    KeplerGL-optimized threat event data.

    Query params:
        hours       int    Time window in hours (default 168 = 7 days, max 8760 = 1 year)
        severity    str    Comma-separated: critical,high,medium,low,info
        actor       str    Actor name substring filter
        source      str    Feed source substring filter
        limit       int    Max rows (default 10000, max 50000)
        bbox        str    Spatial filter: minLon,minLat,maxLon,maxLat

    Returns KeplerGL tabular format:
        {fields: [...], rows: [...], count: int, meta: {...}}
    """
    hours     = _parse_hours(request)
    limit     = _parse_limit(request)
    severity  = request.GET.get('severity', '').strip()
    actor_q   = request.GET.get('actor', '').strip()
    source_q  = request.GET.get('source', '').strip()
    bbox      = _parse_bbox(request)

    since = timezone.now() - timedelta(hours=hours)

    qs = ThreatEvent.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
        event_date__gte=since,
    ).select_related('actor')

    if severity:
        sev_list = [s.strip() for s in severity.split(',') if s.strip()]
        qs = qs.filter(severity__in=sev_list)

    if actor_q:
        qs = qs.filter(actor__name__icontains=actor_q)

    if source_q:
        qs = qs.filter(source__icontains=source_q)

    if bbox:
        min_lon, min_lat, max_lon, max_lat = bbox
        qs = qs.filter(
            latitude__gte=min_lat, latitude__lte=max_lat,
            longitude__gte=min_lon, longitude__lte=max_lon,
        )

    # Use .values() to avoid ORM object instantiation overhead
    fields_wanted = (
        'id', 'title', 'description', 'severity', 'event_date',
        'latitude', 'longitude', 'country', 'city', 'source',
        'actor__name',
    )

    # order_by on event_date DESC so most recent events take priority when limit is hit
    records = (
        qs.order_by('-event_date')
        .values(*fields_wanted)
        [:limit]
    )

    rows = []
    for r in records:
        sev = r['severity'] or 'info'
        rows.append([
            r['id'],
            r['latitude'],
            r['longitude'],
            sev,
            SEV_SCORE.get(sev, 0),
            r['title'] or '',
            (r['description'] or '')[:200],   # truncate for payload size
            r['country'] or '',
            r['city'] or '',
            r['source'] or '',
            r['actor__name'] or 'Unknown',
            r['event_date'].strftime('%Y-%m-%dT%H:%M:%SZ'),
            int(r['event_date'].timestamp() * 1000),
        ])

    return JsonResponse({
        'fields': THREAT_FIELDS,
        'rows':   rows,
        'count':  len(rows),
        'meta': {
            'hours':    hours,
            'severity': severity,
            'actor':    actor_q,
            'source':   source_q,
            'bbox':     bbox,
            'limit':    limit,
            'generated_at': timezone.now().isoformat(),
        },
    })


@require_GET
@cache_page(60 * 5)  # Cache for 5 minutes — heatmap changes slowly
def kepler_heatmap_data(request):
    """
    Aggregated geographic density data for KeplerGL heatmap layer.

    Unlike kepler_threat_data which returns one row per event, this
    endpoint aggregates events to a ~1-degree grid cell to reduce
    payload size for large datasets.

    Returns cells weighted by:
        - Event count in that grid cell
        - Maximum severity score in that cell
        - Combined weight = count × max_severity_score
    """
    hours = _parse_hours(request, default=720)  # default 30 days for heatmap
    severity = request.GET.get('severity', '').strip()
    actor_q  = request.GET.get('actor', '').strip()

    since = timezone.now() - timedelta(hours=hours)

    qs = ThreatEvent.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
        event_date__gte=since,
    )

    if severity:
        qs = qs.filter(severity__in=[s.strip() for s in severity.split(',') if s.strip()])
    if actor_q:
        qs = qs.filter(actor__name__icontains=actor_q)

    # Aggregate to 1-degree grid cells using database-level rounding
    # This dramatically reduces row count for large datasets
    from django.db.models import Count, Max, F
    from django.db.models.functions import Round

    grid = (
        qs
        .annotate(
            grid_lat=Round(F('latitude'),  0),
            grid_lon=Round(F('longitude'), 0),
        )
        .values('grid_lat', 'grid_lon', 'severity', 'actor__name', 'country')
        .annotate(event_count=Count('id'))
        .order_by('-event_count')
        [:5000]  # max 5000 grid cells
    )

    rows = []
    for cell in grid:
        sev = cell['severity'] or 'info'
        count = cell['event_count']
        weight = count * SEV_SCORE.get(sev, 1)
        rows.append([
            float(cell['grid_lat']),
            float(cell['grid_lon']),
            float(weight),
            sev,
            cell['country'] or '',
            cell['actor__name'] or 'Unknown',
            count,
        ])

    return JsonResponse({
        'fields': HEATMAP_FIELDS,
        'rows':   rows,
        'count':  len(rows),
        'meta': {
            'hours':       hours,
            'severity':    severity,
            'actor':       actor_q,
            'grid_size':   '1 degree (~111km)',
            'generated_at': timezone.now().isoformat(),
        },
    })


@require_GET
@cache_page(60 * 15)  # 15-minute cache — actor data is slow-changing
def kepler_actor_density(request):
    """
    Actor-grouped geographic density for overlay layer.

    Returns one row per actor per country, weighted by their IOC count.
    Used to build the actor-frequency correlation view in KeplerGL.
    """
    from django.db.models import Count, Avg

    qs = (
        IOC.objects
        .filter(
            is_active=True,
            latitude__isnull=False,
            longitude__isnull=False,
            actor__isnull=False,
        )
        .values('actor__name', 'country', 'severity')
        .annotate(
            ioc_count=Count('id'),
            avg_lat=Avg('latitude'),
            avg_lon=Avg('longitude'),
            avg_confidence=Avg('confidence'),
        )
        .order_by('-ioc_count')
        [:2000]
    )

    fields = [
        {'name': 'actor',       'format': '', 'type': 'string'},
        {'name': 'country',     'format': '', 'type': 'string'},
        {'name': 'severity',    'format': '', 'type': 'string'},
        {'name': 'ioc_count',   'format': '', 'type': 'integer'},
        {'name': 'weight',      'format': '', 'type': 'real'},
        {'name': 'lat',         'format': '', 'type': 'real'},
        {'name': 'lon',         'format': '', 'type': 'real'},
        {'name': 'confidence',  'format': '', 'type': 'real'},
    ]

    rows = []
    for row in qs:
        sev = row['severity'] or 'info'
        weight = row['ioc_count'] * SEV_SCORE.get(sev, 1)
        rows.append([
            row['actor__name'] or 'Unknown',
            row['country'] or '',
            sev,
            row['ioc_count'],
            float(weight),
            float(row['avg_lat']),
            float(row['avg_lon']),
            float(row['avg_confidence'] or 0),
        ])

    return JsonResponse({
        'fields': fields,
        'rows':   rows,
        'count':  len(rows),
    })
