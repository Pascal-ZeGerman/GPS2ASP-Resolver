---
phase: 16-queens-coverage-fix-geocoded-fixtures
plan: 01
subsystem: coverage
tags: [geocoding, geosearch, soda, fixtures, queens, audit]

requires:
  - phase: 15-queens-and-manhattan-coverage-fix
    provides: initial audit script and fixture format
provides:
  - Reusable geocoding script for any borough (scripts/geocode_fixtures.py)
  - 25 address-geocoded Queens residential GPS fixtures
  - L3 diagnostic output in audit script for normalization gap analysis
affects: [16-02, 17-manhattan-fixtures]

tech-stack:
  added: [geosearch-v2-api]
  patterns: [address-geocoded-fixtures, l3-diagnostic-audit]

key-files:
  created:
    - scripts/geocode_fixtures.py
  modified:
    - tests/fixtures/queens_coverage.json
    - scripts/audit_queens_coverage.py

key-decisions:
  - "GeoSearch v2 API used (v1 returns HTTP 410 Gone)"
  - "Geocoding script supports --borough flag for Phase 17 Manhattan reuse"
  - "L3 diagnostics only query SODA for non-L1/L2 rows to avoid doubling API calls"

patterns-established:
  - "Address-geocoded fixtures: use GeoSearch v2 to convert real street addresses to GPS coords"
  - "L3 diagnostic pattern: compare CSCL-sent cross streets vs SODA-available spans"

requirements-completed: [COV-02]

duration: 5min
completed: 2026-03-19
---

# Phase 16 Plan 01: Geocoded Queens Fixtures and L3 Diagnostics Summary

**Geocoded 25 Queens residential addresses via GeoSearch v2 API and extended audit script with CSCL-vs-SODA span diagnostics for Level 3+ failures**

## What Was Done

### Task 1: Geocoding Script and Queens Fixtures (813d3c0)

Created `scripts/geocode_fixtures.py` -- a reusable CLI script that geocodes NYC street addresses into GPS fixture JSON files using the GeoSearch v2 API (`geosearch.planninglabs.nyc/v2/search`).

- Supports `--borough queens` and `--borough manhattan` (Manhattan addresses placeholder for Phase 17)
- Verifies each geocoded result matches the expected borough
- Extracts GeoJSON coordinates correctly: `lat = coords[1]`, `lon = coords[0]`
- 0.5s courtesy delay between requests
- Handles failures gracefully: logs warning, skips address, continues

Regenerated `tests/fixtures/queens_coverage.json` with 25/25 successfully geocoded addresses covering Jamaica (5), Flushing (5), Astoria (5), Jackson Heights (4), Forest Hills (4), and Union Turnpike area (2).

### Task 2: L3 Diagnostic Output in Audit Script (0ea8fcf)

Extended `scripts/audit_queens_coverage.py` with:

- `diagnose_l3()` async function: queries SODA for all spans on a street+side and returns available (from, to) spans with sign counts
- `--verbose` CLI flag: enables L3 diagnostic section in output
- `audit_fixture()` and `print_report()` accept `verbose` parameter
- Diagnostic queries only run for `soda_level >= 3` or error rows (avoids doubling API calls for L1/L2 successes)
- Output format shows CSCL-sent cross streets vs SODA-available spans for each non-L1/L2 row

## Deviations from Plan

None -- plan executed exactly as written.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 813d3c0 | feat(16-01): add geocoding script and regenerate Queens fixtures |
| 2 | 0ea8fcf | feat(16-01): extend audit script with L3 diagnostic output |

## Test Results

All unit tests pass. 7 pre-existing failures are out of scope:
- 1 spatial index test (test_resolve_prospect_heights -- index mismatch)
- 6 socket-blocked integration tests (network-dependent, documented in STATE.md)
