# dashboard/models_grid.py
# ADD to your existing models.py — do not replace.
"""
ThreatEventGrid: pre-aggregated 1-degree grid cells for heatmap layer.

Rationale for separate model vs materialised view:
  - Django migrations manage the table lifecycle
  - Celery task controls refresh timing and locking
  - update_or_create gives explicit upsert semantics
  - No PostgreSQL superuser privileges required (REFRESH MATERIALIZED VIEW needs CONCURRENTLY privilege)
"""
from django.db import models


class ThreatEventGrid(models.Model):
    """
    One row per (grid_lat, grid_lon, bucket_hour, severity, actor_name).
    Refreshed incrementally every 10 minutes by Celery task.
    Full rebuild runs weekly.
    """
    grid_lat      = models.DecimalField(max_digits=5,  decimal_places=0, db_index=True)
    grid_lon      = models.DecimalField(max_digits=6,  decimal_places=0, db_index=True)
    bucket_hour   = models.DateTimeField(db_index=True)   # truncated to hour
    severity      = models.CharField(max_length=16)
    actor_name    = models.CharField(max_length=200, blank=True)
    country       = models.CharField(max_length=100, blank=True)
    event_count   = models.PositiveIntegerField(default=0)
    max_sev_score = models.SmallIntegerField(default=0)
    weight        = models.FloatField(default=0.0)

    class Meta:
        unique_together = [
            ("grid_lat", "grid_lon", "bucket_hour", "severity", "actor_name")
        ]
        indexes = [
            # Primary heatmap query: time window over grid cells
            models.Index(fields=["bucket_hour", "grid_lat", "grid_lon"],
                         name="ix_grid_hour_cell"),
            # Severity filter on heatmap
            models.Index(fields=["bucket_hour", "severity"],
                         name="ix_grid_hour_sev"),
        ]

    def __str__(self):
        return (
            f"({self.grid_lat},{self.grid_lon}) "
            f"{self.bucket_hour:%Y-%m-%dT%H} "
            f"{self.severity} ×{self.event_count}"
        )
