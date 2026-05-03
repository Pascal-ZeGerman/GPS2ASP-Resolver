# Phase 29 Plan 02 — Deferred / Out-of-Scope Items

Items discovered during 29-02 execution that are pre-existing baseline issues
unrelated to this plan's changes. Logged here for tracking; NOT fixed in scope.

## Pre-existing test failure (worktree base 73f4530)

**Test:** `tests/test_ha_integration.py::TestSuspensionPoll::test_suspension_poll_does_not_require_gps_coordinates`

**Failure mode:** The test asserts `'datetime.now(NYC_TZ).date()' in coordinator.py source`, but
`coordinator.py` at the worktree base commit (`73f4530`) does not contain that exact literal in
its suspension poll code path. The test reads `_COORDINATOR_SRC.read_text()` and string-matches.

**Reproduction:** `git stash` followed by running the test alone reproduces the same failure
*before* any of plan 29-02's edits — confirming it is not a regression introduced by this plan.

**Status:** Out of scope for plan 29-02 (does not touch `coordinator.py`). Likely tracked by
Phase 29 Plan 01 / Plan 03 (which do edit `coordinator.py`) or Phase 27 diagnostics work.

**Mitigation in scope:** Plan 29-02 verification used `--deselect` on this test only. All other
66 selected tests in `tests/test_ha_integration.py` and `tests/test_diagnostics.py` pass.
