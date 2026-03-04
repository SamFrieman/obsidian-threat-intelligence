# core/metrics.py
"""
Prometheus metrics registry for OBSIDIAN.

Usage in views:
    from core.metrics import api_latency, kepler_row_count
    with api_latency.labels(endpoint="threats").time():
        ...  your view logic
    kepler_row_count.labels(dataset="threats").set(len(rows))

Exposed at /metrics — restricted to internal network in Nginx config.
"""
from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, REGISTRY

# ── API metrics ───────────────────────────────────────────────────────

api_requests_total = Counter(
    "obsidian_api_requests_total",
    "Total API requests",
    ["method", "endpoint", "status"],
)

api_latency = Histogram(
    "obsidian_api_duration_seconds",
    "API endpoint latency",
    ["endpoint"],
    buckets=[0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# ── Data metrics ──────────────────────────────────────────────────────

kepler_row_count = Gauge(
    "obsidian_kepler_dataset_rows",
    "Rows in last KeplerGL API response",
    ["dataset"],
)

threat_events_ingested = Counter(
    "obsidian_threat_events_ingested_total",
    "Threat events ingested from feeds",
    ["source", "severity"],
)

feed_ingest_errors = Counter(
    "obsidian_feed_ingest_errors_total",
    "Feed ingestion errors",
    ["source", "error_type"],
)

active_feeds = Gauge(
    "obsidian_active_feeds_total",
    "Number of currently active feed sources",
)

# ── Grid refresh metrics ──────────────────────────────────────────────

grid_refresh_duration = Histogram(
    "obsidian_grid_refresh_duration_seconds",
    "Heatmap grid refresh task duration",
    ["refresh_type"],
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

grid_cells_upserted = Counter(
    "obsidian_grid_cells_upserted_total",
    "Grid cells written during heatmap refresh",
    ["refresh_type"],
)

# ── Auth metrics ──────────────────────────────────────────────────────

auth_failures = Counter(
    "obsidian_auth_failures_total",
    "API authentication failures",
    ["reason"],   # "missing_token", "invalid_token", "scope_denied"
)
