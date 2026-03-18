#!/usr/bin/env python3
"""Audit ASP coverage by running GPS fixture locations through the live pipeline.

Usage:
    python scripts/audit_queens_coverage.py                          # Queens (default)
    python scripts/audit_queens_coverage.py --fixture manhattan      # Manhattan
    python scripts/audit_queens_coverage.py --fixture path/to/file.json  # Custom

Requires network access (live SODA API calls).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from gps2asp import resolve_asp, ASPDebugResult, AmbiguousResolutionError

# Default fixture paths
_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
_NAMED_FIXTURES = {
    "queens": _FIXTURE_DIR / "queens_coverage.json",
    "manhattan": _FIXTURE_DIR / "manhattan_coverage.json",
}


async def audit_fixture(fixture_path: Path) -> list[dict]:
    """Run resolve_asp(debug=True) on each location in the fixture file."""
    with open(fixture_path) as f:
        locations = json.load(f)

    results = []
    for loc in locations:
        desc = loc["description"]
        try:
            result = await resolve_asp(loc["lat"], loc["lon"], debug=True)
            # result is ASPDebugResult when debug=True
            results.append({
                "description": desc,
                "soda_level": result.soda_level,
                "on_street": result.on_street or "",
                "from_street": result.from_street or "",
                "to_street": result.to_street or "",
                "status": "ok",
            })
        except Exception as e:
            results.append({
                "description": desc,
                "soda_level": 0,
                "on_street": "",
                "from_street": "",
                "to_street": "",
                "status": f"error: {type(e).__name__}: {e}",
            })
    return results


def print_report(results: list[dict], fixture_name: str) -> None:
    """Print per-location table and summary statistics."""
    total = len(results)
    print(f"\n{'='*80}")
    print(f"ASP Coverage Audit: {fixture_name} ({total} locations)")
    print(f"{'='*80}\n")

    # Per-location table
    print(f"{'#':>3} | {'Level':>5} | {'Status':<8} | {'On Street':<25} | {'From':<20} | {'To':<20} | {'Description'}")
    print(f"{'-'*3}-+-{'-'*5}-+-{'-'*8}-+-{'-'*25}-+-{'-'*20}-+-{'-'*20}-+-{'-'*30}")
    for i, r in enumerate(results, 1):
        level = str(r["soda_level"]) if r["status"] == "ok" else "fail"
        status = "ok" if r["status"] == "ok" else "FAIL"
        print(f"{i:>3} | {level:>5} | {status:<8} | {r['on_street']:<25} | {r['from_street']:<20} | {r['to_street']:<20} | {r['description']}")

    # Summary
    print(f"\n{'='*80}")
    print("Summary:")
    counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    errors = 0
    for r in results:
        if r["status"] != "ok":
            errors += 1
        else:
            counts[r["soda_level"]] = counts.get(r["soda_level"], 0) + 1

    for level in [1, 2, 3, 4, 0]:
        pct = counts[level] / total * 100 if total else 0
        label = f"Level {level}" if level > 0 else "No match (level 0)"
        print(f"  {label}: {counts[level]}/{total} ({pct:.1f}%)")

    if errors:
        print(f"  Errors: {errors}/{total} ({errors/total*100:.1f}%)")

    l12 = counts[1] + counts[2]
    l12_pct = l12 / total * 100 if total else 0
    print(f"\n  Level 1+2 (target): {l12}/{total} ({l12_pct:.1f}%)")
    print(f"{'='*80}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit ASP coverage for GPS fixture locations")
    parser.add_argument(
        "--fixture",
        default="queens",
        help="Named fixture ('queens', 'manhattan') or path to JSON file",
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

    results = asyncio.run(audit_fixture(fixture_path))
    print_report(results, fixture_name)


if __name__ == "__main__":
    main()
