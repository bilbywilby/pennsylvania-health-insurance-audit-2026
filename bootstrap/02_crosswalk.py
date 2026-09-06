#!/usr/bin/env python3
"""Generates data/public/pa_county_fips_crosswalk.json with strict validation."""
import json
import sys
from pathlib import Path
from typing import Dict, List

# Rating Areas (1-9) mapping to Counties (PA Insurance Department definitions)
RATING_AREAS = {
    1: ["Clarion", "Crawford", "Erie", "Forest", "McKean", "Mercer", "Venango", "Warren"],
    2: ["Cameron", "Elk", "Potter"],
    3: ["Bradford", "Carbon", "Clinton", "Lackawanna", "Luzerne", "Lycoming",
        "Monroe", "Pike", "Sullivan", "Susquehanna", "Tioga", "Wayne", "Wyoming"],
    4: ["Allegheny", "Armstrong", "Beaver", "Butler", "Fayette", "Greene",
        "Indiana", "Lawrence", "Washington", "Westmoreland"],
    5: ["Bedford", "Blair", "Cambria", "Clearfield", "Huntingdon", "Jefferson", "Somerset"],
    6: ["Centre", "Columbia", "Lehigh", "Mifflin", "Montour", "Northampton",
        "Northumberland", "Schuylkill", "Snyder", "Union"],
    7: ["Adams", "Berks", "Lancaster", "York"],
    8: ["Bucks", "Chester", "Delaware", "Montgomery", "Philadelphia"],
    9: ["Cumberland", "Dauphin", "Franklin", "Fulton", "Juniata", "Lebanon", "Perry"],
}

COUNTY_FIPS = {
    "Adams": "42001", "Allegheny": "42003", "Armstrong": "42005", "Beaver": "42007",
    "Bedford": "42009", "Berks": "42011", "Blair": "42013", "Bradford": "42015",
    "Bucks": "42017", "Butler": "42019", "Cambria": "42021", "Cameron": "42023",
    "Carbon": "42025", "Centre": "42027", "Chester": "42029", "Clarion": "42031",
    "Clearfield": "42033", "Clinton": "42035", "Columbia": "42037", "Crawford": "42039",
    "Cumberland": "42041", "Dauphin": "42043", "Delaware": "42045", "Elk": "42047",
    "Erie": "42049", "Fayette": "42051", "Forest": "42053", "Franklin": "42055",
    "Fulton": "42057", "Greene": "42059", "Huntingdon": "42061", "Indiana": "42063",
    "Jefferson": "42065", "Juniata": "42067", "Lackawanna": "42069", "Lancaster": "42071",
    "Lawrence": "42073", "Lebanon": "42075", "Lehigh": "42077", "Luzerne": "42079",
    "Lycoming": "42081", "McKean": "42083", "Mercer": "42085", "Mifflin": "42087",
    "Monroe": "42089", "Montgomery": "42091", "Montour": "42093", "Northampton": "42095",
    "Northumberland": "42097", "Perry": "42099", "Philadelphia": "42101", "Pike": "42103",
    "Potter": "42105", "Schuylkill": "42107", "Snyder": "42109", "Somerset": "42111",
    "Sullivan": "42113", "Susquehanna": "42115", "Tioga": "42117", "Union": "42119",
    "Venango": "42121", "Warren": "42123", "Washington": "42125", "Wayne": "42127",
    "Westmoreland": "42129", "Wyoming": "42131", "York": "42133",
}

TOTAL_PA_COUNTIES = 67


def validate_data() -> bool:
    """Validates uniqueness, FIPS presence, and full PA county coverage."""
    errors = []
    seen_counties: Dict[str, int] = {}

    for area_id, counties in RATING_AREAS.items():
        for county in counties:
            if county not in COUNTY_FIPS:
                errors.append(f"Area {area_id}: '{county}' missing from FIPS reference table.")
            if county in seen_counties:
                errors.append(
                    f"Duplicate mapping: '{county}' found in Area {seen_counties[county]} "
                    f"and Area {area_id}."
                )
            else:
                seen_counties[county] = area_id

    mapped_count = len(seen_counties)
    if mapped_count != TOTAL_PA_COUNTIES:
        missing = sorted(set(COUNTY_FIPS) - set(seen_counties))
        errors.append(
            f"Incomplete PA coverage: mapped {mapped_count} of {TOTAL_PA_COUNTIES} counties. "
            f"Unmapped: {missing}"
        )

    if errors:
        print("[ERROR] Data validation failed:")
        for err in errors:
            print(f"  - {err}")
        return False
    return True


def build_crosswalk() -> Dict[str, List[Dict[str, str]]]:
    crosswalk = {}
    for area_id, counties in RATING_AREAS.items():
        crosswalk[str(area_id)] = [
            {"county": c, "fips": COUNTY_FIPS[c]} for c in sorted(counties)
        ]
    return crosswalk


def main() -> None:
    output_dir = Path("data/public")
    output_file = output_dir / "pa_county_fips_crosswalk.json"
    temp_file = output_dir / ".pa_county_fips_crosswalk.json.tmp"

    print("Validating rating area definitions...")
    if not validate_data():
        print("[FAIL] Aborting execution due to schema errors.")
        sys.exit(1)

    print("Building crosswalk payload...")
    payload = build_crosswalk()

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
        temp_file.rename(output_file)  # POSIX atomic replace
        print(f"[OK] {output_file} written successfully.")
    except Exception as exc:
        print(f"[ERROR] Atomic write failure: {exc}")
        if temp_file.exists():
            temp_file.unlink()
        sys.exit(1)


if __name__ == "__main__":
    main()
