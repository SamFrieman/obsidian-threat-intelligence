# INTEGRATION.md
# How to wire all five blockers into the existing codebase.
# Apply in order. Each step is independently reversible.

---

## File Inventory

```
core/
  auth.py                         ← NEW (Blocker 1)
  observability.py                ← NEW (Blocker 3)
  metrics.py                      ← NEW (Blocker 3)
  settings_observability_snippet  ← reference only, paste into settings.py

dashboard/
  models_apitoken.py              ← APPEND to models.py (Blocker 1)
  models_grid.py                  ← APPEND to models.py (Blocker 2)
  audit.py                        ← NEW (Blocker 5)
  api_kepler_heatmap.py           ← REPLACES kepler_heatmap_data in api_kepler.py (Blocker 2)
  tasks_grid.py                   ← NEW (Blocker 2)
  tasks_retention.py              ← NEW (Blocker 4)
  views_admin_patched.py          ← PATCH into views_admin.py (Blocker 5)
  migrations/
    0002_threateventgrid.py       ← NEW
    0003_auditlog.py              ← NEW
  tests/
    test_auth.py                  ← NEW (Blocker 1)
```

---

## Step 1 — Apply models (Blockers 1, 2, 5)

Append the contents of `models_apitoken.py`, `models_grid.py` to `dashboard/models.py`.
Append `AuditLog` class from `audit.py` to `dashboard/models.py`
  OR keep `audit.py` as a separate module (preferred — it's self-contained).

Run migrations:
```bash
python manage.py migrate dashboard 0002_threateventgrid
python manage.py migrate dashboard 0003_auditlog
```

If the PostgreSQL trigger in 0003 causes issues on your PG version, comment out
the `RunSQL` operation and apply the trigger SQL manually via `dbshell` after migration.

---

## Step 2 — Install new dependencies

```bash
pip install django-prometheus django-redis
# Add to requirements.txt:
# django-prometheus>=0.3.0
# django-redis>=5.4.0
```

---

## Step 3 — Update settings.py (Blocker 3)

From `settings_observability_snippet.py`:

1. Add `django_prometheus` to INSTALLED_APPS
2. Replace MIDDLEWARE list with the ordered version (tracing first, prometheus wrapping)
3. Add the LOGGING dict
4. Add SLOW_QUERY_LOG, SLOW_QUERY_THRESHOLD_MS
5. Add APP_VERSION = os.environ.get("APP_VERSION", "dev")

---

## Step 4 — Wire heatmap endpoint (Blocker 2)

In `dashboard/urls.py`, replace:
```python
path("api/threats/kepler/heatmap/", api_kepler.kepler_heatmap_data),
```
with:
```python
from .api_kepler_heatmap import kepler_heatmap_data as kepler_heatmap_data_v2
path("api/threats/kepler/heatmap/", kepler_heatmap_data_v2),
```

---

## Step 5 — Add @api_auth_required to all KeplerGL endpoints (Blocker 1)

In `dashboard/api_kepler.py`, add to the top:
```python
from core.auth import api_auth_required
```

Add decorator to each endpoint:
```python
@api_auth_required
@require_GET
def kepler_threat_data(request): ...

@api_auth_required
@require_GET
@cache_page(60 * 15)
def kepler_actor_density(request): ...
```

`kepler_heatmap_data` is already decorated in `api_kepler_heatmap.py`.

---

## Step 6 — Register signals for audit (Blocker 5)

In `dashboard/apps.py`:
```python
from django.apps import AppConfig

class DashboardConfig(AppConfig):
    name = "dashboard"

    def ready(self):
        import dashboard.audit  # noqa — registers @receiver decorators
```

In `dashboard/__init__.py`:
```python
default_app_config = "dashboard.apps.DashboardConfig"
```

---

## Step 7 — Register AuditLog in admin (Blocker 5)

In `dashboard/admin.py`, add:
```python
from django.contrib import admin
from .audit import AuditLog

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display   = ("ts", "action", "actor_username", "resource", "outcome", "ip_address")
    list_filter    = ("action", "outcome")
    search_fields  = ("actor_username", "action", "resource", "request_id")
    readonly_fields = (
        "ts", "actor", "actor_username", "action", "resource",
        "ip_address", "request_id", "detail", "outcome",
    )
    ordering = ("-ts",)

    def has_add_permission(self, request):             return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
```

---

## Step 8 — Add Celery tasks to Beat schedule (Blockers 2, 4)

In `core/celery.py` (or wherever you define beat_schedule):
```python
from celery.schedules import crontab

app.conf.beat_schedule.update({
    "heatmap-grid-incremental": {
        "task":     "dashboard.refresh_heatmap_grid_incremental",
        "schedule": 600,  # every 10 minutes
    },
    "heatmap-grid-full": {
        "task":     "dashboard.refresh_heatmap_grid_full",
        "schedule": crontab(day_of_week="sunday", hour=2, minute=0),
    },
    "enforce-retention": {
        "task":     "dashboard.enforce_retention",
        "schedule": crontab(hour=3, minute=0),
        "kwargs":   {"dry_run": False},
    },
})
```

Import tasks in `dashboard/__init__.py` or `celery.py` autodiscovery:
```python
# core/celery.py
app.autodiscover_tasks(["dashboard"])
```

---

## Step 9 — Add /metrics URL (Blocker 3)

In `core/urls.py`:
```python
from django_prometheus import exports
urlpatterns += [
    path("metrics", exports.ExportToDjangoView, name="prometheus-metrics"),
]
```

Verify Nginx config restricts `/metrics` to internal IPs.

---

## Step 10 — Create first API token

```bash
python manage.py shell
>>> from core.auth import generate_token, hash_token
>>> from dashboard.models import APIToken
>>> from django.contrib.auth import get_user_model
>>> User = get_user_model()
>>> u = User.objects.get(username="your_admin_user")
>>> plaintext = generate_token()
>>> APIToken.objects.create(user=u, name="dev", token_hash=hash_token(plaintext), scopes=["threats:read"])
>>> print(plaintext)   # Copy this — shown once
```

Test:
```bash
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/threats/kepler/?hours=24
```

---

## Step 11 — Run auth tests

```bash
python manage.py test dashboard.tests.test_auth --verbosity=2
```

All 11 tests should pass.

---

## Dry-run retention before first production run

```bash
python manage.py shell
>>> from dashboard.tasks_retention import enforce_retention
>>> enforce_retention(dry_run=True)
# Check logs for "would_delete" counts before enabling live deletion
```
