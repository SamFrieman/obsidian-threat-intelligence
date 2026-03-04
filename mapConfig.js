// frontend/src/mapConfig.js
// KeplerGL initial map configuration.
// Defines layers, visual properties, tooltips, and base map style.
// This config is passed to addDataToMap() on first load.
// KeplerGL's UI can override these after load (user can restyle).

// Color ramp matching the intelligence design system
const SEVERITY_COLOR_RANGE = {
  name:     'Threat Severity',
  type:     'custom',
  category: 'Custom',
  colors:   ['#3b82f6', '#22c55e', '#eab308', '#f97316', '#ef4444'],
  colorMap: [
    ['info',     '#3b82f6'],
    ['low',      '#22c55e'],
    ['medium',   '#eab308'],
    ['high',     '#f97316'],
    ['critical', '#ef4444'],
  ],
};

const HEAT_COLOR_RANGE = {
  name:     'Threat Density',
  type:     'sequential',
  category: 'Custom',
  // Low density → high density: neutral → blue → orange → red
  colors:   ['#0f1520', '#1e3a5f', '#1d4ed8', '#f97316', '#ef4444'],
  reversed: false,
};

export const MAP_CONFIG = {
  version: 'v1',
  config: {
    visState: {
      filters: [],
      layers: [
        // ── LAYER 1: Individual threat event points ───────────────────
        {
          id:   'threat-points',
          type: 'point',
          config: {
            dataId:    'threats',
            label:     'Threat Events',
            columns:   { lat: 'lat', lng: 'lon', altitude: null },
            isVisible: true,
            visConfig: {
              radius:       10,
              fixedRadius:  false,
              opacity:      0.85,
              outline:      true,
              thickness:    1.5,
              strokeColor:  null,
              colorRange:   SEVERITY_COLOR_RANGE,
              radiusRange:  [4, 28],
              filled:       true,
            },
            // Color by severity field (ordinal scale)
            colorField: { name: 'severity', type: 'string' },
            colorScale: 'ordinal',
            // Size by severity_score (1–4)
            sizeField:  { name: 'severity_score', type: 'integer' },
            sizeScale:  'sqrt',
            textLabel:  [],
          },
          visualChannels: {
            colorField: { name: 'severity',       type: 'string' },
            colorScale: 'ordinal',
            sizeField:  { name: 'severity_score', type: 'integer' },
            sizeScale:  'sqrt',
          },
        },

        // ── LAYER 2: Geographic heatmap (density × severity) ─────────
        // Uses the /api/threats/kepler/heatmap/ endpoint dataset
        {
          id:   'threat-heatmap',
          type: 'heatmap',
          config: {
            dataId:    'threat-heatmap',
            label:     'Threat Density',
            columns:   { lat: 'lat', lng: 'lon' },
            isVisible: false,   // off by default; user enables via layer panel
            visConfig: {
              opacity:    0.75,
              colorRange: HEAT_COLOR_RANGE,
              radius:     40,
              intensity:  2,
              threshold:  0.05,
            },
          },
          visualChannels: {
            weightField: { name: 'weight', type: 'real' },
            weightScale: 'linear',
          },
        },

        // ── LAYER 3: Actor density overlay (arc layer) ────────────────
        // Requires threat-actors dataset from /api/actors/kepler/
        {
          id:   'actor-density',
          type: 'point',
          config: {
            dataId:    'threat-actors',
            label:     'Actor Concentration',
            columns:   { lat: 'lat', lng: 'lon', altitude: null },
            isVisible: false,
            visConfig: {
              radius:      30,
              fixedRadius: false,
              opacity:     0.5,
              outline:     false,
              colorRange:  SEVERITY_COLOR_RANGE,
              radiusRange: [10, 60],
              filled:      true,
            },
            colorField: { name: 'severity',  type: 'string' },
            colorScale: 'ordinal',
            sizeField:  { name: 'ioc_count', type: 'integer' },
            sizeScale:  'sqrt',
          },
          visualChannels: {
            colorField: { name: 'severity',  type: 'string' },
            colorScale: 'ordinal',
            sizeField:  { name: 'ioc_count', type: 'integer' },
            sizeScale:  'sqrt',
          },
        },
      ],

      // ── Tooltip configuration ──────────────────────────────────────
      interactionConfig: {
        tooltip: {
          fieldsToShow: {
            threats: [
              { name: 'title',          format: null },
              { name: 'severity',       format: null },
              { name: 'actor',          format: null },
              { name: 'country',        format: null },
              { name: 'city',           format: null },
              { name: 'source',         format: null },
              { name: 'timestamp',      format: null },
              { name: 'severity_score', format: null },
            ],
            'threat-heatmap': [
              { name: 'country',     format: null },
              { name: 'actor',       format: null },
              { name: 'event_count', format: null },
              { name: 'severity',    format: null },
            ],
            'threat-actors': [
              { name: 'actor',      format: null },
              { name: 'country',    format: null },
              { name: 'ioc_count',  format: null },
              { name: 'severity',   format: null },
              { name: 'confidence', format: null },
            ],
          },
          compareMode:  false,
          compareType:  'absolute',
          enabled:      true,
        },
        brush:   { enabled: false, size: 0.5 },
        geocoder:{ enabled: false },
        coordinate: { enabled: true },
      },

      layerBlending:   'normal',
      splitMaps:       [],
      animationConfig: { currentTime: null, speed: 1 },
    },

    mapState: {
      bearing:     0,
      dragRotate:  false,
      latitude:    20,
      longitude:   10,
      pitch:       0,
      zoom:        1.8,
      isSplit:     false,
    },

    // MapLibre GL (no Mapbox token required in KeplerGL 3.x)
    mapStyle: {
      styleType:          'dark',
      topLayerGroups:     {},
      visibleLayerGroups: {
        label:    true,
        road:     false,
        border:   true,
        building: false,
        water:    true,
        land:     true,
        '3d building': false,
      },
      threeDBuildingColor: [15, 21, 32],
      mapStyles:           {},
    },
  },
};
