# Graph Report - .  (2026-07-27)

## Corpus Check
- Large corpus: 253 files · ~1,639,887 words. Semantic extraction will be expensive (many Claude tokens). Consider running on a subfolder.

## Summary
- 4011 nodes · 7378 edges · 200 communities (156 shown, 44 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 341 edges (avg confidence: 0.58)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- HA Integration Test Suite
- Schedule Result Models & Suspension Merge
- Coordinator CalDAV Test Fixtures
- CalDAV Sync Core & Tests
- Diagnostic Sensor Entities
- Sign Retrieval & Level-4 Graph Tests
- GPS Coordinate Conversion & Exceptions
- Index Download & Atomic Swap
- Holiday Calendar & ICS Fetch
- Sign Text Parsing & Schedule Windows
- Street Name Normalization (CSCL to SODA)
- Active-Now Schedule Tests
- Debug Mode Switch Entity
- Coordinator Pipeline Orchestration
- Coordinator Rebuild Path Selection Tests
- Coordinator Stale-Data Tests
- CalDAV Event Building
- Coordinator Rebuild Executor Tests
- NYC311 Emergency Suspension Polling
- Temporal Edge-Case Use Cases
- Next-Move Sensor Test Builders
- Sign Retrieval Data Models
- Curb-Based Side Calibration
- Resolver Exceptions & Index Errors
- GPS Resolution Core & Borough Tests
- Spatial Index Build Script
- Coordinator Boundary-Timer Tests
- Ambiguity Classification Logic
- Index I/O Build Helpers
- CalDAV Compatibility Shim
- Index Rebuild Button Entity
- GPS Pipeline Health Sensor
- understand-anything Tour Analysis Tool
- Side-of-Street Confidence Scoring
- Schedule Computation Entry Point
- CalDAV Entry Lifecycle Hooks
- Coordinator Config Properties
- Confidence Scoring Module
- Button/Const/Cache Test Grouping
- Coordinator State Container & Borough Tests
- Schedule Result Variant Models
- Index Build-From-Source Tests
- Suspension Merge Tests
- Vendor Sync Script Tests
- Resolver Unit Tests
- Index Integrity Init Tests
- Diagnostic Sensor Base Classes
- resolve_asp() Pipeline Tests
- HA Diagnostics Export Tests
- Pipeline Demo & API Models
- Index-Rebuilding Binary Sensor Tests
- CalDAV Config & Coordinator Integration
- Street Adjacency Graph (BFS)
- CalDAV Options-Flow Tests
- Curb Calibration Tests
- Schedule Models & Compute Entry
- Schedule Summary & Window Merge
- Coverage Audit Script Tests
- Parking-History Calibration Fallback
- Lane-Snap Confidence Tests
- Index-Last-Rebuilt Sensor Tests
- Coordinate Converter Tests
- Time-Token Parsing Tests
- Side Determination Tests
- Coordinator Debug-Log Tests
- Spatial Index Query Tests
- SODA API Client
- understand-anything Graph Validator Tool
- Active-Now Binary Sensor
- Vendored Mirror Sync Concept
- HA Manifest Metadata
- ASPDebugResult Extended-Fields Tests
- 311 Startup Fetch & Bridge Tests
- Next-Move Computation Models
- Resolver Extended-Fields Tests
- Build-Index Graph Serialization Tests
- Vendor Sync Import-Rewrite Tests
- API Result Models
- Day-Extraction Parsing Tests
- Spatial-Index Radius Query Tests
- Index Rebuild Background Task Tests
- Push Notification Logic Tests
- SODA Client Exceptions
- Graph Filter Load Tests
- Index-Rebuild Workflow Rationale
- CalDAV Compat-Shim Context-Manager Tests
- Options Flow CalDAV Steps
- Coordinator Suspension State Application
- Street Graph Singleton & BFS
- Confidence Threshold Tests
- Normalize Query-Builder Tests
- Synthetic Curb Calibration Tests
- Coordinator Heartbeat Tests
- Active-Window Finder Tests
- understand-anything Cross-Check Tool
- Architecture Doc: Pipeline & Release Decoupling
- Suspension ICS Parsing Tests
- Index Calibration-Fallback Tests
- Resolver Candidate Fixture Tests
- Holiday Calendar Init & SSL
- Holiday Calendar Fallback Logic
- NYC311 Poller Fetch Status
- Curb/Roadbed Spatial Index Build
- Coordinator Periodic Tasks
- Schedule Summary Formatting Helpers
- i18n ICU-Escape Regression Tests
- Coordinator Callback Registration
- Development Guide & Bug-Hunt Docs
- Schedule Analysis: Lazy Merge & Vendor Drift
- CalDAVConfig.from_options Tests
- Coordinator GPS Watchdog
- Index Integrity-Check Tests
- Street-Name Variant Generation Tests
- NYC Holiday Calendar Module
- BFS-Between Segment Tests
- ASP Interior-Block Propagation Tests
- 2-Hop Graph Filter Tests
- Sensor Availability Logic Tests
- Parking-Area Options-Flow Tests
- Index Release Packager Tests
- Cross-Midnight Parsing Regression Tests
- CalDAV Missing-Method Exception Shim
- AmbiguousResolutionError Tests
- Shared Pytest Fixtures
- Config-Flow Step-Title Tests
- CalDAV Event-URL Builder Tests
- Config Flow Setup Steps
- Sensor Value Formatting
- NYC311 Auth & Response Parsing
- Street Adjacency Build Tests
- Intersection Index Build Tests
- HA Repair-Issue Tests
- Center-Offset Side Resolver Tests
- Coordinator CalDAV Write Hooks
- Sign Parser Core Functions
- Queens Coverage Audit Script
- SODA Fallback Strategy Doc
- Suspension Bug Report: Vendored HolidayCalendar
- Zero-Length Segment Guard Tests
- Fixture Geocoding Script
- Binary Sensor Device Info
- Resolution Debug Logging
- CSCL Update Checker
- CalDAV CancelledError Propagation Tests
- understand-anything Layer Verifier Tool
- Coordinator Stale-Check & Rebuild Trigger
- Resolution-Status Sensor
- Build-Index Cross-Street Lookup
- Random Fixture Generator Script
- SODA Fixed-Width Formatting Tests
- Vendor Sync Staged-Tree Fixtures
- Options-Flow Entry Point
- Rebuild-Path Decision Logic
- Coordinator Initialization
- Sign Parser Module Overview
- Sign-Cache Materialization Analysis
- Cross-Street-Match Bug Analysis
- understand-anything Count Tool
- Security Scan Workflows (Bandit/CodeQL)
- HACS/Hassfest Validation Workflows
- understand-anything Snapshot Artifacts
- CalDAV Bug: from_options KeyError
- Coordinator Bug: CalDAV Password Wipe
- Force-Resolve Service Hook
- Refresh-Interval Property
- Stale-Timeout Property
- Integration Icon Assets
- Next-Move Sensor Stale-Data Doc
- Named-Directional-Prefix Test (N)
- Named-Directional-Prefix Test (S)
- Directional-Suffix Test (W)
- Directional False-Positive Test
- Fixed-Width Single-Digit Test
- Non-Directional Spacing Test
- Suffix Expansion Test (Turnpike)
- Suffix Expansion Test (Crescent)
- Lettered Avenue Test (B)
- Lettered Avenue Test (D)
- Lettered Avenue Test (E)
- Numbered-Avenue Non-Expansion Test
- Idempotent Normalization Test (E)
- Idempotent Normalization Test (N)
- Idempotent Normalization Test (S)
- Directional False-Positive Test (Essex)
- Serena Project Config
- resolve_now HA Service Definition
- Coordinator/Infra/CalDAV Analysis Doc
- Borough Coverage Analysis Doc
- Stage-1 Resolver Analysis Doc
- Stage-2 SODA Analysis Doc
- Stage-3 Schedule Analysis Doc
- Suspension Analysis Doc
- Stage-1 Resolver Bug Report
- Stage-2 SODA Bug Report
- Stage-3 Suspension Bug Report
- Project Package Metadata
- SignRetrievalResult Doc Reference
- SuspensionInfo Doc Reference

## God Nodes (most connected - your core abstractions)
1. `ASPParkingCoordinator` - 131 edges
2. `ASPParkingData` - 107 edges
3. `normalize_to_soda()` - 69 edges
4. `TestNormalizeToSoda` - 59 edges
5. `parse_sign()` - 42 edges
6. `_require_caldav_sync()` - 40 edges
7. `_make_coord_stub_caldav()` - 40 edges
8. `_bind()` - 37 edges
9. `sensor_extra_attributes()` - 36 edges
10. `SuspensionInfo` - 35 edges

## Surprising Connections (you probably didn't know these)
- `main()` --shares_data_with--> `custom_components/asp_parking/gps2asp Vendored Mirror Package`  [INFERRED]
  scripts/sync_vendored.py → .github/workflows/vendor-guard.yml
- `Three-Stage GPS-to-ASP Pipeline` --implements--> `resolve_asp()`  [EXTRACTED]
  docs/ARCHITECTURE.md → src/gps2asp/pipeline.py
- `CalDAV Version Compatibility Shim` --implements--> `_CompatAsyncDAVClient`  [EXTRACTED]
  docs/DEVELOPMENT.md → custom_components/asp_parking/caldav_sync.py
- `UC-13: Queens street — Steinway Street, Astoria` --references--> `StreetGraph`  [EXTRACTED]
  docs/superpowers/analysis-stage1-boroughs.md → src/gps2asp/signs/graph.py
- `Side-of-Street Confidence Scoring` --conceptually_related_to--> `determine_side()`  [EXTRACTED]
  docs/superpowers/analysis-stage1-resolver.md → src/gps2asp/resolver/side_resolver.py

## Import Cycles
- 2-file cycle: `src/gps2asp/suspension/__init__.py -> src/gps2asp/suspension/merge.py -> src/gps2asp/suspension/__init__.py`
- 2-file cycle: `src/gps2asp/suspension/__init__.py -> src/gps2asp/suspension/poller.py -> src/gps2asp/suspension/__init__.py`
- 2-file cycle: `custom_components/asp_parking/__init__.py -> custom_components/asp_parking/coordinator.py -> custom_components/asp_parking/__init__.py`
- 2-file cycle: `custom_components/asp_parking/gps2asp/suspension/__init__.py -> custom_components/asp_parking/gps2asp/suspension/merge.py -> custom_components/asp_parking/gps2asp/suspension/__init__.py`
- 2-file cycle: `custom_components/asp_parking/gps2asp/suspension/__init__.py -> custom_components/asp_parking/gps2asp/suspension/poller.py -> custom_components/asp_parking/gps2asp/suspension/__init__.py`

## Hyperedges (group relationships)
- **HACS Release & Validation Pipeline** — _github_workflows_release, _github_workflows_index_rebuild, _github_workflows_hacs, _github_workflows_hassfest [INFERRED 0.75]
- **Vendored gps2asp Mirror Consistency Check** — _github_workflows_vendor_guard, scripts_sync_vendored_main, src_gps2asp_package, custom_components_asp_parking_gps2asp_package [INFERRED 0.85]
- **Functions forming the L1-L4 SODA fallback pipeline** — src_gps2asp_signs___init___retrieve_signs, src_gps2asp_signs_normalize_name_variants, src_gps2asp_signs___init___cross_streets_match, src_gps2asp_signs_graph_find_best_covering_span [INFERRED 0.85]
- **Suspension sources forming the bridge > holiday > 311 priority chain** — src_gps2asp_suspension___init___holidaycalendar, src_gps2asp_suspension_poller_nyc311client, custom_components_asp_parking_coordinator_aspparkingcoordinator [INFERRED 0.80]
- **Unsynced vendored gps2asp copy causes cascading suspension bugs** — docs_superpowers_bugs_coordinator_bug_h_001, docs_superpowers_bugs_coordinator_bug_h_002, docs_superpowers_bugs_coordinator_bug_h_003, concept_vendored_mirror_sync [INFERRED 0.85]

## Communities (200 total, 44 thin omitted)

### Community 0 - "HA Integration Test Suite"
Cohesion: 0.04
Nodes (82): ASPParkingData, _confidence_score_native_value(), _format_move_time(), _last_error_native_value(), _last_resolved_native_value(), _make_asp_active_now(), _make_cleaning_window(), _make_schedule_found() (+74 more)

### Community 1 - "Schedule Result Models & Suspension Merge"
Cohesion: 0.03
Nodes (75): ASPActiveNow, ASP schedule successfully parsed and next move window computed.      Attributes:, Car is currently parked during an active ASP cleaning window.      Attributes:, Full parsed weekly schedule for a block.      Contains all cleaning windows sort, ScheduleFound, WeeklySchedule, Suspension merge layer: apply_suspension() pure function.  Annotates ScheduleFou, ASPNextMoveTimeSensor (+67 more)

### Community 2 - "Coordinator CalDAV Test Fixtures"
Cohesion: 0.05
Nodes (87): _background_task_sink(), _bind(), _make_cleaning_window(), _make_coord_stub_caldav(), _make_schedule_found(), _make_suspension_info(), datetime, SimpleNamespace (+79 more)

### Community 3 - "CalDAV Sync Core & Tests"
Cohesion: 0.05
Nodes (82): _make_cleaning_window(), _make_schedule_found(), datetime, RED tests for caldav_sync (Phase 34) — locks the public API for Plan 02.  Covers, Edge 4: delete succeeds (stored_uid differs) but add_event raises → CalDAVWriteE, CALDAV-04: derive_uid is a pure function of (entry_id, window_start).      Calli, CalDAVWriteError DAVError path: caldav_error.DAVError from add_event → CalDAVWri, Edge 5: naive start_datetime (no tzinfo) → no raise, no TZID= in output (floatin (+74 more)

### Community 4 - "Diagnostic Sensor Entities"
Cohesion: 0.04
Nodes (55): ASPConfidenceScoreSensor, ASPLastErrorSensor, ASPLastResolvedSensor, ASPResolvedStreetSensor, ASPSODALevelSensor, Diagnostic sensor showing the resolved street name., Return the resolved street name, or None if not resolved., Return cross streets, side, confidence, and Phase 30 diagnostic fields. (+47 more)

### Community 5 - "Sign Retrieval & Level-4 Graph Tests"
Cohesion: 0.04
Nodes (63): LogRecord, _CapturingHandler, _make_graph(), Path, Tests for sign retrieval: unit tests for StreetGraph / Level 4, plus integration, BUG-S-001: L4 reuses L3's broad-query records — no duplicate HTTP call.      L3, BUG-S-006: SODA client's final retry attempt must not log 'retry in Xs'.      Th, Return a StreetGraph loaded from _SYNTHETIC_GRAPH (no file I/O). (+55 more)

### Community 6 - "GPS Coordinate Conversion & Exceptions"
Cohesion: 0.06
Nodes (48): GPS2ASP: GPS-to-street resolver for NYC Alternate Side Parking., convert(), WGS84 to NY State Plane (EPSG:2263) coordinate transformation.  Converts GPS coo, Convert WGS84 GPS coordinates to NY State Plane (EPSG:2263).      Args:, AmbiguousResolutionError, IndexNotFoundError, NoSegmentFoundError, OutsideNYCError (+40 more)

### Community 7 - "Index Download & Atomic Swap"
Cohesion: 0.06
Nodes (60): Promote ``<index_dir>_tmp`` to ``<index_dir>`` atomically.      Algorithm:, Remove stale rebuild artifacts; restore backup if live index is missing.      Ha, Extract ``zip_path`` into ``dest_dir`` with zip-slip protection.      For every, _sync_atomic_swap(), _sync_cleanup_stale(), _sync_extract_zip(), Path, RED tests for custom_components/asp_parking/index_io.py (Phase 33 Plan 02).  Cov (+52 more)

### Community 8 - "Holiday Calendar & ICS Fetch"
Cohesion: 0.05
Nodes (57): HTTPStatusError, _fetch_ics(), _get_fallback(), HolidayCalendar, Return hardcoded fallback dates for the given year.      Returns an empty dict f, Fetch ICS file from NYC.gov with retry. Returns None on failure., Holiday-based ASP suspension calendar.      Usage::          cal = HolidayCalend, Fetch and parse the ICS calendar for the given year.          Falls back to hard (+49 more)

### Community 9 - "Sign Text Parsing & Schedule Windows"
Cohesion: 0.05
Nodes (32): UC-23: AllUnparseable, BUG-T-004: cross-midnight windows rejected by end>start guard, parse_sign(), TimeWindow, Parse a raw sign description into a list of TimeWindow objects.      Returns Non, Tests for parse_sign() -- the main entry point., Most common pattern (7,260 records)., Second most common pattern (7,172 records). (+24 more)

### Community 10 - "Street Name Normalization (CSCL to SODA)"
Cohesion: 0.06
Nodes (19): UC-11: Manhattan grid street (Midtown numbered street), normalize_to_soda(), Convert CSCL street name format to SODA parking signs format.      Expansion ord, W BROADWAY should become WEST BROADWAY., E BROADWAY should become EAST BROADWAY., W END AVE should become WEST END AVENUE., CENTRAL PARK S should become CENTRAL PARK SOUTH., Tests for CSCL -> SODA street name conversion. (+11 more)

### Community 11 - "Active-Now Schedule Tests"
Cohesion: 0.05
Nodes (40): UC-20: ASPActiveNow, BUG-T-005: ASPActiveNow lacks weekly_schedule — cleaning_days attribute absent, ASPActiveNow, Car is currently parked during an active ASP cleaning window.      Attributes:, ASPDay, LogCaptureFixture, TimeWindow, WeeklySchedule (+32 more)

### Community 12 - "Debug Mode Switch Entity"
Cohesion: 0.06
Nodes (44): ASPDebugModeSwitch, async_setup_entry(), AddEntitiesCallback, Any, ConfigEntry, DeviceInfo, HomeAssistant, Switch platform for the ASP Parking integration.  Provides ASPDebugModeSwitch -- (+36 more)

### Community 13 - "Coordinator Pipeline Orchestration"
Cohesion: 0.07
Nodes (43): _legal_sides_for(), Event-driven coordinator for the ASP Parking integration.  Orchestrates the full, Run the full GPS-to-schedule pipeline.          Reads pending coordinates, calls, Pre-seed SODA sign cache for segments within the configured parking area., Return the two legal compass sides for a segment based on nominaldir.      For N, GPS2ASP pipeline: full GPS-to-ASP-schedule resolver.  This module contains the i, Async SODA API client for NYC parking sign retrieval.  Handles pagination, retry, _find_best_covering_span() (+35 more)

### Community 14 - "Coordinator Rebuild Path Selection Tests"
Cohesion: 0.08
Nodes (50): _bind(), _install_path_spies(), _make_coord_stub(), datetime, LogCaptureFixture, mock, MonkeyPatch, SimpleNamespace (+42 more)

### Community 15 - "Coordinator Stale-Data Tests"
Cohesion: 0.09
Nodes (50): _bind(), _make_coord_stub_stale(), pn_module(), datetime, fixture, LogCaptureFixture, MonkeyPatch, SimpleNamespace (+42 more)

### Community 16 - "CalDAV Event Building"
Cohesion: 0.06
Nodes (46): build_vevent_ical(), CalDAVWriteError, derive_uid(), _fmt_coord(), _get_calendar(), datetime, dict, Exception (+38 more)

### Community 17 - "Coordinator Rebuild Executor Tests"
Cohesion: 0.09
Nodes (44): BaseException, _bind(), _install_executor_spies(), _make_coord_stub(), datetime, dict, MonkeyPatch, SimpleNamespace (+36 more)

### Community 18 - "NYC311 Emergency Suspension Polling"
Cohesion: 0.08
Nodes (45): NYC_311_API_KEY environment variable, UC-27: Emergency suspension via NYC 311 API, Result of a suspension check for a specific date., SuspensionInfo, NYC311Client, NYC 311 API client for weather/emergency ASP suspension status.  Polls the NYC 3, Async client for NYC 311 GetCalendar API.      Fetches today's ASP suspension st, _make_response() (+37 more)

### Community 19 - "Temporal Edge-Case Use Cases"
Cohesion: 0.07
Nodes (38): UC-24: ScheduleFound with next_window=None, UC-31: Query 1 minute before window start, UC-32: Query exactly at window start, UC-33: Query exactly at window end, UC-34: DST spring-forward, UC-35: Late Saturday evening multi-day scan, UC-36: All 8 lookahead days suspended, UC-37: Year-boundary rollover (Dec 31 → Jan 2) (+30 more)

### Community 20 - "Next-Move Sensor Test Builders"
Cohesion: 0.08
Nodes (27): freeze_time, _build_asp_active_now_for_window(), _build_schedule_found_for_window(), _make_stub_sensor(), datetime, Instantiate ASPNextMoveTimeSensor against a minimal stub coordinator.      Only, Build a ScheduleFound with a CleaningWindow whose start_datetime is start_dt., Build an ASPActiveNow with the given window bounds. (+19 more)

### Community 21 - "Sign Retrieval Data Models"
Cohesion: 0.07
Nodes (44): skip_no_network, _cross_streets_match(), _deduplicate(), materialize_cached_records(), _normalize_street(), SignRecord, SignRetrievalResult, SignRetrievalSuccess (+36 more)

### Community 22 - "Curb-Based Side Calibration"
Cohesion: 0.06
Nodes (28): Build-time curb-derivation core for per-segment side-of-street calibration (SC-1, compute_distance_to_endpoints(), compute_perpendicular_distance(), LineString, Side-of-street determination using cross-product geometry.  Determines which com, Compute the perpendicular distance from a point to a segment centerline.      Us, Compute the minimum distance from a point to either endpoint of a segment., Perpendicular signed distance (feet) from a point to a directed segment.      Us (+20 more)

### Community 23 - "Resolver Exceptions & Index Errors"
Cohesion: 0.08
Nodes (31): UC-44: Index not built — IndexNotFoundError, WGS84 to NY State Plane (EPSG:2263) coordinate transformation.  Converts GPS coo, IndexNotFoundError, NoSegmentFoundError, OutsideNYCError, Exception, Custom exceptions for GPS-to-street resolution., Base exception for all resolution errors. (+23 more)

### Community 24 - "GPS Resolution Core & Borough Tests"
Cohesion: 0.06
Nodes (24): ResolutionResult, Resolve GPS coordinates to a street segment and side of street.      This is the, resolve(), A very high threshold should make most resolutions ambiguous., A point deep inside Prospect Park should fail.          The point is far from an, Eastern Parkway has main road and service roads.          A point on the south s, Test resolution in Manhattan (different grid orientation)., Test resolution in Queens (rotated grid). (+16 more)

### Community 25 - "Spatial Index Build Script"
Cohesion: 0.09
Nodes (40): _bfs_between(), build_index(), _build_intersection_index(), _build_street_adjacency(), _check_has_asp(), _download_cscl_geojson(), _download_curbs(), _download_roadbed() (+32 more)

### Community 26 - "Coordinator Boundary-Timer Tests"
Cohesion: 0.10
Nodes (40): _bind(), _make_asp_active_now(), _make_cleaning_window(), _make_coord_stub(), _make_schedule_found(), ASPActiveNow, CleaningWindow, datetime (+32 more)

### Community 27 - "Ambiguity Classification Logic"
Cohesion: 0.08
Nodes (29): _classify_ambiguity(), Resolve State Plane coordinates to a street segment and side.      Same as resol, Classify the type of ambiguity for debug logging.      BUG-R-001: The 10ft check, resolve_segment(), A point near the road centerline should be ambiguous.          Uses convert() to, A point right at a segment endpoint should be ambiguous.          Programmatical, _FakeIndex, _make_candidate() (+21 more)

### Community 28 - "Index I/O Build Helpers"
Cohesion: 0.08
Nodes (38): _bfs_between(), _build_headers(), _build_intersection_index(), _build_node_lookup(), _build_rtree_and_metadata(), _build_street_adjacency(), _check_has_asp(), _compute_cross_streets() (+30 more)

### Community 29 - "CalDAV Compatibility Shim"
Cohesion: 0.06
Nodes (29): _CompatCalendar, _CompatEvent, _CompatPrincipal, _delete_uid_quiet(), list_calendars(), Any, Return a calendar object for cal_url.          ``caldav.Principal.calendar(cal_u, Delete a CalDAV event by UID without a REPORT-based lookup.      Constructs the (+21 more)

### Community 30 - "Index Rebuild Button Entity"
Cohesion: 0.08
Nodes (31): ButtonEntity, ASPIndexRebuildButton, async_setup_entry(), AddEntitiesCallback, ConfigEntry, DeviceInfo, HomeAssistant, Set up the ASP Parking button platform from a config entry. (+23 more)

### Community 31 - "GPS Pipeline Health Sensor"
Cohesion: 0.09
Nodes (32): ASPGpsPipelineHealthBinarySensor, Diagnostic binary sensor: ON when GPS is recent and no pipeline error has occurr, Initialize the binary sensor.          Args:             coordinator: The ASP Pa, Register update callback when entity is added to HA., Return True when GPS is recent and the last pipeline run succeeded., Return diagnostic attributes including last pipeline error flag., _make_coordinator(), datetime (+24 more)

### Community 32 - "understand-anything Tour Analysis Tool"
Cohesion: 0.06
Nodes (31): adjAll, bfsTraversal, bidirTypes, bottom25PctFanInThreshold, clusters, dedupMap, edgeKey(), edgeSet (+23 more)

### Community 33 - "Side-of-Street Confidence Scoring"
Cohesion: 0.07
Nodes (23): Side-of-Street Confidence Scoring, UC-07: Ambiguous — near centerline, UC-08: Ambiguous — near intersection, UC-09: Ambiguous — low composite confidence, BUG-R-001: _classify_ambiguity label wrong for near-centerline on narrow streets, _classify_ambiguity() — debug outcome labeler, compute_confidence(), Compute confidence score for side-of-street determination.      The confidence i (+15 more)

### Community 34 - "Schedule Computation Entry Point"
Cohesion: 0.09
Nodes (23): compute_schedule(), date, ScheduleResult, SignRetrievalResult, Compute ASP schedule from sign retrieval results.      Main entry point for the, _make_sign_result(), SignRetrievalSuccess, Integration tests for compute_schedule(). (+15 more)

### Community 35 - "CalDAV Entry Lifecycle Hooks"
Cohesion: 0.11
Nodes (34): delete_event(), Delete the event identified by ``uid`` from ``calendar_url``.      Silent on Not, _async_caldav_cleanup_on_deconfigure(), _async_caldav_strip_location(), async_migrate_entry(), _async_options_updated(), async_remove_entry(), async_setup_entry() (+26 more)

### Community 36 - "Coordinator Config Properties"
Cohesion: 0.08
Nodes (20): ASPParkingCoordinator, Event-driven coordinator for ASP Parking.      Subscribes to device_tracker stat, Return the device_tracker entity ID from config., Return the movement threshold in meters., Initialize the sensor.          Args:             coordinator: The ASP Parking c, UC-38: GPS <50m movement — no trigger, UC-39: GPS >50m movement — pipeline runs, UC-40: First GPS update — last_lat is None (+12 more)

### Community 37 - "Confidence Scoring Module"
Cohesion: 0.08
Nodes (32): compute_confidence(), compute_lane_snap_confidence(), is_confident(), lane_half_from_width(), Confidence scoring for side-of-street determination.  Computes a confidence scor, Compute confidence score for side-of-street determination.      The confidence i, Lane-snap (spike 004a) side confidence with an UPPER plausibility bound.      Tw, Check if a confidence score exceeds the threshold.      Args:         confidence (+24 more)

### Community 38 - "Button/Const/Cache Test Grouping"
Cohesion: 0.08
Nodes (31): Button platform for the ASP Parking integration (Phase 33, IDX-01).  Provides AS, Constants for the ASP Parking integration., # NOTE: CONF_DEBUG_ENABLED and DEFAULT_DEBUG_ENABLED have been removed (Phase 29, make_coordinator(), _make_segment_candidate(), fixture, Unit tests for the Phase 26 sign cache and pre-seed lifecycle.  Covers AREA-02:, Pre-seed calls convert(lat, lon) and idx.query_radius(cx, cy, r_ft). (+23 more)

### Community 39 - "Coordinator State Container & Borough Tests"
Cohesion: 0.10
Nodes (33): ASPParkingData, Container for all coordinator state read by entities.      Mutable (not frozen), make_coordinator(), _make_resolution(), _make_schedule(), _make_sign_result(), fixture, ResolutionResult (+25 more)

### Community 40 - "Schedule Result Variant Models"
Cohesion: 0.07
Nodes (25): AllUnparseable, NoASPSchedule, NoMatchSchedule, ParseFailure, Data models for ASP schedule parsing and next-move computation.  All models are, Record of a sign description that failed to parse.      Attributes:         raw:, Phase 2 returned NoASPSigns -- no ASP on this block.      Attributes:         st, Phase 2 returned NoMatchFound -- street not in SODA.      Attributes:         st (+17 more)

### Community 41 - "Index Build-From-Source Tests"
Cohesion: 0.17
Nodes (32): Build the spatial index from the live CSCL + SODA APIs.      Writes 5 files to `, _sync_build_from_source(), _empty_cscl_page(), _load_cscl_fixture(), _load_soda_fixture(), mock, Path, Route (+24 more)

### Community 42 - "Suspension Merge Tests"
Cohesion: 0.10
Nodes (31): apply_suspension(), ScheduleResult, SuspensionInfo, Apply suspension annotation to a schedule result.      If info.is_suspended is F, asp_active_now(), ASPActiveNow, fixture, LogCaptureFixture (+23 more)

### Community 43 - "Vendor Sync Script Tests"
Cohesion: 0.12
Nodes (21): CaptureFixture, MonkeyPatch, Write a source file rooted under src_root and return its path., Write a vendor file rooted under vendor_root and return its path., Integration tests for main() exit-code + stdout contract., When vendor matches normalized source, --dry-run exits 0 with the         in-syn, Mutating one vendor file → exit 1; stdout names the drifted relative         pat, A source file with no vendor counterpart counts as drift. (+13 more)

### Community 44 - "Resolver Unit Tests"
Cohesion: 0.08
Nodes (21): Result of resolving a GPS coordinate to a street segment and side.      Attribut, ResolutionResult, SpatialIndex, _FakeRTree, _make_loader_index(), Minimal rtree stand-in: returns the same ids for nearest()/intersection()., Build a SpatialIndex wired to an in-memory fake rtree + segment dict., Phase 40 Plan 04: both loader paths surface calibration fields.      Absent cali (+13 more)

### Community 45 - "Index Integrity Init Tests"
Cohesion: 0.08
Nodes (29): _index_has_graph_file(), IndexIntegrityError, Exception, Return True if either graph.json.zst or graph.json exists in index_dir.      The, Raised by ``_sync_verify_index`` when on-disk index files are corrupt.      File, _async_download_index(), _async_ensure_index(), ASP Parking - Alternate Side Parking integration for Home Assistant.  Creates th (+21 more)

### Community 46 - "Diagnostic Sensor Base Classes"
Cohesion: 0.07
Nodes (24): ASPCarNameSensor, _ASPDiagnosticSensor, ASPLatitudeSensor, ASPLongitudeSensor, ASPVINSensor, async_setup_entry(), AddEntitiesCallback, ConfigEntry (+16 more)

### Community 47 - "resolve_asp() Pipeline Tests"
Cohesion: 0.11
Nodes (28): _make_resolution_result(), _make_schedule_found(), _make_sign_success(), ResolutionResult, ScheduleFound, SignRetrievalSuccess, Failing tests for resolve_asp() — TDD RED phase (Plan 07-01).  These tests speci, resolve_asp(lat, lon) with no debug flag returns ASPResult, not ASPDebugResult. (+20 more)

### Community 48 - "HA Diagnostics Export Tests"
Cohesion: 0.11
Nodes (28): async_get_config_entry_diagnostics(), Any, ConfigEntry, HomeAssistant, Diagnostics support for ASP Parking.  Exposes async_get_config_entry_diagnostics, Strip embedded HTTP Basic credentials from a URL's userinfo section.      CR-02:, Return diagnostics for the ASP Parking config entry.      Structure (D-01): four, _strip_userinfo() (+20 more)

### Community 49 - "Pipeline Demo & API Models"
Cohesion: 0.09
Nodes (24): UC-01: Valid coordinate resolution (Prospect Heights), BUG-R-007: pipeline.py catches AmbiguousResolutionError but not OutsideNYCError, main(), Live demo: GPS -> ASP schedule pipeline.  Runs the full three-stage pipeline (GP, resolve_asp (src/gps2asp/__init__.py), ASPDebugResult, ASPResult, ResolutionResult (+16 more)

### Community 50 - "Index-Rebuilding Binary Sensor Tests"
Cohesion: 0.11
Nodes (25): ASPIndexRebuildingBinarySensor, Diagnostic binary sensor mirroring the spatial-index rebuild state.      ON whil, Initialize the binary sensor.          Args:             coordinator: The ASP Pa, Register update callback when entity is added to HA., Return True while a spatial-index rebuild is in progress., BUG-H-004: binary_sensor.py hardcodes sw_version instead of VERSION, _make_coordinator(), RED tests for ASPIndexRebuildingBinarySensor (Phase 33, IDX-02 entity contract). (+17 more)

### Community 51 - "CalDAV Config & Coordinator Integration"
Cohesion: 0.10
Nodes (27): CalDAVConfig, Immutable CalDAV connection + content configuration.      Constructed from ``ent, Validate fields at construction time (runs before the dataclass freeze)., Phase 38 (IDX-05): which executor strategy services a rebuild request.      DOWN, RebuildPath, Enum, Edge 10: safety_window_minutes=9999 → no exception (no upper-bound enforcement)., CalDAVConfig(apple_radius_m=-1) raises ValueError (sign/range validation). (+19 more)

### Community 52 - "Street Adjacency Graph (BFS)"
Cohesion: 0.10
Nodes (19): UC-18: L4 BFS mid-span graph traversal, _default_index_dir(), _find_best_covering_span(), Path, Street adjacency graph for Level 4 mid-span sign retrieval.  Loads the graph.jso, Return the singleton StreetGraph, lazy-loading on first call.          Returns:, Return all segment PIDs whose cross_streets include the given street., BFS from any start PID to any target PID, returning minimum hop count. (+11 more)

### Community 53 - "CalDAV Options-Flow Tests"
Cohesion: 0.13
Nodes (27): CalDAVAuthError, Raised when CalDAV credential validation or API call fails., _make_entry(), Options flow tests for Phase 34 CalDAV step (CALDAV-01, CALDAV-02, D-02).  Verif, D-02: empty URL submission = complete no-op; NO CalDAV keys in entry.options., CALDAV-01 / D-03: CalDAVAuthError → error 'caldav_auth_failed'.      T-34-02 mit, CALDAV-01 / D-03: ANY probe failure → same 'caldav_auth_failed' error key., CALDAV-01 → CALDAV-02: successful probe chains to caldav_calendar with a     pop (+19 more)

### Community 54 - "Curb Calibration Tests"
Cohesion: 0.10
Nodes (16): Result of deriving one segment's calibration from flanking curbs.      The field, SegmentCalibration, derive_segment_calibration(), LineString, Result of deriving one segment's calibration from flanking curbs.      The field, Derive a segment's centre offset ``c`` and true width from flanking curbs., SegmentCalibration, Tests for the build-time curb-derivation core (plan 40-05, SC-1).  Synthetic-geo (+8 more)

### Community 55 - "Schedule Models & Compute Entry"
Cohesion: 0.12
Nodes (24): compute_schedule(), date, datetime, ScheduleResult, SignRetrievalResult, Parse ASP sign descriptions into structured schedules and compute next move time, Compute ASP schedule from sign retrieval results.      Main entry point for the, merge_windows() (+16 more)

### Community 56 - "Schedule Summary & Window Merge"
Cohesion: 0.10
Nodes (24): datetime, Parse ASP sign descriptions into structured schedules and compute next move time, merge_windows(), TimeWindow, WeeklySchedule, Window merging for multi-sign ASP blocks.  Combines overlapping or adjacent time, Merge overlapping/adjacent time windows into a WeeklySchedule.      Groups windo, A single time range on a single day, as parsed from one sign.      Represents th (+16 more)

### Community 57 - "Coverage Audit Script Tests"
Cohesion: 0.12
Nodes (17): _make_error_result(), _make_ok_result(), CaptureFixture, Unit tests for audit_queens_coverage.py internal logic.  Tests exercise print_re, Empty results list does not crash (zero-division guard)., Fixture name appears in the report header., Results with missing description still render (loc.get fallback)., An unexpected soda_level (e.g., 5) appears in output rather than silently droppe (+9 more)

### Community 58 - "Parking-History Calibration Fallback"
Cohesion: 0.10
Nodes (18): CalibrationEstimate, estimate_center_offset(), Parking-history cluster-mean calibration estimator (SC-4 fallback tier 2).  When, A learned per-segment side calibration derived from parking history.      Attrib, Estimate a segment's centre offset from settled-park signed offsets.      Uses t, CalibrationEstimate, estimate_center_offset(), Parking-history cluster-mean calibration estimator (SC-4 fallback tier 2).  When (+10 more)

### Community 59 - "Lane-Snap Confidence Tests"
Cohesion: 0.10
Nodes (17): compute_lane_snap_confidence(), lane_half_from_width(), Confidence scoring for side-of-street determination.  Computes a confidence scor, Lane-snap (spike 004a) side confidence with an UPPER plausibility bound.      Tw, Derive the lane half-width `p` (feet) from the true curb-to-curb width.      Two, Tests for confidence scoring., Test the lane-half-width derivation helper (spike 004a: p ~= 9.7 ft)., Unknown curb width -> DEFAULT_LANE_HALF_P (9.7 ft). (+9 more)

### Community 60 - "Index-Last-Rebuilt Sensor Tests"
Cohesion: 0.15
Nodes (24): ASPIndexLastRebuiltSensor, Diagnostic sensor exposing the spatial-index build timestamp (Phase 33, IDX-03)., _make_coordinator(), datetime, RED tests for ASPIndexLastRebuiltSensor (Phase 33, IDX-03).  These tests intenti, native_value is a LIVE property — mutations to coord._last_rebuilt     after con, device_info identifiers must match every other ASP Parking entity., Build a minimal coordinator stub matching the sensor's contract. (+16 more)

### Community 61 - "Coordinate Converter Tests"
Cohesion: 0.11
Nodes (15): UC-03: Outside NYC (Los Angeles), convert(), Convert WGS84 GPS coordinates to NY State Plane (EPSG:2263).      Args:, Test the convert() function for WGS84 -> State Plane transformation., Prospect Heights (40.6778, -73.9690) should convert to approximately         (99, Swapping lat/lon should produce very different results,         verifying correc, Coordinates (0.0, 0.0) in the Gulf of Guinea should raise OutsideNYCError., Los Angeles coordinates should raise OutsideNYCError. (+7 more)

### Community 62 - "Time-Token Parsing Tests"
Cohesion: 0.14
Nodes (7): parse_time_token(), time, Parse a time token into a datetime.time object.      Handles standard AM/PM time, Tests for parse_time_token()., 12PM is noon (12:00), not midnight., 12AM is midnight (00:00), not noon., TestParseTimeToken

### Community 63 - "Side Determination Tests"
Cohesion: 0.11
Nodes (16): UC-05: Confident resolution, N side of E-W street, UC-06: Confident resolution, S side of E-W street, BUG-R-003: determine_side() runs before confidence check — wasted work, BUG-R-004: determine_side() returns arbitrary direction when cross product = 0, determine_side(), Determine the compass side (N/S/E/W) of a point relative to a street segment., Test cross-product based side-of-street determination., Point above an East-West segment should return 'N'. (+8 more)

### Community 64 - "Coordinator Debug-Log Tests"
Cohesion: 0.11
Nodes (23): _coord_source(), _join_string_continuations(), Unit tests for coordinator changes in Phase 29-01 (D-02, D-03, D-10, D-11, D-13), After D-02, CONF_DEBUG_ENABLED and DEFAULT_DEBUG_ENABLED are unused in coordinat, Concatenate adjacent string literals split across lines.      Python source like, D-10, D-13: OutsideNYCError in main resolve loop emits WARNING with actionable t, D-11, D-13: NoSegmentFoundError/AmbiguousResolutionError emit WARNING with actio, Phase 35.1: invalid CONF_DEBUG_DATETIME string must log a WARNING and set _debug (+15 more)

### Community 65 - "Spatial Index Query Tests"
Cohesion: 0.11
Nodes (17): GPS2ASP_INDEX_DIR environment variable, UC-02: SW corner boundary coordinate, UC-04: Deep park interior (Prospect Park), BUG-R-005: nearest() n=5 may miss the true closest segment, BUG-R-006: rw_type=0 silently falls back to 30ft without logging segment id, BUG-R-008: SpatialIndex.get() ignores index_dir on subsequent calls, BUG-S-004: StreetGraph.load() propagates unhandled exception on malformed file, SegmentCandidate (+9 more)

### Community 66 - "SODA API Client"
Cohesion: 0.12
Nodes (15): AsyncClient, Fetch a single page of results with retry logic.          Args:             clie, Build a $where clause for exact four-field block-face match.          Always inc, Async client for querying NYC Open Data SODA API parking signs.      Supports op, Build a $where clause for broad on_street + side match.          Used for Level, Fetch all matching sign records with pagination and retry.          Paginates th, SODAClient, IncompleteResultsError (+7 more)

### Community 67 - "understand-anything Graph Validator Tool"
Cohesion: 0.09
Nodes (17): connectedNodeIds, edgeTypes, FILE_LEVEL_TYPES, fs, isDomainGraph, issues, nodeIdIndices, nodeTypes (+9 more)

### Community 68 - "Active-Now Binary Sensor"
Cohesion: 0.10
Nodes (17): BinarySensorEntity, ASPActiveNowBinarySensor, async_setup_entry(), AddEntitiesCallback, ConfigEntry, HomeAssistant, Binary sensor platform for the ASP Parking integration.  Provides ASPActiveNowBi, Set up the ASP Parking binary sensor from a config entry. (+9 more)

### Community 69 - "Vendored Mirror Sync Concept"
Cohesion: 0.13
Nodes (17): pytest + lint Workflow, vendor-guard Workflow, custom_components/asp_parking/gps2asp Vendored Mirror Package, custom_components/asp_parking HA Integration Package, iter_source_files(), main(), normalize_source(), Path (+9 more)

### Community 70 - "HA Manifest Metadata"
Cohesion: 0.10
Nodes (20): codeowners, config_flow, documentation, domain, integration_type, iot_class, issue_tracker, name (+12 more)

### Community 71 - "ASPDebugResult Extended-Fields Tests"
Cohesion: 0.14
Nodes (20): _make_resolution_result(), _make_schedule_found(), _make_sign_success(), ResolutionResult, ScheduleFound, SignRetrievalSuccess, Failing tests for ASPDebugResult extended diagnostic fields — TDD RED phase (Pla, Test 1: ASPDebugResult exposes the four new fields as top-level attributes (D-07 (+12 more)

### Community 72 - "311 Startup Fetch & Bridge Tests"
Cohesion: 0.13
Nodes (12): Startup 311 API fetch. Fail open on any error., Result of a suspension check for a specific date., SuspensionInfo, Test all Phase 23 ha-nyc311 bridge code paths.      Tests use SimpleNamespace to, CR-01 regression: bridge entity in 'unavailable' state + api_key configured, Bridge entity in 'on' state -> 311 API is NOT called (bridge healthy)., _async_update_suspension with bridge 'on' -> returns early, 311 API not called., _async_update_suspension with bridge 'unavailable' -> falls through to 311 API. (+4 more)

### Community 73 - "Next-Move Computation Models"
Cohesion: 0.16
Nodes (18): ASPDay, CleaningWindow, IntEnum, Day of week for ASP schedules.      Values match datetime.weekday() convention:, A resolved upcoming cleaning window with concrete datetimes.      Used in result, Return all time windows for a specific day.          Args:             day: The, _ensure_aware(), find_active_window() (+10 more)

### Community 74 - "Resolver Extended-Fields Tests"
Cohesion: 0.11
Nodes (17): Return effective street width, falling back to rw_type table when CSCL data is m, resolve_effective_width(), _make_segment_candidate(), LineString, SegmentCandidate, TDD coverage for the four new diagnostic fields on ``ResolutionResult``.  Phase, resolve_segment() threads the four new diagnostic fields onto the result., Built without calibration args: calibrated False, c=0.0, spreads None. (+9 more)

### Community 75 - "Build-Index Graph Serialization Tests"
Cohesion: 0.10
Nodes (8): Unit tests for scripts/build_index.py bug fixes and graph construction.  Tests f, Tests for graph.json serialization (Task 2 integration)., graph.json should have adjacency, segment_streets, segment_cross_streets keys., _fetch_asp_signs() must use sign_design_voided_on_date IS NULL filter., TestFetchAspSignsFilter, TestFindCrossStreet, TestGraphJson, TestNormalizeStreetName

### Community 76 - "Vendor Sync Import-Rewrite Tests"
Cohesion: 0.15
Nodes (12): parametrize, Path, resolver/X.py: pkg_parts=['resolver'], prefix_len=1, dots='.', leading 'resolver, schedule/X.py: pkg_parts=['schedule'], prefix_len=1, dots='.', leading 'schedule, signs/X.py: pkg_parts=['signs'], prefix_len=1, dots='.', leading 'signs.' stripp, schedule/__init__.py → signs.models: pkg_parts=['schedule'], target=['signs','mo, Only the line that starts with `from gps2asp.` is rewritten; continuation, Indented `from gps2asp.X` lines (TYPE_CHECKING blocks or docstring text) (+4 more)

### Community 77 - "API Result Models"
Cohesion: 0.12
Nodes (16): ASPDebugResult, ASPResult, ResolutionResult, ScheduleResult, SignRetrievalResult, Top-level API result models for the resolve_asp() pipeline wrapper.  These froze, Build ASPDebugResult for the successful pipeline resolution path., Build ASPDebugResult when AmbiguousResolutionError is caught. (+8 more)

### Community 78 - "Day-Extraction Parsing Tests"
Cohesion: 0.17
Nodes (7): extract_days(), ASPDay, Extract days of week from sign description text.      Parsing order (per researc, MONDAY-FRIDAY should expand to all 5 weekdays., EXCEPT SUNDAY should return Mon through Sat (6 days)., Tests for extract_days()., TestExtractDays

### Community 79 - "Spatial-Index Radius Query Tests"
Cohesion: 0.11
Nodes (12): integration, Each returned candidate exposes the SegmentCandidate contract fields., BUG-R-008: SpatialIndex.get() must reject mismatched index_dir., Second get() with a different index_dir must raise ValueError.          Pre-fix:, Bounded-radius enumeration via SpatialIndex.query_radius()., query_radius returns at least one segment with distance_ft <= radius_ft., Tight radius is a strict subset of looser radius (compare by segment_id)., Zero radius returns [] (does NOT raise).          Contract: query_radius() calls (+4 more)

### Community 80 - "Index Rebuild Background Task Tests"
Cohesion: 0.12
Nodes (17): Background task body — performs the full rebuild lifecycle.          Strict orde, Download a zip from ``url`` into ``<index_dir>_tmp`` and extract it.      Stream, _sync_download_and_extract(), _build_zip_bytes(), HTTP error propagates; zip file is removed by the finally block., If _sync_extract_zip raises, the exception propagates and the zip is removed., BadZipFile raised by _sync_extract_zip propagates; _download.zip is removed., A ZIP containing only README.txt (no index files) extracts without error.      E (+9 more)

### Community 81 - "Push Notification Logic Tests"
Cohesion: 0.20
Nodes (10): Send push notification if next ASP window is within self._notify_lead_time minut, Test _async_maybe_send_notification business logic with mocked hass.services., Return a minimal namespace that satisfies _async_maybe_send_notification., Build a ScheduleFound using the vendored (coordinator-facing) models., Notification fires when 0 < seconds_until <= notify_lead_time * 60., Notification skipped when seconds_until <= 0 (window already started/past)., Notification skipped when window == last_notified_window (dedup)., last_notified_window is set only after confirmed delivery. (+2 more)

### Community 82 - "SODA Client Exceptions"
Cohesion: 0.16
Nodes (12): AsyncClient, Async SODA API client for NYC parking sign retrieval.  Handles pagination, retry, Fetch a single page of results with retry logic.          Args:             clie, Fetch all matching sign records with pagination and retry.          Paginates th, IncompleteResultsError, Exception, Custom exceptions for ASP sign retrieval., SODA API HTTP error after retries exhausted.      Raised when the SODA API retur (+4 more)

### Community 83 - "Graph Filter Load Tests"
Cohesion: 0.14
Nodes (11): TempPathFactory, LogCaptureFixture, Test StreetGraph.load() with .zst and .json files., Reset StreetGraph singleton before each test to prevent cross-test contamination, Reset StreetGraph singleton after each test to prevent cross-test contamination., StreetGraph.load() reads a .zst file created with zstandard., StreetGraph.load() falls back to .json when no .zst exists., StreetGraph.load() returns None when no graph file exists. (+3 more)

### Community 84 - "Index-Rebuild Workflow Rationale"
Cohesion: 0.14
Nodes (16): Rebuild Spatial Index Workflow, Rationale: index rebuild decoupled from code-release cadence (locked decision #4), Rationale: no push trigger for citywide index rebuild - too heavy per-commit (locked decision #7), Release Workflow (v* tags), NoReturn, NYC CSCL Centerlines Dataset, NYC Open Data App Token (secret), NYC Planimetric Curb Dataset (5xvt-8cbk) (+8 more)

### Community 85 - "CalDAV Compat-Shim Context-Manager Tests"
Cohesion: 0.12
Nodes (14): _CompatAsyncDAVClient, BUG-C-005: compat shim skips server-side principal discovery, _CompatAsyncDAVClient.__aenter__ dispatches DAVClient() via run_in_executor., _CompatAsyncDAVClient.__aexit__ calls close() via executor and sets _client to N, _CompatAsyncDAVClient.__aexit__ is safe when _client is None (aenter failed)., __aexit__ suppresses close() errors so the original block exception is not repla, BUG-C-005 (Phase 35.1 Plan 06): _CompatAsyncDAVClient.get_principal     must inv, _CompatAsyncDAVClient.__aenter__ raises RuntimeError when caldav.DAVClient is ab (+6 more)

### Community 86 - "Options Flow CalDAV Steps"
Cohesion: 0.21
Nodes (11): ConfigFlowResult, ASPParkingOptionsFlow, Return the settings schema with NumberSelector widgets.      Shared between the, Options flow for reconfiguring ASP Parking thresholds.      Allows changing move, Initialize the options flow., Present options form with current values as defaults., Optional home parking area for SODA cache pre-seeding (AREA-01).          Three, CalDAV credentials step (Phase 34 — CALDAV-01).          Submitting an empty URL (+3 more)

### Community 87 - "Coordinator Suspension State Application"
Cohesion: 0.15
Nodes (9): Any, SuspensionInfo, Convert ha-nyc311 entity state to SuspensionInfo (D-06).          Maps:, Choke-point for all suspension_state mutations (D-08 / Pitfall 8 / T-34-06)., Fetch suspension status from all sources and update data.          When ha-nyc31, Start listening for GPS updates and schedule periodic refreshes.          Subscr, _bridge_state_to_info('on', ...) -> is_suspended=True, source='ha_nyc311'., _bridge_state_to_info('off', {}) -> is_suspended=False, source='ha_nyc311'. (+1 more)

### Community 88 - "Street Graph Singleton & BFS"
Cohesion: 0.19
Nodes (10): _default_index_dir(), Path, Return the singleton StreetGraph, lazy-loading on first call.          Returns:, Return all segment PIDs whose cross_streets include the given street., BFS from any start PID to any target PID, returning minimum hop count., Compute graph-distance between a block and a SODA span.          The distance me, Return the default index directory (same as segments.json)., Street adjacency graph loaded from graph.json.      Attributes:         adjacenc (+2 more)

### Community 89 - "Confidence Threshold Tests"
Cohesion: 0.16
Nodes (10): is_confident(), Check if a confidence score exceeds the threshold.      Args:         confidence, Test the is_confident helper., Confidence above default threshold (0.33) should return True., Confidence below default threshold (0.33) should return False., Confidence exactly at threshold should return True (>=)., Custom threshold should be respected., Zero confidence should return False. (+2 more)

### Community 90 - "Normalize Query-Builder Tests"
Cohesion: 0.16
Nodes (8): Build a $where clause for exact four-field block-face match.          Always inc, Build a $where clause for broad on_street + side match.          Used for Level, escape_soql(), Street name normalization between CSCL and SODA formats.  CSCL (Citywide Street, Escape a string value for use in SoQL $where clauses.      Single quotes are the, Unit tests for street name normalization (CSCL to SODA format).  No network requ, Tests for SoQL string escaping., TestEscapeSoql

### Community 91 - "Synthetic Curb Calibration Tests"
Cohesion: 0.21
Nodes (7): Offline synthetic-curb tests for per-segment calibration (SC-1/SC-5).      A tin, North curb at +16 ft, South curb at -14 ft -> c=+1.0, width=30.0., Pavement polygon spanning y in [-14, +16] -> roadbed c ~= +1.0 (agrees)., Clean synthetic curbs -> segment record carries all five keys, calibrated., build_info.json records calibrated_count and non_calibrated_count., --no-curb-calibration -> five keys as non-calibrated defaults., TestCurbCalibration

### Community 92 - "Coordinator Heartbeat Tests"
Cohesion: 0.23
Nodes (15): _bind(), _make_stub(), asyncio, SimpleNamespace, RED tests for periodic 8h heartbeat (quick task 260520-f3o).  Covers the new coo, Null _holiday_calendar: load is skipped but suspension check still runs., Existing _pending_lat/lon are NOT overwritten when already set., Bind ASPParkingCoordinator.method_name to ``stub`` for invocation.      Attribut (+7 more)

### Community 93 - "Active-Window Finder Tests"
Cohesion: 0.17
Nodes (9): Tests for find_active_window()., Create a TUE 8:30-10AM schedule., Tuesday 9AM inside TUE 8:30-10AM -> returns active CleaningWindow., Tuesday 7AM, TUE 8:30-10AM -> returns None., Monday 9AM, TUE 8:30-10AM -> returns None., Exactly at start_time -> returns active (start is inclusive)., Exactly at end_time -> returns None (end is exclusive)., Active window datetimes are timezone-aware. (+1 more)

### Community 94 - "understand-anything Cross-Check Tool"
Cohesion: 0.12
Nodes (15): changedFileNodeCheck, changedFiles, dupFilePaths, extra, fileLevelTypes, fs, graph, inventory (+7 more)

### Community 95 - "Architecture Doc: Pipeline & Release Decoupling"
Cohesion: 0.17
Nodes (14): NYC_OPEN_DATA_APP_TOKEN environment variable, Index Release Decoupled from Code Release Cadence, Three-Stage GPS-to-ASP Pipeline, ARCHITECTURE.md — GPS2ASP-Resolver Architecture Reference, CONFIGURATION.md — Configuration Reference, GETTING-STARTED.md — Getting Started Guide, BUG-S-006: last-retry backoff delay computed and logged but never slept, .github/workflows/index-rebuild.yml — monthly index rebuild (+6 more)

### Community 96 - "Suspension ICS Parsing Tests"
Cohesion: 0.13
Nodes (13): _parse_ics(), date, Parse ICS bytes into a date-to-holiday-name mapping.      Only uses DTSTART (not, All holiday dates as an immutable set for forward-lookahead skipping., Check if ASP is suspended on the given date., If DTSTART returns a datetime instead of date, parser extracts .date()., parse_ics returns dict mapping dates to holiday names from ICS bytes., is_suspended returns True with reason for a holiday date. (+5 more)

### Community 97 - "Index Calibration-Fallback Tests"
Cohesion: 0.25
Nodes (14): _empty_cscl_page(), _load_cscl_fixture(), _load_soda_fixture(), mock, Path, Route, Proof that a from-source rebuild is the safe non-calibrated (c=0) fallback.  Pha, First CSCL fetch returns the fixture; the next returns an empty page. (+6 more)

### Community 98 - "Resolver Candidate Fixture Tests"
Cohesion: 0.17
Nodes (12): _make_candidate(), _patch_index(), prospect_heights_fixtures(), fixture, LineString, SegmentCandidate, End-to-end integration tests for the GPS2ASP resolver.  These tests require a bu, Patch SpatialIndex.get to return a _FakeIndex with the given candidates. (+4 more)

### Community 99 - "Holiday Calendar Init & SSL"
Cohesion: 0.18
Nodes (12): _build_ssl_context(), _extract_reason(), _fetch_ics(), _parse_ics(), SSLContext, NYC holiday-based ASP suspension calendar.  Fetches the NYC DOT annual ICS calen, Parse ICS bytes into a date-to-holiday-name mapping.      Only uses DTSTART (not, Fetch ICS file from NYC.gov with retry. Returns None on failure. (+4 more)

### Community 100 - "Holiday Calendar Fallback Logic"
Cohesion: 0.15
Nodes (9): _get_fallback(), HolidayCalendar, date, Return hardcoded fallback dates for the given year.      Returns an empty dict f, Holiday-based ASP suspension calendar.      Usage::          cal = HolidayCalend, All holiday dates as an immutable set for forward-lookahead skipping., Check if ASP is suspended on the given date., HolidayCalendar.is_suspended() returns is_suspended=True for a known holiday. (+1 more)

### Community 101 - "NYC311 Poller Fetch Status"
Cohesion: 0.19
Nodes (9): NYC311AuthError, NYC311Client, Exception, SuspensionInfo, NYC 311 API client for weather/emergency ASP suspension status.  Polls the NYC 3, Extract ASP suspension status from 311 API response JSON., Raised when the NYC 311 API returns HTTP 401 or 403.      Attributes:         st, Async client for NYC 311 GetCalendar API.      Fetches today's ASP suspension st (+1 more)

### Community 102 - "Curb/Roadbed Spatial Index Build"
Cohesion: 0.23
Nodes (14): GeoDataFrame, _build_curb_strtree(), _build_roadbed_strtree(), _build_rtree_and_metadata(), _derive_segment_fields(), LineString, Derive one segment's calibration, spread-gated and roadbed-cross-checked.      1, Build the R-tree index and save segment metadata.      CRITICAL: Uses index.inse (+6 more)

### Community 103 - "Coordinator Periodic Tasks"
Cohesion: 0.17
Nodes (7): datetime, Periodic suspension status check.          WR-01: bind the task to the config en, Periodic callback to rebuild the SODA sign cache (D-02).          Spawns a new p, 8h heartbeat: re-fetch ICS holiday calendar, re-check suspension, refresh pipeli, Re-fetch ICS, re-check suspension, and fire the pipeline debouncer.          Seq, Return debug datetime override when active, otherwise real now.          Per D-0, Return current time in NYC timezone for calendar-date operations.          WR-07

### Community 104 - "Schedule Summary Formatting Helpers"
Cohesion: 0.21
Nodes (12): _format_days(), format_summary(), _format_time(), _format_time_range(), ASPDay, time, WeeklySchedule, Human-readable schedule summary generation.  Generates compact text like "TUE & (+4 more)

### Community 105 - "i18n ICU-Escape Regression Tests"
Cohesion: 0.19
Nodes (12): _load_strings(), parametrize, Path, Regression tests for Phase 35 — ICU-escape curly placeholders in i18n strings., The caldav_event_title_template description must list all three placeholder name, The caldav_invalid_template error must mention all three placeholder names., Phase 31 CI guard: strings.json and translations/en.json must be byte-identical., No unescaped {street}/{time}/{side} placeholders may appear in caldav strings. (+4 more)

### Community 106 - "Coordinator Callback Registration"
Cohesion: 0.21
Nodes (7): CALLBACK_TYPE, callback, Handle ha-nyc311 entity state changes (D-05).          Converts ha-nyc311 state, Register a callback for entity state updates.          Args:             cb: Cal, Deregister a previously registered entity update callback.          Called autom, Notify all registered entity callbacks of new data., Public alias for entity update notification.          Used by the switch platfor

### Community 107 - "Development Guide & Bug-Hunt Docs"
Cohesion: 0.18
Nodes (12): CalDAV Version Compatibility Shim, DEVELOPMENT.md — Development Guide, CalDAV Bug Hunt Report, Coordinator/Sensor/ConfigFlow Bug Hunt Report, BUG-R-002: has_asp ignores resolved side — false positives, Fix PR #3 CI Failures Implementation Plan, TESTING.md — GPS2ASP Testing Guide, .github/workflows/hacs.yml — HACS validation (+4 more)

### Community 108 - "Schedule Analysis: Lazy Merge & Vendor Drift"
Cohesion: 0.17
Nodes (11): Lazy Suspension Merge Pattern, Vendored Mirror Sync Pattern, compute_schedule() (vendored copy, drifted), UC-19: ScheduleFound with next_window, UC-21: NoASPSchedule, UC-22: NoMatchSchedule, BUG-T-001: ScheduleFound.next_window docstring says 7 days, lookahead is 8, compute_schedule() (src) — Stage 3 orchestration (+3 more)

### Community 109 - "CalDAVConfig.from_options Tests"
Cohesion: 0.17
Nodes (11): Build a CalDAVConfig from a HA config entry options dict.          ``const.py``, Edge 11: CalDAVConfig.from_options({}) → ValueError (BUG-C-003 fix).      Phase, from_options maps all option keys to the correct CalDAVConfig fields., from_options raises ValueError when CONF_CALDAV_URL is absent.      BUG-C-003 (P, from_options uses correct defaults for optional fields.      A calendar_url is s, include_location defaults to False when the option key is absent (decision #2)., test_caldav_config_from_options_default_values(), test_caldav_config_from_options_happy_path() (+3 more)

### Community 110 - "Coordinator GPS Watchdog"
Cohesion: 0.17
Nodes (6): Safety-window guard: delete CalDAV event when the car has moved early., Handle device_tracker state change events.          Checks if the new state has, Cancel and clear the stored boundary timer handle.          D-09: clears ``_boun, Cancel and clear the GPS stale watchdog handle (D-09 clear-first pattern)., Cancel prior GPS stale watchdog, dismiss stale notification, and arm a new timer, Stop all listeners and cancel the debouncer.

### Community 111 - "Index Integrity-Check Tests"
Cohesion: 0.21
Nodes (12): Integrity-check the on-disk index — re-open rtree + decompress 1 graph byte., _sync_verify_index(), _build_minimal_valid_index(), Build a minimal valid rtree + graph.json.zst inside ``index_dir``.      Uses the, A freshly built rtree + valid graph.json.zst passes integrity check., 4-byte garbage in segments.dat triggers IndexIntegrityError., Garbage bytes in graph.json.zst (rtree valid) raises IndexIntegrityError., If graph.json exists (uncompressed) and rtree is valid, integrity passes.      M (+4 more)

### Community 112 - "Street-Name Variant Generation Tests"
Cohesion: 0.23
Nodes (7): UC-10: Brooklyn residential — Prospect Heights, UC-12: Bronx street — Grand Concourse, UC-16: L2 match via name variant iteration, name_variants(), Generate name variants for fallback matching.      Returns the SODA format first, Tests for name variant generation., TestNameVariants

### Community 113 - "NYC Holiday Calendar Module"
Cohesion: 0.17
Nodes (11): _build_ssl_context(), _extract_reason(), SSLContext, NYC holiday-based ASP suspension calendar.  Fetches the NYC DOT annual ICS calen, # NOTE: nyc.gov's edge (Akamai bot protection) returns HTTP 403 for, Build an SSL context outside the event loop (avoids HA blocking-call warning)., Extract holiday name from ICS DESCRIPTION field.      Falls back to ``"Holiday"`, _extract_reason pulls holiday name from standard DESCRIPTION format. (+3 more)

### Community 114 - "BFS-Between Segment Tests"
Cohesion: 0.17
Nodes (7): Tests for _bfs_between()., BFS from {A} to {D} on a linear chain A-B-C-D should return {A,B,C,D}., BFS with max_depth=1 should not traverse beyond depth 1 from start., BFS that never reaches any end_pid should return empty set., If start and end are the same pid, BFS returns just that pid., BFS works with multiple start and end pids., TestBfsBetween

### Community 115 - "ASP Interior-Block Propagation Tests"
Cohesion: 0.23
Nodes (7): Tests for _propagate_asp_to_interior_blocks()., Build a minimal 4-segment linear street for testing.          Layout: seg 1 (72n, BFS spanning 3 blocks should add interior block tuples to asp_lookup., When BFS can't reach endpoint, no tuples should be added., Stats dict should contain expected keys., When asp_lookup has only one side, interior blocks get only that side., TestPropagateAspToInteriorBlocks

### Community 116 - "2-Hop Graph Filter Tests"
Cohesion: 0.17
Nodes (7): ASP PID not in adjacency is silently ignored., Test the 2-hop BFS filter function., 2-hop filter retains ASP seed + 1-hop + 2-hop neighbors., Chain A-B-C-D-E where only A has ASP: retains A,B,C; excludes D,E., Filtered adjacency lists contain no references to excluded PIDs., Multiple ASP seeds expand neighborhoods from each seed., TestFilter2HopNeighborhood

### Community 117 - "Sensor Availability Logic Tests"
Cohesion: 0.21
Nodes (8): Replicate ASPNextMoveTimeSensor.available logic., Test sensor availability based on GPS data freshness., GPS update older than 8 hours -> available returns False., GPS update 1 hour ago -> available returns True., No GPS update received yet -> available returns True (initial state)., GPS update exactly at boundary -> should still be available., sensor_available(), TestStaleTimeout

### Community 118 - "Parking-Area Options-Flow Tests"
Cohesion: 0.23
Nodes (11): _make_entry(), Options flow tests for AREA-01: parking_area step.  Verifies the new parking_are, Pre-existing parking keys round-trip through init→parking_area unchanged.      N, Create and add a MockConfigEntry for the asp_parking integration., init step must chain into a parking_area form on submit., Submitting parking_area with no fields must NOT write parking keys.      NOTE: P, Submitting lat/lon/radius must persist them with correct types.      NOTE: Phase, test_init_step_preserves_parking_keys_when_unchanged() (+3 more)

### Community 119 - "Index Release Packager Tests"
Cohesion: 0.26
Nodes (10): Path, Tests for scripts/package_index_release.py.  The packager is a pure-stdlib CLI t, Populate ``dir_path`` with a synthetic index dir for the packager., test_graph_json_fallback_when_zst_absent(), test_happy_path_writes_flat_five_entry_zip(), test_refuses_when_calibrated_count_missing(), test_refuses_when_calibrated_count_zero(), test_refuses_when_no_graph_file() (+2 more)

### Community 120 - "Cross-Midnight Parsing Regression Tests"
Cohesion: 0.17
Nodes (7): BUG-T-004 regression: parse_sign accepts cross-midnight windows., 11PM-MIDNIGHT must produce a single Monday 23:00-23:59:59 window., 10:30PM-MIDNIGHT must produce a Tuesday 22:30-23:59:59 window., Existing MIDNIGHT-3AM pattern remains a normal same-day window (regression guard, Degenerate non-midnight reversal like 9AM-8AM is still rejected., MIDNIGHT-MIDNIGHT is zero-length and is still rejected., TestCrossMidnightWindow

### Community 121 - "CalDAV Missing-Method Exception Shim"
Cohesion: 0.20
Nodes (9): _missing_validate_connection(), _MissingCalDAVAuthError, Exception, Config flow and options flow for the ASP Parking integration.  Three-step setup, Coerce types and validate settings values.      NumberSelector always returns fl, # NOTE: CONF_DEBUG_ENABLED is intentionally absent — the, Fallback CalDAVAuthError until Plan 02's module is merged., # NOTE: step="any" is used (not 0.000001) because HA 2026.2.3's (+1 more)

### Community 122 - "AmbiguousResolutionError Tests"
Cohesion: 0.20
Nodes (10): AmbiguousResolutionError, ResolutionDebugInfo, Resolution confidence is below the threshold.      Raised when the GPS point is, _make_debug_info(), ResolutionDebugInfo, Build a minimal ResolutionDebugInfo for use in tests., AmbiguousResolutionError is caught by resolve_asp() and not propagated.      The, AmbiguousResolutionError caught in debug=True mode returns ASPDebugResult. (+2 more)

### Community 123 - "Shared Pytest Fixtures"
Cohesion: 0.24
Nodes (10): _index_exists(), fixture, Shared pytest fixtures for GPS2ASP tests.  Provides session-scoped index loading, Check if the spatial index files exist on disk., Session-scoped fixture that checks if the spatial index exists.      Skips integ, Reset the SpatialIndex singleton before each test.      This ensures each test s, Reset the StreetGraph singleton before each test.      Mirrors reset_spatial_ind, reset_spatial_index() (+2 more)

### Community 124 - "Config-Flow Step-Title Tests"
Cohesion: 0.18
Nodes (10): parametrize, Regression tests for Phase 37 — Step N of 3: prefix on config-flow step titles (, All 3 config-flow step titles must equal their exact Step N of 3: ... strings., Each config-flow step title must start with the corresponding Step N of 3: prefi, Phase 31 CI guard: strings.json and translations/en.json must be byte-identical., No options-flow step title may start with 'Step' — options flow is out of scope., test_config_step_title_has_prefix(), test_config_step_titles_exact() (+2 more)

### Community 125 - "CalDAV Event-URL Builder Tests"
Cohesion: 0.20
Nodes (10): _build_event_url(), Construct the CalDAV event URL from a calendar URL and event UID.      Mirrors c, _build_event_url percent-encodes '@' as '%40' (standard RFC 3986 encoding)., _build_event_url adds exactly one trailing slash regardless of input., _build_event_url matches caldav's _quote_uid: literal '/' in UID becomes '%252F', _build_event_url raises ValueError when calendar_url is None., test_build_event_url_at_sign_encoding(), test_build_event_url_none_raises() (+2 more)

### Community 126 - "Config Flow Setup Steps"
Cohesion: 0.24
Nodes (6): ASPParkingConfigFlow, Two-step config flow for ASP Parking Monitor.      Step 1 (user): Select device_, Initialize the config flow., Step 1: Select the device_tracker entity., Step 2: Configure thresholds., Step 3: Optional NYC 311 API key for weather/emergency suspensions.

### Community 127 - "Sensor Value Formatting"
Cohesion: 0.20
Nodes (6): date, datetime, Return human-friendly move time string with date-aware tier.          Three tier, Return the sensor state based on coordinator data.          Maps coordinator dat, Return rich state attributes across 5 groups.          Groups: schedule, locatio, Return tz-aware build_timestamp datetime, or None when unset.

### Community 128 - "NYC311 Auth & Response Parsing"
Cohesion: 0.22
Nodes (6): NYC311AuthError, Exception, SuspensionInfo, Extract ASP suspension status from 311 API response JSON., Raised when the NYC 311 API returns HTTP 401 or 403.      Attributes:         st, Fetch today's ASP suspension status from the 311 API.          Returns:

### Community 129 - "Street Adjacency Build Tests"
Cohesion: 0.20
Nodes (6): Tests for _build_street_adjacency()., 3 segments A-B-C on BROADWAY sharing nodes should be adjacent A-B and B-C but no, Segments at the same node with different street names are NOT connected., Segments at (100,200) and (101,200) on same street should be connected., A single segment with no neighbors has no adjacent segments., TestBuildStreetAdjacency

### Community 130 - "Intersection Index Build Tests"
Cohesion: 0.20
Nodes (6): Tests for _build_intersection_index()., (on_street, cross_street) should map to the correct PIDs., Both from_street and to_street endpoints are indexed for each segment., Segments with empty cross streets should not create empty-key entries., Street names should be normalized via _normalize_street_name., TestBuildIntersectionIndex

### Community 131 - "HA Repair-Issue Tests"
Cohesion: 0.27
Nodes (9): _make_entry(), Verify ImportError handling creates a repair issue and auto-dismisses on success, A pre-existing repair issue is removed when setup succeeds (D-07)., Create and add a v2 MockConfigEntry for the asp_parking integration., ImportError during setup logs an ERROR mentioning gps2asp + reinstall via HACS., ImportError during setup creates the gps2asp_import_error repair issue., test_import_error_creates_repair(), test_import_error_logs_actionable() (+1 more)

### Community 132 - "Center-Offset Side Resolver Tests"
Cohesion: 0.20
Nodes (6): Omitting center_offset is identical to passing 0.0 (no-op default)., Every pre-existing quadrant case is unchanged under the default center_offset., determine_side splits N/S at the fitted centre `c` (center_offset), not at 0., center_offset=0.0 reproduces the CSCL-centerline behaviour exactly., A point 1 ft south of the CSCL line is NORTH of a centre 2.38 ft south., TestCenterOffsetSplit

### Community 133 - "Coordinator CalDAV Write Hooks"
Cohesion: 0.28
Nodes (5): ScheduleResult, Write or update the CalDAV VEVENT for the upcoming cleaning window.          Wra, Delete the active CalDAV event by stored UID.          Args:             uid_to_, Decide whether to spawn a CalDAV write or delete after a successful resolve., Register a one-shot timer that fires at the next window boundary.          D-02:

### Community 134 - "Sign Parser Core Functions"
Cohesion: 0.25
Nodes (9): extract_days(), parse_sign(), parse_time_token(), ASPDay, time, TimeWindow, Extract days of week from sign description text.      Parsing order (per researc, Parse a raw sign description into a list of TimeWindow objects.      Returns Non (+1 more)

### Community 135 - "Queens Coverage Audit Script"
Cohesion: 0.33
Nodes (8): audit_fixture(), diagnose_l3(), main(), print_report(), Path, Print per-location table and summary statistics., Query SODA for all spans on a street+side and return available spans.      Used, Run resolve_asp(debug=True) on each location in the fixture file.

### Community 136 - "SODA Fallback Strategy Doc"
Cohesion: 0.29
Nodes (8): Four-Level SODA Fallback Query Strategy, UC-13: Queens street — Steinway Street, Astoria, UC-14: Staten Island — zero SODA coverage exhaustion, UC-15: L1 exact match, BUG-S-001: L4 re-issues identical broad HTTP request already made by L3, BUG-S-002: any_soda_results wrongly yields NoASPSigns for never-matched blocks, BUG-T-006: apply_suspension unknown-source fallback misclassifies as holiday, retrieve_signs() — Stage 2 orchestration

### Community 137 - "Suspension Bug Report: Vendored HolidayCalendar"
Cohesion: 0.25
Nodes (8): HolidayCalendar (vendored copy, missing suspended_dates), UC-25: Normal weekday — no suspension, UC-26: Holiday suspension on Thanksgiving, BUG-H-002: HolidayCalendar.suspended_dates missing in embedded copy, BUG-T-007: is_suspended() before load() silently fail-opens, BUG-T-008: ICS fallback returns empty dict for years beyond 2026, BUG-T-009: _fetch_ics retries HTTP 401/403 instead of fast-failing, HolidayCalendar (src) — NYC DOT ICS parser

### Community 138 - "Zero-Length Segment Guard Tests"
Cohesion: 0.25
Nodes (5): Tests for side-of-street determination., BUG-R-004: zero-length segments must raise, not silently return 'S'., Degenerate zero-length LineString must raise ValueError, not return 'S'., Sanity: the happy path must continue to work after the zero-length guard., TestZeroLengthSegment

### Community 139 - "Fixture Geocoding Script"
Cohesion: 0.43
Nodes (6): Client, geocode_address(), geocode_addresses(), main(), Geocode a single address via GeoSearch v2 API.      Returns a fixture dict with, Geocode a list of addresses, returning fixture dicts.

### Community 140 - "Binary Sensor Device Info"
Cohesion: 0.29
Nodes (4): DeviceInfo, Return device info for grouping entities under the same device., Return device info for grouping entities under the same device., Return device info for grouping entities under the same device.

### Community 141 - "Resolution Debug Logging"
Cohesion: 0.29
Nodes (6): configure_logging(), log_resolution(), ResolutionDebugInfo, JSON debug logging for GPS-to-street resolution.  Logs every resolution attempt, Log a resolution attempt as structured JSON at DEBUG level.      Captures the fu, Configure the gps2asp.resolver logger level.      Convenience function for users

### Community 142 - "CSCL Update Checker"
Cohesion: 0.29
Nodes (6): check_for_updates(), Path, Monthly auto-check for CSCL data updates.  Queries the NYC Open Data CSCL datase, Configure build logging to stdout., Check if the CSCL dataset has been updated since last build.      Queries the CS, _setup_logging()

### Community 143 - "CalDAV CancelledError Propagation Tests"
Cohesion: 0.29
Nodes (7): asyncio, CancelledError from get_principal must not be swallowed as CalDAVAuthError., CancelledError at the outer level must not be swallowed as CalDAVAuthError., CancelledError from get_display_name must not fall into the URL-fallback path., test_list_calendars_cancelled_error_propagates(), test_list_calendars_get_display_name_cancelled_propagates(), test_validate_connection_cancelled_error_propagates()

### Community 144 - "understand-anything Layer Verifier Tool"
Cohesion: 0.29
Nodes (6): allInputIds, fs, input, layers, missing, seen

### Community 145 - "Coordinator Stale-Check & Rebuild Trigger"
Cohesion: 0.33
Nodes (3): Shared startup + daily-interval stale-check helper.          Pitfall 12: the cal, Public entry point: fire-and-forget spawn of the rebuild task.          IDX-02 c, Initialise the index-stale Store, hydrate state, wire startup + daily check.

### Community 146 - "Resolution-Status Sensor"
Cohesion: 0.33
Nodes (4): ASPResolutionStatusSensor, Diagnostic sensor showing the pipeline resolution status., Return the pipeline outcome string., Return metadata about the last pipeline run.

### Community 147 - "Build-Index Cross-Street Lookup"
Cohesion: 0.33
Nodes (6): _build_node_lookup(), _compute_cross_streets(), _find_cross_street(), Build a spatial lookup from node coordinates to segment info.      For each segm, Find the cross street name at a node.      Searches the node lookup for segments, Pre-compute from_street and to_street cross streets for each segment.      Args:

### Community 148 - "Random Fixture Generator Script"
Cohesion: 0.47
Nodes (5): generate_fixtures(), geocode(), main(), Geocode using NYC Planning GeoSearch API., Geocode addresses and return up to `count` unique-block fixtures.

### Community 149 - "SODA Fixed-Width Formatting Tests"
Cohesion: 0.20
Nodes (3): Internal whitespace is reformatted to SODA fixed-width.          CSCL uses varia, AVE W (Brooklyn) should become AVENUE W, not AVENUE WEST., WESTERN BLVD should NOT expand W prefix (not followed by digit).

### Community 150 - "Vendor Sync Staged-Tree Fixtures"
Cohesion: 0.40
Nodes (4): fixture, Unit + integration tests for scripts/sync_vendored.py., Set up isolated SRC_ROOT and VENDOR_ROOT inside tmp_path and patch the module., staged_trees()

### Community 151 - "Options-Flow Entry Point"
Cohesion: 0.50
Nodes (3): callback, ConfigEntry, Return the options flow handler.

### Community 153 - "Coordinator Initialization"
Cohesion: 0.50
Nodes (3): ConfigEntry, HomeAssistant, Initialize the coordinator.          Args:             hass: Home Assistant inst

### Community 156 - "Cross-Street-Match Bug Analysis"
Cohesion: 0.67
Nodes (3): UC-17: L3 broad query with client-side cross-street filter, BUG-S-003: _cross_streets_match() returns True for empty cross-street strings, _cross_streets_match() — Level 3 cross-street filter

## Knowledge Gaps
- **192 isolated node(s):** `fs`, `d`, `fs`, `graph`, `inventory` (+187 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **44 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ASPParkingCoordinator` connect `Coordinator Config Properties` to `Force-Resolve Service Hook`, `Refresh-Interval Property`, `Coordinator CalDAV Write Hooks`, `Stale-Timeout Property`, `Coordinator Periodic Tasks`, `311 Startup Fetch & Bridge Tests`, `Coordinator Callback Registration`, `Coordinator Pipeline Orchestration`, `Coordinator GPS Watchdog`, `Index Rebuild Background Task Tests`, `Coordinator Stale-Check & Rebuild Trigger`, `Push Notification Logic Tests`, `CalDAV Config & Coordinator Integration`, `Coordinator Suspension State Application`, `Rebuild-Path Decision Logic`, `Coordinator Initialization`?**
  _High betweenness centrality (0.006) - this node is a cross-community bridge._
- **Why does `ASPParkingData` connect `HA Integration Test Suite` to `Coordinator Config Properties`, `Diagnostic Sensor Entities`?**
  _High betweenness centrality (0.003) - this node is a cross-community bridge._
- **Why does `ASPNextMoveTimeSensor` connect `Schedule Result Models & Suspension Merge` to `Coordinator Config Properties`, `Diagnostic Sensor Base Classes`, `Sensor Value Formatting`?**
  _High betweenness centrality (0.001) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `ASPParkingData` (e.g. with `ASPParkingCoordinator` and `ASPConfidenceScoreSensor`) actually correct?**
  _`ASPParkingData` has 6 INFERRED edges - model-reasoned connections that need verification._
- **What connects `fs`, `d`, `fs` to the rest of the system?**
  _192 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `HA Integration Test Suite` be split into smaller, more focused modules?**
  _Cohesion score 0.036071273359408955 - nodes in this community are weakly interconnected._
- **Should `Schedule Result Models & Suspension Merge` be split into smaller, more focused modules?**
  _Cohesion score 0.0340883093113704 - nodes in this community are weakly interconnected._