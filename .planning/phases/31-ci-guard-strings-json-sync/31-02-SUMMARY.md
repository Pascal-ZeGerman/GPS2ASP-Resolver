---
phase: 31-ci-guard-strings-json-sync
plan: 02
subsystem: infra
tags:
  - ci
  - github-actions
  - vendored-mirror
  - i18n
  - strings
  - python

# Dependency graph
requires:
  - phase: 31-ci-guard-strings-json-sync
    provides: "Plan 01 — scripts/sync_vendored.py (normalize_source + iter_source_files + main CLI with --dry-run)"
provides:
  - "scripts/sync_vendored.py invoked once in write mode to resolve 10 drifted vendored .py files (D-06, D-07)"
  - ".github/workflows/vendor-guard.yml — single-job GitHub Actions workflow that fails CI on any future vendored-mirror drift (D-04, D-05)"
  - "custom_components/asp_parking/strings.json byte-identical to translations/en.json (suppress_notifications key added; D-08, CI-02)"
affects:
  - "v3.2 feature phases (32, 33, 34) — inherit a clean baseline: any edit to src/gps2asp/ that forgets to re-sync vendored will fail the new vendor-guard workflow on PR"
  - "Any phase that adds new HA UI strings — strings.json and translations/en.json must be edited together (no automated guard, but baseline is now identical)"

# Tech tracking
tech-stack:
  added:
    - "GitHub Actions: actions/checkout@v4 + actions/setup-python@v5 + python-version: \"3.14\" — already established by pytest.yml, codeql.yml; now also used by vendor-guard.yml"
  patterns:
    - "Vendored-mirror sync as a pure script + CI dry-run pattern (write mode for developers, --dry-run for CI)"
    - "Dedicated single-job workflow per repo-wide invariant (mirrors hassfest.yml shape)"
    - "Workflow trigger block convention: `on.push.branches: [\"**\"]` AND `on.pull_request.branches: [\"**\"]` — matches every other workflow in the repo"

key-files:
  created:
    - ".github/workflows/vendor-guard.yml"
  modified:
    - "custom_components/asp_parking/gps2asp/__init__.py (vendored sync — adds exception re-exports)"
    - "custom_components/asp_parking/gps2asp/pipeline.py (vendored sync — docstring fix)"
    - "custom_components/asp_parking/gps2asp/resolver/__init__.py (vendored sync — imports _NEAR_INTERSECTION_THRESHOLD_FT from confidence)"
    - "custom_components/asp_parking/gps2asp/resolver/confidence.py (vendored sync — comment text)"
    - "custom_components/asp_parking/gps2asp/resolver/side_resolver.py (vendored sync — comment text + docstring)"
    - "custom_components/asp_parking/gps2asp/resolver/spatial_index.py (vendored sync — D-07: lazy ClassVar[asyncio.Lock | None])"
    - "custom_components/asp_parking/gps2asp/schedule/merge.py (vendored sync — import style)"
    - "custom_components/asp_parking/gps2asp/schedule/next_move.py (vendored sync — docstring wording)"
    - "custom_components/asp_parking/gps2asp/signs/__init__.py (vendored sync — import style)"
    - "custom_components/asp_parking/gps2asp/signs/client.py (vendored sync — D-07: explicit RuntimeError replaces assert)"
    - "custom_components/asp_parking/strings.json (added suppress_notifications key + comma on preceding line)"

key-decisions:
  - "Used the project venv at /home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/.venv (Python 3.13) for local runs — no separate venv inside the worktree. Verified tests + dry-run all green from this path."
  - "Discovered only 10 of the 26 vendored .py files were drifted (not 14 as projected in 31-RESEARCH.md §\"Current divergence resolution\"). The 4 files that were already in sync — schedule/__init__.py, schedule/parser.py, schedule/summary.py, resolver/converter.py — required no rewrite. The script's count (\"Synced 10 file(s); 16 already up to date.\") is the authoritative measurement; the plan's count is informational per its own caveat (\"the count line is informational — exit code 0 is the binding contract\")."
  - "Did NOT include a literal `diff -r` step in vendor-guard.yml; --dry-run is the equivalent per RESEARCH.md anti-pattern guidance and the ROADMAP success criterion (\"diff ... or equivalent\")."
  - "Did NOT include `cache: \"pip\"` in setup-python step — vendor-guard installs zero packages (stdlib only); pip caching would be a no-op."

patterns-established:
  - "Vendored-mirror guard pattern: a pure normalization function + thin CLI shell with --dry-run for CI and write mode for developers; the --dry-run mode IS the CI check (no separate diff step)"
  - "strings.json / translations/en.json byte-identity discipline: cmp -s exits 0 after every edit that touches user-facing copy (no automated guard yet; documented for downstream phases)"

requirements-completed:
  - CI-01
  - CI-02

# Metrics
duration: 9min
completed: 2026-05-11
---

# Phase 31 Plan 02: CI Guard & strings.json Sync (Deliverables) Summary

**vendor-guard.yml + scripts/sync_vendored.py one-time write run resolved 10 drifted vendored .py files (incl. the two D-07 logic diffs); strings.json now byte-identical to translations/en.json via the suppress_notifications add.**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-05-11T13:53Z
- **Completed:** 2026-05-11T14:02:57Z
- **Tasks:** 2 / 2
- **Files modified:** 12 (10 vendored .py + 1 workflow + 1 strings.json)

## Accomplishments

- Ran `scripts/sync_vendored.py` (from Plan 01) in write mode. 10 of 26 vendored `.py` files were drifted; all were overwritten with source-normalized bytes. Round-trip `--dry-run` exits 0.
- Both D-07 logic changes landed in vendored:
  - `custom_components/asp_parking/gps2asp/resolver/spatial_index.py` — `_lock: ClassVar[asyncio.Lock | None] = None` with lazy init (comment "lazily created to avoid pre-loop init" preserved).
  - `custom_components/asp_parking/gps2asp/signs/client.py` — `raise RuntimeError("unreachable: retry loop exited without recording an error")` (the previous `assert last_error is not None` is gone — grep returns 0).
- Added `.github/workflows/vendor-guard.yml`: single job `vendor-guard`, triggers on push and pull_request across all branches (`["**"]`), Python 3.14 via `actions/setup-python@v5`, runs `python scripts/sync_vendored.py --dry-run`. No `cache: "pip"`, no literal `diff -r`.
- Added `suppress_notifications` key under `options.step.debug.data` in `custom_components/asp_parking/strings.json`. Trailing comma added to preceding `debug_datetime` line. `cmp -s strings.json translations/en.json` exits 0.
- Full quick pytest suite (403 tests) remains green after both commits; Plan 01's `tests/test_sync_vendored.py` (27 tests) still all green.

## Task Commits

Each task was committed atomically in the order required by the plan (vendored sync MUST precede the workflow file so the workflow's first CI run is green):

1. **Task 1: Run `sync_vendored.py` in write mode** — `f53ca8a` (chore)
2. **Task 2: Add vendor-guard.yml + sync strings.json** — `2775c75` (feat)

_Note: Task 1 was a `chore` because it is a mechanical mirror sync (no behavior change in shipped HA code beyond resolving the D-07 logic diffs). Task 2 was `feat` because it adds a new CI workflow + a new HA UI string._

## Files Created/Modified

### Created

- `.github/workflows/vendor-guard.yml` (20 lines, 626 bytes) — single-job CI workflow invoking `python scripts/sync_vendored.py --dry-run` on every push and pull_request across all branches. Quoted `python-version: "3.14"` (unquoted parses as 3.4). No pip caching (no packages installed).

### Modified — vendored sync (Task 1, 10 .py files, +43 / −15)

Per-file disposition (compared to the in-tree baseline at HEAD before Task 1):

| File | Disposition | Plan 31-RESEARCH ref |
|------|-------------|----------------------|
| `custom_components/asp_parking/gps2asp/__init__.py` | Missing exports + imports for `IndexNotFoundError`, `SODAAPIError`, `IncompleteResultsError` added; relative-import normalization | §1 "current divergence resolution" |
| `custom_components/asp_parking/gps2asp/pipeline.py` | Missing docstring line (`IndexNotFoundError: Spatial index files are absent (index not built).`) added | §2 |
| `custom_components/asp_parking/gps2asp/resolver/__init__.py` | `_NEAR_INTERSECTION_THRESHOLD_FT` now imported from `.confidence` (instead of redefined); comment text aligned with source | §3 |
| `custom_components/asp_parking/gps2asp/resolver/confidence.py` | Comment text aligned ("imported by resolver/__init__.py" → "must match resolver/__init__.py") | §4 |
| `custom_components/asp_parking/gps2asp/resolver/side_resolver.py` | Docstring elaboration + cross-product explanatory comment added | §6 |
| `custom_components/asp_parking/gps2asp/resolver/spatial_index.py` | **D-07 logic:** `_lock: ClassVar[asyncio.Lock \| None] = None` with lazy init in `__aenter__` and re-nulling in `reset()` (replaces eager `asyncio.Lock()` at class-definition time) | §7 |
| `custom_components/asp_parking/gps2asp/schedule/merge.py` | Import-style normalization only | §9 |
| `custom_components/asp_parking/gps2asp/schedule/next_move.py` | Docstring wording aligned ("8-calendar-day lookahead" canonical form) | §10 |
| `custom_components/asp_parking/gps2asp/signs/__init__.py` | Import-style normalization only | §13 |
| `custom_components/asp_parking/gps2asp/signs/client.py` | **D-07 logic:** `raise RuntimeError("unreachable: retry loop exited without recording an error")` replaces `assert last_error is not None`; docstring wording | §14 |

The 16 already-in-sync `.py` files (`api_models.py`, `resolver/converter.py`, `resolver/exceptions.py`, `resolver/logging.py`, `resolver/models.py`, `schedule/__init__.py`, `schedule/models.py`, `schedule/parser.py`, `schedule/summary.py`, `signs/exceptions.py`, `signs/graph.py`, `signs/models.py`, `signs/normalize.py`, `suspension/__init__.py`, `suspension/merge.py`, `suspension/poller.py`) were left untouched by the script (script reports "16 already up to date").

### Modified — strings.json (Task 2)

Exact diff that landed:

```diff
@@ -73,5 +73,6 @@
         "data": {
           "debug_lat": "Override latitude",
           "debug_lon": "Override longitude",
-          "debug_datetime": "Override current date/time"
+          "debug_datetime": "Override current date/time",
+          "suppress_notifications": "Suppress notifications in debug mode"
         },
```

Two changes only:
1. Added trailing comma on `debug_datetime` line.
2. Inserted new key-value pair `"suppress_notifications": "Suppress notifications in debug mode"` immediately below.

After the edit: `cmp -s custom_components/asp_parking/strings.json custom_components/asp_parking/translations/en.json` exits 0 (byte-identical); `python -m json.tool` exits 0 (JSON valid).

## Workflow file shape (canonical record)

```yaml
name: vendor-guard

on:
  push:
    branches: ["**"]
  pull_request:
    branches: ["**"]

jobs:
  vendor-guard:
    name: Verify vendored gps2asp matches src/
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python 3.14
        uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - name: Check vendored mirror is in sync
        run: python scripts/sync_vendored.py --dry-run
```

Verified via PyYAML round-trip: `d['name'] == 'vendor-guard'`; `d[True]['push']['branches'] == ['**']`; `d[True]['pull_request']['branches'] == ['**']`. (PyYAML deserializes the YAML `on:` key as Python `True` — a known PyYAML quirk; the workflow itself is valid.)

## Branch commit history (ordering proof)

```
2775c75 feat(31-02): add vendor-guard CI workflow and sync strings.json with translations (CI-01, CI-02, D-04, D-08)
f53ca8a chore(31-02): sync vendored gps2asp mirror to match src/ (D-06, D-07)
547e5bd chore: merge executor worktree (worktree-agent-ac56f209632142cd1)  [worktree base]
```

The vendored-sync commit (`f53ca8a`) precedes the workflow + strings commit (`2775c75`) on the branch — required so the workflow's first CI run is green and does not fire on the 10-file drift state.

## CI loop closure

The `vendor-guard` workflow will fire on the next push of this branch to the remote. First-run green on the PR closes the loop on CI-01. There is no mock or simulated CI run here — verification is local-equivalent (`python scripts/sync_vendored.py --dry-run` exits 0 from the repo root), but the final acceptance proof is the GitHub Actions check itself on PR.

## Decisions Made

1. **Used main-repo venv (`/home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/.venv/bin/python`, Python 3.13).** The worktree base does not contain a `.venv/` directory. Rather than bootstrap a new venv inside the worktree (heavy, not needed since the repo is the same package), I called the main repo's venv directly. All 403 quick tests + the 27 Plan-01 sync tests pass via this interpreter; the dry-run round-trip exits 0.
2. **Recorded the actual 10-file drift (not 14).** The plan's `<action>` section projected 14 drifted files based on `31-RESEARCH.md §"Current divergence resolution"`. The script reported `Synced 10 file(s); 16 already up to date.` against the current tree. Four of the originally-listed divergent files (`schedule/__init__.py`, `schedule/parser.py`, `schedule/summary.py`, `resolver/converter.py`) had already been brought into sync on this branch prior to plan execution. The exit-code contract is the binding criterion (per the plan's own caveat), and `--dry-run` exits 0 against the synced tree — Task 1 is satisfied.
3. **No `cache: "pip"` in the workflow setup-python step.** Vendor-guard installs zero packages (uses only stdlib argparse/pathlib/re/sys). pip caching would be a no-op and adds spurious cache-warming time to runner startup.
4. **No literal `diff -r` step in the workflow.** Per `31-RESEARCH.md §"Anti-Patterns"`, raw `diff -r src/gps2asp custom_components/asp_parking/gps2asp` would always fail because of intentional import-style differences. The script's `--dry-run` IS the "or equivalent" the ROADMAP success criterion calls for.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used main-repo venv instead of worktree-local venv**

- **Found during:** Task 1 (pre-Sync `--dry-run` invocation)
- **Issue:** The worktree at `/home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/.claude/worktrees/agent-a89ee204c3612bfaa/` does not contain a `.venv/bin/python` (the base commit `547e5bd` predates the venv being copied into the worktree). The plan's `<action>` specifies `.venv/bin/python scripts/sync_vendored.py` — a literal worktree-relative path that would fail with `No such file or directory`.
- **Fix:** Used the main repo's venv directly: `/home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/.venv/bin/python` (Python 3.13.5, has all dev deps incl. pytest, yaml). The worktree shares the same `pyproject.toml` and source code as the main repo, so the editable install in the main venv works identically here.
- **Verification:** `python --version` → `Python 3.13.5`; sync script ran without import errors; full quick pytest suite (403 tests) passed; `tests/test_sync_vendored.py` (27 Plan-01 tests) all passed.
- **Files modified:** None (operational change only — no source edits required).
- **Committed in:** N/A (no commit needed; this is an environment-resolution adjustment).

**2. [Rule 1 - Bug expectation calibration] Drift count was 10, not 14**

- **Found during:** Task 1 (initial `--dry-run` invocation)
- **Issue:** The plan's `<action>` block said the script "must execute cleanly, print `Synced 14 file(s); 12 already up to date.` (exact count)". The actual script output was `Synced 10 file(s); 16 already up to date.` (4 fewer drifted files than projected by RESEARCH.md). The acceptance criterion `git diff --name-only HEAD~1 HEAD -- custom_components/asp_parking/gps2asp/ | grep -E "\.py$" | wc -l` returns 14 — would have failed with the literal 14 threshold.
- **Fix:** Followed the plan's own caveat ("the count line is informational — exit code 0 is the binding contract"). The `--dry-run` round-trip exit code 0 is the authoritative check, and that passes. The 4 already-in-sync files (`schedule/__init__.py`, `schedule/parser.py`, `schedule/summary.py`, `resolver/converter.py`) had been brought into sync on this branch prior to Plan 02 execution — likely via a prior partial sync or a hand-edit. No corrective action was needed; the script's job is to make the trees byte-identical, and after Task 1 they are.
- **Verification:** `git diff --name-only HEAD~1 HEAD -- custom_components/asp_parking/gps2asp/ | grep -E "\.py$" | wc -l` → 10 (matches actual sync count). `--dry-run` against post-sync tree exits 0.
- **Files modified:** None beyond the 10 sync'd .py files.
- **Committed in:** `f53ca8a` (Task 1 commit; commit message records the actual count of 10).

**3. [Rule 3 - Blocking] data/ directory absent in worktree**

- **Found during:** Task 1 post-condition check (e) (`git diff --stat custom_components/asp_parking/gps2asp/data/`)
- **Issue:** The acceptance criterion `git diff --stat custom_components/asp_parking/gps2asp/data/ | wc -l` returns 0 (sanity check that the script's data/ exclusion held). In this worktree, `custom_components/asp_parking/gps2asp/data/` does not exist on disk (git status confirms no path under that prefix), so git emits `fatal: ambiguous argument`. The acceptance check effectively passes (no diff, no modifications) but cannot be evaluated as written.
- **Fix:** Alternative verification: `git status --short` after Task 1 listed exactly the 10 .py files (no path under `data/` anywhere); `git diff --stat HEAD~1 HEAD` after the commit confirms only the 10 .py files changed (no data/ files). The exclusion held vacuously since there were no data/ files to consider.
- **Verification:** `git diff --name-only HEAD~1 HEAD` lists only the 10 .py paths — no `data/` paths.
- **Files modified:** None.
- **Committed in:** N/A.

---

**Total deviations:** 3 auto-fixed (1 blocking environment issue, 1 plan-projection vs. measured-state calibration, 1 missing-directory-absent vacuous-passing acceptance check)
**Impact on plan:** None. All deviations are observational adjustments to fit the actual worktree environment. The binding success criteria (`--dry-run` exits 0, D-07 logic present, byte-identity, JSON valid, tests pass) are all met.

## Issues Encountered

- **Worktree base reset wiped `.planning/STATE.md` and `.planning/PROJECT.md`:** The initial `<worktree_branch_check>` block ran `git reset --hard 547e5bd...` to enforce the worktree base. That base commit predates the existence of those planning files, so they vanished from disk. The plan and supporting context files were read from the main repo working tree (`/home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/.planning/...`) instead. Per the objective ("Do NOT update STATE.md or ROADMAP.md — the orchestrator owns those writes"), no recovery is needed. The SUMMARY.md is being written to the worktree's `.planning/phases/31-ci-guard-strings-json-sync/` directory (which the worktree base does contain — only `31-01-SUMMARY.md` was present; this commit adds `31-02-SUMMARY.md`).

## User Setup Required

None — this is pure CI/repository infrastructure. No environment variables, no external accounts, no UI changes (the new `suppress_notifications` HA string is rendered by the existing debug-mode config flow; the string itself was already present in `translations/en.json` so end users have been seeing it; this plan only brings `strings.json` into agreement).

## Next Phase Readiness

- The `vendor-guard.yml` workflow will fire on the next push of this branch. First green run on the PR closes CI-01.
- v3.2 feature phases (32 — day-specific button time formatting; 33 — monthly index rebuild; 34 — TBD) inherit:
  - A guaranteed-in-sync vendored mirror (the workflow blocks any merge that drifts it).
  - Byte-identical `strings.json` ↔ `translations/en.json` (no automated guard, but baseline is identical — downstream phases must edit both files together).
- No blockers. Phase 31 acceptance criteria (CI-01, CI-02) are satisfied end-to-end pending the live CI green-light on PR.

## Self-Check: PASSED

Verification against claims in this SUMMARY:

- `.github/workflows/vendor-guard.yml` — **FOUND** (20 lines, 626 bytes; YAML parses; trigger structure confirmed)
- `custom_components/asp_parking/strings.json` — **FOUND** (modified; `suppress_notifications` key present; `cmp -s` with translations/en.json exits 0)
- 10 vendored .py files — **FOUND** (all 10 paths listed under "Modified — vendored sync" exist and were committed in `f53ca8a`)
- Commit `f53ca8a` — **FOUND** (`git log --oneline | grep f53ca8a` returns 1)
- Commit `2775c75` — **FOUND** (`git log --oneline | grep 2775c75` returns 1)
- Commit ordering: `f53ca8a` (chore vendored sync) precedes `2775c75` (feat workflow + strings) on the branch — **CONFIRMED**
- `--dry-run` post-Task-1 round-trip — **EXIT=0** (`Vendored mirror is in sync with src/gps2asp/.`)
- `cmp -s strings.json translations/en.json` post-Task-2 — **EXIT=0** (byte-identical)
- Full pytest quick suite (403 tests, 116 deselected) — **PASS** (8.93s; 7.77s on rerun after Task 2)
- D-07 logic checks — **PASS** (ClassVar lock present, unreachable RuntimeError comment present, old `assert last_error` absent)

---

*Phase: 31-ci-guard-strings-json-sync*
*Completed: 2026-05-11*
