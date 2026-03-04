// frontend/src/main.jsx
// React microfrontend entry point.
// Mounts into <div id="kepler-root"> rendered by Django template.
// Django passes config via data attributes on the mount element.

import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';

const mountEl = document.getElementById('kepler-root');

if (mountEl) {
  // Read config from data attributes set by Django template:
  //   <div id="kepler-root"
  //        data-api-base="/api"
  //        data-height="600"
  //        data-theme="dark">
  const config = {
    apiBase:    mountEl.dataset.apiBase    || '/api',
    height:     parseInt(mountEl.dataset.height || '600', 10),
    theme:      mountEl.dataset.theme      || 'dark',
    pollInterval: parseInt(mountEl.dataset.pollInterval || '60000', 10),
  };

  createRoot(mountEl).render(
    <React.StrictMode>
      <App config={config} />
    </React.StrictMode>
  );
} else {
  // Graceful degradation: kepler-root not present (different view)
  console.debug('[OBSIDIAN] kepler-root not found — map not mounted');
}
