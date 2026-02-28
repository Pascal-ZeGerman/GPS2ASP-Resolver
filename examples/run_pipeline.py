"""Live demo: GPS -> ASP schedule pipeline.

Runs the full three-stage pipeline (GPS -> street segment -> SODA signs -> schedule)
using the real CSCL spatial index and live SODA API. Both normal and debug modes
are demonstrated in sequence.

Requirements:
    pip install -e ".[dev]"  # install gps2asp package into current venv
    python -m gps2asp.build.build_index  # build spatial index (if not already built)

Usage:
    python examples/run_pipeline.py [lat] [lon]

Default coordinates: PROSPECT PL between VANDERBILT AVE and CARLTON AVE, Brooklyn.
This is the canonical regression case for Phase 6 confidence algorithm fixes.

Examples:
    python examples/run_pipeline.py
    python examples/run_pipeline.py 40.677629 -73.968527
    python examples/run_pipeline.py 40.7580 -73.9855
"""
from __future__ import annotations

import argparse
import asyncio

from gps2asp import resolve_asp

DEFAULT_LAT = 40.677629
DEFAULT_LON = -73.968527


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GPS to ASP schedule -- live pipeline demo"
    )
    parser.add_argument(
        "lat",
        nargs="?",
        type=float,
        default=DEFAULT_LAT,
        help=f"Latitude in WGS84 (default: {DEFAULT_LAT})",
    )
    parser.add_argument(
        "lon",
        nargs="?",
        type=float,
        default=DEFAULT_LON,
        help=f"Longitude in WGS84 (default: {DEFAULT_LON})",
    )
    args = parser.parse_args()

    async def run() -> None:
        print(f"Coordinates: lat={args.lat}, lon={args.lon}")
        print()

        print("=== Normal mode (debug=False) ===")
        result = await resolve_asp(args.lat, args.lon)
        print(result)
        print()

        print("=== Debug mode (debug=True) ===")
        debug_result = await resolve_asp(args.lat, args.lon, debug=True)
        print(debug_result)

    asyncio.run(run())


if __name__ == "__main__":
    main()
