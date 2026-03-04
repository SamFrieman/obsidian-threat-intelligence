// frontend/src/useMapData.js
// Data-fetching hook for KeplerGL datasets.
// Handles initial load, polling, filter changes, and error recovery.

import { useEffect, useRef, useCallback } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { addDataToMap, removeDataset } from 'kepler.gl/actions';
import { uiActions } from './store';
import { MAP_CONFIG } from './mapConfig';

const DATASET_IDS = {
  threats:      'threats',
  heatmap:      'threat-heatmap',
  actorDensity: 'threat-actors',
};

/**
 * Fetch one dataset from the API and dispatch it to KeplerGL store.
 * On first load for a dataset, includes MAP_CONFIG to initialise layers.
 * On subsequent loads (filter changes, polling), uses addDataToMap
 * which replaces the dataset in-place without re-creating layers.
 */
async function fetchAndDispatch(dispatch, url, datasetId, config = null) {
  try {
    const res = await fetch(url, {
      credentials: 'same-origin',   // Passes Django session cookie
      headers: { 'Accept': 'application/json' },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status} from ${url}`);

    const data = await res.json();
    if (!data.fields || !data.rows) throw new Error('Malformed KeplerGL response');

    const payload = {
      datasets: [{
        info:  { id: datasetId, label: datasetId },
        data:  { fields: data.fields, rows: data.rows },
      }],
      options: {
        centerMap: false,
        readOnly:  false,
        keepExistingConfig: true,  // Don't reset layer styles on data refresh
      },
    };

    // Only inject MAP_CONFIG on first load (when config is provided)
    if (config) payload.config = config;

    dispatch(addDataToMap(payload));
    return data;

  } catch (err) {
    console.error(`[OBSIDIAN] Failed to fetch ${datasetId}:`, err);
    throw err;
  }
}


/**
 * Builds the URL for /api/threats/kepler/ with current filters applied.
 */
function buildThreatUrl(apiBase, filters) {
  const params = new URLSearchParams();
  params.set('hours',  String(filters.hours || 168));
  params.set('limit',  '10000');
  if (filters.severity?.length) params.set('severity', filters.severity.join(','));
  if (filters.actor)             params.set('actor',    filters.actor);
  if (filters.source)            params.set('source',   filters.source);
  return `${apiBase}/threats/kepler/?${params}`;
}


/**
 * Primary data hook. Call once from KeplerMap.jsx.
 *
 * Behaviour:
 *   - Fetches threats + heatmap + actor-density on mount
 *   - Re-fetches threats when filters change
 *   - Polls threats every pollInterval ms
 *   - Cleans up timers on unmount
 */
export function useMapData(apiBase, pollInterval = 60000) {
  const dispatch  = useDispatch();
  const filters   = useSelector(s => s.ui.filters);
  const filtersRef = useRef(filters);
  const timerRef   = useRef(null);
  const isFirstLoad = useRef(true);

  // Always keep filtersRef in sync so the poll closure reads current filters
  useEffect(() => {
    filtersRef.current = filters;
  }, [filters]);

  // ── Fetch threat points (filter-aware, polled) ──────────────────
  const fetchThreats = useCallback(async (currentFilters, includeConfig) => {
    dispatch(uiActions.setLoading(true));
    try {
      const url  = buildThreatUrl(apiBase, currentFilters);
      const data = await fetchAndDispatch(
        dispatch,
        url,
        DATASET_IDS.threats,
        includeConfig ? MAP_CONFIG : null,
      );
      dispatch(uiActions.setFetchMeta({
        lastFetched: new Date().toISOString(),
        count:       data.count,
      }));
    } catch (err) {
      dispatch(uiActions.setError(err.message));
    } finally {
      dispatch(uiActions.setLoading(false));
    }
  }, [dispatch, apiBase]);

  // ── Fetch heatmap data (cached 5 min on server) ─────────────────
  const fetchHeatmap = useCallback(async () => {
    const url = `${apiBase}/threats/kepler/heatmap/?hours=720`;
    try {
      await fetchAndDispatch(dispatch, url, DATASET_IDS.heatmap, null);
    } catch {
      // Non-critical — heatmap layer is optional
    }
  }, [dispatch, apiBase]);

  // ── Fetch actor density (cached 15 min on server) ───────────────
  const fetchActorDensity = useCallback(async () => {
    const url = `${apiBase}/actors/kepler/`;
    try {
      await fetchAndDispatch(dispatch, url, DATASET_IDS.actorDensity, null);
    } catch {
      // Non-critical — actor layer is optional
    }
  }, [dispatch, apiBase]);

  // ── Initial load ─────────────────────────────────────────────────
  useEffect(() => {
    if (!isFirstLoad.current) return;
    isFirstLoad.current = false;

    // Sequential: threats first (with MAP_CONFIG), then supporting datasets
    fetchThreats(filtersRef.current, true)
      .then(() => fetchHeatmap())
      .then(() => fetchActorDensity());

    // Start polling for threat points
    timerRef.current = setInterval(() => {
      fetchThreats(filtersRef.current, false);
    }, pollInterval);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // ^ intentionally empty dep array — runs once. filtersRef handles closure.

  // ── Re-fetch when filters change (debounced 400ms) ────────────────
  const debounceRef = useRef(null);
  useEffect(() => {
    if (isFirstLoad.current) return;   // skip — initial load handles first fetch
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetchThreats(filters, false);
    }, 400);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [filters, fetchThreats]);
}
