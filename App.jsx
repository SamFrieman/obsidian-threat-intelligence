// frontend/src/App.jsx
// Root component. Wraps KeplerMap with Redux Provider and
// computes responsive dimensions from the mount element.

import React, { useState, useEffect, useRef } from 'react';
import { Provider } from 'react-redux';
import { store } from './store';
import KeplerMap from './KeplerMap';

function ResponsiveMap({ config }) {
  const containerRef = useRef(null);
  const [dims, setDims] = useState({ width: 0, height: config.height });

  useEffect(() => {
    const observe = () => {
      const el = containerRef.current?.parentElement;
      if (!el) return;
      setDims({
        width:  el.clientWidth,
        height: config.height,
      });
    };

    observe();
    const ro = new ResizeObserver(observe);
    if (containerRef.current?.parentElement) {
      ro.observe(containerRef.current.parentElement);
    }
    return () => ro.disconnect();
  }, [config.height]);

  return (
    <div ref={containerRef} style={{ width: '100%' }}>
      {dims.width > 0 && (
        <KeplerMap
          width={dims.width}
          height={dims.height}
          apiBase={config.apiBase}
          pollInterval={config.pollInterval}
        />
      )}
    </div>
  );
}

export default function App({ config }) {
  return (
    <Provider store={store}>
      <ResponsiveMap config={config} />
    </Provider>
  );
}
