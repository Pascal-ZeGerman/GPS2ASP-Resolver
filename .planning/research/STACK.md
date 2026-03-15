# Stack Research

**Domain:** GPS-to-ASP parking regulation resolver — v2.0 coverage and observability additions
**Researched:** 2026-03-13
**Confidence:** HIGH

> **Scope note:** This update covers ONLY the three new capability areas for v2.0:
> (1) graph.json size reduction, (2) Queens coverage investigation tooling,
> (3) structured logging/metrics for Level 4 SODA fallback observability.
> The validated v1.x stack (Python 3.11+, pyproj, shapely, rtree, httpx, numpy) is
> NOT re-researched here. See the 2026-02-21 STACK.md history for that foundation.

---

## Capability 1: graph.json Size Reduction (7.9 MB → ≤4 MB)

### Problem Analysis

graph.json is 7.9 MB of JSON containing three keys:
- `adjacency`: maps every CSCL segment PID → list of adjacent PID ints
- `segment_streets`: maps every PID → on-street name string
- `segment_cross_streets`: maps every PID → list of cross-street name strings

The file covers ALL ~62K vehicular segments, but Level 4 only needs segments
on streets that have ASP signs. The 26,374 ASP segments represent roughly 42%
of the total. Filtering to ASP-reachable segments is the primary reduction lever.
Beyond filtering, compression is a secondary lever.

### Recommended Approach: Filter-First, Then Compress

**Step 1 — Filter graph.json to ASP-relevant segments only (build-time)**

During `build_index.py`, mark only segments with `has_asp_left=True` or
`has_asp_right=True` (already in segments.json). Include those segments plus
their immediate neighbors (one BFS hop) to preserve graph connectivity for
Level 4 traversal. This alone targets ~50-55% size reduction before compression.

No new library needed. Pure Python dict/set operations in the existing build script.

**Step 2 — Compress with zstandard at load time (optional, further reduction)**

If filtering alone does not reach ≤4 MB, apply zstd compression to graph.json.gz
at build time and decompress transparently in `StreetGraph.load()`.

### Supporting Libraries for Compression

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| zstandard | 0.25.0 | Compress graph.json at build time; decompress at load time | Best compression ratio vs speed tradeoff. 30-40% size reduction on JSON. Self-contained wheels — no external C library install needed. `python-zstandard` package name on PyPI. Python >=3.9 compatible. NOT needed if filtering alone achieves ≤4 MB target |

**Do NOT use:**
- `gzip` / `zlib` (stdlib): Lower compression ratio than zstd at same speed
- `bz2` (stdlib): Better ratio but slower decompression — adds latency on HA startup
- `msgpack`: Binary serialization is an alternative encoding, but (1) msgpack +
  compression is not meaningfully smaller than JSON + compression for string-heavy
  data like street names, and (2) it adds a dependency with no load-time benefit
  since decompression dominates

**orjson as faster JSON loader (optional, not required):**

If zstd is not used and raw JSON parse time on HA startup becomes a concern,
`orjson` (3.11.7) parses JSON roughly 2x faster than stdlib `json`. However:
- The current load path is already in `asyncio.to_thread()` so it never blocks HA
- orjson is a compiled Rust extension (binary wheel); adds ~2 MB to HA install footprint
- **Verdict: Do not add orjson unless profiling shows graph.json parse as a bottleneck**

### Compression Sizing Estimate

| Approach | Estimated Size | New Dependency |
|----------|---------------|----------------|
| Current (all segments, plain JSON) | 7.9 MB | — |
| Filter ASP-relevant + 1-hop neighbors | ~3.5–4.5 MB | None |
| Filter + zstd level 3 compression | ~1.0–1.5 MB | zstandard 0.25.0 |

**Recommendation: Implement filtering first. Add zstd only if filtered size > 4 MB.**

The filtering change is in `build_index.py` (build-time) and `graph.py` (load-time
path stays the same). No change to `StreetGraph` class interface.

---

## Capability 2: Queens Coverage Investigation

### Problem Analysis

Queens is at 36.8% coverage vs 58.2% Manhattan and 74.1% Brooklyn. The root
cause is almost certainly street name normalization mismatches between CSCL and
SODA formats specific to Queens naming conventions — NOT a data gap in the SODA
dataset itself.

Queens-specific naming issues known to cause mismatches:

1. **Numbered avenue variants**: Queens uses "108 AVENUE", "108 AVE", "108TH
   AVENUE", "108TH AVE" interchangeably. The current `normalize_to_soda()`
   handles `AVE → AVENUE` suffix but does NOT handle the ordinal suffix variant
   (`108 AVENUE` vs `108TH AVENUE`). CSCL uses `108 AVE`; SODA may use `108
   AVENUE` or `108TH AVENUE`.

2. **Numbered street ordinal variants**: `108 ST` → `108 STREET` (handled) vs
   `108TH STREET` (not handled). Queens numbered streets consistently use ordinal
   form in SODA data.

3. **Named avenues with directional qualifiers**: `HILLSIDE AVE` → `HILLSIDE
   AVENUE` (handled) but `UNION TPKE` (Turnpike) is not in `_SUFFIX_EXPANSIONS`.

4. **Multiple carriageways**: Queens Boulevard, Woodhaven Boulevard, and similar
   divided highways have separate centerlines per carriageway in CSCL. The BFS
   graph may not connect across the median, causing Level 4 to fail for mid-span
   blocks on these roads.

### Investigation Tooling Needed

No new library is needed for the investigation itself. The work is:

1. **Coverage audit script** (`scripts/audit_queens_coverage.py`):
   - Query all Queens segments from segments.json (borocode=4)
   - For each segment without has_asp_left/right, attempt Level 1-4 sign retrieval
     against live SODA API
   - Log the outcome (which level matched, or NoMatchFound) and the exact street
     names submitted to SODA
   - Output CSV for pattern analysis

2. **Normalization additions** in `normalize.py`:
   - Add ordinal number suffix handling: `"108 AVE"` → `"108TH AVENUE"` variant
   - Add `TPKE → TURNPIKE`, `EXPY → EXPRESSWAY` (already in), `PKWY → PARKWAY`
     (already in), `HWY → HIGHWAY` (already in)
   - `name_variants()` should return the ordinal form as an additional variant
     so Level 2 tries it

3. **BFS connectivity for divided highways** in `build_index.py`:
   - Investigate whether `physicalid` adjacency correctly links parallel
     carriageways (it should via shared node coordinates, but verify for Queens
     Boulevard specifically)

**No new library is required for Queens investigation.** The work is diagnostic
(audit script using existing stack) followed by normalization table expansion.

### Supporting Libraries — Queens Coverage

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pandas | Already available via geopandas in build deps | Aggregate audit CSV results by pattern | Only in `scripts/` (build-time), not in runtime package |

Do NOT add pandas as a runtime dependency. It is already available in the `[build]`
extra via geopandas. The audit script runs offline.

---

## Capability 3: Structured Logging / Level 4 Observability

### Problem Analysis

Current logging uses Python stdlib `logging` with free-form `logger.info()`/
`logger.debug()` calls. There is no machine-readable way to extract:
- Which SODA fallback level was used per resolve call
- How often Level 4 fires (indicating mid-span blocks being resolved)
- The graph BFS hop distances involved in Level 4 span selection
- Borough-level breakdown of level distributions

The HA sensor already exposes `soda_level` in `ASPDebugResult`, but this is only
visible when `debug=True`. Normal production resolves silently succeed/fail.

### Recommended Approach: stdlib logging with structured extras

**Do NOT add structlog.** Home Assistant custom components must interoperate with
HA's logging infrastructure, which is built entirely on Python stdlib `logging`.
HA users configure log levels via `configuration.yaml` using logger names like
`custom_components.asp_parking`. Adding structlog as a dependency introduces:
- A 200 KB+ wheel to HA's install footprint
- A separate configuration surface (structlog processors) that bypasses HA's
  logger configuration UI
- Import-order coupling that is fragile in HA's custom component loading model

**Use stdlib `logging` with structured `extra={}` dicts instead.**

Python's stdlib `logging.getLogger(__name__).info(msg, extra={...})` passes
key-value pairs into `LogRecord.__dict__`. Combined with a custom `Formatter`
or HA's existing JSON log formatter, these fields become queryable. This is the
pattern all HA core integrations use.

### Implementation Pattern

**In `signs/__init__.py` — add structured log at each level match:**

```python
logger.info(
    "SODA match",
    extra={
        "soda_level": 4,
        "on_street": on_street,
        "borough": _infer_borough(on_street),
        "bfs_distance": best_distance,
        "event": "soda_level_match",
    }
)
```

**In `signs/graph.py` — log BFS outcomes:**

```python
logger.debug(
    "BFS span score",
    extra={
        "event": "bfs_span_scored",
        "span_from": span_from,
        "span_to": span_to,
        "distance": dist,
    }
)
```

**In `pipeline.py` — log resolve outcome:**

```python
logger.info(
    "resolve_asp complete",
    extra={
        "event": "resolve_complete",
        "soda_level": soda_level,
        "resolution_failed": False,
        "borocode": resolution.borocode,
    }
)
```

### soda_level in HA Sensor Attributes

The `soda_level` is already in `ASPDebugResult.soda_level` but not exposed in
the HA sensor attributes for production resolves. The fix is to:
1. Add `soda_level: int` to `ASPResult` (the non-debug result type)
2. Populate it from `sign_result.soda_level` in `pipeline.py`
3. Expose it as a sensor state attribute in `sensor.py`

This requires no new library — it is a field addition to an existing frozen
dataclass.

### Supporting Libraries — Observability

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| None required | — | stdlib logging + extra= dicts covers all needs | — |

**Do NOT add:**
- `structlog`: Incompatible with HA logging model (see above)
- `prometheus_client`: Overkill for a single-user local HA integration; no
  Prometheus scraping infrastructure in home HA setups
- `opentelemetry`: Same reason — designed for distributed systems, not home automation

---

## Installation Changes for v2.0

### Runtime dependencies (pyproject.toml and manifest.json)

**No new runtime dependencies required** for Queens coverage improvement or
observability. Both use existing stdlib (`logging`) and existing data structures.

**Conditional new dependency** (only if filtering alone does not reach ≤4 MB):

```toml
# pyproject.toml — add to dependencies only if compression needed
"zstandard>=0.23.0",
```

```json
// manifest.json — add to requirements only if compression needed
"zstandard>=0.23.0"
```

### Build-time dependencies (pyproject.toml `[build]` extra only)

No change needed. geopandas already available for the audit script.

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Graph compression | zstandard | gzip/zlib | Lower ratio at same decompression speed; no advantage |
| Graph compression | zstandard | msgpack binary | String-heavy data compresses similarly either way; adds encoding migration risk |
| Graph size reduction | Filter ASP-relevant segments | Reduce stored fields per segment | Fields (street name, cross streets) are load-time normalized; can't be removed without changing BFS logic |
| Observability | stdlib logging + extra= | structlog | Incompatible with HA logging model; unnecessary dependency weight |
| Observability | stdlib logging + extra= | prometheus_client | Requires Prometheus infrastructure; no value for single-user home setup |
| Queens normalization | Extend name_variants() | NYC Geoclient API | Geoclient API requires developer account registration; adds network dependency to the build path; overkill when the normalization gap is a known pattern |
| soda_level exposure | Add to ASPResult dataclass | Separate metrics endpoint | HA sensor attributes are the natural home for resolution metadata; no separate endpoint needed |

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| structlog | Bypasses HA logging infrastructure; incompatible with logger configuration UI | stdlib `logging` with `extra={}` dicts |
| orjson | 2x JSON parse speedup not needed; graph.json load is already in `asyncio.to_thread()`; adds ~2 MB compiled wheel | stdlib `json` (keep current) |
| msgpack | String-heavy graph.json does not benefit from binary encoding after compression; adds format migration cost | JSON + zstandard if compression needed |
| pandas (runtime) | Already available in `[build]` extras via geopandas; should not be a runtime dependency | pandas in scripts/ only via build extras |
| geopandas (runtime) | Same reason; build-time only | geopandas in `[build]` extras only |

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| zstandard 0.25.0 | Python >=3.9 | No conflict with Python 3.11+ requirement |
| zstandard 0.25.0 | Home Assistant 2025.x | Not a HA core dependency; safe to add as custom component requirement |
| orjson 3.11.7 | Python 3.10–3.15 | If ever needed; NOT recommended for this project |

## Sources

- [zstandard on PyPI](https://pypi.org/project/zstandard/) — Version 0.25.0, Sep 2025, Python >=3.9, prebuilt wheels (HIGH confidence)
- [python-zstandard documentation](https://python-zstandard.readthedocs.io/en/latest/) — API docs, compression levels, file-like object API (HIGH confidence)
- [orjson on PyPI](https://pypi.org/project/orjson/) — Version 3.11.7, Feb 2026, 10x faster than stdlib json (HIGH confidence)
- [structlog documentation](https://www.structlog.org/en/stable/logging-best-practices.html) — Best practices, stdlib integration pattern (HIGH confidence — verified NOT appropriate for HA custom components)
- [Home Assistant Logger integration docs](https://www.home-assistant.io/integrations/logger/) — How HA manages logger namespaces and log levels for custom components (HIGH confidence)
- [NYC Queens address format](https://streeteasy.com/blog/queens-addresses-hyphenated-confusing-street-names/) — Queens street naming conventions and ordinal suffix usage (MEDIUM confidence — secondary source for normalization rationale)
- [msgpack vs JSON compression benchmark](https://www.peterbe.com/plog/msgpack-vs-json-with-gzip) — Compressed JSON size comparable to compressed msgpack for string-heavy data (MEDIUM confidence)

---
*Stack research for: GPS2ASP Resolver v2.0 — coverage and observability additions*
*Researched: 2026-03-13*
