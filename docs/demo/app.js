/* ==========================================================================
   ASP Parking demo — client controller (Phase 41, Plan 41-04)

   Single plain-ES controller (no bundler, no npm import) loaded via the
   `defer` <script> in index.html. It:
     1. loads the committed demo.json / demo-segments.geojson snapshot,
     2. wires a Leaflet map whose pins resolve a block from the dataset,
     3. renders the restriction readout, the mock Home Assistant sensor card,
        and an animated next-move calendar,
     4. recomputes the next-move day client-side (America/New_York) from the
        stored WEEKLY pattern so the demo never decays (mirrors
        `find_next_window`, src/gps2asp/schedule/next_move.py),
     5. re-renders every surface from the already-loaded dataset on profile
        switch with NO network call.

   Security (T-41-05 / ASVS V5): every dataset-derived string — NYC sign text,
   summaries, sensor attributes — is written via `textContent` and DOM node
   creation ONLY. The HTML-parsing sink and dynamic code evaluation are never
   used. Parsing is done with
   `response.json()`, never dynamic code evaluation.
   ========================================================================== */

'use strict';

/* --------------------------------------------------------------------------
   Config (CONTEXT locked decision: expose demo ⇄ full-resolver modes).

   No backend ships this phase (RESEARCH A5 / Open Question 3), so
   FULL_RESOLVER_ENDPOINT defaults to null and the "Full resolver" mode is
   inert — it shows a graceful not-configured message and stays on the demo
   dataset. A maintainer can later point this at a URL to activate the branch.
   NEVER hardcode a real endpoint or any token here.
   -------------------------------------------------------------------------- */
const FULL_RESOLVER_ENDPOINT = null;

const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const TILE_ATTRIBUTION = '&copy; OpenStreetMap contributors';
const MAP_CENTER = [40.6776, -73.9685]; // demo dataset centroid (Prospect Pl area)
const MAP_ZOOM = 15;
const MAX_ZOOM = 19;
const ACCENT = '#4da3ff';

/* Python ASPDay convention: Monday = 0 .. Sunday = 6 (matches weekly[].day). */
const DAY_NAMES = [
  'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
];
const DAY_ABBR = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/* Shared runtime state. */
const state = {
  data: null,          // parsed demo.json
  geo: null,           // parsed demo-segments.geojson
  map: null,
  markers: {},         // point_key -> Leaflet layer
  overlay: null,       // current segment polyline layer
  activeProfile: 'A',
  mode: 'demo',
  selectedKey: null,
};

/* ==========================================================================
   Pure next-move computation — mirrors find_next_window EXACTLY
   (src/gps2asp/schedule/next_move.py lines 91–176): 8-day lookahead
   (today + 7), first window whose start is strictly in the future wins, all
   wall-clock reasoning pinned to America/New_York (never the naive local
   Date, RESEARCH Pitfall 1 & 2).
   ========================================================================== */

/** Current wall-clock parts in America/New_York (never the machine's tz). */
function nycNowParts() {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  });
  const p = {};
  for (const part of fmt.formatToParts(new Date())) {
    p[part.type] = part.value;
  }
  let hour = parseInt(p.hour, 10);
  if (hour === 24) hour = 0; // some engines emit "24" for midnight
  return {
    year: parseInt(p.year, 10),
    month: parseInt(p.month, 10),
    day: parseInt(p.day, 10),
    hour,
    minute: parseInt(p.minute, 10),
  };
}

/** "HH:MM" -> minutes-since-midnight. */
function hhmmToMinutes(hhmm) {
  const [h, m] = String(hhmm).split(':').map(Number);
  return h * 60 + m;
}

/**
 * Next upcoming ASP window computed from the stored weekly pattern.
 *
 * @param {Array<{day:number,start:string,end:string,sign:string}>} weekly
 * @returns {null | {date:Date, day:number, offset:number, start:string,
 *                   end:string, sign:string, isToday:boolean}}
 */
function computeNextMove(weekly) {
  if (!Array.isArray(weekly) || weekly.length === 0) return null;

  const now = nycNowParts();
  const nowMinutes = now.hour * 60 + now.minute;
  // Use a UTC Date purely as a calendar for the NYC "today" date so day
  // arithmetic and weekday extraction are immune to the machine's timezone.
  const baseMs = Date.UTC(now.year, now.month - 1, now.day);

  for (let offset = 0; offset < 8; offset++) {
    const candidate = new Date(baseMs + offset * 86400000);
    // JS getDay()/getUTCDay() is Sunday=0..Saturday=6; convert to the Python
    // Mon=0..Sun=6 ASPDay convention via (getUTCDay() + 6) % 7.
    const jsDay = candidate.getUTCDay();
    const pyDay = (jsDay + 6) % 7;

    // windows_for_day equivalent: preserve stored order (mirrors Python).
    const dayWindows = weekly.filter((w) => w.day === pyDay);
    for (const w of dayWindows) {
      const startMinutes = hhmmToMinutes(w.start);
      // Later calendar days are always in the future; today only if the
      // start is strictly greater than the current NYC time.
      const isFuture = offset > 0 ? true : startMinutes > nowMinutes;
      if (isFuture) {
        return {
          date: candidate,
          day: pyDay,
          offset,
          start: w.start,
          end: w.end,
          sign: w.sign,
          isToday: offset === 0,
        };
      }
    }
  }
  return null;
}

/* ==========================================================================
   Small formatting helpers
   ========================================================================== */

/** "08:30" -> "8:30 AM". */
function to12Hour(hhmm) {
  const [h, m] = String(hhmm).split(':').map(Number);
  const period = h < 12 ? 'AM' : 'PM';
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${String(m).padStart(2, '0')} ${period}`;
}

/** Human relative label for the next-move state string. */
function relativeDayLabel(move) {
  if (move.isToday) return 'Today';
  if (move.offset === 1) return 'Tomorrow';
  return DAY_NAMES[move.day];
}

/** Whether a point entry carries a real weekly ASP schedule. */
function hasSchedule(point) {
  return point.status === 'schedule_found' || point.status === 'asp_active_now';
}

/* ==========================================================================
   DOM helpers — text-only rendering (never the HTML-parsing sink)
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

/** Build an attributes <tbody> from a plain object using textContent only. */
function renderAttrs(tbodyId, attributes) {
  const tbody = el(tbodyId);
  if (!tbody) return;
  tbody.textContent = ''; // clear via textContent, not the HTML-parsing sink
  if (!attributes) return;
  for (const [key, value] of Object.entries(attributes)) {
    const tr = document.createElement('tr');
    const tdKey = document.createElement('td');
    const tdVal = document.createElement('td');
    tdKey.textContent = key;
    tdVal.textContent = Array.isArray(value) ? value.join(', ') : String(value);
    tr.appendChild(tdKey);
    tr.appendChild(tdVal);
    tbody.appendChild(tr);
  }
}

/* ==========================================================================
   Surface 2 — restriction readout + state chip
   ========================================================================== */

function renderReadout(point, move) {
  show(el('readout'));

  // Summary copy — scripted for non-schedule states (Copywriting Contract).
  let summary;
  if (hasSchedule(point)) {
    summary = point.summary || 'Alternate-side parking applies on this block.';
  } else if (point.status === 'no_asp') {
    summary = "No alternate-side rules on this block. The sensor reports 'No restrictions'.";
  } else {
    summary = 'This block is outside the demo dataset. In Home Assistant the '
      + "sensor reports 'Outside coverage area'.";
  }
  setText('restriction-summary', summary);

  // Meta line: street + cross-streets + side label (all via textContent).
  const metaParts = [];
  if (point.on_street) metaParts.push(point.on_street);
  if (point.from_street && point.to_street) {
    metaParts.push(`${point.from_street} to ${point.to_street}`);
  }
  if (point.side_label) metaParts.push(point.side_label);
  setText('restriction-meta', metaParts.join(' · '));

  // State chip: positive = no restrictions, warning = move today, else neutral.
  const chip = el('state-chip');
  if (chip) {
    let chipClass = 'chip-neutral';
    let chipText = '';
    if (point.status === 'no_asp') {
      chipClass = 'chip-positive';
      chipText = 'No restrictions';
    } else if (!hasSchedule(point)) {
      chipClass = 'chip-neutral';
      chipText = 'Outside coverage area';
    } else if (move && move.isToday) {
      chipClass = 'chip-warning';
      chipText = 'Move today';
    } else if (move) {
      chipClass = 'chip-neutral';
      chipText = `Next move ${relativeDayLabel(move)}`;
    }
    chip.className = `chip ${chipClass}`;
    chip.textContent = chipText;
  }
}

/* ==========================================================================
   Surface 3 — mock Home Assistant sensor card
   ========================================================================== */

function renderHaCard(point) {
  const card = el('ha-card');
  const sensors = point.sensors;
  if (!sensors) {
    hide(card);
    return;
  }
  show(card);

  // Primary next-move sensor (entity id + stable attributes; the large
  // date-relative state string is set in renderCalendar).
  const nextMove = sensors.next_move || {};
  setText('sensor-next-move-entity', nextMove.entity_id
    || 'sensor.asp_parking_monitor_next_move_time');
  renderAttrs('sensor-next-move-attrs', nextMove.attributes);

  // Secondary resolved-street sensor.
  const resolved = sensors.resolved_street || {};
  setText('sensor-resolved-entity', resolved.entity_id
    || 'sensor.asp_parking_monitor_resolved_street');
  renderAttrs('sensor-resolved-attrs', resolved.attributes);
}

/** Build a copy-pasteable HA config snippet for the selected block. */
function buildYamlSnippet(point) {
  const lines = [
    '# GPS2ASP-Resolver — Home Assistant configuration',
    '# Reproduces the sensors shown in this demo for one location.',
    'sensor:',
    '  - platform: asp_parking',
    `    name: "${(point.on_street || 'ASP Parking Monitor').replace(/"/g, "'")}"`,
    `    latitude: ${point.lat}`,
    `    longitude: ${point.lon}`,
  ];
  return lines.join('\n');
}

function wireCopyYaml() {
  const btn = el('copy-yaml');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    const point = state.selectedKey && state.data
      ? state.data.points[state.selectedKey]
      : null;
    if (!point) return;
    const yaml = buildYamlSnippet(point);
    try {
      await navigator.clipboard.writeText(yaml);
      setText('copy-status', 'Copied!');
    } catch (err) {
      setText('copy-status', 'Copy failed — select the text manually.');
    }
    window.setTimeout(() => setText('copy-status', ''), 2000);
  });
}

/* ==========================================================================
   Surface 4 — animated next-move calendar
   ========================================================================== */

function renderCalendar(point, move) {
  const calendar = el('calendar');
  const card = document.querySelector('.calendar-card');
  show(card);
  setText('calendar-caption', 'Next move (NYC time)');
  if (!calendar) return;

  calendar.textContent = ''; // clear via textContent, not the HTML-parsing sink

  // Non-schedule states: show scripted copy instead of a highlighted day.
  if (!move) {
    const note = document.createElement('p');
    note.className = 'label muted';
    note.textContent = hasSchedule(point)
      ? 'No upcoming move found in the next 8 days.'
      : 'No scheduled move for this block.';
    calendar.appendChild(note);
    setText('sensor-next-move-state', point.status === 'no_asp'
      ? 'No restrictions'
      : 'Outside coverage area');
    return;
  }

  const now = nycNowParts();
  const baseMs = Date.UTC(now.year, now.month - 1, now.day);
  const tooltip = (point.sensors
    && point.sensors.next_move
    && point.sensors.next_move.attributes
    && point.sensors.next_move.attributes.schedule_summary)
    || point.summary || '';

  // Seven cells, one per upcoming weekday (offsets 0..6 cover all 7 weekdays).
  for (let offset = 0; offset < 7; offset++) {
    const candidate = new Date(baseMs + offset * 86400000);
    const pyDay = (candidate.getUTCDay() + 6) % 7;

    const cell = document.createElement('div');
    cell.className = 'calendar-day';

    const isNext = move.day === pyDay;
    if (isNext) {
      cell.classList.add(move.isToday && offset === 0 ? 'is-today' : 'is-next');
      if (tooltip) cell.title = tooltip;
    }

    const dow = document.createElement('span');
    dow.textContent = DAY_ABBR[pyDay];
    cell.appendChild(dow);

    if (isNext) {
      const timeLabel = document.createElement('span');
      timeLabel.textContent = to12Hour(move.start);
      cell.appendChild(timeLabel);
    }

    calendar.appendChild(cell);
  }

  // Large date-relative sensor state string (formatted at NYC time).
  const prefix = move.isToday ? '⚠ ' : ''; // ⚠ for "today"
  setText('sensor-next-move-state',
    `${prefix}${relativeDayLabel(move)}, ${to12Hour(move.start)}`);
}

/* ==========================================================================
   Map + selection
   ========================================================================== */

function clearOverlay() {
  if (state.overlay && state.map) {
    state.map.removeLayer(state.overlay);
    state.overlay = null;
  }
}

function drawSegment(key) {
  clearOverlay();
  if (!state.geo || !state.map) return;
  const feature = state.geo.features.find(
    (f) => f.properties && f.properties.point_key === key,
  );
  if (!feature) return;
  state.overlay = L.geoJSON(feature, {
    style: { color: ACCENT, weight: 5, opacity: 0.9 },
  }).addTo(state.map);
}

function highlightMarker(key) {
  for (const [k, marker] of Object.entries(state.markers)) {
    if (k === key) {
      marker.setStyle({ weight: 2, color: '#ffffff' }); // 2px white selection ring
    } else {
      marker.setStyle({ weight: 0 });
    }
  }
}

function selectPoint(key) {
  if (!state.data) return;
  const point = state.data.points[key];
  if (!point) return;

  state.selectedKey = key;
  hide(el('empty-state'));

  drawSegment(key);
  highlightMarker(key);

  const move = computeNextMove(point.weekly);
  renderReadout(point, move);
  renderHaCard(point);
  renderCalendar(point, move);
}

function addMarkers() {
  if (!state.data || !state.map) return;
  for (const [key, point] of Object.entries(state.data.points)) {
    if (typeof point.lat !== 'number' || typeof point.lon !== 'number') continue;
    const marker = L.circleMarker([point.lat, point.lon], {
      radius: 9,
      color: '#ffffff',
      weight: 0,
      fillColor: ACCENT,
      fillOpacity: 1,
      className: 'demo-pin',
    }).addTo(state.map);

    marker.on('click', () => selectPoint(key));

    // Keyboard operability: make the SVG node focusable and Enter/Space active.
    const node = marker.getElement && marker.getElement();
    if (node) {
      node.setAttribute('tabindex', '0');
      node.setAttribute('role', 'button');
      node.setAttribute('aria-label', `Check block ${point.on_street || key}`);
      node.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
          e.preventDefault();
          selectPoint(key);
        }
      });
    }

    state.markers[key] = marker;
  }
}

function initMap() {
  state.map = L.map('map').setView(MAP_CENTER, MAP_ZOOM);
  L.tileLayer(TILE_URL, {
    maxZoom: MAX_ZOOM,
    attribution: TILE_ATTRIBUTION,
  }).addTo(state.map);
  // Leaflet collapses to 0px if the container was laid out after init (Pitfall 7).
  state.map.invalidateSize();
  window.setTimeout(() => state.map.invalidateSize(), 200);
}

/* ==========================================================================
   Profile radiogroup + demo/full mode toggle
   ========================================================================== */

function setRadioState(groupId, activeId) {
  const group = el(groupId);
  if (!group) return;
  for (const btn of group.querySelectorAll('[role="radio"]')) {
    btn.setAttribute('aria-checked', btn.id === activeId ? 'true' : 'false');
  }
}

function wireProfileToggle() {
  const group = el('profile-toggle');
  if (!group) return;
  group.addEventListener('click', (e) => {
    const btn = e.target.closest('[role="radio"]');
    if (!btn) return;
    activateProfile(btn.dataset.profile, btn.id);
  });
  group.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
    const btn = e.target.closest('[role="radio"]');
    if (!btn) return;
    e.preventDefault();
    activateProfile(btn.dataset.profile, btn.id);
  });
}

function activateProfile(profileKey, btnId) {
  if (!state.data || !state.data.profiles || !state.data.profiles[profileKey]) return;
  state.activeProfile = profileKey;
  setRadioState('profile-toggle', btnId);
  // Re-render all downstream surfaces from the loaded dataset — NO network call.
  const pointKey = state.data.profiles[profileKey].point_key;
  selectPoint(pointKey);
}

function wireModeToggle() {
  const group = el('mode-toggle');
  if (!group) return;
  group.addEventListener('click', (e) => {
    const btn = e.target.closest('[role="radio"]');
    if (!btn) return;
    activateMode(btn.dataset.mode, btn.id);
  });
  group.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
    const btn = e.target.closest('[role="radio"]');
    if (!btn) return;
    e.preventDefault();
    activateMode(btn.dataset.mode, btn.id);
  });
}

function activateMode(mode, btnId) {
  state.mode = mode;
  setRadioState('mode-toggle', btnId);
  if (mode === 'full') {
    if (FULL_RESOLVER_ENDPOINT) {
      // Inert-by-default branch: a maintainer who sets FULL_RESOLVER_ENDPOINT
      // to a URL activates a live fetch for the selected pin. Kept present but
      // never exercised while the constant is null (no backend this phase).
      setText('mode-status', 'Full resolver mode active.');
      if (state.selectedKey) {
        fetchFullResolver(state.selectedKey);
      }
    } else {
      setText('mode-status',
        'Full resolver backend not configured — showing demo data');
      // Stay on the committed demo dataset; no network request is made.
    }
  } else {
    setText('mode-status', '');
  }
}

/** Guarded live-resolver path — only reachable when an endpoint is configured. */
async function fetchFullResolver(key) {
  if (!FULL_RESOLVER_ENDPOINT) return; // hard guard: inert by default
  const point = state.data && state.data.points[key];
  if (!point) return;
  try {
    const url = `${FULL_RESOLVER_ENDPOINT}?lat=${point.lat}&lon=${point.lon}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    // A live backend would return the same point shape; render it directly.
    const live = await res.json();
    state.data.points[key] = live;
    selectPoint(key);
  } catch (err) {
    setText('mode-status', 'Full resolver request failed — showing demo data.');
  }
}

/* ==========================================================================
   Bootstrap
   ========================================================================== */

async function loadDataset() {
  const [dataRes, geoRes] = await Promise.all([
    fetch('data/demo.json'),
    fetch('data/demo-segments.geojson'),
  ]);
  if (!dataRes.ok || !geoRes.ok) {
    throw new Error('dataset fetch failed');
  }
  // Parse with the standard JSON parser only — never eval/dynamic evaluation.
  state.data = await dataRes.json();
  state.geo = await geoRes.json();
}

async function init() {
  try {
    await loadDataset();
  } catch (err) {
    show(el('error-state'));
    return;
  }

  setText('data-freshness',
    `Demo data snapshot: ${state.data.generation_date}. Live results may differ.`);

  initMap();
  addMarkers();

  wireProfileToggle();
  wireModeToggle();
  wireCopyYaml();

  // Empty state stays until the user (or a profile switch) selects a pin.
  show(el('empty-state'));
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}

/* Node-testability: expose the pure function without affecting the browser
   (module is undefined under the deferred <script> tag). */
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { computeNextMove };
}
