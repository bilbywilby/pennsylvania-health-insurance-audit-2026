#!/usr/bin/env python3
"""
Ingests carrier-level rate filings and county termination datasets.
- Cross-references county/FIPS telemetry against the PA county crosswalk.
- Cross-references carrier-declared rating areas against the crosswalk's
  actual set of rating areas (catches typo'd or out-of-range area IDs).
- Aggregates carrier rate changes weighted by member count / covered lives.
- Aggregates county-level termination and disenrollment totals by rating area.
- Exports structured anomaly logs and aggregate reports.

NOTE: REQUIRED_CARRIER_COLS / REQUIRED_TERMINATION_COLS below are best-guess
column names. Point CARRIER_RATES_FILE / COUNTY_TERMINATIONS_FILE at your real
extracts and update those two lists to match your actual headers before
relying on this in production — it has only been exercised against synthetic
fixtures, not real PID/carrier filings.
"""
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional

class CarrierIngestionError(Exception):
    """Base exception for carrier ingestion pipeline."""

class CarrierSchemaError(CarrierIngestionError):
    """Raised when CSV schemas or required headers are missing/malformed."""

# --- Configuration Paths ---
DATA_DIR = Path("data")
CROSSWALK_FILE = DATA_DIR / "public" / "pa_county_fips_crosswalk.json"
CARRIER_RATES_FILE = DATA_DIR / "carrier-rate-changes.csv"
COUNTY_TERMINATIONS_FILE = DATA_DIR / "county-termination-rates.csv"

CARRIER_ANOMALY_FILE = DATA_DIR / "private" / "carrier_anomalies_2026.csv"
CARRIER_AGGREGATE_FILE = DATA_DIR / "private" / "carrier_aggregates_2026.csv"
TERMINATION_AGGREGATE_FILE = DATA_DIR / "private" / "county_termination_aggregates_2026.csv"

# Best-guess schema — verify against real files (see module docstring).
REQUIRED_CARRIER_COLS = ["carrier_name", "approved_rate_change", "rating_area"]
OPTIONAL_WEIGHT_COLS = ["covered_lives", "member_count", "enrolled_count", "weight"]
REQUIRED_TERMINATION_COLS = ["county", "termination_count"]

def load_crosswalk() -> Dict[str, Dict[str, str]]:
    """Loads crosswalk JSON into a case-insensitive lookup keyed by lowercase county name."""
    if not CROSSWALK_FILE.exists():
        raise CarrierSchemaError(f"Crosswalk file not found: {CROSSWALK_FILE}")

    with open(CROSSWALK_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise CarrierSchemaError(f"Crosswalk file is not valid JSON: {e}") from e

    county_map = {}
    for area_id, counties in data.items():
        for item in counties:
            key = item["county"].strip().lower()
            county_map[key] = {
                "display_name": item["county"].strip(),
                "fips": item["fips"],
                "area": str(area_id),
            }
    return county_map

def sanitize_numeric(value: str) -> Optional[float]:
    """Strips currency, percent, and comma formatting; returns float or None.
    Negative values are preserved (a carrier rate *decrease* is legitimate)."""
    if not value:
        return None
    clean_val = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return float(clean_val)
    except (ValueError, TypeError):
        return None

def ingest_carrier_rates(county_map: Dict[str, Dict]) -> Dict:
    """Ingests carrier rate filings, weights rate changes, and outputs aggregates.
    Rating areas are validated against the crosswalk's actual area set — a
    carrier row declaring an area that doesn't exist in the crosswalk (typo,
    out-of-range PA area, wrong state's filing) is flagged, not silently kept."""
    if not CARRIER_RATES_FILE.exists():
        raise CarrierSchemaError(f"Carrier rates file missing: {CARRIER_RATES_FILE}")

    valid_areas = {info["area"] for info in county_map.values()}

    anomalies = []
    # rating_area -> carrier_name -> accumulators
    area_carrier_stats = defaultdict(
        lambda: defaultdict(lambda: {"weighted_rate_sum": 0.0, "total_weight": 0.0, "records": 0})
    )

    with open(CARRIER_RATES_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise CarrierSchemaError("Carrier rates CSV is empty or missing headers.")

        headers = [h.strip().lower() for h in reader.fieldnames]
        missing = set(REQUIRED_CARRIER_COLS) - set(headers)
        if missing:
            raise CarrierSchemaError(f"Carrier rates missing required columns: {missing}")

        weight_col = next((col for col in OPTIONAL_WEIGHT_COLS if col in headers), None)

        for row in reader:
            normalized = {
                k.strip().lower(): (v or "").strip() for k, v in row.items() if k is not None
            }
            carrier = normalized.get("carrier_name", "")
            area_key = normalized.get("rating_area", "").strip()
            raw_change = normalized.get("approved_rate_change", "")

            if area_key not in valid_areas:
                anomalies.append(
                    {
                        "source": "carrier_rates",
                        "reason": f"Rating area '{area_key}' not found in crosswalk",
                        "raw_record": json.dumps(normalized),
                    }
                )
                continue

            rate_change = sanitize_numeric(raw_change)
            if rate_change is None:
                anomalies.append(
                    {
                        "source": "carrier_rates",
                        "reason": f"Invalid rate change value: '{raw_change}'",
                        "raw_record": json.dumps(normalized),
                    }
                )
                continue

            weight = 1.0
            if weight_col and normalized.get(weight_col):
                parsed_w = sanitize_numeric(normalized[weight_col])
                if parsed_w is not None and parsed_w > 0:
                    weight = parsed_w

            stats = area_carrier_stats[area_key][carrier]
            stats["weighted_rate_sum"] += rate_change * weight
            stats["total_weight"] += weight
            stats["records"] += 1

    return {"stats": area_carrier_stats, "anomalies": anomalies}

def ingest_county_terminations(county_map: Dict[str, Dict]) -> Dict:
    """Ingests county termination counts and aggregates total terminations by rating area."""
    if not COUNTY_TERMINATIONS_FILE.exists():
        raise CarrierSchemaError(f"County terminations file missing: {COUNTY_TERMINATIONS_FILE}")

    anomalies = []
    area_term_stats = defaultdict(
        lambda: {"total_terminations": 0, "total_enrollees": 0, "counties": 0}
    )

    with open(COUNTY_TERMINATIONS_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise CarrierSchemaError("County terminations CSV is empty or missing headers.")

        headers = [h.strip().lower() for h in reader.fieldnames]
        missing = set(REQUIRED_TERMINATION_COLS) - set(headers)
        if missing:
            raise CarrierSchemaError(f"County terminations missing required columns: {missing}")

        for row in reader:
            normalized = {
                k.strip().lower(): (v or "").strip() for k, v in row.items() if k is not None
            }
            raw_county = normalized.get("county", "")
            lookup_key = raw_county.lower()

            if lookup_key not in county_map:
                anomalies.append(
                    {
                        "source": "county_terminations",
                        "reason": f"County not found in crosswalk: '{raw_county}'",
                        "raw_record": json.dumps(normalized),
                    }
                )
                continue

            area_id = county_map[lookup_key]["area"]

            terms = sanitize_numeric(normalized.get("termination_count", ""))
            if terms is None or terms < 0:
                anomalies.append(
                    {
                        "source": "county_terminations",
                        "reason": f"Invalid termination count: '{normalized.get('termination_count')}'",
                        "raw_record": json.dumps(normalized),
                    }
                )
                continue

            enrollees = sanitize_numeric(normalized.get("total_enrollees", "0")) or 0.0
            if enrollees < 0:
                enrollees = 0.0

            stats = area_term_stats[area_id]
            stats["total_terminations"] += int(terms)
            stats["total_enrollees"] += int(enrollees)
            stats["counties"] += 1

    return {"stats": area_term_stats, "anomalies": anomalies}

def run_carrier_ingestion() -> Dict:
    """Runs the full ingestion pipeline. Raises CarrierSchemaError on missing
    files or bad headers; never calls sys.exit — safe to import and call."""
    county_map = load_crosswalk()

    carrier_res = ingest_carrier_rates(county_map)
    term_res = ingest_county_terminations(county_map)

    all_anomalies = carrier_res["anomalies"] + term_res["anomalies"]

    if all_anomalies:
        CARRIER_ANOMALY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CARRIER_ANOMALY_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["source", "reason", "raw_record"])
            writer.writeheader()
            for anomaly in all_anomalies:
                writer.writerow(anomaly)

    CARRIER_AGGREGATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CARRIER_AGGREGATE_FILE, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["rating_area", "carrier_name", "records", "total_weight", "weighted_avg_rate_change"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        carrier_stats = carrier_res["stats"]
        for area_id in sorted(carrier_stats.keys()):
            for carrier in sorted(carrier_stats[area_id].keys()):
                st = carrier_stats[area_id][carrier]
                w_avg = st["weighted_rate_sum"] / st["total_weight"] if st["total_weight"] > 0 else 0.0
                writer.writerow(
                    {
                        "rating_area": area_id,
                        "carrier_name": carrier,
                        "records": st["records"],
                        "total_weight": f"{st['total_weight']:.2f}",
                        "weighted_avg_rate_change": f"{w_avg:.4f}",
                    }
                )

    TERMINATION_AGGREGATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TERMINATION_AGGREGATE_FILE, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["rating_area", "counties_reporting", "total_terminations", "total_enrollees", "termination_rate_pct"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        term_stats = term_res["stats"]
        for area_id in sorted(term_stats.keys()):
            st = term_stats[area_id]
            t_rate = (
                st["total_terminations"] / st["total_enrollees"] * 100.0
                if st["total_enrollees"] > 0
                else 0.0
            )
            writer.writerow(
                {
                    "rating_area": area_id,
                    "counties_reporting": st["counties"],
                    "total_terminations": st["total_terminations"],
                    "total_enrollees": st["total_enrollees"],
                    "termination_rate_pct": f"{t_rate:.2f}%",
                }
            )

    return {
        "anomalies_count": len(all_anomalies),
        "carrier_areas": len(carrier_res["stats"]),
        "termination_areas": len(term_res["stats"]),
    }

def main():
    try:
        summary = run_carrier_ingestion()
    except CarrierSchemaError as e:
        print(f"\n[FAIL] Schema or file error: {e}")
        sys.exit(1)

    print("\n=== Carrier Extensions Ingestion Summary ===")
    print(f"Carrier Rating Areas Processed    : {summary['carrier_areas']}")
    print(f"Termination Rating Areas Processed: {summary['termination_areas']}")
    print(f"Total Anomalies Logged            : {summary['anomalies_count']}")

    if summary["anomalies_count"] > 0:
        print(f"\n[WARNING] Ingestion completed with anomalies logged to {CARRIER_ANOMALY_FILE}")
        sys.exit(1)
    print("\n[PASSED] All carrier filings and termination telemetry ingested cleanly.")
    sys.exit(0)

if __name__ == "__main__":
    main()
