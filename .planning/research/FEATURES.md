# Feature Research

**Domain:** GPS-to-ASP resolver — spatial coverage and observability improvements (v2.0 milestone)
**Researched:** 2026-03-13
**Confidence:** HIGH (all claims sourced directly from codebase — build_index.py, graph.py, signs/__init__.py, coordinator.py, sensor.py, normalize.py, PROJECT.md, STATE.md)

---

## Context: What Is Already Built

This is a subsequent milestone for an operational system. The four features in scope are incremental improvements to a working pipeline, not new capabilities. Understanding existing behavior is essential for correctly scoping each feature.

**Existing pipeline (v1.1 operational):**
- R-tree spatial index: 26,374 ASP vehicular segments + 62,455 BFS-propagated interior blocks
- 4-level SODA API fallback: L1 exact match → L2 name variants → L3 broad + client-filter → L4 best-covering span via BFS graph distance
- graph.json: 7.9 MB, covers ALL vehicular segments (not filtered to ASP-only), loaded as singleton at runtime by `StreetGraph.get()`
- `soda_level` tracked in `SignRetrievalSuccess.soda_level` (1-4) and `ASPDebugResult.soda_level`, but NOT stored in `ASPParkingData` and NOT exposed in HA sensor attributes
- Coverage: Manhattan 58.2%, Brooklyn 74.1%, Bronx 52.4%, Queens 36.8%
- Coordinator calls 3-stage pipeline manually (not `resolve_asp()`) — tech debt, out of scope for this milestone

---

## Feature Landscape

### Table Stakes (Users Expect These)

For this milestone, "table stakes" means the minimum required for v2.0 to be considered done. Each feature either closes a known gap or surfaces data the system already computes but doesn't expose.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Queens coverage >= 50% | v2.0 milestone target; currently 36.8% — largest gap by 13.2 points | HIGH | Root cause unknown; must diagnose before fixing. Likely missing normalization patterns for Queens street names in `normalize_to_soda()` or cross-street name format mismatches. Cannot skip diagnosis step. |
| Manhattan coverage >= 60% | v2.0 milestone target; currently 58.2% — 1.8 points short | LOW-MEDIUM | Small gap likely explained by same normalization class of bug as Queens. Expect this closes as a side effect of Queens normalization audit. If not, may require targeted BFS tuning. |
| `soda_level` in HA sensor attributes | Without this, users/developers cannot tell whether a result came from an exact match (Level 1) or a BFS fallback (Level 4); essential for trust and debugging | LOW | `soda_level` already flows through the library. The only missing links are: add `soda_level: int = 0` to `ASPParkingData`, populate it in `_async_resolve_pipeline()`, expose it in `extra_state_attributes` metadata group. |
| graph.json <= 4 MB | v2.0 target; current 7.9 MB is loaded entirely into memory as a Python dict on first Level 4 call — oversized for HA startup on low-memory hardware | MEDIUM | BFS traversal correctness is the key constraint; the filter must retain ASP segments AND their immediate neighbors (see Anti-Features for why strict ASP-only is wrong). |

### Differentiators (Competitive Advantage)

Features that go beyond baseline correctness and improve the user's ability to trust and debug the system.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Structured Level 4 hit-rate logging | Enables data-driven decisions about where to improve normalization; without this, coverage improvements are guesswork | LOW | Add structured log lines at each level exit in `signs/__init__.py`: level number, on_street, outcome (matched/no-records/no-broom-signs). Borough could be passed through if available. |
| Borough-specific normalization diagnosis report | Queens uses patterns that may be absent from the shared `_SUFFIX_EXPANSIONS` / `_DIRECTIONAL_EXPANSIONS` tables; a systematic audit converts guessing into evidence | MEDIUM | Requires sampling Queens SODA records and CSCL cross-street names for known failures, then comparing formats. Outputs concrete rule additions. |
| BFS-correct graph compression (ASP + 1-hop neighbors) | Reduces cold-start time and memory footprint without breaking Level 4 correctness | MEDIUM | Compress at build time in `build_index.py`; zero runtime cost. Expected to reach 3-4 MB. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Strict ASP-only graph.json (no neighbor expansion) | Maximizes file size reduction | Breaks Level 4 BFS correctness. `_bfs_min_hops()` traverses from block cross-street segments to span endpoint segments. If a non-ASP segment sits between two ASP segments on the same street, removing it disconnects the traversal path — `span_distance()` returns `float('inf')` for a valid span. | Include ASP segments + their immediate 1-hop adjacency neighbors. This is the minimal correct set. |
| Real-time Level 4 counters (Prometheus-style) | Developer wants hit-rate metrics per borough | HA custom components have no native metrics endpoint; adding a metrics server creates deployment complexity and an HA certification blocker | Use structured log lines with consistent format that can be grepped or exported post-hoc; expose `soda_level` in HA sensor attributes for dashboard visibility |
| Per-borough normalization tables | Separate `_SUFFIX_EXPANSIONS` dict per borough | Queens issues are almost certainly missing patterns in the shared table, not conflicts between boroughs; separate tables add maintenance burden | Audit shared table; add missing Queens patterns; confirm via coverage regression |
| Dynamic graph re-compression at runtime | Reduce memory after load by dropping non-traversed keys | Python dict cannot be lazily compressed; any re-encoding adds CPU overhead at startup. The correct place to compress is build time. | Compress at build time in `build_index.py` |
| Coordinator migration to `resolve_asp()` (COV-03) | Simplifies `soda_level` capture and removes manual 3-stage wiring | Correct but out of scope for this milestone; touching the coordinator risks behavioral regressions in HA integration code. `soda_level` can be captured without migrating the coordinator. | Defer to v2.x; add `soda_level` field to `ASPParkingData` directly |

---

## Feature Dependencies

```
[Queens normalization audit]
    └──produces──> [New rules in normalize_to_soda()]
                       └──requires rebuild──> [scripts/build_index.py rebuild]
                                                  └──improves──> [Queens coverage >= 50%]
                                                  └──likely fixes──> [Manhattan coverage >= 60%]

[graph.json size reduction]
    └──depends on──> [ASP segment set from segments.json]
    └──independent of──> [Queens normalization audit]
    (can be developed in parallel)

[Level 4 observability: soda_level in HA sensor]
    └──requires──> [soda_level field in ASPParkingData]
                       └──requires──> [Populate from sign_result in _async_resolve_pipeline()]
                                          └──enables──> [soda_level in extra_state_attributes]

[Structured Level 4 logging]
    └──independent of all above (just adds log lines to signs/__init__.py)
```

### Dependency Notes

- **Queens normalization requires index rebuild:** `normalize_to_soda()` is called at build time inside `_build_intersection_index()` to construct the `(on_street, cross_street) -> set[pid]` lookup that drives BFS propagation. Any new rules only take effect after `scripts/build_index.py` is rerun. Runtime changes to `normalize_to_soda()` immediately affect SODA query construction (Levels 1-3), but `has_asp` flags in `segments.json` reflect the build-time state.

- **graph.json reduction is independent:** The filter operates on `adjacency` dict construction (build_index.py lines 917-926). It does not touch normalization. These can ship in the same build-index rebuild invocation, or separately.

- **soda_level in HA does not require coordinator migration:** `soda_level` is available on `sign_result` at line 311 of coordinator.py (`isinstance(sign_result, SignRetrievalSuccess)`). Adding `self.data.soda_level = sign_result.soda_level if isinstance(sign_result, SignRetrievalSuccess) else 0` requires no architectural change.

- **Manhattan coverage likely closes via Queens normalization:** Manhattan 58.2% gap is 1.8 points. Given BFS propagation already near-doubled Manhattan coverage (from ~30% to 58%), the residual gap is almost certainly spans where `start_pids` or `end_pids` is empty in `_propagate_asp_to_interior_blocks()` (build_index.py line 565-566). This happens when `intersection_index.get((on_street, cross_street))` returns empty because a name variant is missing from the normalization table — the same class of failure as Queens.

---

## MVP Definition

This is a subsequent milestone; "MVP" means minimum required to close v2.0.

### Launch With (v2.0)

- [ ] **Queens normalization audit + rule additions** — diagnose format mismatches, add patterns to `normalize_to_soda()`, rebuild index, confirm coverage >= 50%
- [ ] **Manhattan coverage >= 60%** — expected side effect of Queens fix; explicit target to verify after rebuild
- [ ] **`soda_level` in HA sensor `extra_state_attributes`** — one field in `ASPParkingData` + one line in coordinator + one line in sensor
- [ ] **graph.json <= 4 MB** — ASP + 1-hop neighbor filter in `build_index.py`, same rebuild as Queens fix

### Add After Validation (v2.x)

- [ ] **Structured Level 4 logging** — low complexity enhancement; add during or after v2.0 coverage work
- [ ] **COV-03: Coordinator to `resolve_asp()`** — tech debt; enables cleaner `soda_level` capture and simpler testing, but not a v2.0 blocker
- [ ] **CACHE-01: SQLite sign data cache** — reduces SODA API calls; deferred, not needed for coverage goals
- [ ] **HA diagnostics endpoint** — blocked on HA diagnostics API familiarity; defer

### Future Consideration (v3+)

- [ ] **SUSP-01/02/03: NYC holiday and weather suspension** — separate data source (311 API), separate milestone
- [ ] **NOTIF-01/02: HA actionable notifications** — requires stable schedule data first

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Queens normalization audit + fix | HIGH — 13.2-point coverage gap | MEDIUM — must sample data, identify patterns, add rules, rebuild index | P1 |
| `soda_level` in HA sensor attributes | HIGH — transparency and debugging | LOW — one field, one coordinator line, one sensor line | P1 |
| graph.json size reduction to <= 4 MB | MEDIUM — startup cost and memory | MEDIUM — correct ASP + neighbor filter; verify BFS correctness | P1 |
| Manhattan coverage >= 60% | MEDIUM — 1.8-point gap | LOW if fixed by Queens normalization; MEDIUM if needs separate BFS investigation | P1 |
| Structured Level 4 logging | MEDIUM — developer observability | LOW — add structured log lines in signs/__init__.py | P2 |

**Priority key:**
- P1: Must have for v2.0
- P2: Should have; add before v2.0 close
- P3: Nice to have, future milestone

---

## Implementation Notes by Feature

### Feature 1: Queens Normalization Audit

**What goes wrong today:** `retrieve_signs()` Levels 1-3 all fail for Queens blocks. This means either:
(a) the SODA query uses the wrong on-street or cross-street name format, or
(b) `normalize_to_soda()` produces a form that doesn't match what SODA stores.

**How to diagnose:** Run `resolve_asp(lat, lon, debug=True)` on known Queens ASP locations (e.g., Jackson Heights, Flushing, Astoria). Inspect `sign_result` type — `NoMatchFound` confirms SODA had no records at all (query format wrong); `NoASPSigns` confirms SODA had records but no broom signs (location truly has no ASP). Sample actual SODA records for Queens streets via `build_on_street_query(on_street, side)` to compare what name forms SODA actually stores.

**Likely Queens-specific patterns to audit:**
- Numbered streets: CSCL stores "37 AVE", "74 ST" — `normalize_to_soda()` correctly expands these to "37 AVENUE", "74 STREET". If Queens is failing here, the issue may be in cross-street normalization at the intersection level, not on-street.
- Named highways: "NORTHERN BOULEVARD", "QUEENS BOULEVARD", "WOODHAVEN BOULEVARD" — verify CSCL stores these in abbreviated form that triggers suffix expansion.
- Direction-named streets: "N CONDUIT BLVD" → "NORTH CONDUIT BOULEVARD" — verify prefix expansion fires correctly. "NORTHERN BLVD" must NOT expand ("NORTHERN" starts with N but has no space after N, so the `startswith("N ")` guard correctly skips it).
- Hyphenated cross-street references: Queens uses hyphenated addresses in street names (e.g., "67-11 METROPOLITAN AVENUE") in some data; verify this doesn't appear as a cross-street value in SODA.

**What changes:** Add missing abbreviation mappings to `_SUFFIX_EXPANSIONS` or `_DIRECTIONAL_EXPANSIONS` in `src/gps2asp/signs/normalize.py`. Rebuild spatial index after to update `intersection_index` and `has_asp` flags.

### Feature 2: graph.json Size Reduction

**Current behavior (build_index.py lines 921-926):**
```python
for pid, neighbors in adjacency.items():
    pid_str = str(pid)
    graph_adjacency[pid_str] = sorted(neighbors)
    graph_segment_streets[pid_str] = gdf_street_names.get(pid, "")
    ...
```
This includes ALL segments with at least one adjacency neighbor — regardless of `has_asp`. This is intentional (per [Phase 11-01] decision), but the conservative choice now costs 7.9 MB.

**Correct minimum filter:** Include a segment in graph.json if:
1. It has `has_asp_left=True` OR `has_asp_right=True` (direct ASP segment), OR
2. It is an immediate neighbor (1-hop) of any ASP segment.

Condition 2 is required because `_bfs_min_hops()` in `graph.py` traverses from `block_cross_street_pids` to `span_endpoint_pids`. If the queried block is non-ASP but physically adjacent to an ASP segment, the BFS needs that non-ASP block in the graph to establish a 1-hop distance and correctly score the covering span.

**Build-time change:**
After computing the full `adjacency` and `asp_lookup`, derive the set of `asp_pids` (segments where `has_asp_left or has_asp_right`). Expand to include their 1-hop neighbors: `neighbor_pids = {n for pid in asp_pids for n in adjacency.get(pid, set())}`. The filtered set is `asp_pids | neighbor_pids`. Filter `graph_adjacency`, `graph_segment_streets`, and `graph_segment_cross_streets` to this set before writing.

**Expected size impact:** ASP segments are ~26,374 of ~88,000 vehicular segments (~30%). 1-hop expansion adds at most one neighbor per endpoint, likely reaching 40-50% of the full graph — targeting 3-4 MB.

### Feature 3: Level 4 Observability

**What is missing today:**

1. `ASPParkingData` (coordinator.py lines 67-99) has no `soda_level` field. The coordinator extracts `sign_count` from `sign_result` at line 311 but does not extract `soda_level`. The sensor cannot expose what it doesn't have.

2. Log lines at each level exit are unstructured `logger.info()` calls without consistent machine-parseable format.

**Minimum change for HA sensor:**
- Add `soda_level: int = 0` to `ASPParkingData` dataclass
- In `_async_resolve_pipeline()`, after the `isinstance(sign_result, SignRetrievalSuccess)` block at line 311, add: `self.data.soda_level = sign_result.soda_level if isinstance(sign_result, SignRetrievalSuccess) else 0`
- In `ASPNextMoveTimeSensor.extra_state_attributes()`, add `"soda_level": data.soda_level` to the metadata group (alongside `confidence_score`, `sign_count`, `parse_failures`)

**Structured logging enhancement (P2):**
At each level success path in `signs/__init__.py`, emit a structured log line with consistent field order:
```python
logger.info("soda_resolve level=%d on_street=%r outcome=matched signs=%d", soda_level, on_street, len(signs))
logger.info("soda_resolve level=%d on_street=%r outcome=no_records", soda_level, on_street)
```
This format is grep-friendly for post-hoc analysis of which streets are failing which levels.

---

## Sources

- `/home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/scripts/build_index.py` — BFS propagation, graph construction, filter logic (direct code analysis, HIGH confidence)
- `/home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/src/gps2asp/signs/__init__.py` — 4-level fallback, soda_level tracking at each return site (direct code analysis, HIGH confidence)
- `/home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/src/gps2asp/signs/graph.py` — StreetGraph, BFS hop scoring, `_find_best_covering_span` (direct code analysis, HIGH confidence)
- `/home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/src/gps2asp/signs/normalize.py` — `_SUFFIX_EXPANSIONS`, `_DIRECTIONAL_EXPANSIONS`, `normalize_to_soda()` (direct code analysis, HIGH confidence)
- `/home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/custom_components/asp_parking/coordinator.py` — `ASPParkingData` fields, `_async_resolve_pipeline()` execution (direct code analysis, HIGH confidence)
- `/home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/custom_components/asp_parking/sensor.py` — `extra_state_attributes`, diagnostic sensors (direct code analysis, HIGH confidence)
- `/home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/.planning/PROJECT.md` — milestone targets, coverage numbers, key decisions log (HIGH confidence)
- `/home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/.planning/STATE.md` — accumulated context, phase decisions, pending todos (HIGH confidence)

---
*Feature research for: GPS2ASP Resolver v2.0 — spatial coverage improvements and observability*
*Researched: 2026-03-13*
