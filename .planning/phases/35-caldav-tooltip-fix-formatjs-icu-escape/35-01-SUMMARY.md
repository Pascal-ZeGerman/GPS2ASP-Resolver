---
phase: 35-caldav-tooltip-fix-formatjs-icu-escape
plan: 01
subsystem: home-assistant-i18n
tags: [home-assistant, i18n, formatjs, icu, strings.json, caldav]

# Dependency graph
requires:
  - phase: 31-ci-guard-strings-json-sync
    provides: byte-identity discipline between strings.json and translations/en.json (manual diff convention preserved)
  - phase: 34-caldav-calendar-integration
    provides: the CalDAV options-flow tooltip + caldav_invalid_template error string that this phase fixes (CALDAV-09 requirement)
provides:
  - ICU-escaped CalDAV tooltip and error strings (lines 115 and 132 of both JSON files)
  - tests/test_strings_icu_escape.py (4 deterministic unit tests as regression guard against raw-brace re-introduction)
affects:
  - any future i18n string edit in custom_components/asp_parking/ (must use ICU '{name}' escape for literal braces)
  - future Phase 31 follow-ups (automated CI guard for byte-identity is still manual)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ICU MessageFormat single-quote-wrap escape: wrap every literal `{name}` in ASCII U+0027 apostrophes so FormatJS treats it as a quoted literal, not an i18n argument slot"
    - "Two-pipeline discipline for `{name}` tokens: frontend (FormatJS, needs ICU escape) vs backend (Python `str.format_map`, raw braces correct)"
    - "JSON-content regression test pattern: `Path(__file__).resolve().parent.parent` anchoring + `json.loads(path.read_text())` + key-path navigation + regex assertions (analog: tests/test_sync_vendored.py)"

key-files:
  created:
    - "tests/test_strings_icu_escape.py — 4 unit tests covering CALDAV-09"
  modified:
    - "custom_components/asp_parking/strings.json — lines 115 and 132 ICU-escaped"
    - "custom_components/asp_parking/translations/en.json — same two-line edit (byte-identical)"

key-decisions:
  - "Apply ICU single-quote-wrap '{name}' escape (not Mustache `{{name}}` or backslash `\\{name\\}`) — both alternatives raise FormatJS MALFORMED_ARGUMENT (per RESEARCH.md empirical verification)"
  - "Did NOT touch any .py file — Python const DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE in const.py:78 uses raw {street} correctly for str.format_map"
  - "Phase 31 byte-identity preserved via paired Edit calls and post-edit diff; no new CI automation added (out of scope per RESEARCH.md Open Question 1)"

patterns-established:
  - "ICU literal-brace escape for HA strings.json: ASCII U+0027 apostrophe wrap (`'{name}'`); never U+2019, never doubled braces, never backslash"
  - "Two-pipeline mental model: a `{name}` in JSON is rendered by FormatJS (frontend) — needs escape; the SAME-looking token in a Python module is parsed by str.format_map (backend) — never escape"

requirements-completed:
  - CALDAV-09

# Metrics
duration: 4min
completed: 2026-05-20
---

# Phase 35 Plan 01: CalDAV Tooltip Fix (FormatJS ICU Escape) Summary

**Single-quote-wrap escape of 7 literal `{street}`/`{time}`/`{side}` placeholders across 2 lines × 2 JSON files, closing CALDAV-09 by stopping the HA frontend FormatJS MISSING_VALUE overlay on the CalDAV options-flow tooltip and validation-error message.**

## Performance

- **Duration:** 4 min (Task 1: ~1 min, Task 2: ~1 min, Task 3: ~22s pytest, paperwork: ~2 min)
- **Started:** 2026-05-20T02:47:17Z
- **Completed:** 2026-05-20T02:50:51Z
- **Tasks:** 3 of 4 executed (Task 4 is `checkpoint:human-verify` — pending operator UAT)
- **Files modified:** 3 (1 created, 2 edited)

## Accomplishments

- ICU-escaped tooltip (line 115) — `caldav_event_title_template` now reads `"Title template. Placeholders: '{street}', '{time}', '{side}'. Default: ASP: '{street}'."` in both `strings.json` and `translations/en.json`.
- ICU-escaped error string (line 132) — `caldav_invalid_template` now reads `"Invalid title template. Use only plain text and supported placeholders: '{street}', '{side}', '{time}'."` in both files (note: `'{side}'` precedes `'{time}'` on this line — order preserved from original).
- All 7 raw `{name}` occurrences replaced with the wrapped `'{name}'` form using ASCII U+0027 (verified via `grep -o`: 3 `'{street}'`, 2 `'{time}'`, 2 `'{side}'` per file).
- `strings.json` ↔ `translations/en.json` byte-identity preserved (Phase 31 discipline; `diff` exits 0).
- New `tests/test_strings_icu_escape.py` with 4 deterministic offline unit tests as a permanent regression guard.
- Full offline pytest suite green (570 passed / 158 deselected / 0 failed, 21s runtime).
- Python runtime path (`const.py:78` DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE and `caldav_sync.py` render_title) UNCHANGED — confirmed via `git diff --name-only | grep '\.py$'` returning empty (Pitfall 5 avoided).

## Task Commits

Each task was committed atomically on branch `worktree-agent-a7256825dc78093cd`:

1. **Task 1: Failing ICU-escape unit test scaffold** — `a47c6f4` (test)
   - Created `tests/test_strings_icu_escape.py` with 4 module-level test functions.
   - RED state confirmed: 3 of 4 tests failed against unfixed JSON (`test_caldav_event_title_template_is_icu_escaped`, `test_caldav_invalid_template_is_icu_escaped`, `test_no_raw_curly_placeholders`); `test_strings_and_en_json_byte_identical` started GREEN.
2. **Task 2: ICU single-quote-wrap escape applied to both JSON files** — `fb7a344` (fix)
   - Two paired `Edit` calls per file (4 total Edits) — lines 115 and 132 in `strings.json` and `translations/en.json`.
   - GREEN state confirmed: all 4 unit tests pass; `diff` exits 0; both files parse as valid JSON.
3. **Task 3: Full non-integration suite regression gate** — no commit (verification-only task; plan `<files></files>` is empty).
   - `.venv/bin/python -m pytest -m "not integration and not ha_integration"` → 570 passed, 0 failed, 21.08s.
   - Zero git diff introduced (`git status --porcelain` empty after the run).
4. **Task 4: Human UAT — verify live HA tooltip + error rendering** — `checkpoint:human-verify`, NOT executed by this agent. See "Awaiting UAT" section below.

**Plan metadata commit:** added with this SUMMARY (separate from per-task commits per execute-plan.md `<final_commit>`).

## Files Created/Modified

- `tests/test_strings_icu_escape.py` — **created**. 4 module-level pytest tests: `test_caldav_event_title_template_is_icu_escaped`, `test_caldav_invalid_template_is_icu_escaped`, `test_strings_and_en_json_byte_identical`, `test_no_raw_curly_placeholders`. Path-anchored via `Path(__file__).resolve().parent.parent`. No HA imports, no markers — picked up by the offline suite filter `not integration and not ha_integration`.
- `custom_components/asp_parking/strings.json` — **modified**, lines 115 and 132. ICU-escape applied to 7 placeholder occurrences (4 on line 115, 3 on line 132).
- `custom_components/asp_parking/translations/en.json` — **modified**, lines 115 and 132. Identical edit; remains byte-identical to `strings.json`.

## Decisions Made

- Followed plan as specified — no deviations triggered.
- Used `Edit` (not `sed` or `Write` rewrite) per CLAUDE.md "Native Tools Over Shell Commands" and RESEARCH.md §Project Constraints. Two paired Edits per file (one for each affected line).
- Used `.venv/bin/python -m pytest` instead of the missing `.venv/bin/pytest` entrypoint binary (the binary entrypoint is absent in this venv layout; the pytest module is installed and works via `-m pytest`). No deviation — same test runner, same configuration.

## Deviations from Plan

None — plan executed exactly as written. Zero auto-fixes triggered (Rules 1, 2, 3 did not fire); no architectural decisions deferred (Rule 4 did not fire).

## Issues Encountered

- **Minor:** Plan acceptance criteria for Task 2 used `grep -c "'{street}'"` (line-count) with expected value `3`, which actually returns `2` (the pattern appears on 2 distinct lines). The intent was clearly "3 occurrences" — `grep -o ... | wc -l` returns `3` as expected. Not a deviation; the verification block at the plan tail (line 399) used the same shorthand. Recorded here for future planner-side cleanup.
- No browser cache flush noted (Task 4 not yet executed; if UAT operator sees stale rendering, RESEARCH.md §Runtime State Inventory and Task 4 step 7 cover the hard-refresh fallback).

## Self-Check

Verified before SUMMARY commit:

- **Files exist:**
  - `tests/test_strings_icu_escape.py` — FOUND
  - `custom_components/asp_parking/strings.json` (modified) — FOUND
  - `custom_components/asp_parking/translations/en.json` (modified) — FOUND
- **Commits exist:**
  - `a47c6f4` (Task 1, test) — FOUND in `git log`
  - `fb7a344` (Task 2, fix) — FOUND in `git log`
- **Phase verification cross-check (from PLAN §verification):**
  - `git diff --name-only` vs base shows exactly 3 files — ✓
  - `diff strings.json translations/en.json` exits 0 — ✓
  - `grep -o "'{street}'" strings.json | wc -l` returns 3, same for en.json — ✓
  - `grep -nE "(^|[^'])\{(street|time|side)\}([^']|$)"` returns empty in both files — ✓
  - JSON parse on both files exits 0 — ✓
  - U+2019 count is 0 in both files — ✓
  - `const.py:78 DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE = "ASP: {street}"` — UNCHANGED ✓
  - No `.py` files in diff vs HEAD~1 (only Task 1 added the test file; Task 2's diff is JSON-only) — ✓
  - Vendored mirror under `custom_components/asp_parking/gps2asp/` untouched — ✓
- **TDD gate compliance:**
  - `test(35-01)` commit `a47c6f4` exists (RED gate) — ✓
  - `fix(35-01)` commit `fb7a344` exists after the test commit (GREEN gate; `fix` accepted in lieu of `feat` because the source-of-truth change was a correctness patch to existing strings, not new functionality) — ✓
  - REFACTOR phase: not applicable (3-character-per-occurrence edit, no further cleanup possible)

**Self-Check: PASSED**

## Known Stubs

None. The fix is content-only and complete; no placeholder UI, no mocked data path, no "coming soon" text.

## TDD Gate Compliance

Task 1 was `type="auto" tdd="true"` and the plan operates as a single TDD cycle:

- **RED:** `a47c6f4` (`test(35-01)`) — 3 of 4 tests fail against unfixed JSON (`test_strings_and_en_json_byte_identical` starts GREEN as a byte-identity baseline guard for Task 2).
- **GREEN:** `fb7a344` (`fix(35-01)`) — all 4 tests pass after the JSON edits. Commit type is `fix` rather than `feat` because Phase 35 corrects an existing-string defect (no new behavior was added). The TDD gate sequence is preserved (test commit precedes fix commit).
- **REFACTOR:** Not applicable. No further cleanup possible on a 3-character escape.

## User Setup Required

None. The fix is shipped in the integration's JSON files and takes effect on next HA reload. The user MAY need to hard-refresh their browser (Ctrl+Shift+R / Cmd+Shift+R) after reload because HA caches translation files per-session — see RESEARCH.md §Runtime State Inventory.

## Awaiting UAT (Task 4)

Task 4 is a `checkpoint:human-verify` task and was NOT executed by this autonomous agent. The orchestrator must pause the workflow and present the verification procedure to the human operator. The procedure (verbatim from PLAN §Task 4 `<how-to-verify>`):

1. Deploy this branch to a live HA instance with the ASP Parking integration installed (e.g. copy `custom_components/asp_parking/` to the HA `config/custom_components/` directory, or restart HA so it picks up the updated integration files).
2. In HA, navigate: **Settings → Devices & Services → ASP Parking → Configure** → step into the "CalDAV" options page (the step labeled `caldav`).
3. Locate the "Event title template" form field. Read the help text directly under or next to that field.
4. **Expected:** the text reads literally `Title template. Placeholders: {street}, {time}, {side}. Default: ASP: {street}.` — curly braces visible, NO formatjs error overlay, NO `MISSING_VALUE` text, NO red banner.
5. In the same form, type an invalid template such as `ASP: {bogus_field}` and submit.
6. **Expected:** the form returns the error message `Invalid title template. Use only plain text and supported placeholders: {street}, {side}, {time}.` — again with curly braces visible and no formatjs overlay.
7. If you previously viewed this options page before the fix, hard-refresh the browser (Ctrl+Shift+R / Cmd+Shift+R) — HA caches translations per-session.
8. If either expected text does NOT render correctly (e.g., apostrophes visible in output → smart-quote slip; formatjs overlay still present → check quote balance), capture a screenshot and report back so the plan can be re-opened.

**Resume signal:** Type `approved` after confirming both renders match expected literal text; otherwise describe which render still shows a formatjs error.

## Next Phase Readiness

- CALDAV-09 implementation complete in code; phase closure pending UAT.
- No follow-up phases blocked on this work — the fix is localized to two strings.
- A future quick task may automate the byte-identity guard (RESEARCH.md §Open Question 1); explicitly out of scope per the plan's anti-scope-creep posture.

---
*Phase: 35-caldav-tooltip-fix-formatjs-icu-escape*
*Completed: 2026-05-20 (Tasks 1-3; Task 4 awaiting human UAT)*
