#!/usr/bin/env python3
"""Audit ASP coverage by running GPS fixture locations through the live pipeline.

Usage:
    python scripts/audit_queens_coverage.py                          # Queens (default)
    python scripts/audit_queens_coverage.py --fixture manhattan      # Manhattan
    python scripts/audit_queens_coverage.py --fixture path/to/file.json  # Custom
    python scripts/audit_queens_coverage.py --verbose                # With L3 diagnostics

Requires network access (live SODA API calls).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from pathlib import Path

from gps2asp import resolve_asp
from gps2asp.signs.client import SODAClient
from gps2asp.signs.models import NoMatchFound
from gps2asp.signs.normalize import normalize_to_soda

# Default fixture paths
_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
_NAMED_FIXTURES = {
    "queens": _FIXTURE_DIR / "queens_coverage.json",
    "manhattan": _FIXTURE_DIR / "manhattan_coverage.json",
}


async def diagnose_l3(
    on_street: str,
    side: str,
    cscl_from: str,
    cscl_to: str,
) -> list[dict]:
    """Query SODA for all spans on a street+side and return available spans.

    Used to diagnose Level 3+ failures by showing what CSCL cross streets
    were sent vs what SODA spans actually exist for the on_street.

    Returns a list of {"from": str, "to": str, "count": int} dicts,
    sorted alphabetically by (from, to).
    """
    client = SODAClient()
    normalized_on = normalize_to_soda(on_street)
    query = client.build_on_street_query(normalized_on, side)
    try:
        records = await client.fetch_signs(query)
    except Exception as exc:  # noqa: BLE001 — best-effort audit script, skip and keep going
        print(
            f"  WARNING: diagnose_l3 SODA query failed for '{on_street}' {side}: {exc}",
            file=sys.stderr,
        )
        return []

    # Count unique (from_street, to_street) spans
    span_counts: Counter[tuple[str, str]] = Counter()
    for rec in records:
        f = rec.get("from_street", "")
        t = rec.get("to_street", "")
        span_counts[(f, t)] += 1

    return sorted(
        [{"from": f, "to": t, "count": n} for (f, t), n in span_counts.items()],
        key=lambda x: (x["from"], x["to"]),
    )


async def audit_fixture(fixture_path: Path, *, verbose: bool = False) -> list[dict]:
    """Run resolve_asp(debug=True) on each location in the fixture file."""
    with open(fixture_path, encoding="utf-8") as f:
        locations = json.load(f)

    results = []
    for loc in locations:
        try:
            desc = loc["description"]
            result = await resolve_asp(loc["lat"], loc["lon"], debug=True)
            # result is ASPDebugResult when debug=True
            entry: dict = {
                "description": desc,
                "soda_level": result.soda_level,
                "on_street": result.on_street or "",
                "from_street": result.from_street or "",
                "to_street": result.to_street or "",
                "side_of_street": result.side_of_street or "",
                "status": "ok",
            }

            # L3 diagnostic: only for NoMatchFound (soda_level==0) or high fallback
            # levels (3+). Excludes NoASPSigns (soda_level==0 but SODA was found),
            # which has no diagnostic value and would waste extra API calls.
            is_no_match = isinstance(result.sign_result, NoMatchFound)
            if (
                verbose
                and entry["on_street"]
                and (result.soda_level >= 3 or is_no_match)
            ):
                diag = await diagnose_l3(
                    entry["on_street"],
                    entry["side_of_street"],
                    entry["from_street"],
                    entry["to_street"],
                )
                entry["l3_diag"] = diag
                entry["l3_cscl_from"] = normalize_to_soda(entry["from_street"])
                entry["l3_cscl_to"] = normalize_to_soda(entry["to_street"])

            results.append(entry)
        except Exception as e:  # noqa: BLE001 — best-effort audit script, skip and keep going
            results.append(
                {
                    "description": loc.get("description", "<unknown>"),
                    "soda_level": 0,
                    "on_street": "",
                    "from_street": "",
                    "to_street": "",
                    "side_of_street": "",
                    "status": f"error: {type(e).__name__}: {e}",
                }
            )
    return results


def print_report(
    results: list[dict], fixture_name: str, *, verbose: bool = False
) -> None:
    """Print per-location table and summary statistics."""
    total = len(results)
    print(f"\n{'=' * 80}")
    print(f"ASP Coverage Audit: {fixture_name} ({total} locations)")
    print(f"{'=' * 80}\n")

    # Per-location table
    print(
        f"{'#':>3} | {'Level':>5} | {'Status':<8} | {'On Street':<25} | {'From':<20} | {'To':<20} | {'Description'}"
    )
    print(
        f"{'-' * 3}-+-{'-' * 5}-+-{'-' * 8}-+-{'-' * 25}-+-{'-' * 20}-+-{'-' * 20}-+-{'-' * 30}"
    )
    for i, r in enumerate(results, 1):
        level = str(r["soda_level"]) if r["status"] == "ok" else "fail"
        status = "ok" if r["status"] == "ok" else "FAIL"
        print(
            f"{i:>3} | {level:>5} | {status:<8} | {r['on_street']:<25} | {r['from_street']:<20} | {r['to_street']:<20} | {r['description']}"
        )

    # Summary
    print(f"\n{'=' * 80}")
    print("Summary:")
    counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    errors = 0
    for r in results:
        if r["status"] != "ok":
            errors += 1
        elif r["soda_level"] in counts:
            counts[r["soda_level"]] += 1
        else:
            counts[r["soda_level"]] = 1  # unexpected level — surface it explicitly

    for level in sorted(counts.keys()):
        pct = counts[level] / total * 100 if total else 0
        label = f"Level {level}" if level > 0 else "No match (level 0)"
        print(f"  {label}: {counts[level]}/{total} ({pct:.1f}%)")

    if errors:
        print(f"  Errors: {errors}/{total} ({errors / total * 100:.1f}%)")

    l12 = counts[1] + counts[2]
    l12_pct = l12 / total * 100 if total else 0
    print(f"\n  Level 1+2 (target): {l12}/{total} ({l12_pct:.1f}%)")
    print(f"{'=' * 80}")

    # L3 Diagnostics section (verbose only)
    if verbose:
        diag_rows = [
            (i, r) for i, r in enumerate(results, 1) if r.get("l3_diag") is not None
        ]
        if diag_rows:
            print("\nL3 Diagnostics:")
            print("─" * 60)
            for idx, r in diag_rows:
                on = r["on_street"]
                side = r.get("side_of_street", "?")
                lvl = r["soda_level"]
                print(f"  #{idx}: {r['description']}  (Level {lvl}, on={on} {side})")
                cscl_from = r.get("l3_cscl_from", "")
                cscl_to = r.get("l3_cscl_to", "")
                print(f"    CSCL sent:  from={cscl_from!r}  to={cscl_to!r}")
                spans = r["l3_diag"]
                if spans:
                    for span in spans:
                        print(
                            f"    SODA spans: from={span['from']!r}  to={span['to']!r}  ({span['count']} signs)"
                        )
                else:
                    print("    SODA spans: (none found)")
                print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit ASP coverage for GPS fixture locations"
    )
    parser.add_argument(
        "--fixture",
        default="queens",
        help="Named fixture ('queens', 'manhattan') or path to JSON file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show L3 diagnostic output for non-L1/L2 rows",
    )
    args = parser.parse_args()

    # Resolve fixture path
    fixture_input = args.fixture
    if fixture_input in _NAMED_FIXTURES:
        fixture_path = _NAMED_FIXTURES[fixture_input]
        fixture_name = fixture_input.title()
    else:
        fixture_path = Path(fixture_input)
        fixture_name = fixture_path.stem

    if not fixture_path.exists():
        print(f"Error: Fixture file not found: {fixture_path}", file=sys.stderr)
        sys.exit(1)

    # Enable INFO logging to see l4_event entries
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")

    results = asyncio.run(audit_fixture(fixture_path, verbose=args.verbose))
    print_report(results, fixture_name, verbose=args.verbose)


if __name__ == "__main__":
    main()
