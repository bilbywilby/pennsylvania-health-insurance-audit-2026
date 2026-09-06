#!/usr/bin/env python3
"""
Performs the core Pennsylvania Health Insurance Audit.
- Loads approved rates and crosswalk data.
- Validates every record against the crosswalk (case-insensitive).
- Sanitizes and validates numeric rate values.
- Aggregates weighted average rate by rating area.
- Writes anomaly and aggregate reports.
"""
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

# --- Configuration (single source of truth for all output paths) ---
DATA_DIR = Path("data")
APPROVED_RATES_FILE = DATA_DIR / "approved_rates_2026.csv"
CROSSWALK_FILE = DATA_DIR / "public" / "pa_county_fips_crosswalk.json"
REPORT_FILE = DATA_DIR / "private" / "audit_anomalies_2026.csv"
AGGREGATE_REPORT_FILE = DATA_DIR / "private" / "audit_aggregates_2026.csv"

REQUIRED_RATE_COLUMNS = ["county", "rate", "age", "plan_type"]


# --- Custom Exceptions ---
class AuditError(Exception):
    """Base exception for audit operations."""


class AuditSchemaError(AuditError):
    """Raised when data loading fails or CSV schema validation fails."""


class AuditDataValidationError(AuditError):
    """Reserved for callers that want a hard failure on data anomalies rather
    than inspecting the returned AuditResult counts. Not raised internally —
    run_audit() always returns normally when the *schema* is sound, even if
    individual records are anomalous; main() decides the exit code from the
    result counts."""


class AuditResult:
    def __init__(self):
        self.total_records = 0
        self.valid_records = 0
        self.missing_counties = 0
        self.missing_fips = 0
        self.invalid_rates = 0
        self.anomalies: List[Dict] = []
        # area_id -> running weighted-sum accumulators
        self.area_stats: Dict[str, Dict] = defaultdict(
            lambda: {"total_weight": 0.0, "sum_rate_weighted": 0.0, "record_count": 0}
        )

    def add_anomaly(self, record: Dict, reason: str):
        self.anomalies.append(
            {
                "reason": reason,
                "county": record.get("county"),
                "rate": record.get("rate"),
                "age": record.get("age"),
                "plan_type": record.get("plan_type"),
                "raw_record": json.dumps(record),
            }
        )


def load_crosswalk() -> Dict[str, Dict[str, str]]:
    """Loads crosswalk JSON into a case-insensitive lookup keyed by lowercase county name."""
    if not CROSSWALK_FILE.exists():
        raise AuditSchemaError(f"Crosswalk file not found: {CROSSWALK_FILE}")

    with open(CROSSWALK_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise AuditSchemaError(f"Crosswalk file is not valid JSON: {e}") from e

    county_map = {}
    for area_id, counties in data.items():
        for item in counties:
            key = item["county"].strip().lower()
            county_map[key] = {
                "display_name": item["county"].strip(),
                "fips": item["fips"],
                "area": area_id,
            }
    return county_map


def load_rates() -> List[Dict]:
    """Loads approved rates CSV with normalized (stripped, lowercased) column keys."""
    if not APPROVED_RATES_FILE.exists():
        raise AuditSchemaError(f"Rates file not found: {APPROVED_RATES_FILE}")

    records = []
    with open(APPROVED_RATES_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise AuditSchemaError("CSV file is empty or missing header row.")

        normalized_headers = [h.strip().lower() for h in reader.fieldnames]
        missing_cols = set(REQUIRED_RATE_COLUMNS) - set(normalized_headers)
        if missing_cols:
            raise AuditSchemaError(f"CSV missing required columns: {missing_cols}")

        for row in reader:
            # k can be None when a row has more fields than the header (ragged CSV);
            # v can be None when a row has fewer fields than the header.
            records.append(
                {
                    k.strip().lower(): (v or "").strip()
                    for k, v in row.items()
                    if k is not None
                }
            )

    return records


def validate_and_parse_rate(value: str) -> Optional[float]:
    """Strips currency/percent/comma formatting and returns a non-negative float, or None."""
    if not value:
        return None
    clean_val = re.sub(r"[^\d.\-]", "", value)
    try:
        rate = float(clean_val)
        return rate if rate >= 0 else None
    except (ValueError, TypeError):
        return None


def run_audit() -> AuditResult:
    """Runs the audit and returns an AuditResult. Never calls sys.exit — safe to
    import and call from other Python code. Raises AuditSchemaError on missing
    files, malformed JSON, or missing CSV columns; anomalies in otherwise-valid
    data are recorded on the returned AuditResult, not raised."""
    result = AuditResult()

    print("Loading datasets...")
    try:
        county_map = load_crosswalk()
        print(f"[OK] Loaded crosswalk for {len(county_map)} counties.")

        rates = load_rates()
        print(f"[OK] Loaded {len(rates)} rate records.")
    except AuditSchemaError:
        raise
    except Exception as e:
        raise AuditSchemaError(f"Data loading error: {e}") from e

    print("Running record verification and aggregation...")

    for record in rates:
        result.total_records += 1
        normalized_county = record.get("county", "").strip().lower()

        if normalized_county not in county_map:
            result.missing_counties += 1
            result.add_anomaly(record, "County not found in crosswalk")
            continue

        county_info = county_map[normalized_county]
        area_id = county_info["area"]

        fips = county_info.get("fips")
        if not fips or fips.upper() == "UNKNOWN":
            result.missing_fips += 1
            result.add_anomaly(record, "Missing or unresolved FIPS code")
            continue

        raw_rate = record.get("rate", "")
        parsed_rate = validate_and_parse_rate(raw_rate)
        if parsed_rate is None:
            result.invalid_rates += 1
            result.add_anomaly(record, f"Invalid or non-numeric rate value: '{raw_rate}'")
            continue

        # Optional per-record weight (e.g. enrolled member count). Defaults to 1.0
        # (unweighted / simple average) when absent or non-positive.
        weight = 1.0
        if "weight" in record:
            w = validate_and_parse_rate(record["weight"])
            if w is not None and w > 0:
                weight = w

        stats = result.area_stats[area_id]
        stats["total_weight"] += weight
        stats["sum_rate_weighted"] += parsed_rate * weight
        stats["record_count"] += 1
        result.valid_records += 1

    print("\n=== Audit Summary ===")
    print(f"Total Records Processed : {result.total_records}")
    print(f"Valid Records           : {result.valid_records}")
    print(f"Missing Counties        : {result.missing_counties}")
    print(f"Missing FIPS Codes      : {result.missing_fips}")
    print(f"Invalid Rate Values     : {result.invalid_rates}")

    if result.anomalies:
        print(f"\n[!] Identified {len(result.anomalies)} anomalies. Writing report...")
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(REPORT_FILE, "w", newline="", encoding="utf-8") as f:
            fieldnames = ["reason", "county", "rate", "age", "plan_type", "raw_record"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for anomaly in result.anomalies:
                writer.writerow(anomaly)
        print(f"[OK] Detailed anomaly log written to: {REPORT_FILE}")

    print("\nGenerating rating area aggregates...")
    AGGREGATE_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(AGGREGATE_REPORT_FILE, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["rating_area", "total_records", "total_weight", "weighted_avg_rate"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for area_id in sorted(result.area_stats.keys()):
            stats = result.area_stats[area_id]
            total_weight = stats["total_weight"]
            weighted_avg = (
                stats["sum_rate_weighted"] / total_weight if total_weight > 0 else 0.0
            )
            writer.writerow(
                {
                    "rating_area": area_id,
                    "total_records": stats["record_count"],
                    "total_weight": total_weight,
                    "weighted_avg_rate": f"{weighted_avg:.4f}",
                }
            )
    print(f"[OK] Aggregates written to: {AGGREGATE_REPORT_FILE}")
    print(f"    Areas processed: {len(result.area_stats)}")

    return result


def main():
    try:
        result = run_audit()
    except AuditSchemaError as e:
        print(f"\n[FAIL] Schema or file error: {e}")
        sys.exit(1)

    if result.valid_records < result.total_records:
        print("\n[WARNING] Audit completed with validation exceptions.")
        sys.exit(1)
    print("\n[PASSED] All records validated against crosswalk and rate constraints.")
    sys.exit(0)


if __name__ == "__main__":
    main()
