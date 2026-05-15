---
plan: 34-05
phase: 34
status: complete
completed_at: "2026-05-15"
requirements_satisfied: [CALDAV-07]
---

# Plan 34-05 — async_remove_entry CalDAV teardown

## Objective

Implement `async_remove_entry` in `custom_components/asp_parking/__init__.py` to satisfy CALDAV-07: delete the CalDAV event from the user's server before HA forgets the config entry. Runs AFTER `async_unload_entry`, so runtime_data is unavailable — reconstructs the Store from scratch.

## Commits

| Hash | Description |
|------|-------------|
| `fcd6044` | feat(34-05): implement async_remove_entry — CalDAV cleanup on config entry removal (CALDAV-07) |

## Files Modified

- `custom_components/asp_parking/__init__.py` — added `async_remove_entry` function (69 lines)

## Acceptance Criteria — All Met

- [x] `async_remove_entry` exists in `__init__.py` and is exported
- [x] D-02 guard: empty `CONF_CALDAV_URL` → zero-cost no-op (no Store I/O)
- [x] Pitfall 5: `raw or {}` coercion handles None payload gracefully
- [x] Best-effort delete: `delete_event` failure caught + logged (uid only, no creds) → Store still removed
- [x] `store.async_remove()` always called, even on delete failure
- [x] Credentials never appear in log output (T-34-01 / T-34-08)

## Test Results

```
tests/test_init_caldav_remove.py — 4/4 passed
```

- `test_async_remove_entry_deletes_event_and_store_when_uid_present` ✓
- `test_async_remove_entry_noop_when_caldav_url_absent` ✓
- `test_async_remove_entry_noop_when_no_stored_uid` ✓
- `test_async_remove_entry_continues_when_delete_fails` ✓

## Implementation Notes

- Lazy imports (`Store`, `caldav_sync`) inside the function body to keep module-top imports focused on the hot setup path (RESEARCH §finding 2 — caldav has a ~25 MB transitive dep tree).
- Storage key `f"{DOMAIN}_caldav_{entry.entry_id}"` matches Plan 04's Store namespace exactly.
- The function reconstructs the Store from scratch because `async_remove_entry` runs after `async_unload_entry` — `entry.runtime_data` (the coordinator) is no longer available.

## Deviations

None. Plan executed exactly as specified.
