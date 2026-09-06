"""
Schema Reconciliation: carrier x rating-area filings -> county-level audit engine.
Jurisdiction: Commonwealth of Pennsylvania (Rating Areas 1-9, 67 Counties).
"""
import csv
import json
import logging
import re
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SERFF_REGEX = re.compile(r"^[A-Z]{4}-\d{9}$")

class ReconciliationError(Exception):
    """Structural failure in crosswalk data."""

class FilingValidationError(ReconciliationError):
    """Structural failure in carrier filing data."""

CROSSWALK_PATH = Path(__file__).resolve().parent.parent / "data" / "public" / "pa_county_fips_crosswalk.json"
EXPOSURE_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "private" / "county_rate_exposure.csv"
EXPECTED_COUNTIES = 67
VALID_RATING_AREAS = set(range(1, 10))

COLUMN_ALIASES = {"carrier_name": "carrier", "approved_rate_change": "rate_change"}

CARRIER_RATE_FILINGS: List[Dict[str, Any]] = [
    # placeholder watermarked shares — replace with real covered_lives on PID extract
    {"carrier": "Ambetter (Centene)", "serff_id": "CECO-134506033", "rate_change": 37.8, "share": 0.06, "rating_areas": list(range(1, 10)), "verified": False},
    {"carrier": "UPMC Health Plan Inc.", "serff_id": "UPMC-134504084", "rate_change": 24.78, "share": 0.18, "rating_areas": [1, 4, 5], "verified": True},
    {"carrier": "UPMC Health Options Inc.", "serff_id": "UPMC-134504074", "rate_change": 20.18, "share": 0.06, "rating_areas": [1, 2, 3, 4, 5, 6, 7, 9], "verified": True},
    {"carrier": "Capital Advantage Assurance", "serff_id": "CABC-134505011", "rate_change": 24.56, "share": 0.08, "rating_areas": [6, 7, 9], "verified": False},
    {"carrier": "Keystone Health Plan Central", "serff_id": "INAC-134505999", "rate_change": 22.40, "share": 0.05, "rating_areas": [6, 7, 9], "verified": False},
    {"carrier": "Keystone Health Plan East", "serff_id": "INAC-134505843", "rate_change": 22.04, "share": 0.14, "rating_areas": [8], "verified": True},
    {"carrier": "Highmark Benefits Group", "serff_id": "HGHM-134397666", "rate_change": 18.37, "share": 0.07, "rating_areas": [3, 8], "verified": True},
    {"carrier": "Highmark Inc.", "serff_id": "HGHM-134504750", "rate_change": 17.75, "share": 0.24, "rating_areas": [1, 2, 4, 5, 6, 7, 9], "verified": True},
    {"carrier": "Geisinger Health Plan", "serff_id": "GSHP-134496810", "rate_change": 11.59, "share": 0.09, "rating_areas": [2, 3, 5, 6, 7, 9], "verified": False},
    {"carrier": "Oscar Health Plan of PA", "serff_id": "OHIN-134536199", "rate_change": 23.12, "share": 0.02, "rating_areas": [3, 6, 7, 8], "verified": True},
    {"carrier": "QCC Insurance Company", "serff_id": "INAC-134505902", "rate_change": 15.18, "share": 0.05, "rating_areas": [8], "verified": True},
    {"carrier": "Partners Insurance Co.", "serff_id": "PICI-134521223", "rate_change": -10.12, "share": 0.04, "rating_areas": [3, 6, 8], "verified": True},
]

PA_RATING_AREA_COUNTY_MAP: Dict[int, List[Dict[str, str]]] = {
    1: [{"fips": "42031", "name": "Clarion"}, {"fips": "42039", "name": "Crawford"}, {"fips": "42049", "name": "Erie"}, {"fips": "42053", "name": "Forest"}, {"fips": "42083", "name": "McKean"}, {"fips": "42085", "name": "Mercer"}, {"fips": "42121", "name": "Venango"}, {"fips": "42123", "name": "Warren"}],
    2: [{"fips": "42023", "name": "Cameron"}, {"fips": "42047", "name": "Elk"}, {"fips": "42105", "name": "Potter"}],
    3: [{"fips": "42015", "name": "Bradford"}, {"fips": "42025", "name": "Carbon"}, {"fips": "42035", "name": "Clinton"}, {"fips": "42069", "name": "Lackawanna"}, {"fips": "42079", "name": "Luzerne"}, {"fips": "42081", "name": "Lycoming"}, {"fips": "42089", "name": "Monroe"}, {"fips": "42103", "name": "Pike"}, {"fips": "42113", "name": "Sullivan"}, {"fips": "42115", "name": "Susquehanna"}, {"fips": "42117", "name": "Tioga"}, {"fips": "42127", "name": "Wayne"}, {"fips": "42131", "name": "Wyoming"}],
    4: [{"fips": "42003", "name": "Allegheny"}, {"fips": "42005", "name": "Armstrong"}, {"fips": "42007", "name": "Beaver"}, {"fips": "42019", "name": "Butler"}, {"fips": "42051", "name": "Fayette"}, {"fips": "42059", "name": "Greene"}, {"fips": "42063", "name": "Indiana"}, {"fips": "42073", "name": "Lawrence"}, {"fips": "42125", "name": "Washington"}, {"fips": "42129", "name": "Westmoreland"}],
    5: [{"fips": "42009", "name": "Bedford"}, {"fips": "42013", "name": "Blair"}, {"fips": "42021", "name": "Cambria"}, {"fips": "42033", "name": "Clearfield"}, {"fips": "42061", "name": "Huntingdon"}, {"fips": "42065", "name": "Jefferson"}, {"fips": "42111", "name": "Somerset"}],
    6: [{"fips": "42027", "name": "Centre"}, {"fips": "42037", "name": "Columbia"}, {"fips": "42077", "name": "Lehigh"}, {"fips": "42087", "name": "Mifflin"}, {"fips": "42093", "name": "Montour"}, {"fips": "42095", "name": "Northampton"}, {"fips": "42097", "name": "Northumberland"}, {"fips": "42107", "name": "Schuylkill"}, {"fips": "42109", "name": "Snyder"}, {"fips": "42119", "name": "Union"}],
    7: [{"fips": "42001", "name": "Adams"}, {"fips": "42011", "name": "Berks"}, {"fips": "42071", "name": "Lancaster"}, {"fips": "42133", "name": "York"}],
    8: [{"fips": "42017", "name": "Bucks"}, {"fips": "42029", "name": "Chester"}, {"fips": "42045", "name": "Delaware"}, {"fips": "42091", "name": "Montgomery"}, {"fips": "42101", "name": "Philadelphia"}],
    9: [{"fips": "42041", "name": "Cumberland"}, {"fips": "42043", "name": "Dauphin"}, {"fips": "42055", "name": "Franklin"}, {"fips": "42057", "name": "Fulton"}, {"fips": "42067", "name": "Juniata"}, {"fips": "42075", "name": "Lebanon"}, {"fips": "42099", "name": "Perry"}],
}

def normalize_crosswalk(raw: Any) -> List[Dict[str, Any]]:
    """Normalize crosswalk shapes A/B/C into canonical county entries."""
    if isinstance(raw, dict) and "counties" in raw:
        return raw["counties"]
    if isinstance(raw, dict):
        entries: List[Dict[str, Any]] = []
        for area_key, counties in raw.items():
            try:
                area_id = int(area_key)
            except (TypeError, ValueError):
                raise ReconciliationError(f"Non-numeric rating area key in crosswalk: {area_key!r}")
            if not isinstance(counties, list):
                raise ReconciliationError(f"Expected list for area key {area_key!r}, got {type(counties).__name__}")
            for c in counties:
                if not isinstance(c, dict):
                    raise ReconciliationError(f"Malformed county entry: {c!r}")
                name = c.get("name") or c.get("county")
                if not name or "fips" not in c:
                    raise ReconciliationError(f"Malformed county entry: {c!r}")
                entries.append({"fips": c["fips"], "name": name, "rating_area": area_id})
        return entries
    if isinstance(raw, list):
        return raw
    raise ReconciliationError(f"Unrecognized crosswalk structure: {type(raw).__name__}")

def load_crosswalk(path: Path = CROSSWALK_PATH) -> Dict[str, Dict[str, Any]]:
    """Load and validate the county/FIPS/rating-area crosswalk (all known shapes)."""
    if path.exists():
        entries = normalize_crosswalk(json.loads(path.read_text()))
    else:
        logger.warning("Crosswalk file not found at %s. Falling back to internal map.", path)
        entries = [
            {"fips": c["fips"], "name": c["name"], "rating_area": area}
            for area, counties in PA_RATING_AREA_COUNTY_MAP.items()
            for c in counties
        ]
    fips_to_area: Dict[str, Dict[str, Any]] = {}
    seen: set = set()
    for entry in entries:
        fips = str(entry["fips"]).zfill(5)
        if fips in seen:
            raise ReconciliationError(f"Duplicate FIPS in crosswalk: {fips}")
        if not fips.startswith("42"):
            raise ReconciliationError(f"Non-PA FIPS in crosswalk: {fips}")
        seen.add(fips)
        fips_to_area[fips] = {
            "county_name": entry["name"], "rating_area": int(entry["rating_area"]),
            "carriers": [], "weighted_rate_increase": 0.0,
        }
    if len(fips_to_area) != EXPECTED_COUNTIES:
        raise ReconciliationError(f"Crosswalk has {len(fips_to_area)} counties, expected {EXPECTED_COUNTIES}")
    return fips_to_area

def validate_filings(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate filings: required keys, SERFF format, collisions and duplicates raise."""
    if not isinstance(entries, list):
        raise FilingValidationError(f"Filings input must be a list, received {type(entries).__name__}")
    seen_serff: Dict[str, str] = {}
    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(entries):
        if not isinstance(item, dict):
            raise FilingValidationError(f"Item at index {idx} is not a dictionary: {item!r}")
        carrier = str(item.get("carrier") or "").strip()
        serff_id = str(item.get("serff_id") or "").strip()
        if not carrier or not serff_id:
            raise FilingValidationError(f"Filing at index {idx} missing 'carrier'/'serff_id': {item!r}")
        if not SERFF_REGEX.match(serff_id):
            raise FilingValidationError(f"Malformed SERFF ID '{serff_id}' for '{carrier}'.")
        if serff_id in seen:
            if seen[serff_id] != carrier:
                raise FilingValidationError(f"SERFF ID collision: '{serff_id}' assigned to both '{seen[serff_id]}' and '{carrier}'.")
            raise FilingValidationError(f"Duplicate filing for ('{carrier}', '{serff_id}') at index {idx}.")
        seen[serff_id] = carrier
        clean = dict(item)
        clean["carrier"], clean["serff_id"] = carrier, serff_id
        ras = clean.get("rating_areas", [])
        if isinstance(ras, (list, tuple, set)):
            clean["rating_areas"] = sorted(int(r) for r in ras)
        normalized.append(clean)
    return normalized

def _canonicalize(row: Dict[str, str]) -> Dict[str, str]:
    out = dict(row)
    for legacy, canon in COLUMN_ALIASES.items():
        if legacy in row and canon not in row:
            out[canon] = row[legacy]
            logger.info("Normalized legacy column '%s' -> '%s'", legacy, canon)
    return out

def load_filings_from_csv(csv_path) -> List[Dict[str, Any]]:
    """Load carrier filings from CSV; group rows by serff_id with per-area accumulators."""
    if not csv_path.exists():
        logger.warning("Filings CSV not found at '%s'.", csv_path)
        return []
    filings_map: Dict[str, Dict[str, Any]] = {}
    with Path(csv_path).open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row = _canonicalize(row)
            carrier = (row.get("carrier") or "").strip()
            serff_id = (row.get("serff_id") or "").strip()
            if not carrier:
                raise FilingValidationError(f"Row missing 'carrier': {row!r}")
            if not serff_id:
                serff_id = "SYNT-%09d" % (zlib.crc32(carrier.encode("utf-8")) % 10**9)
                logger.info("Synthesized SERFF ID %s for legacy row (carrier '%s')", serff_id, carrier)
            try:
                rate_change = float(str(row.get("rate_change", "")).replace("%", "").replace(",", ""))
                rating_area = int(float(row.get("rating_area", "")))
                covered = float(str(row.get("covered_lives", "0")).replace(",", "") or 0.0)
            except ValueError as exc:
                raise FilingValidationError(f"Unparseable numeric in filings CSV row: {row!r}") from exc
            verified = str(row.get("verified", "false")).strip().lower() in ("true", "1", "yes")
            rec = filings_map.setdefault(serff_id, {
                "carrier": carrier, "serff_id": serff_id, "rate_change": rate_change,
                "rating_areas": [], "rate_by_area": {}, "lives_by_area": {}, "verified": verified,
            })
            if rating_area not in rec["rating_areas"]:
                rec["rating_areas"].append(rating_area)
            rec["rate_by_area"][rating_area] = rate_change
            rec["lives_by_area"][rating_area] = covered
            if not verified:
                rec["verified"] = False
    return validate_filings(list(filings_map.values()))

def compute_rating_area_exposure(filings: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Covered-lives weighted rate change per rating area; unweighted fallback logged."""
    exposure: Dict[int, Dict[str, Any]] = {}
    for area in range(1, 10):
        covering = [f for f in filings if area in f.get("rating_areas", [])]
        if not covering:
            exposure[area] = {"weighted_rate_change": None, "basis": "no_active_carrier", "verified": False}
            continue
        rows = [(f.get("rate_change", 0.0), f.get("lives_by_area", {}).get(area, 0.0)) for f in covering]
        total_lives = sum(l for _, l in rows)
        if total_lives > 0:
            weighted, basis = sum(r * l for r, l in rows) / total_lives, "covered_lives"
        else:
            logger.warning("No covered-lives data for RA %d — unweighted fallback.", area)
            weighted, basis = sum(r for r, _ in rows) / len(covering), "unweighted_fallback"
        exposure[area] = {
            "weighted_rate_change": round(weighted, 2), "carrier_count": len(covering),
            "total_covered_lives": int(total_lives), "basis": basis,
            "verified": all(f.get("verified", False) for f in covering),
        }
    return exposure

def build_county_rate_matrix(filings: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """County x carrier matrix with market-share weighted exposure per county."""
    fips_to_area = load_crosswalk()
    for filing in filings or CARRIER_RATE_FILINGS:
        bad = set(filing["rating_areas"]) - VALID_RATING_AREAS
        if bad:
            raise ReconciliationError(f"{filing['carrier']}: invalid rating areas {sorted(bad)}")
        for area in filing["rating_areas"]:
            for data in fips_to_area.values():
                if data["rating_area"] == area:
                    data["carriers"].append({"carrier": filing["carrier"], "approved_rate_change": filing["rate_change"], "market_share": filing["share"]})
    for data in fips_to_area.values():
        if data["carriers"]:
            total = sum(c["market_share"] for c in data["carriers"])
            if total <= 0:
                raise ReconciliationError(f"Zero or negative total market share in county {data['county_name']}")
            data["weighted_rate_increase"] = round(sum(c["approved_rate_change"] * c["market_share"] for c in data["carriers"]) / total, 2)
        else:
            data["weighted_rate_increase"] = None
    return fips_to_area

def write_county_exposure(out_path: Path = EXPOSURE_OUTPUT_PATH) -> Path:
    """Export county rate exposure CSV for bootstrap/04_audit.py."""
    matrix = build_county_rate_matrix()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fips", "county_name", "rating_area", "carrier_count", "weighted_rate_increase"])
        for fips in sorted(matrix):
            r = matrix[fips]
            w.writerow([fips, r["county_name"], r["rating_area"], len(r["carriers"]), r["weighted_rate_increase"] if r["weighted_rate_increase"] is not None else ""])
    logger.info("Wrote exposure for %d counties to %s", len(matrix), out_path)
    return out_path

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    write_county_exposure()
