# OBSIDIAN — Architecture Decision Record
## Stage 03 · KeplerGL + Redesign + Dependency Management

---

## 1. KeplerGL Integration — Architectural Decision

### Decision: React Microfrontend via Vite, Mounted into Django Template

**Rejected options:**

| Option | Reason Rejected |
|---|---|
| KeplerGL UMD bundle via CDN | ~10MB uncompressed, no tree-shaking, React version lock conflicts, no hot reload |
| Cartopy server-rendered PNG | Static. Cannot do real-time updates, hover tooltips, layer toggles, or time filtering. Wrong tool for interactive threat maps. |
| Full SPA decoupled from Django | Requires separate deploy pipeline, CORS management, and breaks the existing Django session/auth model |

**Chosen: React microfrontend (Vite) mounted into Django template**

A `<div id="kepler-root">` in `templates/dashboard.html` receives a compiled React bundle served as Django static files. The bundle loads from `/static/kepler/bundle.js`. Django renders the shell; React owns the map subtree.

This preserves:
- Django template rendering and context
- Existing REST API (`/api/threats/`)
- Session-based auth (cookies pass through naturally)
- `python manage.py collectstatic` deployment model
- No separate server or CORS config

Build output: `frontend/dist/` → `static/kepler/` via `vite build`.

---

## 2. Data Pipeline Architecture

### Query Strategy

```
ThreatEvent (PostgreSQL/SQLite)
  → .values() queryset (avoids ORM object overhead)
  → /api/threats/kepler/ endpoint
  → KeplerGL tabular format (fields[] + rows[][])
  → React component dispatch(addDataToMap)
  → KeplerGL internal WebGL renderer
```

### Why Tabular over GeoJSON for KeplerGL

KeplerGL is optimized for tabular data, not GeoJSON. Internally it converts GeoJSON to columnar arrays anyway. Sending tabular directly:
- ~40% smaller payload (no GeoJSON wrapper overhead per feature)
- Direct mapping to KeplerGL's internal data model
- Enables column-type inference (integer, real, timestamp, string)
- Required for time animation layer

### Index Strategy

Add to `dashboard/migrations/`:
```sql
-- ThreatEvent: composite index for the kepler endpoint's common filter pattern
CREATE INDEX ix_threatevent_date_sev ON dashboard_threatevent (event_date, severity)
  WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

-- IOC: source + last_seen for feed freshness queries
CREATE INDEX ix_ioc_source_seen ON dashboard_ioc (source, last_seen)
  WHERE is_active = true;
```

### Pagination / Streaming Strategy

For datasets up to ~50,000 points:
- Single request, `LIMIT 10000` default (KeplerGL renders ~10k points comfortably in WebGL)
- `?limit=` param, max 50000
- For > 50k: use `?bbox=minLon,minLat,maxLon,maxLat` spatial filter
- KeplerGL's viewport-aware decimation handles visual density automatically

For real-time updates: 60-second polling in the React component.  
WebSocket upgrade (Stage 05) replaces polling with Django Channels push.

---

## 3. UI Redesign — Design System Philosophy

### From: Cyber Neon → To: Intelligence-Grade Neutral

The current aesthetic (neon cyan, violet glow, black void) communicates "hacker tool."  
The target aesthetic communicates "serious analytical platform."

Reference: Palantir Gotham, ANSYS Minerva, Linear dark mode, Vercel dashboard.

**Key structural changes (not just color swaps):**
1. Sidebar collapses to icon-rail at 48px (was always-open 220px)
2. KPI cards lose neon accents, gain soft left-border status indicators
3. Map container has no chrome — it bleeds full-width
4. Typography hierarchy: weight-based, not color-based
5. Status dots eliminated where text is clearer
6. Spacing system moves from ad-hoc to strict 8px grid

---

## 4. Dependency Management — Security Analysis

### Why UI-triggered `pip install --upgrade` is Production-Dangerous

1. **No rollback.** pip modifies the live Python environment with no atomic transaction. A failed upgrade leaves a partially-upgraded state.
2. **Dependency resolution is global.** Upgrading `django` can silently break `djangorestframework`, `celery`, or custom middleware.
3. **No testing gate.** Production upgrades must run a test suite first. A UI button cannot enforce this.
4. **Privilege escalation.** The web process running as `www-data` should not have write access to site-packages. If it does, that's a security misconfiguration independently.
5. **Supply chain attack surface.** A compromised PyPI package served to the auto-upgrader could execute arbitrary code in the web process.

### Safe Alternative: Read-Only Scan + GitHub Actions

```
UI ("Scan Dependencies") → pip list --outdated → display table
                                                ↓
                         "Generate Upgrade Plan" → dry-run diff → display
                                                ↓
                         "Create GitHub PR" → triggers Actions workflow
                                                ↓
                         Actions: upgrade in venv → run test suite → open PR
                                                ↓
                         Human reviews diff → approves → merge → staging deploy
```

The Django admin UI **never installs anything.** It only reads and displays.

---

## 5. Migration Plan from Leaflet to KeplerGL

### Phase 1 (non-breaking, 1–2 days)
- Add `/api/threats/kepler/` endpoint alongside existing `/api/threats/`
- Build `frontend/` React app scaffold
- Add `<div id="kepler-root">` to dashboard template generator
- KeplerGL renders alongside existing Leaflet map (feature flag: `?map=kepler`)

### Phase 2 (parallel, 1 week)
- Implement all layer configs: point, heatmap, time animation
- Implement actor filter, severity filter via KeplerGL's filter API
- Validate performance with real feed data

### Phase 3 (cutover)
- Remove Leaflet and Leaflet CSS from dashboard
- Remove `renderMap1()`, `initMap2()`, `makeMarkerIcon()` from generated template
- Remove Leaflet script tags
- Feature flag removed; KeplerGL is default

---

## 6. Folder Structure After Changes

```
obsidian/
├── core/
├── dashboard/
│   ├── api.py                  # existing REST endpoints (unchanged)
│   ├── api_kepler.py           # NEW: KeplerGL-optimized endpoint
│   ├── dep_scanner.py          # NEW: safe dependency scanning
│   ├── views_admin.py          # NEW: admin views for dep scan
│   └── urls.py                 # UPDATED: new routes added
├── feeds/
├── frontend/                   # NEW: React microfrontend
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.jsx            # React entry point
│       ├── App.jsx             # Root component
│       ├── KeplerMap.jsx       # Map component
│       ├── store.js            # Redux store
│       ├── mapConfig.js        # KeplerGL layer/style config
│       └── useMapData.js       # Data fetching hook
├── static/
│   ├── css/
│   │   └── design_system.css   # NEW: full CSS variable system
│   └── kepler/                 # GENERATED by vite build
│       ├── bundle.js
│       └── bundle.css
├── templates/
│   └── dashboard.html          # GENERATED by Claude sessions + deploy.sh
├── .github/
│   └── workflows/
│       └── dependency_check.yml # NEW: safe dep management
├── deploy.sh
├── DEPLOY.md
└── ARCHITECTURE.md
```

---

## 7. Required Dependencies

### Python (add to requirements.txt)
```
# Already present: django, celery, redis, psutil
# Add:
django-ratelimit>=4.1.0        # Rate-limit the dep scanner endpoint
```

### Node.js (frontend only, dev toolchain — not deployed to server)
```json
{
  "dependencies": {
    "kepler.gl": "^3.0.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-redux": "^9.0.0",
    "redux": "^5.0.0",
    "@reduxjs/toolkit": "^2.0.0"
  },
  "devDependencies": {
    "vite": "^5.0.0",
    "@vitejs/plugin-react": "^4.0.0"
  }
}
```

Node.js is required only for the build step. Production servers do not run Node.js.

---

## 8. Risk Analysis

| Risk | Severity | Mitigation |
|---|---|---|
| KeplerGL bundle size (~3MB gzipped) | Medium | Vite code-splitting; serve with Brotli compression from Nginx |
| WebGL not supported in all browsers | Low | KeplerGL gracefully degrades; add `<noscript>` fallback |
| React + KeplerGL version compatibility | Medium | Pin exact versions in package-lock.json; test before each upgrade |
| Dep scanner subprocess injection | High (if not guarded) | Use argument list form, never shell=True, allowlist packages |
| CSS design system breaking existing layout | Medium | New design system is additive; load alongside existing CSS, migrate panel by panel |
| KeplerGL Mapbox token requirement | Low | KeplerGL 3.x works with MapLibre (no token required); configure accordingly |

---

## 9. Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                        OBSIDIAN PLATFORM                             │
│                                                                       │
│  ┌────────────────────┐    ┌─────────────────────────────────────┐   │
│  │   DJANGO BACKEND   │    │         BROWSER CLIENT              │   │
│  │                    │    │                                     │   │
│  │  ┌──────────────┐  │    │  ┌─────────────────────────────┐   │   │
│  │  │  views.py    │──┼────┼─▶│  templates/dashboard.html   │   │   │
│  │  │  (shell)     │  │    │  │  (Django-rendered shell)     │   │   │
│  │  └──────────────┘  │    │  └────────────┬────────────────┘   │   │
│  │                    │    │               │ mounts              │   │
│  │  ┌──────────────┐  │    │  ┌────────────▼────────────────┐   │   │
│  │  │  api.py      │◀─┼────┼──│  React App (static/kepler/) │   │   │
│  │  │  /api/kpis/  │  │    │  │  ┌──────────────────────┐   │   │   │
│  │  │  /api/iocs/  │  │    │  │  │  KeplerMap.jsx        │   │   │   │
│  │  │  /api/feeds/ │  │    │  │  │  - Point layer        │   │   │   │
│  │  └──────────────┘  │    │  │  │  - Heatmap layer      │   │   │   │
│  │                    │    │  │  │  - Time animation      │   │   │   │
│  │  ┌──────────────┐  │    │  │  │  - Actor filter        │   │   │   │
│  │  │api_kepler.py │◀─┼────┼──│  │  - Severity filter    │   │   │   │
│  │  │/api/threats/ │  │    │  │  └──────────────────────┘   │   │   │
│  │  │    kepler/   │  │    │  │  Redux Store (keplerGl)      │   │   │
│  │  └──────────────┘  │    │  └─────────────────────────────┘   │   │
│  │                    │    │                                     │   │
│  │  ┌──────────────┐  │    │  ┌─────────────────────────────┐   │   │
│  │  │dep_scanner.py│◀─┼────┼──│  Admin: Dep Scan Panel      │   │   │
│  │  │(read-only)   │  │    │  │  (read-only, staff-only)    │   │   │
│  │  └──────────────┘  │    │  └─────────────────────────────┘   │   │
│  │                    │    │                                     │   │
│  │  ┌──────────────┐  │    └─────────────────────────────────────┘  │
│  │  │  models.py   │  │                                              │
│  │  │  IOC         │  │    ┌─────────────────────────────────────┐   │
│  │  │  ThreatEvent │  │    │         BACKGROUND WORKERS          │   │
│  │  │  ThreatActor │  │    │                                     │   │
│  │  └──────┬───────┘  │    │  Celery Worker ──▶ Feed Ingestors   │   │
│  │         │          │    │  Celery Beat  ──▶ Schedules         │   │
│  │  ┌──────▼───────┐  │    │  Redis        ──▶ Broker/Cache      │   │
│  │  │   Database   │  │    │                                     │   │
│  │  │  SQLite/PG   │  │    └─────────────────────────────────────┘   │
│  │  └──────────────┘  │                                              │
│  └────────────────────┘    ┌─────────────────────────────────────┐   │
│                            │       CI/CD (GitHub Actions)        │   │
│                            │  dependency_check.yml               │   │
│                            │  - pip list --outdated              │   │
│                            │  - safety check                     │   │
│                            │  - open PR with diff                │   │
│                            └─────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘

Build Pipeline (dev only):
  frontend/ (Vite + React)
    └─▶ npm run build
          └─▶ static/kepler/bundle.js
                └─▶ python manage.py collectstatic
                      └─▶ staticfiles/kepler/bundle.js (served by Nginx/Django)
```
