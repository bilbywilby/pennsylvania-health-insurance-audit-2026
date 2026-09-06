#!/usr/bin/env python3
"""Validates structural integrity and schemas of mandatory source files."""
import csv
import sys
from pathlib import Path
from typing import List, Optional

DATA_DIR = Path("data")
APPROVED_RATES = DATA_DIR / "approved_rates_2026.csv"
CROSSWALK_JSON = DATA_DIR / "public" / "pa_county_fips_crosswalk.json"

REQUIRED_RATE_COLUMNS = ["county", "rate", "age", "plan_type"]


def check_csv_schema(path: Path, expected_cols: Optional[List[str]] = None) -> bool:
    if not path.exists():
        print(f"[FAIL] Missing target file: {path}")
        return False

    print(f"[OK] File present: {path}")

    if expected_cols:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    print(f"[FAIL] {path} contains no headers or is empty.")
                    return False

                headers = {h.strip().lower() for h in reader.fieldnames}
                missing = set(expected_cols) - headers
                if missing:
                    print(f"[FAIL] {path} missing required columns: {sorted(missing)}")
                    return False

                print(f"[OK] {path} schema validated. Found columns: {reader.fieldnames}")
        except Exception as exc:
            print(f"[FAIL] Error parsing {path}: {exc}")
            return False

    return True


def main() -> None:
    print("=== Validating Source Files and Schemas ===")
    errors = 0

    # Single strict check — no existence-only fallback that would mask a
    # schema failure (that fallback bug let bad-header files pass silently).
    if not check_csv_schema(APPROVED_RATES, REQUIRED_RATE_COLUMNS):
        errors += 1

    if not CROSSWALK_JSON.exists():
        print(f"[FAIL] Crosswalk missing at {CROSSWALK_JSON}. Run 02_crosswalk.py first.")
        errors += 1
    else:
        print(f"[OK] Found crosswalk JSON: {CROSSWALK_JSON}")

    if errors > 0:
        print(f"=== Validation Failed with {errors} error(s) ===")
        sys.exit(1)

    print("=== Validation Complete ===")


if __name__ == "__main__":
    main()
