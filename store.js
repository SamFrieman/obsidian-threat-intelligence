// frontend/src/store.js
// Redux store for KeplerGL.
// KeplerGL manages all its own state through keplerGlReducer.
// We add a lightweight `ui` slice for our own filter controls.

import { configureStore, createSlice } from '@reduxjs/toolkit';
import { keplerGlReducer, enhanceReduxMiddleware } from 'kepler.gl/reducers';

// ── UI slice — tracks our filter panel state ─────────────────────────
const uiSlice = createSlice({
  name: 'ui',
  initialState: {
    filters: {
      hours:    168,
      severity: [],   // [] = all
      actor:    '',
      source:   '',
    },
    loading:      false,
    error:        null,
    lastFetched:  null,
    recordCount:  0,
  },
  reducers: {
    setFilters(state, action) {
      state.filters = { ...state.filters, ...action.payload };
    },
    setLoading(state, action) {
      state.loading = action.payload;
    },
    setError(state, action) {
      state.error = action.payload;
    },
    setFetchMeta(state, action) {
      state.lastFetched = action.payload.lastFetched;
      state.recordCount = action.payload.count;
      state.error = null;
    },
    resetFilters(state) {
      state.filters = { hours: 168, severity: [], actor: '', source: '' };
    },
  },
});

export const uiActions = uiSlice.actions;

// ── Store ─────────────────────────────────────────────────────────────
export const store = configureStore({
  reducer: {
    keplerGl: keplerGlReducer,
    ui:       uiSlice.reducer,
  },
  middleware: (getDefaultMiddleware) =>
    enhanceReduxMiddleware(
      getDefaultMiddleware({
        // KeplerGL stores large dataset objects in Redux —
        // disable serializability check to prevent console spam
        serializableCheck: false,
        immutableCheck:    false,
      })
    ),
  devTools: process.env.NODE_ENV !== 'production',
});
