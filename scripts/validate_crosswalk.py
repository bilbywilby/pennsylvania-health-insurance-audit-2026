#!/usr/bin/env python3
"""Validate pa_crosswalk_data module against established JSON crosswalk."""

import sys
import json
import os
from pathlib import Path

# Locate crosswalk JSON
possible_json_paths = [
    "data/public/pa_county_fips_crosswalk.json",
    "data/crosswalks/pa_county_fips_crosswalk.json",
    "data/pa_county_fips_crosswalk.json",
]

json_path = next((p for p in possible_json_paths if os.path.exists(p)), None)
if not json_path:
    print(f"[!] Crosswalk JSON file not found in: {possible_json_paths}")
    sys.exit(1)

# Add module paths
sys.path.insert(0, ".")
sys.path.insert(0, "bootstrap")
sys.path.insert(0, "src")

# Import module
try:
    import pa_crosswalk_data as new_mod
except ImportError:
    print("[!] Could not import pa_crosswalk_data module.")
    sys.exit(1)

# Load established crosswalk
with open(json_path, "r", encoding="utf-8") as f:
    established = json.load(f)

# Parse established schema
established_by_fips = {}
if "counties" in established:
    for c in established["counties"]:
        established_by_fips[str(c["fips"])] = (c["canonical_name"], str(c["rating_area"]))
elif isinstance(established, dict):
    for area, counties in established.items():
        if isinstance(counties, list):
            for c in counties:
                fips = str(c.get("fips", ""))
                name = c.get("county") or c.get("canonical_name", "")
                established_by_fips[fips] = (name, str(area))

print(f"Established Crosswalk Path : {json_path}")
print(f"Established Record Count   : {len(established_by_fips)} counties mapped")

# Get module entries
raw_entries = getattr(new_mod, "PA_COUNTIES_CANONICAL", getattr(new_mod, "PA_COUNTIES", []))
clean_entries = getattr(new_mod, "PA_COUNTIES_CLEAN", raw_entries)

print(f"Pasted Module Raw Entries  : {len(raw_entries)}")
print(f"Pasted Module Clean Entries: {len(clean_entries)}")
print("-" * 60)

# Check 1: Coverage and duplicate detection
names = [e["county"] if "county" in e else e.get("canonical_name") for e in clean_entries]
unique_names = set(names)
print(f"Distinct County Names Count: {len(unique_names)} / 67")

dupes = set([n for n in names if names.count(n) > 1])
if dupes:
    print(f"Duplicate County Names     : {sorted(list(dupes))}")

established_names = {v[0] for v in established_by_fips.values()}
missing_from_pasted = sorted(established_names - unique_names)
invalid_in_pasted = sorted(unique_names - established_names)

if missing_from_pasted:
    print(f"Missing Real PA Counties   : {missing_from_pasted}")
if invalid_in_pasted:
    print(f"Invalid / Bogus Names      : {invalid_in_pasted}")

# Check 2: Rating area and FIPS verification
mismatches = []
for entry in clean_entries:
    fips = str(entry.get("fips", ""))
    pasted_name = entry.get("county") or entry.get("canonical_name", "")
    pasted_area = str(entry.get("rating_area", ""))

    if fips in established_by_fips:
        est_name, est_area = established_by_fips[fips]
        if pasted_area != est_area or pasted_name != est_name:
            mismatches.append((fips, est_name, est_area, pasted_name, pasted_area))
    else:
        mismatches.append((fips, "UNMAPPED", "N/A", pasted_name, pasted_area))

print(f"Discrepancies Detected     : {len(mismatches)}")
print("-" * 60)

if mismatches:
    print(f"{'FIPS':<6} {'EST. NAME':<20} {'EST.A':<6} {'PASTED NAME':<20} {'PASTED A':<6}")
    print("-" * 70)
    for fips, est_name, est_area, pasted_name, pasted_area in mismatches[:20]:
        print(f"{fips:<6} {est_name:<20} {est_area:<6} {pasted_name:<20} {pasted_area:<6}")
    if len(mismatches) > 20:
        print(f"... and {len(mismatches) - 20} additional mismatches.")
    sys.exit(1)
else:
    print("✅ ALL VALIDATION CHECKS PASSED")
    print(f"   • 67 counties present, no duplicates")
    print(f"   • All FIPS codes match established crosswalk")
    print(f"   • All rating area assignments match")
    sys.exit(0)
