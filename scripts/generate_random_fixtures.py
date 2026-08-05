#!/usr/bin/env python3
"""Generate random geocoded address fixtures for coverage auditing.

Uses NYC Planning GeoSearch API to geocode real addresses across
different blocks in Queens and Manhattan.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import httpx

from geocode_fixtures import geocode_address

# Queens: neighborhoods with street grids
QUEENS_ADDRESSES = [
    # Astoria
    "21-10 24 AVENUE, Astoria, NY",
    "28-15 36 STREET, Astoria, NY",
    "31-50 21 STREET, Astoria, NY",
    "25-40 38 STREET, Astoria, NY",
    "23-10 DITMARS BOULEVARD, Astoria, NY",
    "30-10 NEWTOWN AVENUE, Astoria, NY",
    "36-15 30 AVENUE, Astoria, NY",
    "24-20 STEINWAY STREET, Astoria, NY",
    # Long Island City
    "10-20 46 AVENUE, Long Island City, NY",
    "47-10 VERNON BOULEVARD, Long Island City, NY",
    "11-15 44 ROAD, Long Island City, NY",
    "27-10 QUEENS PLAZA NORTH, Long Island City, NY",
    # Jackson Heights
    "37-10 75 STREET, Jackson Heights, NY",
    "34-15 BROADWAY, Jackson Heights, NY",
    "40-20 82 STREET, Jackson Heights, NY",
    "76-10 35 AVENUE, Jackson Heights, NY",
    "33-50 85 STREET, Jackson Heights, NY",
    # Elmhurst
    "86-10 BROADWAY, Elmhurst, NY",
    "42-15 JUDGE STREET, Elmhurst, NY",
    "80-20 45 AVENUE, Elmhurst, NY",
    "51-10 QUEENS BOULEVARD, Elmhurst, NY",
    # Woodside
    "60-15 39 AVENUE, Woodside, NY",
    "58-20 WOODSIDE AVENUE, Woodside, NY",
    "54-10 ROOSEVELT AVENUE, Woodside, NY",
    # Flushing
    "41-20 MAIN STREET, Flushing, NY",
    "135-15 40 ROAD, Flushing, NY",
    "38-10 UNION STREET, Flushing, NY",
    "144-20 BARCLAY AVENUE, Flushing, NY",
    "37-15 PRINCE STREET, Flushing, NY",
    "34-40 MURRAY STREET, Flushing, NY",
    "147-10 NORTHERN BOULEVARD, Flushing, NY",
    # Jamaica
    "160-20 JAMAICA AVENUE, Jamaica, NY",
    "89-15 PARSONS BOULEVARD, Jamaica, NY",
    "107-20 GUY BREWER BOULEVARD, Jamaica, NY",
    "150-10 HILLSIDE AVENUE, Jamaica, NY",
    "109-15 MERRICK BOULEVARD, Jamaica, NY",
    # Forest Hills
    "108-10 72 AVENUE, Forest Hills, NY",
    "70-15 YELLOWSTONE BOULEVARD, Forest Hills, NY",
    "99-20 67 ROAD, Forest Hills, NY",
    "63-15 SAUNDERS STREET, Forest Hills, NY",
    # Rego Park
    "97-10 63 ROAD, Rego Park, NY",
    "62-50 BOOTH STREET, Rego Park, NY",
    "96-15 QUEENS BOULEVARD, Rego Park, NY",
    # Ridgewood
    "60-20 MYRTLE AVENUE, Ridgewood, NY",
    "18-15 PUTNAM AVENUE, Ridgewood, NY",
    "55-10 CATALPA AVENUE, Ridgewood, NY",
    # Corona
    "104-15 ROOSEVELT AVENUE, Corona, NY",
    "37-50 103 STREET, Corona, NY",
    "42-10 NATIONAL STREET, Corona, NY",
    # Sunnyside
    "46-15 GREENPOINT AVENUE, Sunnyside, NY",
    "43-20 QUEENS BOULEVARD, Sunnyside, NY",
    # Bayside
    "38-10 BELL BOULEVARD, Bayside, NY",
    "213-15 40 AVENUE, Bayside, NY",
    "42-20 CORPORAL KENNEDY STREET, Bayside, NY",
    # Fresh Meadows
    "188-10 UNION TURNPIKE, Fresh Meadows, NY",
    "73-20 188 STREET, Fresh Meadows, NY",
    # Kew Gardens
    "83-10 LEFFERTS BOULEVARD, Kew Gardens, NY",
    "118-15 METROPOLITAN AVENUE, Kew Gardens, NY",
]

# Manhattan: neighborhoods with diverse street patterns
MANHATTAN_ADDRESSES = [
    # Upper West Side
    "205 WEST 80 STREET, New York, NY",
    "315 WEST 95 STREET, New York, NY",
    "155 WEST 68 STREET, New York, NY",
    "420 WEST 110 STREET, New York, NY",
    "280 RIVERSIDE DRIVE, New York, NY",
    "510 WEST 86 STREET, New York, NY",
    "170 WEST 73 STREET, New York, NY",
    # Upper East Side
    "215 EAST 75 STREET, New York, NY",
    "330 EAST 85 STREET, New York, NY",
    "170 EAST 93 STREET, New York, NY",
    "425 EAST 65 STREET, New York, NY",
    "240 EAST 79 STREET, New York, NY",
    "155 EAST 88 STREET, New York, NY",
    # East Village / Lower East Side
    "210 EAST 6 STREET, New York, NY",
    "315 EAST 10 STREET, New York, NY",
    "175 AVENUE B, New York, NY",
    "130 EAST 3 STREET, New York, NY",
    "85 CLINTON STREET, New York, NY",
    "150 RIVINGTON STREET, New York, NY",
    "95 AVENUE A, New York, NY",
    # Harlem
    "210 WEST 125 STREET, New York, NY",
    "145 WEST 139 STREET, New York, NY",
    "230 LENOX AVENUE, New York, NY",
    "350 WEST 145 STREET, New York, NY",
    "280 WEST 115 STREET, New York, NY",
    "110 WEST 131 STREET, New York, NY",
    "415 EDGECOMBE AVENUE, New York, NY",
    # Washington Heights / Inwood
    "615 WEST 170 STREET, New York, NY",
    "530 WEST 181 STREET, New York, NY",
    "4850 BROADWAY, New York, NY",
    "95 NAGLE AVENUE, New York, NY",
    "610 WEST 158 STREET, New York, NY",
    # Midtown
    "315 WEST 48 STREET, New York, NY",
    "235 EAST 53 STREET, New York, NY",
    "410 WEST 42 STREET, New York, NY",
    "150 EAST 39 STREET, New York, NY",
    "220 WEST 57 STREET, New York, NY",
    # Chelsea / West Village
    "310 WEST 20 STREET, New York, NY",
    "155 WEST 15 STREET, New York, NY",
    "85 PERRY STREET, New York, NY",
    "210 WEST 10 STREET, New York, NY",
    "130 7 AVENUE SOUTH, New York, NY",
    # Gramercy / Murray Hill
    "225 EAST 24 STREET, New York, NY",
    "320 EAST 34 STREET, New York, NY",
    "150 EAST 30 STREET, New York, NY",
    "235 EAST 22 STREET, New York, NY",
    # East Harlem
    "175 EAST 105 STREET, New York, NY",
    "230 EAST 112 STREET, New York, NY",
    "310 EAST 119 STREET, New York, NY",
    "110 EAST 100 STREET, New York, NY",
    # Financial District / Tribeca
    "75 MURRAY STREET, New York, NY",
    "130 CHAMBERS STREET, New York, NY",
    "50 THOMAS STREET, New York, NY",
    "180 BROADWAY, New York, NY",
    # Morningside Heights
    "420 WEST 121 STREET, New York, NY",
    "515 WEST 113 STREET, New York, NY",
    "210 CLAREMONT AVENUE, New York, NY",
]


def generate_fixtures(
    client: httpx.Client, addresses: list[str], borough_name: str, count: int = 50
) -> list[dict]:
    """Geocode addresses and return up to `count` unique-block fixtures."""
    random.shuffle(addresses)
    fixtures = []
    seen_blocks = set()

    for addr in addresses:
        if len(fixtures) >= count:
            break

        result = geocode_address(client, addr, borough_name)
        if not result:
            continue

        # Deduplicate by rough block (round to ~100m grid)
        block_key = (round(result["lat"], 3), round(result["lon"], 3))
        if block_key in seen_blocks:
            continue
        seen_blocks.add(block_key)

        fixtures.append(result)
        print(f"  [{len(fixtures):>2}/{count}] {result['description']}")
        time.sleep(0.15)  # Rate limit

    return fixtures


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

    with httpx.Client(timeout=10.0) as client:
        print("\n=== Generating Queens fixtures ===")
        queens = generate_fixtures(client, QUEENS_ADDRESSES, "Queens", 50)
        queens_path = out_dir / "queens_coverage_50.json"
        with open(queens_path, "w") as f:
            json.dump(queens, f, indent=2)
        print(f"\nWrote {len(queens)} Queens fixtures to {queens_path}")

        print("\n=== Generating Manhattan fixtures ===")
        manhattan = generate_fixtures(client, MANHATTAN_ADDRESSES, "Manhattan", 50)
        manhattan_path = out_dir / "manhattan_coverage_50.json"
        with open(manhattan_path, "w") as f:
            json.dump(manhattan, f, indent=2)
        print(f"\nWrote {len(manhattan)} Manhattan fixtures to {manhattan_path}")


if __name__ == "__main__":
    main()
