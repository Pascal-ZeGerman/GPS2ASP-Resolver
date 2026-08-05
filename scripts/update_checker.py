"""Monthly auto-check for CSCL data updates.

Queries the NYC Open Data CSCL dataset metadata to determine when the data
was last updated, compares it to the local build timestamp, and reports
whether an update is available.

Usage:
    python scripts/update_checker.py
    python scripts/update_checker.py --build-info /path/to/build_info.json
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger("gps2asp.build")

# NYC Open Data CSCL dataset metadata URL
CSCL_METADATA_URL = "https://data.cityofnewyork.us/api/views/3mf9-qshr.json"


def _setup_logging() -> None:
    """Configure build logging to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def check_for_updates(
    current_build_info_path: Path | None = None,
) -> dict:
    """Check if the CSCL dataset has been updated since last build.

    Queries the CSCL dataset metadata for the rowsUpdatedAt timestamp
    and compares it to the local build timestamp from build_info.json.

    Args:
        current_build_info_path: Path to the local build_info.json file.
            If None, uses the default location relative to this package.

    Returns:
        Dict with keys:
        - update_available: bool
        - current_build: str (ISO timestamp of last build)
        - latest_data: str (ISO timestamp of latest CSCL data update)
        - days_since_build: int
    """
    # Determine build_info.json location
    if current_build_info_path is None:
        package_dir = Path(__file__).parent.parent
        current_build_info_path = (
            package_dir / "src" / "gps2asp" / "data" / "index" / "build_info.json"
        )

    # Read current build info
    if not current_build_info_path.exists():
        logger.warning("No build_info.json found at %s", current_build_info_path)
        return {
            "update_available": True,
            "current_build": "never",
            "latest_data": "unknown",
            "days_since_build": -1,
        }

    with open(current_build_info_path, "r") as f:
        build_info = json.load(f)

    current_build_ts = build_info.get("build_timestamp", "")
    logger.info("Current build timestamp: %s", current_build_ts)

    # Parse current build timestamp
    try:
        current_build_dt = datetime.fromisoformat(
            current_build_ts.replace("Z", "+00:00")
        )
    except (ValueError, AttributeError):
        logger.warning("Could not parse build timestamp: %s", current_build_ts)
        current_build_dt = datetime.min.replace(tzinfo=timezone.utc)

    # Query CSCL dataset metadata
    try:
        response = requests.get(CSCL_METADATA_URL, timeout=30)
        response.raise_for_status()
        metadata = response.json()
    except requests.RequestException as e:
        logger.exception("Failed to fetch CSCL metadata: %s", e)
        # Fail toward "check manually": a swallowed network error must not be
        # reported as "up to date", which would silently suppress every future
        # update notification.
        return {
            "update_available": True,
            "current_build": current_build_ts,
            "latest_data": "fetch_failed",
            "days_since_build": (datetime.now(timezone.utc) - current_build_dt).days,
        }

    # Extract rowsUpdatedAt (Unix timestamp in seconds)
    rows_updated_at = metadata.get("rowsUpdatedAt")
    if rows_updated_at is None:
        # Missing field: defaulting to 0 (epoch 1970) would always compare as
        # "up to date" and silently hide real updates. Surface it instead.
        logger.error(
            "CSCL metadata missing 'rowsUpdatedAt'; cannot determine update status"
        )
        return {
            "update_available": True,
            "current_build": current_build_ts,
            "latest_data": "unknown",
            "days_since_build": (datetime.now(timezone.utc) - current_build_dt).days,
        }
    latest_data_dt = datetime.fromtimestamp(rows_updated_at, tz=timezone.utc)
    latest_data_ts = latest_data_dt.isoformat()

    logger.info("Latest CSCL data update: %s", latest_data_ts)

    # Compare
    days_since_build = (datetime.now(timezone.utc) - current_build_dt).days
    update_available = latest_data_dt > current_build_dt

    result = {
        "update_available": update_available,
        "current_build": current_build_ts,
        "latest_data": latest_data_ts,
        "days_since_build": days_since_build,
    }

    if update_available:
        logger.info(
            "Update available! Data updated %s, build is %d days old.",
            latest_data_ts,
            days_since_build,
        )
    else:
        logger.info(
            "Index is up to date. Build is %d days old.",
            days_since_build,
        )

    return result


if __name__ == "__main__":
    import argparse

    _setup_logging()

    parser = argparse.ArgumentParser(
        description="Check if CSCL data has been updated since last index build"
    )
    parser.add_argument(
        "--build-info",
        type=Path,
        default=None,
        help="Path to build_info.json (default: src/gps2asp/data/index/build_info.json)",
    )
    args = parser.parse_args()

    result = check_for_updates(current_build_info_path=args.build_info)
    print(json.dumps(result, indent=2))
