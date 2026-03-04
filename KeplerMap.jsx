// frontend/src/KeplerMap.jsx
// Main map component. Owns the KeplerGL instance and filter UI.
// Designed to mount inside the intelligence dashboard layout.

import React, { useEffect, useRef, useCallback } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import KeplerGl from 'kepler.gl';
import { useMapData } from './useMapData';
import { uiActions } from './store';

// ── Filter control sub-component ─────────────────────────────────────
const SEVERITY_OPTIONS = ['critical', 'high', 'medium', 'low', 'info'];

const STATUS_COLORS = {
  critical: '#ef4444',
  high:     '#f97316',
  medium:   '#eab308',
  low:      '#22c55e',
  info:     '#3b82f6',
};

const TIME_WINDOWS = [
  { label: '6h',   value: 6    },
  { label: '24h',  value: 24   },
  { label: '7d',   value: 168  },
  { label: '30d',  value: 720  },
  { label: '90d',  value: 2160 },
  { label: '1y',   value: 8760 },
];

function FilterBar({ filters, onFilterChange, loading, recordCount, lastFetched }) {
  const dispatch = useDispatch();

  const toggleSeverity = useCallback((sev) => {
    const current = filters.severity;
    const next = current.includes(sev)
      ? current.filter(s => s !== sev)
      : [...current, sev];
    onFilterChange({ severity: next });
  }, [filters.severity, onFilterChange]);

  const lastFetchedFmt = lastFetched
    ? new Date(lastFetched).toLocaleTimeString()
    : '—';

  return (
    <div style={styles.filterBar}>
      {/* Time window */}
      <div style={styles.filterGroup}>
        <span style={styles.filterLabel}>TIME</span>
        <div style={styles.segmented}>
          {TIME_WINDOWS.map(tw => (
            <button
              key={tw.value}
              style={{
                ...styles.segBtn,
                ...(filters.hours === tw.value ? styles.segBtnActive : {}),
              }}
              onClick={() => onFilterChange({ hours: tw.value })}
            >
              {tw.label}
            </button>
          ))}
        </div>
      </div>

      {/* Severity toggles */}
      <div style={styles.filterGroup}>
        <span style={styles.filterLabel}>SEVERITY</span>
        <div style={styles.severityRow}>
          {SEVERITY_OPTIONS.map(sev => {
            const active = filters.severity.length === 0 || filters.severity.includes(sev);
            return (
              <button
                key={sev}
                style={{
                  ...styles.sevBtn,
                  borderColor: active ? STATUS_COLORS[sev] : 'transparent',
                  background:  active ? `${STATUS_COLORS[sev]}18` : 'transparent',
                  color:       active ? STATUS_COLORS[sev] : '#475569',
                }}
                onClick={() => toggleSeverity(sev)}
              >
                {sev.toUpperCase()}
              </button>
            );
          })}
          {filters.severity.length > 0 && (
            <button
              style={styles.clearBtn}
              onClick={() => onFilterChange({ severity: [] })}
            >
              ALL
            </button>
          )}
        </div>
      </div>

      {/* Actor search */}
      <div style={styles.filterGroup}>
        <span style={styles.filterLabel}>ACTOR</span>
        <input
          style={styles.textInput}
          type="text"
          placeholder="filter actor..."
          value={filters.actor}
          onChange={e => onFilterChange({ actor: e.target.value })}
        />
      </div>

      {/* Meta */}
      <div style={styles.metaGroup}>
        <span style={styles.metaItem}>
          {loading
            ? <span style={{ color: '#3b82f6' }}>LOADING…</span>
            : <span style={{ color: '#22c55e' }}>{recordCount.toLocaleString()} EVENTS</span>
          }
        </span>
        <span style={styles.metaItem}>UPDATED {lastFetchedFmt}</span>
        <button
          style={styles.resetBtn}
          onClick={() => dispatch(uiActions.resetFilters())}
        >
          RESET
        </button>
      </div>
    </div>
  );
}

// ── Main map component ────────────────────────────────────────────────
export default function KeplerMap({ width, height, apiBase, pollInterval }) {
  const dispatch    = useDispatch();
  const filters     = useSelector(s => s.ui.filters);
  const loading     = useSelector(s => s.ui.loading);
  const error       = useSelector(s => s.ui.error);
  const recordCount = useSelector(s => s.ui.recordCount);
  const lastFetched = useSelector(s => s.ui.lastFetched);

  // Register data loading — hook handles all fetch/poll/filter logic
  useMapData(apiBase, pollInterval);

  const handleFilterChange = useCallback((partial) => {
    dispatch(uiActions.setFilters(partial));
  }, [dispatch]);

  // Dynamic height: total container minus filter bar (52px)
  const mapHeight = height - 52;

  return (
    <div style={{ ...styles.container, width, height }}>
      <FilterBar
        filters={filters}
        onFilterChange={handleFilterChange}
        loading={loading}
        recordCount={recordCount}
        lastFetched={lastFetched}
      />

      {error && (
        <div style={styles.errorBanner}>
          ⚠ {error} — retrying on next poll
        </div>
      )}

      <div style={{ width, height: mapHeight }}>
        <KeplerGl
          id="obsidian-threat-map"
          // No Mapbox token — KeplerGL 3.x uses MapLibre GL by default
          mapboxApiAccessToken=""
          width={width}
          height={mapHeight}
          theme="dark"
          // Suppress KeplerGL's own header (we have our own UI chrome)
          getState={state => state.keplerGl}
        />
      </div>
    </div>
  );
}

// ── Styles (inline — no build-time CSS dependency) ────────────────────
const styles = {
  container: {
    display:   'flex',
    flexDirection: 'column',
    background: '#0f1520',
    overflow:   'hidden',
    fontFamily: "'DM Mono', 'JetBrains Mono', monospace",
  },

  filterBar: {
    height:     52,
    display:    'flex',
    alignItems: 'center',
    gap:        24,
    padding:    '0 16px',
    background: '#141b2d',
    borderBottom: '1px solid rgba(148,163,184,0.08)',
    flexShrink: 0,
    overflowX:  'auto',
  },

  filterGroup: {
    display:    'flex',
    alignItems: 'center',
    gap:        8,
    flexShrink: 0,
  },

  filterLabel: {
    fontSize:      10,
    letterSpacing: '0.15em',
    color:         '#475569',
    fontWeight:    500,
  },

  segmented: {
    display:    'flex',
    background: '#0f1520',
    borderRadius: 4,
    border:     '1px solid rgba(148,163,184,0.08)',
    overflow:   'hidden',
  },

  segBtn: {
    padding:    '3px 10px',
    border:     'none',
    background: 'transparent',
    color:      '#64748b',
    fontSize:   11,
    cursor:     'pointer',
    fontFamily: 'inherit',
    letterSpacing: '0.06em',
    transition: 'all 0.15s',
  },

  segBtnActive: {
    background: 'rgba(59,130,246,0.15)',
    color:      '#3b82f6',
  },

  severityRow: {
    display: 'flex',
    gap:     4,
  },

  sevBtn: {
    padding:       '3px 9px',
    borderRadius:  3,
    border:        '1px solid transparent',
    fontSize:      10,
    letterSpacing: '0.08em',
    cursor:        'pointer',
    fontFamily:    'inherit',
    transition:    'all 0.15s',
  },

  clearBtn: {
    padding:       '3px 9px',
    borderRadius:  3,
    border:        '1px solid rgba(148,163,184,0.15)',
    background:    'transparent',
    color:         '#94a3b8',
    fontSize:      10,
    letterSpacing: '0.08em',
    cursor:        'pointer',
    fontFamily:    'inherit',
  },

  textInput: {
    background:   '#0f1520',
    border:       '1px solid rgba(148,163,184,0.12)',
    borderRadius: 4,
    padding:      '4px 10px',
    color:        '#e2e8f0',
    fontSize:     11,
    fontFamily:   'inherit',
    width:        140,
    outline:      'none',
  },

  metaGroup: {
    marginLeft: 'auto',
    display:    'flex',
    alignItems: 'center',
    gap:        16,
    flexShrink: 0,
  },

  metaItem: {
    fontSize:      10,
    letterSpacing: '0.10em',
    color:         '#475569',
  },

  resetBtn: {
    padding:       '3px 10px',
    borderRadius:  3,
    border:        '1px solid rgba(148,163,184,0.12)',
    background:    'transparent',
    color:         '#64748b',
    fontSize:      10,
    letterSpacing: '0.1em',
    cursor:        'pointer',
    fontFamily:    'inherit',
  },

  errorBanner: {
    padding:    '6px 16px',
    background: 'rgba(239,68,68,0.08)',
    borderBottom: '1px solid rgba(239,68,68,0.2)',
    color:      '#ef4444',
    fontSize:   11,
    fontFamily: 'inherit',
    letterSpacing: '0.06em',
  },
};
