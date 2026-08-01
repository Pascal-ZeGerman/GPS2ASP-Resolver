/* ==========================================================================
   Sign-coverage explorer — client controller (Phase 42, Plan 42-04)

   Single plain-ES controller (no bundler, no npm import) loaded via the
   `defer` <script> in index.html. It:
     1. loads the committed docs/explorer/data/coverage.json snapshot,
     2. renders ONE canvas circleMarker per street segment on a citywide
        Leaflet map, colored AND sized by SODA-match confidence tier,
     3. shows a per-marker popup (schedule / confidence / SODA level +
        Street View + FreeNYC link-outs, explicit unresolved state),
     4. applies four AND-composed filters with a zero-result state, and
     5. exports the currently-visible set as GeoJSON — all client-side.

   Security (T-42-02 / T-41-01 / ASVS V5): every dataset-derived string — NYC
   street text, summaries, SODA levels — is written via `textContent` and DOM
   node creation ONLY. The HTML-parsing sink and dynamic code evaluation are
   never used. Parsing is done with `response.json()`, never dynamic code
   evaluation. No SODA app token or any credential material is referenced
   client-side (T-42-01).
   ========================================================================== */

'use strict';

/* --------------------------------------------------------------------------
   Config — tiles and citywide framing (D-14: all five boroughs visible on
   load). NEVER hardcode any token or credential here.
   -------------------------------------------------------------------------- */
const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const TILE_ATTRIBUTION = '&copy; OpenStreetMap contributors';
const MAX_ZOOM = 19;

// Citywide view so all five boroughs are visible on load (D-14).
const CITY_CENTER = [40.70, -73.94];
const CITY_ZOOM = 11;

/* Python ASPDay convention: Monday = 0 .. Sunday = 6 (matches wk[].d). */
const DAY_ABBR = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/* Standard NYC borocode -> name fallback (top-level coverage.json `boroughs`
   map is the source of truth; this only backstops a missing map). */
const BOROUGH_FALLBACK = {
  1: 'Manhattan', 2: 'Bronx', 3: 'Brooklyn', 4: 'Queens', 5: 'Staten Island',
};

/* --------------------------------------------------------------------------
   Confidence-tier scale — VENDORED MIRROR of scripts/build_coverage_dataset.py
   TIER_BOUNDS / tier_for_confidence (42-01). These half-open boundaries MUST
   stay in sync with that Python source: it is the single authority and this is
   its client-side mirror (vendored-mirror discipline). One rule, four tiers.
     [0.00, 0.33) -> 'unresolved'
     [0.33, 0.50) -> 'low'
     [0.50, 0.75) -> 'medium'
     [0.75, 1.00] -> 'high'
   -------------------------------------------------------------------------- */
function tierForConfidence(v) {
  const n = Number(v);
  if (!(n >= 0)) return 'unresolved'; // NaN / negative -> treat as a gap
  if (n >= 0.75) return 'high';
  if (n >= 0.50) return 'medium';
  if (n >= 0.33) return 'low';
  return 'unresolved';
}

/* HUE channel — the four CSS tier colors (styles.css --tier-* tokens, D-09). */
function colorForTier(tier) {
  switch (tier) {
    case 'high': return '#35d67f'; // green — exact block match (--tier-high)
    case 'medium': return '#2dd4bf'; // teal-green — approximate (--tier-medium)
    case 'low': return '#f5a623'; // amber — fuzzy/fallback (--tier-low)
    default: return '#e5484d'; // red — unresolved, the gaps (--tier-unresolved)
  }
}

/* SECOND (non-hue) channel — per-tier marker radius (styles.css convention:
   unresolved > low > medium > high, so data gaps pop and are distinguishable
   by SIZE regardless of color vision — Prohibition 3 / T-42-05). */
function radiusForTier(tier) {
  switch (tier) {
    case 'high': return 2;
    case 'medium': return 3;
    case 'low': return 4;
    default: return 5; // unresolved — largest so gaps pop at citywide zoom
  }
}

/* Shared runtime state. */
const state = {
  data: null,          // parsed coverage.json
  map: null,
  renderer: null,      // one shared L.canvas() renderer for all markers
  markerLayer: null,   // single L.layerGroup holding the current subset
  points: [],          // all segments (plain array)
  visible: [],         // currently-filtered subset (export source)
  boroughByCode: null, // borocode -> borough name
};

/* ==========================================================================
   DOM helpers — text-only rendering (never the HTML-parsing sink)
   (copied verbatim from docs/demo/app.js:171-186)
   ========================================================================== */

function el(id) {
  return document.getElementById(id);
}

function setText(id, text) {
  const node = el(id);
  if (node) node.textContent = text == null ? '' : String(text);
}

function show(node) {
  if (node) node.hidden = false;
}

function hide(node) {
  if (node) node.hidden = true;
}

/* ==========================================================================
   Map + render
   ========================================================================== */

/** borocode -> borough name (coverage.json `boroughs` map first, then fallback). */
function boroughName(bc) {
  const key = String(bc);
  if (state.boroughByCode && state.boroughByCode[key] != null) {
    return state.boroughByCode[key];
  }
  return BOROUGH_FALLBACK[key] || key;
}

function initMap() {
  state.map = L.map('map', { preferCanvas: true }).setView(CITY_CENTER, CITY_ZOOM);
  L.tileLayer(TILE_URL, {
    maxZoom: MAX_ZOOM,
    attribution: TILE_ATTRIBUTION,
  }).addTo(state.map);
  // ONE shared canvas renderer for every circleMarker (RESEARCH: ~105K points).
  state.renderer = L.canvas({ padding: 0.5 });
  // Leaflet collapses to 0px if the container was laid out after init (Pitfall 7).
  state.map.invalidateSize();
  window.setTimeout(() => state.map.invalidateSize(), 200);
}

/**
 * Redraw the given subset onto the single shared canvas layer group (clear +
 * re-add rather than per-marker add/remove — RESEARCH perf note). One
 * tier-colored + tier-sized circleMarker per point.
 */
function renderMarkers(points) {
  if (!state.map) return;
  if (!state.markerLayer) {
    state.markerLayer = L.layerGroup().addTo(state.map);
  } else {
    state.markerLayer.clearLayers();
  }
  for (const p of points) {
    if (typeof p.lat !== 'number' || typeof p.lon !== 'number') continue;
    const tier = tierForConfidence(p.cf);
    const color = colorForTier(tier);
    const marker = L.circleMarker([p.lat, p.lon], {
      renderer: state.renderer,
      radius: radiusForTier(tier),
      color,
      weight: 0,
      fillColor: color,
      fillOpacity: 0.85,
    });
    state.markerLayer.addLayer(marker);
  }
}

/* ==========================================================================
   Bootstrap
   ========================================================================== */

async function loadDataset() {
  const res = await fetch('data/coverage.json');
  if (!res.ok) throw new Error(`coverage.json fetch failed: HTTP ${res.status}`);
  // Parse with the standard JSON parser only — never eval/dynamic evaluation.
  state.data = await res.json();
}

async function init() {
  try {
    await loadDataset();
  } catch (err) {
    // Dataset failed to load — show the visible alert, never a blank map (R2).
    show(el('error-state'));
    return;
  }

  // Freshness stamp (D-17).
  setText('data-freshness', state.data.generation_date);

  state.points = Array.isArray(state.data.segments) ? state.data.segments : [];
  state.boroughByCode = state.data.boroughs || null;

  initMap();
  renderMarkers(state.points);
  state.visible = state.points;
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}

/* Node-testability: expose the pure functions without affecting the browser
   (module is undefined under the deferred <script> tag). Task 2 and Task 3
   extend this export set. */
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { tierForConfidence, colorForTier, radiusForTier };
}
