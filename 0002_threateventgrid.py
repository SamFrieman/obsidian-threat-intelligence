# dashboard/migrations/0002_threateventgrid.py
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        # Replace with your actual latest migration name
        ("dashboard", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ThreatEventGrid",
            fields=[
                ("id",          models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("grid_lat",    models.DecimalField(db_index=True, decimal_places=0, max_digits=5)),
                ("grid_lon",    models.DecimalField(db_index=True, decimal_places=0, max_digits=6)),
                ("bucket_hour", models.DateTimeField(db_index=True)),
                ("severity",    models.CharField(max_length=16)),
                ("actor_name",  models.CharField(blank=True, max_length=200)),
                ("country",     models.CharField(blank=True, max_length=100)),
                ("event_count", models.PositiveIntegerField(default=0)),
                ("max_sev_score", models.SmallIntegerField(default=0)),
                ("weight",      models.FloatField(default=0.0)),
            ],
        ),
        migrations.AlterUniqueTogether(
            name="threateventgrid",
            unique_together={("grid_lat", "grid_lon", "bucket_hour", "severity", "actor_name")},
        ),
        migrations.AddIndex(
            model_name="threateventgrid",
            index=models.Index(
                fields=["bucket_hour", "grid_lat", "grid_lon"],
                name="ix_grid_hour_cell",
            ),
        ),
        migrations.AddIndex(
            model_name="threateventgrid",
            index=models.Index(
                fields=["bucket_hour", "severity"],
                name="ix_grid_hour_sev",
            ),
        ),
        # ── Raw SQL: additional indexes on ThreatEvent for heatmap queries ──
        # CONCURRENTLY cannot run inside a transaction. Apply manually:
        #
        #   python manage.py dbshell
        #   CREATE INDEX CONCURRENTLY ix_te_date_geo
        #     ON dashboard_threatevent (event_date DESC)
        #     WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
        #
        #   CREATE INDEX CONCURRENTLY ix_te_date_sev_geo
        #     ON dashboard_threatevent (event_date DESC, severity)
        #     WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
        #
        # These are listed here as documentation. Do NOT run them inside
        # a migration transaction (Django wraps migrations in transactions by default).
    ]
