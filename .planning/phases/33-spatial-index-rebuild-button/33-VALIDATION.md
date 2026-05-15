---
phase: 33
slug: spatial-index-rebuild-button
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-14
audited: 2026-05-14
---

# Phase 33 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-homeassistant-custom-component |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `.venv/bin/pytest tests/ -m "not integration" -x -q` |
| **Full suite command** | `.venv/bin/pytest` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/ -m "not integration" -x -q`
- **After every plan wave:** Run `.venv/bin/pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 33-01-01 | 01 | 0 | IDX-01 | — | N/A | unit | `.venv/bin/pytest tests/test_index_rebuild_button.py -x -q` | ✅ | ✅ green |
| 33-01-02 | 01 | 0 | IDX-02 | T-33-01 | Lock prevents concurrent rebuild tasks | unit | `.venv/bin/pytest tests/test_index_rebuilding_binary_sensor.py -x -q` | ✅ | ✅ green |
| 33-01-03 | 01 | 0 | IDX-03 | — | N/A | unit | `.venv/bin/pytest tests/test_index_last_rebuilt_sensor.py -x -q` | ✅ | ✅ green |
| 33-01-04 | 01+02 | 0 | IDX-04 | T-33-02 | Atomic swap + zip-slip prevention | unit | `.venv/bin/pytest tests/test_index_io.py tests/test_coordinator_rebuild.py -x -q` | ✅ | ✅ green |
| 33-04-i18n | 04 | 2 | IDX-01..04 | T-33-04-04 | strings.json ↔ translations/en.json byte-equivalence | unit | `.venv/bin/pytest tests/test_sync_vendored.py -x -q` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_index_rebuild_button.py` — 7 tests for IDX-01 (button entity press → background task created)
- [x] `tests/test_index_rebuilding_binary_sensor.py` — 8 tests for IDX-02 (binary sensor entity contract)
- [x] `tests/test_index_last_rebuilt_sensor.py` — 9 tests for IDX-03 (last-rebuilt sensor reads build_info.json)
- [x] `tests/test_index_io.py` — 17 tests for IDX-04 (atomic swap, zip-slip prevention, build_info parse)
- [x] `tests/test_coordinator_rebuild.py` — 9 tests for IDX-02/IDX-04 (lock semantics, concurrent press blocked, coordinator orchestration)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| HA UI button entity appears in dashboard | IDX-01 | Requires live HA instance | Load integration, check Devices & Services → ASP Parking → button.asp_parking_rebuild_index visible |
| Persistent notification shown and dismissed on rebuild | IDX-01/IDX-04 | Requires live HA + network | Press button, confirm "Rebuilding…" notification appears; on completion confirm it is replaced by success/failure notification |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** 2026-05-14 — all 50 Phase 33 tests green; 455 non-network tests pass with zero regressions

---

## Validation Audit 2026-05-14

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |
| Tests confirmed green | 50 |
| Full non-network suite | 455 passed, 136 deselected |
| Manual-only items | 2 (live HA UI verification) |

All requirements IDX-01..IDX-04 have machine-checkable coverage across 5 test files. i18n sync enforced by `test_sync_vendored.py` (Phase 31 CI guard). No auditor spawn needed.
