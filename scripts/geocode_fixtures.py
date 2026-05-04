#!/usr/bin/env python3
"""Geocode NYC street addresses into GPS fixture JSON files.

Uses the NYC GeoSearch v2 API (geosearch.planninglabs.nyc/v2/search)
to convert street addresses into lat/lon coordinates suitable for
GPS coverage fixture files.

Usage:
    python scripts/geocode_fixtures.py --borough queens --output tests/fixtures/queens_coverage.json
    python scripts/geocode_fixtures.py --borough manhattan --output tests/fixtures/manhattan_coverage.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

GEOSEARCH_URL = "https://geosearch.planninglabs.nyc/v2/search"
REQUEST_DELAY = 0.5  # courtesy delay between requests (seconds)

QUEENS_ADDRESSES = [
    # Jamaica (5)
    "160-20 89th Avenue, Jamaica, NY",
    "107-15 150th Street, Jamaica, NY",
    "144-30 Sanford Avenue, Flushing, NY",
    "109-35 168th Street, Jamaica, NY",
    "147-20 Archer Avenue, Jamaica, NY",
    # Flushing (5)
    "41-15 Kissena Boulevard, Flushing, NY",
    "136-20 Sanford Avenue, Flushing, NY",
    "33-16 Farrington Street, Flushing, NY",
    "45-15 Bowne Street, Flushing, NY",
    "138-20 Franklin Avenue, Flushing, NY",
    # Astoria (5)
    "31-15 Ditmars Boulevard, Astoria, NY",
    "25-30 31st Street, Astoria, NY",
    "23-15 28th Avenue, Astoria, NY",
    "30-50 38th Street, Astoria, NY",
    "22-40 35th Street, Astoria, NY",
    # Jackson Heights (4)
    "37-21 80th Street, Jackson Heights, NY",
    "34-20 74th Street, Jackson Heights, NY",
    "35-40 82nd Street, Jackson Heights, NY",
    "78-10 34th Avenue, Jackson Heights, NY",
    # Forest Hills (4)
    "108-25 68th Road, Forest Hills, NY",
    "67-35 Dartmouth Street, Forest Hills, NY",
    "98-20 67th Avenue, Forest Hills, NY",
    "71-15 Austin Street, Forest Hills, NY",
    # Union Turnpike area (2)
    "164-10 Union Turnpike, Fresh Meadows, NY",
    "80-40 Chevy Chase Street, Jamaica Estates, NY",
]

MANHATTAN_ADDRESSES: list[str] = [
    # Upper West Side (5)
    "215 West 76th Street, New York, NY",
    "310 West 83rd Street, New York, NY",
    "225 West 88th Street, New York, NY",
    "305 West 72nd Street, New York, NY",
    "240 West 91st Street, New York, NY",
    # Harlem (4)
    "210 West 122nd Street, New York, NY",
    "215 West 130th Street, New York, NY",
    "310 West 116th Street, New York, NY",
    "120 West 135th Street, New York, NY",
    # East Village (5)
    "215 East 7th Street, New York, NY",
    "220 East 5th Street, New York, NY",
    "310 East 9th Street, New York, NY",
    "225 East 4th Street, New York, NY",
    "25 St Marks Place, New York, NY",
    # Midtown side streets (4)
    "340 West 46th Street, New York, NY",
    "225 East 50th Street, New York, NY",
    "410 West 54th Street, New York, NY",
    "320 East 43rd Street, New York, NY",
]

_BOROUGH_ADDRESSES: dict[str, list[str]] = {
    "queens": QUEENS_ADDRESSES,
    "manhattan": MANHATTAN_ADDRESSES,
}

# GeoSearch borough label mapping (API returns full borough names)
_BOROUGH_LABELS: dict[str, str] = {
    "queens": "Queens",
    "manhattan": "Manhattan",
}

# Validate that both dicts are in sync — adding a new borough requires both.
assert set(_BOROUGH_ADDRESSES.keys()) == set(_BOROUGH_LABELS.keys()), (
    "Borough address and label dicts are out of sync"
)


def geocode_address(
    client: httpx.Client,
    address: str,
    expected_borough: str,
) -> dict | None:
    """Geocode a single address via GeoSearch v2 API.

    Returns a fixture dict with description, lat, lon or None on failure.
    GeoJSON coordinates are [lon, lat] -- lat is index 1, lon is index 0.
    """
    try:
        resp = client.get(GEOSEARCH_URL, params={"text": address, "size": 1})
        resp.raise_for_status()
        data = resp.json()

        features = data.get("features", [])
        if not features:
            print(f"  WARNING: No results for '{address}' -- skipping", file=sys.stderr)
            return None

        feature = features[0]
        geometry = feature.get("geometry")
        if not geometry or not geometry.get("coordinates"):
            print(
                f"  WARNING: No geometry in GeoSearch result for '{address}' -- skipping",
                file=sys.stderr,
            )
            return None
        coords = geometry["coordinates"]
        props = feature.get("properties", {})

        # Verify borough matches expected
        borough = props.get("borough", "")
        if borough != expected_borough:
            print(
                f"  WARNING: '{address}' geocoded to {borough}, "
                f"expected {expected_borough} -- skipping",
                file=sys.stderr,
            )
            return None

        label = props.get("label", address)

        return {
            "description": label,
            "lat": coords[1],  # GeoJSON: [lon, lat]
            "lon": coords[0],  # GeoJSON: [lon, lat]
        }
    except Exception as e:
        print(f"  WARNING: Failed to geocode '{address}': {e} -- skipping", file=sys.stderr)
        return None


def geocode_addresses(
    addresses: list[str],
    expected_borough: str,
) -> list[dict]:
    """Geocode a list of addresses, returning fixture dicts."""
    results: list[dict] = []
    borough_label = _BOROUGH_LABELS.get(expected_borough, expected_borough.title())

    with httpx.Client(timeout=10.0) as client:
        for i, addr in enumerate(addresses):
            print(f"  [{i + 1}/{len(addresses)}] Geocoding: {addr}")
            fixture = geocode_address(client, addr, borough_label)
            if fixture is not None:
                print(f"    -> {fixture['description']}")
                results.append(fixture)
            if i < len(addresses) - 1:
                time.sleep(REQUEST_DELAY)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Geocode NYC street addresses into GPS fixture JSON files"
    )
    parser.add_argument(
        "--borough",
        required=True,
        choices=list(_BOROUGH_ADDRESSES.keys()),
        help="Borough to geocode addresses for",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output JSON file path",
    )
    args = parser.parse_args()

    addresses = _BOROUGH_ADDRESSES[args.borough]
    if not addresses:
        print(f"Error: No addresses defined for borough '{args.borough}'", file=sys.stderr)
        sys.exit(1)

    borough_label = _BOROUGH_LABELS.get(args.borough, args.borough.title())
    print(f"Geocoding {len(addresses)} addresses for {borough_label}...")

    results = geocode_addresses(addresses, args.borough)

    print(f"\nSuccessfully geocoded {len(results)}/{len(addresses)} addresses")

    if not results:
        print(
            f"Error: Zero addresses geocoded successfully. Output file NOT written "
            f"to avoid overwriting existing fixture.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Write output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
        f.write("\n")

    print(f"Written to {args.output}")


if __name__ == "__main__":
    main()
