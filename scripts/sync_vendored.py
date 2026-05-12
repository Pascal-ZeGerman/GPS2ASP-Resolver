#!/usr/bin/env python3
"""Sync the vendored gps2asp mirror from the authoritative library source.

Walks ``src/gps2asp/*.py`` (excluding the ``data/`` subtree), rewrites
column-zero ``from gps2asp.X.Y import Z`` lines into the correct relative
form for each file's subpackage depth, and either writes the result to
``custom_components/asp_parking/gps2asp/`` (write mode, the default) or
compares against the existing vendored bytes and exits non-zero when any
file would change (``--dry-run`` mode, used by CI).

Usage:
    .venv/bin/python scripts/sync_vendored.py             # write mode
    .venv/bin/python scripts/sync_vendored.py --dry-run   # CI / drift check

Exit codes:
    0  -- write mode completed, OR --dry-run found no drift
    1  -- --dry-run found drift (offending files printed to stdout)

All non-import content is copied verbatim. The regex is column-zero anchored
so indented ``from gps2asp.`` imports inside ``TYPE_CHECKING`` blocks and
docstring text round-trip unchanged.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "gps2asp"
VENDOR_ROOT = REPO_ROOT / "custom_components" / "asp_parking" / "gps2asp"

# Match ONLY column-zero ``from gps2asp.X import ...`` lines. The trailing
# escaped dot enforces a dotted-tail prefix, so ``gps2asp_helpers`` and the
# bare (unused) ``from gps2asp import X`` form do NOT match.
_FROM_GPS2ASP = re.compile(r"^from gps2asp\.[A-Za-z0-9_.]+ import ", re.MULTILINE)


def normalize_source(rel_path: Path, text: str) -> str:
    """Rewrite top-level absolute gps2asp imports to the relative form.

    Args:
        rel_path: Path of the file relative to ``SRC_ROOT`` (e.g.
            ``Path("resolver/spatial_index.py")`` or ``Path("__init__.py")``).
        text: Full text of the source file.

    Returns:
        The text with every column-zero ``from gps2asp.X import`` line
        rewritten. Indented imports and ``gps2asp_helpers``-style lookalikes
        are left untouched.
    """
    pkg_parts = list(rel_path.parts[:-1])

    def rewrite(m: re.Match[str]) -> str:
        # The regex captures e.g. ``from gps2asp.resolver.exceptions import ``.
        # Strip the leading ``from gps2asp.`` prefix and the trailing
        # `` import `` suffix to obtain the dotted target path.
        matched = m.group(0)
        target = matched[len("from gps2asp.") : -len(" import ")]
        target_parts = target.split(".")
        # Longest leading equal run between pkg_parts and target_parts.
        prefix_len = 0
        for a, b in zip(pkg_parts, target_parts):
            if a == b:
                prefix_len += 1
            else:
                break
        dots = "." * (len(pkg_parts) - prefix_len + 1)
        remaining = target_parts[prefix_len:]
        tail = ".".join(remaining)
        return f"from {dots}{tail} import " if tail else f"from {dots} import "

    return _FROM_GPS2ASP.sub(rewrite, text)


def iter_source_files() -> list[Path]:
    """Return all ``.py`` files under ``SRC_ROOT``, excluding the ``data/`` subtree.

    Sorted for deterministic dry-run output (drift list ordering is stable).
    """
    return sorted(
        p
        for p in SRC_ROOT.rglob("*.py")
        if "data" not in p.relative_to(SRC_ROOT).parts
    )


def main() -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(
        description="Sync vendored gps2asp/ from src/gps2asp/, or check drift."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Exit non-zero if vendored files differ from the normalized "
            "source. Writes nothing. Used by .github/workflows/vendor-guard.yml."
        ),
    )
    args = parser.parse_args()

    drifted: list[str] = []
    src_written = 0
    stale_deleted = 0
    source_files = iter_source_files()
    for src_path in source_files:
        rel = src_path.relative_to(SRC_ROOT)
        vendor_path = VENDOR_ROOT / rel
        source_text = src_path.read_text(encoding="utf-8")
        target_text = normalize_source(rel, source_text)
        existing = (
            vendor_path.read_text(encoding="utf-8") if vendor_path.exists() else None
        )
        if existing != target_text:
            if args.dry_run:
                drifted.append(str(rel))
            else:
                vendor_path.parent.mkdir(parents=True, exist_ok=True)
                vendor_path.write_text(target_text, encoding="utf-8")
                src_written += 1

    # Second pass: detect vendor-only files that have no src counterpart.
    # These are stale modules left behind after a source file was deleted.
    synced_rels = {src.relative_to(SRC_ROOT) for src in source_files}
    for vendor_py in sorted(
        p
        for p in VENDOR_ROOT.rglob("*.py")
        if "data" not in p.relative_to(VENDOR_ROOT).parts
    ):
        rel = vendor_py.relative_to(VENDOR_ROOT)
        if rel not in synced_rels:
            if args.dry_run:
                drifted.append(f"[stale] {rel}")
            else:
                vendor_py.unlink()
                stale_deleted += 1

    if args.dry_run:
        if drifted:
            print(
                "Vendored mirror drift detected. The following files in "
                "custom_components/asp_parking/gps2asp/ do not match "
                "src/gps2asp/ (run `python scripts/sync_vendored.py` to fix):"
            )
            for path in drifted:
                print(f"  {path}")
            return 1
        print("Vendored mirror is in sync with src/gps2asp/.")
        return 0

    unchanged = len(source_files) - src_written
    print(
        f"Synced {src_written} file(s), deleted {stale_deleted} stale file(s);"
        f" {unchanged} already up to date."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
