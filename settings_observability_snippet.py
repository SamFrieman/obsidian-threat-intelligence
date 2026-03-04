# core/settings_observability_snippet.py
"""
Paste these blocks into your core/settings.py.
Do not use this file directly — it's an annotated snippet.
"""

# ── 1. Add to INSTALLED_APPS ──────────────────────────────────────────
INSTALLED_APPS_ADD = [
    "django_prometheus",   # pip install django-prometheus
]

# ── 2. MIDDLEWARE — order is critical ────────────────────────────────
#
# Replace your existing MIDDLEWARE list with this structure:
MIDDLEWARE = [
    # Prometheus must wrap everything to measure all requests
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    # Tracing must be second so request_id is available to all below
    "core.observability.RequestTracingMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Slow query logging (only active when SLOW_QUERY_LOG=True)
    "core.observability.SlowQueryLoggingMiddleware",
    # Prometheus must also be last
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

# ── 3. LOGGING config ─────────────────────────────────────────────────
import os
_DEBUG = os.environ.get("DEBUG", "False") == "True"
_SLOW_QUERY_LOG = os.environ.get("SLOW_QUERY_LOG", "False") == "True"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "core.observability.StructuredJsonFormatter",
        },
        "simple": {
            "format": "%(levelname)-8s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            # Use simple formatter locally for readability; JSON in production
            "formatter": "simple" if _DEBUG else "json",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        # Application namespaces
        "obsidian": {
            "level": "DEBUG" if _DEBUG else "INFO",
            "propagate": True,
        },
        # Security events: NEVER suppress below WARNING
        "obsidian.security": {
            "level": "WARNING",
            "propagate": True,
        },
        # Access log: INFO in prod, DEBUG locally
        "obsidian.access": {
            "level": "DEBUG" if _DEBUG else "INFO",
            "propagate": True,
        },
        # DB query log: only when slow query logging is enabled
        "django.db.backends": {
            "level": "DEBUG" if (_DEBUG or _SLOW_QUERY_LOG) else "WARNING",
            "propagate": True,
        },
        # Suppress noisy Django internals
        "django.utils.autoreload": {
            "level": "WARNING",
            "propagate": False,
        },
    },
}

# ── 4. Slow query config ──────────────────────────────────────────────
SLOW_QUERY_LOG = _SLOW_QUERY_LOG
SLOW_QUERY_THRESHOLD_MS = int(os.environ.get("SLOW_QUERY_THRESHOLD_MS", "200"))

# ── 5. Add /metrics URL ───────────────────────────────────────────────
# In core/urls.py:
#
# from django_prometheus import exports
# urlpatterns += [
#     path("metrics", exports.ExportToDjangoView, name="prometheus-metrics"),
# ]
#
# Nginx: restrict /metrics to internal IPs (see nginx.conf in architecture doc)


# ── 6. Usage pattern in views ─────────────────────────────────────────
# import time
# from core.metrics import api_latency, kepler_row_count, api_requests_total
#
# @api_auth_required
# @require_GET
# def kepler_threat_data(request):
#     start = time.monotonic()
#     try:
#         # ... your logic ...
#         result = JsonResponse({...})
#         api_requests_total.labels(
#             method=request.method,
#             endpoint="kepler_threats",
#             status=200,
#         ).inc()
#         return result
#     except Exception:
#         api_requests_total.labels(
#             method=request.method,
#             endpoint="kepler_threats",
#             status=500,
#         ).inc()
#         raise
#     finally:
#         api_latency.labels(endpoint="kepler_threats").observe(
#             time.monotonic() - start
#         )
#         kepler_row_count.labels(dataset="threats").set(len(rows))
