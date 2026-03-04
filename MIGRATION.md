# OBSIDIAN — Stage 03 Migration Plan

## Phase 1: Design System (0 risk, 1 day)

1. Add Google Fonts import to dashboard template generator:
   ```html
   <link rel="preconnect" href="https://fonts.googleapis.com">
   <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
   <link rel="stylesheet" href="{% static 'css/design_system.css' %}">
   ```
2. Add `app-shell`, `topbar`, `sidebar`, `main`, `kpi-row`, `content-split`,
   `feed-panel` classes to the dashboard template generator's HTML structure.
3. Remove old neon-glow CSS (`text-shadow`, `box-shadow` glow rules, `#00ffcc` colors).
4. Test: Open dashboard — layout should be identical with neutral palette.

## Phase 2: KeplerGL Backend (low risk, 1 day)

1. Add to `dashboard/urls.py`:
   ```python
   from . import api_kepler, views_admin
   path('api/threats/kepler/',          api_kepler.kepler_threat_data),
   path('api/threats/kepler/heatmap/',  api_kepler.kepler_heatmap_data),
   path('api/actors/kepler/',           api_kepler.kepler_actor_density),
   path('admin/deps/scan/',             views_admin.dep_scan),
   path('admin/deps/plan/',             views_admin.dep_plan),
   ```
2. Add DB indexes to a new migration:
   ```python
   # dashboard/migrations/0XXX_add_kepler_indexes.py
   from django.db import migrations
   class Migration(migrations.Migration):
       operations = [
           migrations.RunSQL(
               "CREATE INDEX IF NOT EXISTS ix_threatevent_date_sev "
               "ON dashboard_threatevent (event_date, severity) "
               "WHERE latitude IS NOT NULL AND longitude IS NOT NULL;",
               reverse_sql="DROP INDEX IF EXISTS ix_threatevent_date_sev;"
           ),
       ]
   ```
3. Test endpoint: `curl http://localhost:8000/api/threats/kepler/?hours=24`
   Verify fields[] and rows[] structure.

## Phase 3: KeplerGL Frontend (medium risk, 2-3 days)

1. Install Node.js >= 18 (dev/build only):
   ```bash
   node -v   # verify
   ```
2. Build the microfrontend:
   ```bash
   cd frontend/
   npm install
   npm run build
   # Output: ../static/kepler/bundle.js
   ```
3. Add to dashboard template generator (inside `<body>`):
   ```html
   <!-- KeplerGL mount point -->
   <div id="kepler-root"
        data-api-base="/api"
        data-height="600"
        data-poll-interval="60000">
   </div>
   <!-- KeplerGL bundle (built by npm run build) -->
   <script src="{% static 'kepler/bundle.js' %}"></script>
   ```
4. Add `static/kepler/` to `.gitignore`:
   ```
   static/kepler/
   ```
   The built bundle is generated at deploy time, not committed.
5. Update `deploy.sh` to run `npm run build` before `collectstatic`:
   ```bash
   cd frontend && npm run build && cd ..
   python manage.py collectstatic --noinput
   ```
6. Enable feature flag `?map=kepler` to test alongside Leaflet.
7. Validate: open dashboard, verify map loads, points render, filters work.

## Phase 4: Leaflet Removal (after Phase 3 validation, low risk)

1. Remove from dashboard template generator:
   - Leaflet CDN `<link>` and `<script>` tags
   - `makeMarkerIcon()`, `renderMap1()`, `initMap2()` functions
   - `buildMarkerGroups()`, `toggleLayer()`, `filterMapSeverity()`
   - `map1`, `map2`, `map1Layers`, `map2Layers` variables
   - `const sevCfg` (Leaflet version)
2. Remove from `static/`: any local leaflet CSS/JS files.
3. Test thoroughly: map view, layer toggles, severity filter.

## Phase 5: Dependency Scanner (no risk, 1 day)

1. Confirm `views_admin.py` routes are registered (from Phase 2).
2. Add nav item to sidebar:
   ```html
   <button class="nav-item" data-view="admin-deps">
     <span class="nav-item__label">Dep Scanner</span>
   </button>
   ```
3. Add admin deps JS panel to dashboard (reads `is_staff` from template context).
4. Set up GitHub Actions:
   - Add `.github/workflows/dependency_check.yml` to repo
   - Ensure test suite runs (`python manage.py test`)
   - First run: trigger manually from GitHub Actions UI

## Rollback Plan

Each phase is independently reversible:
- Phase 1: Revert CSS file link in template generator
- Phase 2: Comment out URL patterns
- Phase 3: Remove `<script>` tag and `kepler-root` div
- Phase 4: Re-add Leaflet tags (backed up in git)
- Phase 5: Remove URL patterns (no data changes)
