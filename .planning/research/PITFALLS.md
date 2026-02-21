# Pitfalls Research

**Domain:** GPS-to-ASP parking regulation resolver for NYC (Home Assistant integration)
**Researched:** 2026-02-21
**Confidence:** HIGH (verified against official data sources, pyproj docs, SODA API docs)

## Critical Pitfalls

### Pitfall 1: GPS Cannot Reliably Determine Street Side in Urban Canyons

**What goes wrong:**
Consumer GPS (including car GPS from VW CarNet) has 3-5m accuracy under good conditions, but in NYC's urban canyons -- tall buildings on both sides of narrow streets -- accuracy degrades to 10-30m due to multipath reflections. GPS signals bounce off building facades, placing the vehicle on the wrong side of the street, wrong block, or even the wrong street entirely. Research confirms "the current GNSS positioning accuracy in urban canyons is not sufficient for identifying the sides of a street." A typical Brooklyn residential street is ~18m (60 feet) wide curb-to-curb. A 10m GPS error puts you on the wrong side; a 20m error puts you on the wrong block.

**Why it happens:**
Developers test in open areas or with simulator coordinates and assume GPS accuracy is always ~3m. In real conditions, particularly in NYC boroughs with tall buildings, multipath effects cause systematic bias, not just random scatter. The VW CarNet integration updates only every 5-10 minutes (constrained by VW API rate limits of ~480 calls/day), so the position fix may be stale from when the car was still moving.

**How to avoid:**
Do NOT rely on GPS alone for street-side determination. Implement a multi-signal approach:
1. Use GPS to narrow to a candidate block segment (street name + cross streets)
2. Use nearest-segment snapping: project the GPS point onto the nearest street centerline, then determine which side based on perpendicular offset direction
3. For ambiguous cases (GPS point within ~5m of centerline), present BOTH sides to the user or use heading/bearing from recent GPS fixes to infer the side
4. Allow manual override -- a "confirm side" button in the HA notification
5. Consider using the street geometry from NYC LION data (street centerlines) for the snapping algorithm rather than sign coordinates alone

**Warning signs:**
- Test coordinates always work perfectly (you are using ideal simulator data)
- No test cases for locations where streets are close together (e.g., intersections, angled streets in Greenwich Village or parts of Brooklyn near Prospect Park)
- No handling for "ambiguous" result when GPS point is equidistant from both sides
- No user confirmation flow in the design

**Phase to address:**
Phase 1 (Core GPS Resolution). This is foundational -- if you get the wrong side of the street, every downstream computation is wrong. Build the nearest-segment snapping algorithm with confidence scoring from day one.

---

### Pitfall 2: NY State Plane Coordinate Conversion -- Axis Order and Unit Traps

**What goes wrong:**
The NYC Open Data parking sign dataset uses NY State Plane coordinates (EPSG:2263, NAD83/New York Long Island, US Survey Feet). Converting from WGS84 GPS coordinates (EPSG:4326) has three documented gotchas that produce silently wrong results:

1. **Axis order confusion**: EPSG:4326 officially has latitude-first (north, east) ordering, while EPSG:2263 uses easting-first. Pyproj 2.0+ respects the official axis order by default, meaning `transform(lat, lon)` not `transform(lon, lat)` for EPSG:4326. Getting this backwards doesn't throw an error -- it returns coordinates somewhere in the mid-Atlantic ocean.

2. **Unit mismatch (historical)**: Pyproj versions before 2.0 defaulted to `preserve_units=False`, silently converting all output to meters even when the target CRS specified US Survey Feet. This bug (pyproj issue #67) produced coordinates at roughly 1/3 the expected values. While fixed in pyproj >=2.0 (preserve_units=True is now default), legacy code examples and tutorials still show the old pattern.

3. **Deprecated Proj vs Transformer**: Using `pyproj.Proj` and `pyproj.transform()` is deprecated. These functions do not account for datum shifts between WGS84 and NAD83. While the datum difference is small (~1-2m for NYC), it compounds with GPS error. Use `pyproj.Transformer.from_crs()` exclusively.

**Why it happens:**
Stack Overflow answers and tutorials from 2016-2020 still rank highly and show deprecated patterns. Developers copy these, get results that "look about right" on a map, and ship it. The 1-2m datum shift error is invisible when GPS itself has 5m error -- until you are resolving which side of a street someone is on, where every meter counts.

**How to avoid:**
```python
from pyproj import Transformer

# CORRECT: Use EPSG codes, not proj strings. Use Transformer, not Proj.
transformer = Transformer.from_crs("EPSG:4326", "EPSG:2263", always_xy=True)

# With always_xy=True, input is (longitude, latitude) regardless of CRS axis order
x_feet, y_feet = transformer.transform(longitude, latitude)
```

Key rules:
- Always use `Transformer.from_crs()`, never `Proj` + `transform()`
- Always pass `always_xy=True` to normalize axis order to (x/lon, y/lat)
- Verify output is in US Survey Feet (values in 900,000-1,100,000 range for x, 120,000-280,000 range for y in NYC)
- Write a unit test that converts a known NYC address (e.g., Brooklyn Borough Hall: -73.9903, 40.6934) and asserts the State Plane output is within 1 foot of expected values
- Pin pyproj version in requirements to avoid regression

**Warning signs:**
- Using `from pyproj import Proj` or `pyproj.transform()` anywhere
- Using proj4 strings (`+proj=lcc +lat_1=...`) instead of EPSG codes
- No unit test validating a round-trip conversion
- Output coordinates look like meters (~300,000) instead of feet (~980,000)

**Phase to address:**
Phase 1 (Core GPS Resolution). Coordinate conversion is the first computation in the pipeline. Get it wrong and nothing else works. Write conversion utilities with tests before touching the SODA API.

---

### Pitfall 3: Dataset Contains Historical/Voided Signs -- Must Filter Aggressively

**What goes wrong:**
The NYC parking regulation dataset (`nfid-uabd`) contains over 1 million records including both current AND historical signs. Signs that have been replaced, voided, or superseded remain in the dataset. If you query by location without filtering, you will get back multiple conflicting regulations for the same curb segment -- some current, some from years ago. Your parser will either pick the wrong one or try to reconcile contradictory schedules.

The dataset has a `sign_design_voided_on_date` field (null for active signs, a date for voided ones) and a `record_type` field that distinguishes current from historical records. Failing to filter on these fields means treating superseded regulations as active.

**Why it happens:**
The default SODA API query returns all matching records. The dataset documentation does not prominently warn that historical records are included. A developer queries by street/block and gets back results that "look right" without realizing some are from signs that no longer exist.

**How to avoid:**
Always include these filters in every SODA query:
```
$where=sign_design_voided_on_date IS NULL
```
Additionally, filter or sort by `order_completed_on_date` to prefer the most recently installed signs. When multiple active signs exist for the same segment and side, they may represent DIFFERENT sign poles along the block (which is valid -- different stretches can have different rules based on arrow direction).

Validate by:
1. Querying a known block and comparing results against the NYC DOT Signs Locator (nycdotsigns.net)
2. Checking that the number of results for a block is reasonable (typically 2-8 active signs per block side, not 20+)

**Warning signs:**
- Getting 50+ results for a single block segment
- Seeing conflicting schedules for the same side of the same block
- No `sign_design_voided_on_date IS NULL` filter in your SODA queries
- Not cross-referencing results against the visual sign locator tool

**Phase to address:**
Phase 2 (SODA API Integration). This filter must be in every query from the start. Build it into the query builder function, not as an afterthought.

---

### Pitfall 4: Sign Description Parsing -- Wildly Inconsistent Formats

**What goes wrong:**
The `sign_description` field in the dataset is free-text, not structured data. ASP signs (identifiable by containing "SANITATION BROOM SYMBOL") have numerous format variations that break naive regex parsers:

**Known format variations include:**
- `NO PARKING (SANITATION BROOM SYMBOL) 9:30AM-11AM MON & THURS`
- `NO PARKING (SANITATION BROOM SYMBOL) 3AM-6AM MON & THURS`
- `NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 8:30AM-10AM`
- `NO PARKING (SANITATION BROOM SYMBOL) MON THRU FRI 8AM-6PM` (uses "THRU" for ranges)
- `NO PARKING (SANITATION BROOM SYMBOL) 8AM-9:30AM MON & THURS EXCEPT HOLIDAYS`
- Day names may be abbreviated (MON, TUES, WED, THURS, FRI, SAT, SUN) or full (MONDAY, TUESDAY...)
- Time format may use period (9.30AM) or colon (9:30AM)
- Ampersand (&) vs comma vs space as day separator
- "EXCEPT HOLIDAYS" or "EXCEPT LEGAL HOLIDAYS" suffix
- Some signs have multiple time windows on a single sign
- "SCHOOL DAYS ONLY" or "SCHOOL DAYS" qualifiers
- AM/PM may or may not have a space before it

A regex that handles 90% of formats will silently produce wrong results for the other 10%, and you will not know until someone gets a ticket.

**Why it happens:**
Sign descriptions are entered by DOT field workers over decades. There is no enforced schema. Developers write a parser that handles the first 5-10 examples they encounter and assume they have covered all cases. The long tail of unusual formats only surfaces in production.

**How to avoid:**
1. Download a representative sample (all ASP signs -- filter for `SANITATION BROOM SYMBOL`) and catalog ALL unique format patterns before writing a single regex
2. Build a parser that returns a confidence score: HIGH (known pattern matched), LOW (partial match, best guess), NONE (unrecognizable)
3. Log all NONE and LOW confidence parses for manual review
4. Write individual test cases for each format variation discovered
5. Consider a layered approach: normalize the text first (uppercase, collapse whitespace, standardize abbreviations), then parse the normalized form
6. For any sign you cannot confidently parse, surface the raw text to the user rather than silently guessing wrong

**Warning signs:**
- Parser has fewer than 20 test cases
- No logging of unparseable signs
- No confidence scoring on parse results
- Tested against fewer than 100 real sign descriptions
- Using a single regex for all formats

**Phase to address:**
Phase 2 (SODA API Integration) and Phase 3 (Schedule Computation). The parser is built in Phase 2 but validated comprehensively in Phase 3 when computing actual next-move times. Include a "parser coverage" metric: what percentage of all ASP signs in the dataset does your parser successfully handle?

---

### Pitfall 5: Holiday Calendar Drift and Emergency Suspensions Are Not Static Data

**What goes wrong:**
ASP is suspended on 30+ NYC holidays per year. The holiday list changes annually -- the city publishes a new calendar each January for the coming year (available as PDF and ICS). Additionally, emergency suspensions (snow, severe weather) are announced with as little as a few hours' notice and have no structured API. Developers who hardcode the holiday list or import it once at build time will have wrong data by the following January. Developers who skip emergency suspension handling will tell users to move their car during a blizzard when ASP is actually suspended.

**Why it happens:**
The holiday calendar feels static -- "it is the same holidays every year." But exact dates shift (religious holidays based on lunar calendars), and the city occasionally adds or removes holidays. Emergency suspensions are fundamentally unpredictable and require polling.

**How to avoid:**
1. **Holiday calendar**: Download the official ICS file from NYC DOT (https://www.nyc.gov/html/dot/downloads/ics/asp-calendar-2026.ics) and parse it. Refresh annually in January. Store as data, not code.
2. **Emergency suspensions**: Use the NYC 311 API (confirmed working by aspnyc.info). The 311 Today RSS feed contains 39 days of data (7 past + current + 31 future). Poll every 1-2 hours during weather events, daily otherwise.
3. **Fallback**: Follow @NYCASP on X/Twitter as a secondary signal. The Notify NYC service also provides notifications that could be monitored.
4. **Never assume**: If you cannot confirm suspension status, default to "ASP IS IN EFFECT" (the safe assumption that prompts the user to move their car). False alarm is better than a ticket.

Data sources ranked by reliability:
- NYC 311 API (official, programmatic, confirmed by third-party apps) -- PRIMARY
- NYC DOT ICS calendar file (official, structured, annual refresh) -- FOR KNOWN HOLIDAYS
- @NYCASP Twitter/X (official, but no API -- requires scraping) -- FALLBACK
- Notify NYC (official, push-based, but scraping required) -- SECONDARY

**Warning signs:**
- Holiday list is a Python list/dict in source code rather than an external data file
- No mechanism to refresh the holiday calendar annually
- No polling for emergency suspensions
- No fallback behavior when suspension data is unavailable
- Testing only with "today is not a holiday" scenarios

**Phase to address:**
Phase 3 (Schedule Computation) for the holiday calendar. Phase 4 (Suspension Monitoring) for emergency suspension polling. The holiday calendar is needed before you can compute "next time to move" correctly; emergency suspensions are a separate polling concern.

---

### Pitfall 6: SODA API Default Pagination Silently Truncates Results

**What goes wrong:**
The SODA API defaults to returning only 1,000 records per request. If a query matches more than 1,000 records (common when querying by borough or broad area), the API silently returns only the first 1,000 with no error or warning. Your code processes these 1,000 records thinking it has everything, missing signs that happen to fall outside the first page.

For the parking regulation dataset with 1M+ records, even a filtered query for a few blocks could exceed 1,000 if you are not filtering tightly enough (e.g., forgetting to filter out voided signs).

**Why it happens:**
The API follows REST pagination conventions but does not include a "total_count" or "has_more" header that would make truncation obvious. Developers test with small result sets that fit in one page and never discover the limit.

**How to avoid:**
1. Always set an explicit `$limit` parameter. If you expect few results (a single block), set `$limit=100` -- if you get 100, something is wrong. If you expect many, paginate.
2. For block-level queries (the primary use case), filter tightly: `on_street`, `from_street`, `to_street`, `side_of_street`, plus voided filter. This should return <20 results.
3. If building a cache of all signs, implement proper pagination: loop with `$offset` incrementing by `$limit` until a response returns fewer records than the limit.
4. Register for a SODA app token (free) to avoid the lower unauthenticated throttle. Without a token, you hit lower rate limits; with one, effectively unlimited for reasonable use.

**Warning signs:**
- Getting exactly 1,000 results from any query (this is almost certainly truncated)
- No `$limit` parameter in API calls
- No SODA app token configured
- Cache-building code that makes a single API call for a borough

**Phase to address:**
Phase 2 (SODA API Integration). Pagination awareness must be built into the API client from the start.

---

## Moderate Pitfalls

### Pitfall 7: Arrow Direction and Sign Sequence Create Block-Segment Complexity

**What goes wrong:**
ASP rules are not uniform for an entire block side. A single block can have different regulations at different positions along the curb, delimited by sign arrow directions:
- **Single arrow**: regulation applies from this sign in the direction of the arrow until the next sign or end of block
- **Double arrow**: regulation applies in both directions from this sign until the next sign or end of block

The dataset includes `arrow_direction`, `sign_location` (intersection placement), and `distance_from_intersection` (feet from corner). To determine which regulation applies at a specific GPS position, you must reconstruct the curb segments by ordering signs by their distance from intersection, applying arrow logic, and finding which segment contains your car.

Most developers treat the entire block side as having one uniform regulation.

**How to avoid:**
1. For MVP, query all signs on a block side, check if they all have the same ASP schedule. If yes (common case), use that schedule. If schedules differ, report the most restrictive one (earliest next-move time) and flag uncertainty.
2. For V2, implement proper segment matching using `distance_from_intersection` and the GPS-derived distance from the nearest intersection to determine exactly which sign covers the car's position.
3. Test with blocks known to have mixed regulations (e.g., near school zones or commercial/residential boundaries).

**Warning signs:**
- Assuming one ASP schedule per block side
- Ignoring `arrow_direction` and `distance_from_intersection` fields
- Not handling the case where a block has zero ASP signs (no cleaning on that block)

**Phase to address:**
Phase 2 (basic: uniform block assumption with warning) and Phase 5 (advanced: per-segment resolution).

---

### Pitfall 8: OpenCurb API Is NOT a Viable Fallback for Brooklyn

**What goes wrong:**
The PROJECT.md states OpenCurb "works in Brooklyn despite claiming Manhattan only." Research reveals this is incorrect. The OpenCurb API documentation explicitly states coverage is limited to "Midtown Manhattan (from 30th to 59th street both East and West)" only. The primary use area (Prospect Heights, Brooklyn) is completely outside OpenCurb's coverage. Additionally, OpenCurb returns regulation status (can/cannot park at time X) but not the raw schedule needed to compute "next time to move."

Designing the system with OpenCurb as a validation layer or fallback will waste development time on an integration that cannot serve the primary use case.

**How to avoid:**
Remove OpenCurb from the architecture. Rely exclusively on NYC Open Data (SODA API) as the sign data source. If a secondary validation source is needed, use the NYC DOT Signs Locator (nycdotsigns.net) for manual spot-checking during development, not as a runtime dependency.

**Warning signs:**
- Architecture diagrams showing OpenCurb as a fallback or validation data source
- Any code importing or calling opencurb.nyc
- Testing only in Midtown Manhattan where OpenCurb happens to work

**Phase to address:**
Phase 1 (Architecture). Remove from design before building anything.

---

### Pitfall 9: VW CarNet API Rate Limits Constrain GPS Update Frequency

**What goes wrong:**
The VW Connect API has a hard limit of approximately 480 calls per day (~1 call every 3 minutes). The default HA integration polls every 5 minutes (288 calls/day). If the user also uses the VW app directly, combined calls may hit the limit, causing the integration to fail silently or return stale location data. At a 5-minute poll interval, the car could have parked and the driver could have walked away before the system even registers the final parked position.

**Why it happens:**
Developers treat the GPS position as "real-time" when it may be 5-10 minutes old. The last fix before the car was turned off might have been captured while the car was still rolling into the spot, not at its final resting position.

**How to avoid:**
1. Design for stale data: the GPS coordinate received is "approximately where the car was up to 10 minutes ago"
2. Use a wider search radius for candidate block segments (e.g., 50m instead of 10m)
3. When the car transitions from "driving" to "parked" (velocity drops to 0 or ignition off), trigger one final position refresh if the VW API allows on-demand requests
4. Document the 480/day limit and recommend users set the HA integration to 10-minute intervals if they use the VW app simultaneously
5. Cache the last known position and do not re-query ASP signs unless the position changes by more than 20m

**Warning signs:**
- Assuming GPS updates arrive within seconds of parking
- No handling for "position hasn't changed" between polls
- VW API errors appearing in HA logs (429 rate limit responses)
- No mention of VW API rate limits in documentation

**Phase to address:**
Phase 1 (Architecture design) and Phase 5 (HA Integration). Account for stale GPS in the core design; handle VW-specific rate limits in the integration phase.

---

### Pitfall 10: Caching Strategy Must Handle Data Staleness Without Silent Failures

**What goes wrong:**
ASP signs rarely change (~yearly), making caching attractive. But a naive cache has multiple failure modes:
1. Cache is populated but sign was replaced/voided -- user gets wrong schedule until cache expires
2. Cache expires during a network outage -- system has no data and fails to provide any answer
3. Cache key is too broad (e.g., entire street) -- returns signs from wrong block segment
4. Cache key is too narrow (e.g., exact GPS coordinate) -- almost never hits, cache is useless

**How to avoid:**
1. Cache key should be `(on_street, from_street, to_street, side_of_street)` -- the block segment, not the GPS coordinate
2. Set cache TTL to 7 days (weekly refresh as specified in requirements), but serve stale data if refresh fails (stale-while-revalidate pattern)
3. On refresh failure, log a warning but continue serving cached data. Only hard-fail after 30+ days of stale data.
4. Store cache timestamp with the data so the system can report "based on data from [date]" for transparency
5. When a new sign query succeeds, compare with cached version. If different, log the change -- it could indicate a sign update that needs attention.

**Warning signs:**
- Cache key includes GPS coordinates instead of block identifiers
- No fallback to stale cache when API is down
- No timestamp tracking on cached data
- No alerting when cache is more than 14 days old

**Phase to address:**
Phase 2 (SODA API Integration) for cache architecture. Phase 4 for cache health monitoring.

---

## Minor Pitfalls

### Pitfall 11: Street Name Matching Between GPS Geocoding and NYC Dataset

**What goes wrong:**
To query the SODA API, you need street names (`on_street`, `from_street`, `to_street`). Getting these from a GPS coordinate requires reverse geocoding (e.g., via Nominatim, Google Geocoding, or NYC GeoClient). The street names returned by geocoding may not match the dataset exactly: "FIFTH AVE" vs "5TH AVE" vs "5 AVE" vs "FIFTH AVENUE", "PROSPECT PL" vs "PROSPECT PLACE". A query for "5TH AVE" when the dataset has "5 AVE" returns zero results.

**How to avoid:**
1. Use the NYC GeoClient API (api.nyc.gov) for reverse geocoding -- it returns street names in the same format as DOT datasets because they share NYC geographic infrastructure
2. If using a different geocoder, build a normalization layer: strip directional prefixes (N/S/E/W), normalize avenue/street/place/boulevard suffixes, convert ordinals to the NYC format
3. Test with at least 20 addresses from different boroughs, including edge cases like "AVENUE OF THE AMERICAS" (6th Ave), "ADAM CLAYTON POWELL JR BLVD" (7th Ave uptown), and Brooklyn streets with numbered names

**How to avoid:**
Use NYC GeoClient as the geocoder. It speaks the same vocabulary as NYC DOT datasets.

**Warning signs:**
- SODA queries returning zero results for locations you know have ASP signs
- Using Google Maps or Nominatim for reverse geocoding without normalization
- No test cases for street name format variations

**Phase to address:**
Phase 1 (GPS Resolution). Street name resolution is needed before you can query SODA.

---

### Pitfall 12: "EXCEPT HOLIDAYS" in Signs Requires Holiday-Aware Schedule Logic

**What goes wrong:**
Many ASP signs include "EXCEPT HOLIDAYS" or "EXCEPT LEGAL HOLIDAYS" in their description. If you parse the day/time schedule without also checking for this qualifier, you will tell users to move their car on holidays when ASP is suspended. This is the most common source of false-positive "time to move" notifications in parking apps.

**How to avoid:**
1. Parse the "EXCEPT HOLIDAYS" flag as a boolean on the schedule object
2. When computing next-move time, cross-reference the candidate date against the holiday calendar
3. If the next ASP window falls on a holiday, skip to the following occurrence
4. Handle the edge case of multi-day holidays (e.g., some religious holidays span 2 days)

**Warning signs:**
- Schedule computation does not reference a holiday calendar
- No test cases for "next move time falls on a holiday"
- Treating "EXCEPT HOLIDAYS" as decoration rather than a functional modifier

**Phase to address:**
Phase 3 (Schedule Computation).

---

### Pitfall 13: Side-of-Street Field Uses Compass Directions, Not Left/Right

**What goes wrong:**
The dataset's `side_of_street` field uses N/S/E/W (compass directions relative to the street's orientation), not "left" or "right" relative to travel direction. To match a GPS position to the correct side, you must know the street's compass orientation. For Manhattan's grid this is predictable (avenues run ~N/S, streets run ~E/W), but Brooklyn has diagonal streets, curved streets, and irregular grid sections (especially near Prospect Park, the primary use area).

**How to avoid:**
1. Use NYC LION street centerline data or OpenStreetMap to get the actual bearing/azimuth of each street segment
2. Project the GPS point onto the street centerline; determine which side based on perpendicular offset relative to the street's bearing
3. Map the computed side (left/right of centerline facing increasing addresses) to compass direction (N/S/E/W) using the street bearing
4. For diagonal streets, the N/S/E/W assignment follows DOT conventions, which may not match intuition

**Warning signs:**
- Hardcoding Manhattan grid assumptions (avenues=N/S, streets=E/W) for all boroughs
- No handling for diagonal or curved streets
- Not testing with Prospect Heights/Park Slope addresses where streets curve around the park

**Phase to address:**
Phase 1 (GPS Resolution). Street orientation determination is part of the core resolution algorithm.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Assume uniform ASP schedule per block side | Simpler parsing, faster MVP | Wrong results on blocks with mixed regulations (~15% of blocks) | MVP only; add segment resolution in v2 |
| Hardcode holiday calendar for current year | No ICS parsing needed | Breaks every January; wrong for religious holidays that shift yearly | Never -- ICS parsing is low effort |
| Skip emergency suspension polling | Avoid 311 API integration | Users told to move car during snowstorms | Never -- this is a core safety feature |
| Use Google/Nominatim for reverse geocoding | Familiar API, quick to implement | Street name mismatches with NYC dataset; requires normalization layer | Acceptable if normalization layer is robust; prefer NYC GeoClient |
| Cache entire borough of signs locally | Fast lookups, no API dependency | 100MB+ data, complex refresh, wasteful | Never for full borough; cache per-block on demand |
| Skip sign_design_voided filter | Fewer API parameters | Historical signs treated as current, wrong regulations served | Never -- one line of SoQL, critical correctness |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| SODA API (NYC Open Data) | Not registering an app token; hitting anonymous rate limits | Register free app token at data.cityofnewyork.us; include in every request |
| SODA API | Not setting `$limit`; getting silently truncated results at 1,000 | Always set explicit `$limit`; paginate if needed |
| SODA API | Querying `nfid-uabd` without filtering voided signs | Always include `sign_design_voided_on_date IS NULL` |
| pyproj | Using deprecated `Proj` + `transform()` instead of `Transformer` | Use `Transformer.from_crs("EPSG:4326", "EPSG:2263", always_xy=True)` |
| pyproj | Feeding (latitude, longitude) instead of (longitude, latitude) with `always_xy=True` | With `always_xy=True`, always pass (x=lon, y=lat) |
| VW CarNet HA integration | Polling too frequently, exceeding 480 calls/day VW API limit | Set scan_interval to 10+ minutes; check for position change before re-resolving |
| Home Assistant | Not using `DataUpdateCoordinator` for polling | Use coordinator pattern with appropriate `update_interval`; handle `ConfigEntryNotReady` for setup failures |
| Home Assistant | Missing unique entity IDs | Assign deterministic unique IDs based on VIN or entity config to enable UI management |
| NYC 311 API | Assuming structured data for emergency suspensions | 311 Today RSS returns text descriptions; parse carefully for ASP-specific entries |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Querying SODA API on every GPS update | Slow response, API throttling, unnecessary network calls | Cache signs per block segment; only re-query when car moves to a new block | Immediately in production use |
| Downloading all signs for a borough to build a local DB | 100MB+ download, long startup, memory pressure on HA host (often Raspberry Pi) | Cache on-demand per block; keep max ~100 blocks in LRU cache | On first run |
| Recomputing "next move time" on every HA poll | CPU load, unnecessary writes to HA state | Only recompute when: position changes, clock crosses a schedule boundary, or suspension status changes | With sub-minute polling (not current, but future-proofing) |
| Parsing sign descriptions with complex regex on every request | Measurable latency if many signs | Parse once at cache-write time; store structured schedule alongside raw text | If cache is disabled or bypassed |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Reporting only "next ASP window starts" without buffer time | User gets notification at 8:30 AM that ASP starts at 8:30 AM -- too late to move | Report "move by [time]" with configurable buffer (default 30-60 min before window) |
| Not distinguishing "ASP suspended" from "no ASP on this block" | User thinks suspension means their block has no ASP ever | Clear messaging: "ASP suspended today (holiday)" vs "No ASP regulations found for this location" |
| Silent failure when GPS resolution is ambiguous | User trusts the result but car is on wrong side; gets a ticket | Show confidence level: "HIGH: ASP Mon & Thu 8:30-10AM" vs "UNCERTAIN: could not determine street side, check signs" |
| Notification only via HA push | Notification buried among other HA alerts | Support HA persistent notification + optional separate notification channel (e.g., critical alert tag) |
| Showing next window without "all clear until" time | User moves car but doesn't know when to bring it back | Show both: "Move by 8AM Monday" AND "All clear after 10AM Monday" |

## "Looks Done But Isn't" Checklist

- [ ] **Sign parsing:** Tested against ALL format variations in real dataset, not just 5-10 hand-picked examples -- verify parser coverage >= 95% of actual ASP signs
- [ ] **Street-side resolution:** Tested with addresses on diagonal/curved streets (Prospect Heights, Park Slope) -- verify correct side determination on non-grid streets
- [ ] **Holiday calendar:** Tested rollover from December to January -- verify system picks up new year's calendar
- [ ] **Emergency suspensions:** Tested with mocked 311 API returning suspension -- verify notification changes from "move by X" to "ASP suspended"
- [ ] **Cache expiry:** Tested with expired cache + API down -- verify stale data served with warning, not hard failure
- [ ] **Coordinate conversion:** Tested round-trip conversion (WGS84 -> State Plane -> WGS84) -- verify <1 foot drift
- [ ] **Pagination:** Tested with block that returns > `$limit` results -- verify all results retrieved (should not happen with proper filtering, but defensive check)
- [ ] **Multiple signs per block:** Tested with block having different ASP schedules at different positions -- verify correct schedule (or most-restrictive fallback)
- [ ] **Edge case times:** Tested for "it's 9:55 AM and ASP ends at 10:00 AM" -- verify reports next occurrence, not current one

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Wrong street-side determination | LOW | Add manual override; user corrects once, system remembers for that location |
| Coordinate conversion bug | LOW | Fix transformer call; re-query and re-cache affected blocks; no data loss |
| Parsing wrong sign format | MEDIUM | Add format to parser; re-parse cached signs; review any incorrect notifications sent |
| Missing holiday suspension | MEDIUM | User may have moved car unnecessarily; update calendar; apologize in notification |
| Missing emergency suspension | HIGH | User may have gotten a ticket; add 311 polling immediately; consider reimbursement flow documentation |
| Stale cache serving voided signs | LOW | Force cache refresh; add voided filter if missing; re-query affected blocks |
| SODA API pagination truncation | MEDIUM | Add pagination; re-cache all affected blocks; audit past results for correctness |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| GPS street-side ambiguity (#1) | Phase 1: GPS Resolution | Test with 20+ real Brooklyn addresses; verify side matches physical observation |
| Coordinate conversion errors (#2) | Phase 1: GPS Resolution | Round-trip conversion test; known-address validation within 1 foot |
| Historical/voided sign inclusion (#3) | Phase 2: SODA Integration | Compare query results vs nycdotsigns.net for 5 test blocks |
| Sign description parsing failures (#4) | Phase 2-3: Parsing & Schedule | Parser coverage metric >= 95% of all BROOM SYMBOL signs |
| Holiday calendar maintenance (#5) | Phase 3: Schedule Computation | Test with dates spanning year boundaries and known holidays |
| SODA pagination truncation (#6) | Phase 2: SODA Integration | Assert no query returns exactly $limit records without investigation |
| Block-segment complexity (#7) | Phase 2 (basic) / Phase 5 (full) | Test blocks with mixed regulations; verify most-restrictive fallback |
| OpenCurb false reliance (#8) | Phase 1: Architecture | Remove from architecture; no OpenCurb code in codebase |
| VW CarNet rate limits (#9) | Phase 5: HA Integration | Monitor VW API error rate; document recommended poll interval |
| Cache staleness (#10) | Phase 2: SODA Integration | Simulate API outage; verify stale-serve with warning |
| Street name mismatches (#11) | Phase 1: GPS Resolution | Test 20 addresses across boroughs; zero SODA queries returning empty for known ASP streets |
| Holiday-aware scheduling (#12) | Phase 3: Schedule Computation | Test "next move" computation with holiday falling on ASP day |
| Compass direction mapping (#13) | Phase 1: GPS Resolution | Test with diagonal Brooklyn streets; verify N/S/E/W mapping matches dataset |

## Sources

- [SODA API App Tokens Documentation](https://dev.socrata.com/docs/app-tokens.html) -- Rate limits and throttling (MEDIUM confidence)
- [NYC Open Data Parking Regulation Dataset](https://data.cityofnewyork.us/Transportation/Parking-Regulation-Locations-and-Signs/nfid-uabd) -- Dataset structure (HIGH confidence, official)
- [NYC DOT ASP Suspensions Page](https://www.nyc.gov/html/dot/html/motorist/alternate-side-parking.shtml) -- Holiday calendar and suspension info (HIGH confidence, official)
- [NYC DOT 2026 ASP Calendar PDF](https://www.nyc.gov/html/dot/downloads/pdf/asp-calendar-2026.pdf) -- Annual suspension dates (HIGH confidence, official)
- [pyproj Gotchas Documentation](https://pyproj4.github.io/pyproj/stable/gotchas.html) -- Axis order, deprecated syntax (HIGH confidence, official)
- [pyproj Issue #67: EPSG 2263 Transformation Bug](https://github.com/pyproj4/pyproj/issues/67) -- Units bug in older versions (HIGH confidence, primary source)
- [EPSG:2263 Definition](https://epsg.io/2263) -- NY State Plane coordinate system (HIGH confidence, official)
- [OpenCurb API Documentation](https://www.opencurb.nyc/doc) -- Coverage limited to Midtown Manhattan only (HIGH confidence, official)
- [aspnyc.info](https://www.aspnyc.info/) -- Confirms NYC 311 API works for ASP suspension status (MEDIUM confidence, third-party)
- [VW CarNet HA Integration](https://github.com/robinostlund/homeassistant-volkswagencarnet) -- 480 calls/day VW API limit (MEDIUM confidence, community)
- [SODA API $limit Documentation](https://dev.socrata.com/docs/queries/limit.html) -- Default 1,000 record limit (HIGH confidence, official)
- [NYC Parking Sign Arrow Meanings](https://newyorkparkingticket.com/know-purpose-arrows-nyc-parking-sign/) -- Single vs double arrow semantics (MEDIUM confidence)
- [Home Assistant Fetching Data Documentation](https://developers.home-assistant.io/docs/integration_fetching_data/) -- DataUpdateCoordinator pattern (HIGH confidence, official)
- [Home Assistant Setup Failures Documentation](https://developers.home-assistant.io/docs/integration_setup_failures/) -- ConfigEntryNotReady pattern (HIGH confidence, official)
- [Sidewalk Matching Research](https://satellite-navigation.springeropen.com/articles/10.1186/s43020-025-00159-8) -- GPS urban canyon accuracy limitations (HIGH confidence, peer-reviewed)

---
*Pitfalls research for: GPS2ASP Resolver -- NYC Alternate Side Parking regulation resolver*
*Researched: 2026-02-21*
