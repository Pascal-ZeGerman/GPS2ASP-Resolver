---
phase: 31-ci-guard-strings-json-sync
plan: 01
subsystem: infra
tags: [ci, tooling, python, vendored-mirror, regex, argparse, tdd]

# Dependency graph
requires: []
provides:
  - scripts/sync_vendored.py — pure normalize_source + thin CLI shell with --dry-run and write modes
  - tests/test_sync_vendored.py — unit + integration coverage for normalize_source and main()
  - normalize_source(rel_path, text) function importable from scripts/sync_vendored.py for reuse
affects: [31-02, future-vendor-mirror-maintenance]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-phase tooling script: pure deterministic transform function + thin argparse CLI shell"
    - "Column-zero regex anchoring (^ + re.MULTILINE) to skip indented imports inside TYPE_CHECKING / docstrings"
    - "tmp_path + monkeypatch of module-level constants for CLI integration tests (in-process, no subprocess)"

key-files:
  created:
    - scripts/sync_vendored.py
    - tests/test_sync_vendored.py
  modified: []

key-decisions:
  - "Regex over AST: column-anchored `^from gps2asp\\.` with re.MULTILINE preserves byte-identity for all non-import content (vs ast.unparse which would reformat whitespace and comments)"
  - "In-process CLI tests via monkeypatch of SRC_ROOT/VENDOR_ROOT (not subprocess) -- simpler, faster, capsys-friendly"
  - "Acceptance criterion 'from __future__ import annotations on line ≤ 5' satisfied by demoting the test module description to a one-line docstring + comment block"

patterns-established:
  - "Pure transform + thin CLI: normalize_source(rel_path, text) is I/O-free; main() owns the file walk, dry-run vs write branching, and stdout contract"
  - "Deterministic file ordering: iter_source_files() returns sorted(SRC_ROOT.rglob('*.py')) so drift output is stable"
  - "Sentinel value for missing vendor: vendor_path.read_text(...) if exists else None means absence compares unequal to any target_text and surfaces as drift"

requirements-completed: [CI-01]

# Metrics
duration: ~12min
completed: 2026-05-11
---

# Phase 31 Plan 01: CI Guard sync script + RED/GREEN test suite Summary

**Deterministic absolute-to-relative import rewriter for the vendored gps2asp mirror, with --dry-run drift detection and a 27-test TDD suite (RED then GREEN commits) proving the 26-row normalization oracle.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-11 (Plan 31-01 spawn)
- **Completed:** 2026-05-11
- **Tasks:** 2 (RED test, GREEN implementation)
- **Files created:** 2

## Accomplishments

- `scripts/sync_vendored.py` ships a 143-line script with a 17-line pure `normalize_source` and a thin argparse CLI shell — stdlib only, no new dependencies.
- The column-zero regex `^from gps2asp\.[A-Za-z0-9_.]+ import ` (re.MULTILINE) is proven by negative tests to skip indented `TYPE_CHECKING` imports, docstring text, and `gps2asp_helpers` underscore lookalikes.
- `tests/test_sync_vendored.py` has 27 collected tests (22 unit + 5 integration) covering every row of the 31-RESEARCH.md normalization oracle plus the full CLI exit-code contract (in-sync → 0, drift → 1 with named paths, missing vendor → 1, write mode round-trips clean, `data/` excluded).
- Full quick suite remains green (403 tests pass; no regressions).

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Write failing tests for sync_vendored.py** — `f467202` (test)
2. **Task 2 (GREEN): Implement sync_vendored.py with --dry-run + write modes** — `3a7cd57` (feat)

_TDD cycle: RED commit precedes GREEN; no refactor commit was needed (script is ≤150 LOC, single concern)._

## Files Created/Modified

- `scripts/sync_vendored.py` — CLI tool. Walks `src/gps2asp/*.py` (excluding `data/`), normalizes column-zero gps2asp imports, and either writes to `custom_components/asp_parking/gps2asp/` (default) or diffs against on-disk vendor bytes (`--dry-run`).
- `tests/test_sync_vendored.py` — 22 unit cases on `normalize_source` (parametrized across the 26-row oracle plus negative cases) + 5 integration cases on `main()` via `tmp_path` + `monkeypatch` of `SRC_ROOT`/`VENDOR_ROOT`.

## Decisions Made

- **Regex, not AST:** Per RESEARCH.md anti-patterns, `ast.unparse` would reformat whitespace and comments, violating D-01 ("all other content copied verbatim"). A column-anchored regex naturally skips indented imports.
- **In-process CLI tests:** PLAN.md offered "in-process monkeypatched OR subprocess" — chose monkeypatch of module-level `SRC_ROOT`/`VENDOR_ROOT` (no env-var coupling needed in the script, simpler test setup, capsys catches stdout directly).
- **Sentinel for missing vendor:** `existing = vendor_path.read_text(...) if vendor_path.exists() else None` lets the `existing != target_text` check classify absent vendor files as drift naturally — no special-case branch.

## Test Coverage Matrix

| CI-01 sub-requirement | Test(s) |
|------------------------|---------|
| (a) normalize_source rewrites every documented import per the 26-row oracle | `TestNormalizeSource.test_top_level_imports_get_single_dot_prefix` (4 cases) + `..._resolver_subpackage_...` (7) + `..._schedule_subpackage_...` (5) + `..._signs_subpackage_...` (2) + `test_cross_subpackage_imports_use_double_dot_prefix` (1) + `test_parenthesized_multiline_import_rewrites_only_first_line` (1) |
| (b) Indented TYPE_CHECKING / docstring imports untouched + gps2asp_helpers untouched | `test_typecheck_and_docstring_imports_untouched`, `test_unrelated_imports_untouched` |
| (c) --dry-run on in-sync tree exits 0 | `TestCliDryRun.test_dry_run_in_sync_exits_zero` |
| (d) --dry-run on mutated vendor file exits 1 with path | `test_dry_run_detects_drift`, `test_dry_run_detects_missing_vendor_file` |
| (e) Write mode → subsequent --dry-run clean (round-trip) | `test_write_mode_creates_vendor_file_and_dry_run_after_is_clean` |
| (extra) data/ subtree excluded from both modes | `test_data_subtree_is_excluded` |

## Deviations from Plan

### Adjustments (not auto-fix rule deviations)

**1. [Test-file docstring → leading one-liner + comments] PLAN.md acceptance criterion required `from __future__ import annotations` on line ≤ 5**
- **Found during:** Task 1 acceptance-criteria check
- **Issue:** The natural module-level docstring (multi-paragraph) pushed `from __future__` to line 21, failing the literal "line ≤ 5" criterion. The analog `tests/test_audit_script.py` has it on line 7, so the criterion is stricter than the established pattern.
- **Fix:** Demoted the multi-paragraph description to a 1-line docstring followed by a `#`-prefixed comment block. `from __future__ import annotations` is now on line 3.
- **Files modified:** `tests/test_sync_vendored.py`
- **Verification:** `grep -n "^from __future__" tests/test_sync_vendored.py` reports line 3.
- **Committed in:** `f467202` (Task 1 RED commit)

**2. [Acceptance grep is over-escaped — followed intent, not literal pattern]**
- **Found during:** Task 2 acceptance-criteria check
- **Issue:** The plan's literal-grep criterion `grep -c '"^from gps2asp\\\\\\.' scripts/sync_vendored.py` interprets `\\\\\\.` in BRE as three literal backslashes + dot — a pattern that cannot appear in any Python source file (Python source has at most one `\\` for a literal backslash). The over-escaped grep returns 0 against any sane implementation.
- **Fix:** Treated the criterion as expressing "literal raw-string regex `r\"^from gps2asp\\.[...] import \"` is present in the source", which it is. Verified by `grep -c '"\^from gps2asp\\\.' scripts/sync_vendored.py` (returns 1) and by the import-clean smoke test `not sync_vendored._FROM_GPS2ASP.search("from gps2asp_helpers.foo import bar")` (returns True).
- **Files modified:** none — `scripts/sync_vendored.py` already contains the canonical raw-string regex literal.
- **Verification:** All 27 tests pass; `_FROM_GPS2ASP.search('from gps2asp_helpers.foo import bar')` returns `None`.
- **Committed in:** `3a7cd57` (Task 2 GREEN commit)

---

**Total deviations:** 0 auto-fix rule violations.
**Impact on plan:** Both adjustments are test-presentation tweaks (no behavior change); the contract from PLAN.md `<interfaces>` is delivered exactly.

## Issues Encountered

- No `.venv` exists inside the worktree (worktree mode resets the tree to a base commit). Used the main repo's `/home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/.venv/bin/python` directly for all test runs — pytest 9.0.0, Python 3.13.5, all 27 new tests + 403 existing tests pass. Documented here so the orchestrator/verifier knows the test commands resolve against the parent venv.

## Handoff Notes for Plan 02

- **No vendored file has been modified by this plan.** The 14 currently-divergent files in `custom_components/asp_parking/gps2asp/` are untouched. Running `.venv/bin/python scripts/sync_vendored.py` (without `--dry-run`) from `main` will write them; that one-time sync run is the first task of Plan 02, alongside `.github/workflows/vendor-guard.yml` and the strings.json one-line CI-02 edit.
- **The script is ready to be invoked from a GitHub Actions workflow.** Plan 02 should use the literal CLI: `python scripts/sync_vendored.py --dry-run` (no `.venv` on the runner; `setup-python@v5` provides the interpreter).
- **Test suite is part of the standard quick-suite** (no markers added → collected by default `not integration and not ha_integration` run).

## Threat Flags

None — pure repo tooling, no network, no user input, no credentials. Operates on absolute paths derived from `Path(__file__).resolve()` and refuses to walk outside `SRC_ROOT` (rglob is rooted; `relative_to` raises if escape attempted).

## Known Stubs

None — every documented behavior is implemented and exercised by tests.

## Next Phase Readiness

- Plan 31-02 unblocked: can land the workflow YAML, run the one-time sync, and commit the regenerated vendored files in three atomic commits.
- Forward compatibility: if a future contributor adds a 4th subpackage under `src/gps2asp/`, the algorithm handles it without code change (it's depth-agnostic). The 26-row oracle table will need extension, but that's a test-data update only.

## Self-Check: PASSED

- scripts/sync_vendored.py exists: FOUND
- tests/test_sync_vendored.py exists: FOUND
- Commit f467202 (RED test): FOUND in git log
- Commit 3a7cd57 (GREEN implementation): FOUND in git log
- All 27 tests pass: VERIFIED (`.venv/bin/pytest tests/test_sync_vendored.py -v`)
- No regressions: VERIFIED (full quick suite 403/403 pass)

---
*Phase: 31-ci-guard-strings-json-sync*
*Completed: 2026-05-11*
