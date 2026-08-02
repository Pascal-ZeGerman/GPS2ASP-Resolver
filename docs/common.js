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
