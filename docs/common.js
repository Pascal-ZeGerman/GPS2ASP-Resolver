/* ==========================================================================
   Shared DOM helpers for the static docs/demo/ and docs/explorer/ pages —
   text-only rendering (never the HTML-parsing sink). Loaded as a plain,
   non-module `defer` <script> BEFORE each page's own app.js, so these
   functions land in the shared global scope both controllers already run in
   (no bundler, no npm import — same constraint as app.js itself).
   ========================================================================== */

'use strict';

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

/* Python ASPDay convention: Monday = 0 .. Sunday = 6 (matches weekly[].day
   / wk[].d in both docs/demo/data/demo.json and docs/explorer/data/coverage.json). */
const DAY_ABBR = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** Whether a point entry carries a real weekly ASP schedule. */
function hasSchedule(point) {
  return point.status === 'schedule_found' || point.status === 'asp_active_now';
}

/** Build one <tr> with a key cell and a value cell, both textContent-set. */
function buildAttrRow(key, value) {
  const tr = document.createElement('tr');
  const tdKey = document.createElement('td');
  const tdVal = document.createElement('td');
  tdKey.textContent = key;
  tdVal.textContent = value == null ? '' : String(value);
  tr.appendChild(tdKey);
  tr.appendChild(tdVal);
  return tr;
}
