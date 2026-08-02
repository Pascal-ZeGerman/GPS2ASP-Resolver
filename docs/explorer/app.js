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

/* Standard NYC borocode -> name fallback (top-level coverage.json `boroughs`
   map is the source of truth; this only backstops a missing map). */
const BOROUGH_FALLBACK = {
  1: 'Manhattan', 2: 'Bronx', 3: 'Brooklyn', 4: 'Queens', 5: 'Staten Island',
};

/* --------------------------------------------------------------------------
   Confidence-tier scale (42-01). ``TIER_BOUNDS`` is overwritten from
   coverage.json's own `tier_bounds` field at load time (see init()) so the
   tier partition can never silently drift from scripts/build_coverage_
   dataset.py's TIER_BOUNDS / tier_for_confidence — the dataset IS the single
   authority. This literal is only the fallback for a dataset predating the
   `tier_bounds` field. One rule, four tiers, ordered high -> low so the
   first matching lower bound wins:
     [0.00, 0.33) -> 'unresolved'
     [0.33, 0.50) -> 'low'
     [0.50, 0.75) -> 'medium'
     [0.75, 1.00] -> 'high'
   -------------------------------------------------------------------------- */
let TIER_BOUNDS = [
  [0.75, 'high'],
  [0.50, 'medium'],
  [0.33, 'low'],
  [0.00, 'unresolved'],
];

function tierForConfidence(v) {
  const n = Number(v);
  if (!(n >= 0)) return 'unresolved'; // NaN / negative -> treat as a gap
  for (const [lower, name] of TIER_BOUNDS) {
    if (n >= lower) return name;
  }
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
   DOM helpers — el/setText/show/hide live in ../common.js (shared with
   docs/demo/app.js), loaded before this script.
   ========================================================================== */

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
    // Build the popup lazily (function form) so its text stays textContent-rendered.
    marker.bindPopup(() => buildPopup(p));
    state.markerLayer.addLayer(marker);
  }
}

/* ==========================================================================
   Popup builder — fields, link-outs, explicit unresolved state
   (textContent / DOM node creation ONLY; never an HTML-string assignment)
   ========================================================================== */

/* hasSchedule and buildAttrRow (formerly attrRow) live in ../common.js,
   shared with docs/demo/app.js, loaded before this script. */

/** Human "Mon 08:30–10:00" line for one weekly window ({d,s,e}). */
function weeklyLine(w) {
  const abbr = DAY_ABBR[Number(w.d)] || '?';
  const start = w.s == null ? '' : String(w.s);
  const end = w.e == null ? '' : String(w.e);
  return `${abbr} ${start}–${end}`.trim();
}

/** Explicit, safety-correct status copy — NEVER a "confirmed clear" reading for
    a gap / no-match (Prohibition 2 / T-42-04). */
function statusCopy(point) {
  switch (point.status) {
    case 'schedule_found':
    case 'asp_active_now':
      return null; // schedule is shown in the attributes table instead
    case 'no_asp':
      return 'No ASP broom sign found on this block (SODA had records for this street).';
    case 'no_match':
    case 'resolution_failed':
    case 'all_unparseable':
    default:
      return 'Unresolved — no SODA record for this block (coverage gap; not a confirmed clear street).';
  }
}

/**
 * Build a popup DOM node (NOT an HTML string) for one segment. All
 * dataset-derived text is set via textContent only.
 */
function buildPopup(point) {
  const root = document.createElement('div');
  root.className = 'marker-popup';

  // Street label + cross streets.
  const title = document.createElement('p');
  title.className = 'popup-street';
  title.textContent = point.st == null ? '' : String(point.st);
  root.appendChild(title);

  if (point.fr && point.to) {
    const cross = document.createElement('p');
    cross.className = 'popup-cross';
    cross.textContent = `${point.fr} to ${point.to}`;
    root.appendChild(cross);
  }

  // Attributes table — confidence + tier label, SODA level, schedule summary.
  const table = document.createElement('table');
  table.className = 'popup-attrs';
  const tbody = document.createElement('tbody');

  const tier = tierForConfidence(point.cf);
  const cfNum = Number(point.cf);
  const cfText = Number.isFinite(cfNum) ? cfNum.toFixed(2) : '—';
  tbody.appendChild(buildAttrRow('Confidence', `${cfText} (${tier})`));

  const lv = Number(point.lv);
  tbody.appendChild(buildAttrRow('SODA level', lv === 0 ? '0 (no match)' : String(point.lv)));

  if (hasSchedule(point)) {
    if (point.sm) tbody.appendChild(buildAttrRow('Schedule', point.sm));
    if (Array.isArray(point.wk) && point.wk.length > 0) {
      tbody.appendChild(buildAttrRow('Cleaning', point.wk.map(weeklyLine).join('; ')));
    }
  }

  table.appendChild(tbody);
  root.appendChild(table);

  // Explicit status line for non-schedule states (unresolved / no_asp). NEVER
  // renders "confirmed clear" copy for a gap (Prohibition 2 / T-42-04).
  const copy = statusCopy(point);
  if (copy) {
    const note = document.createElement('p');
    note.className = 'popup-status';
    note.textContent = copy;
    root.appendChild(note);
  }

  // Link-outs — Street View + FreeNYC. Both open a NEW TAB and carry
  // target="_blank" + rel="noopener" (reverse-tabnabbing guard, T-42-06).
  // The NYC DOT sign-lookup link is intentionally DROPPED (no stable URL, D-05).
  const links = document.createElement('p');
  links.className = 'popup-links';

  const sv = document.createElement('a');
  sv.textContent = 'Open in Street View';
  sv.href = `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${point.lat},${point.lon}`;
  sv.setAttribute('target', '_blank');
  sv.setAttribute('rel', 'noopener');
  links.appendChild(sv);

  const freenyc = document.createElement('a');
  freenyc.textContent = 'Check FreeNYC';
  freenyc.href = 'https://www.free.nyc/';
  freenyc.setAttribute('target', '_blank');
  freenyc.setAttribute('rel', 'noopener');
  links.appendChild(freenyc);

  root.appendChild(links);
  return root;
}

/* ==========================================================================
   Filters (four AND-composed controls) + no-results state
   ========================================================================== */

/**
 * Compute the currently-visible subset from the plain points array using AND
 * logic across the four controls, redraw that subset onto the shared canvas
 * layer group, and toggle the #no-results state (R4).
 */
function applyFilters() {
  const borough = el('filter-borough') ? el('filter-borough').value : '';
  const tier = el('filter-tier') ? el('filter-tier').value : '';
  const level = el('filter-level') ? el('filter-level').value : '';
  const search = (el('filter-search') ? el('filter-search').value : '')
    .trim().toLowerCase();

  const visible = state.points.filter((p) => {
    // Borough — match the resolved borough NAME (42-03's select uses names).
    if (borough && boroughName(p.bc) !== borough) return false;
    // Tier — the SAME tierForConfidence used by coloring and the popup label.
    if (tier && tierForConfidence(p.cf) !== tier) return false;
    // SODA level — literal 0|1|2|3 (Level 4 folded into 3 per Open-Q4 / D-18).
    if (level !== '' && String(p.lv) !== String(level)) return false;
    // Street search — case-insensitive substring on full_street_name (st).
    if (search && !String(p.st || '').toLowerCase().includes(search)) return false;
    return true;
  });

  state.visible = visible;
  renderMarkers(visible);

  const noResults = el('no-results');
  if (visible.length === 0) show(noResults);
  else hide(noResults);
}

/* ==========================================================================
   GeoJSON export of the currently-visible set (R5)
   ========================================================================== */

/**
 * PURE FeatureCollection builder (node-testable, no side effects). An empty
 * `visible` yields a VALID empty FeatureCollection (features:[]) — never an
 * error and never a silent fall back to the full set (R5).
 */
function buildFeatureCollection(visible) {
  // Same numeric-lat/lon guard renderMarkers() applies before drawing (line
  // ~158) — a point invisible on the map must never be exported either.
  const exportable = (visible || []).filter(
    (p) => typeof p.lat === 'number' && typeof p.lon === 'number'
  );
  return {
    type: 'FeatureCollection',
    features: exportable.map((p) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
      properties: {
        segment_id: p.id,
        on_street: p.st,
        from_street: p.fr,
        to_street: p.to,
        side: p.sd,
        borocode: p.bc,
        soda_level: p.lv,
        confidence: p.cf,
        status: p.status,
      },
    })),
  };
}

/**
 * Build the FeatureCollection for the visible set and, in a browser, trigger a
 * client-side download via a Blob + object URL + temporary anchor (no server).
 * Returns the FeatureCollection so the builder stays node-testable.
 */
function exportGeoJSON(visible) {
  const fc = buildFeatureCollection(visible || []);
  if (typeof document !== 'undefined'
    && typeof Blob !== 'undefined'
    && typeof URL !== 'undefined' && URL.createObjectURL) {
    const blob = new Blob([JSON.stringify(fc, null, 2)], {
      type: 'application/geo+json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'coverage-visible.geojson';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
  return fc;
}

/**
 * Return a debounced wrapper around `fn`: a burst of calls within `delayMs`
 * of each other collapses into ONE trailing call. Used on the street-search
 * input so typing doesn't redraw the full (up to ~105K point) canvas layer
 * on every keystroke.
 */
function debounce(fn, delayMs) {
  let timer = null;
  return (...args) => {
    if (timer !== null) window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      timer = null;
      fn(...args);
    }, delayMs);
  };
}

const SEARCH_DEBOUNCE_MS = 200;

/** Wire filter controls and the export button to their handlers. */
function wireControls() {
  const search = el('filter-search');
  if (search) {
    search.addEventListener('input', debounce(applyFilters, SEARCH_DEBOUNCE_MS));
  }
  for (const id of ['filter-borough', 'filter-tier', 'filter-level']) {
    const ctrl = el(id);
    if (ctrl) ctrl.addEventListener('change', applyFilters);
  }
  const exportBtn = el('export-geojson');
  if (exportBtn) {
    exportBtn.addEventListener('click', () => exportGeoJSON(state.visible));
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
  // The dataset is the single authority on the tier partition (see
  // tierForConfidence above) — sync it before any marker/popup rendering.
  if (Array.isArray(state.data.tier_bounds) && state.data.tier_bounds.length > 0) {
    TIER_BOUNDS = state.data.tier_bounds;
  }

  initMap();
  wireControls();
  // Initial render: empty filters match all, so this draws the full set and
  // hides the no-results state, and seeds state.visible for export.
  applyFilters();
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
  module.exports = {
    tierForConfidence,
    colorForTier,
    radiusForTier,
    buildPopup,
    applyFilters,
    buildFeatureCollection,
    exportGeoJSON,
  };
}
