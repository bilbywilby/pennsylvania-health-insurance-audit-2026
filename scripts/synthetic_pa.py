"""
Synthetic Pennsylvania: a fake-but-valid universe with ground-truth answers.

Generates a deterministic 67-county / 9-area crosswalk and synthetic filings
whose weighted exposures are known analytically. The pipeline must reproduce
the construction numbers exactly — any drift is a regression.

Pure stdlib. Deterministic under seed.
"""
import random
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Tuple

AREA_COUNTS = {1: 8, 2: 3, 3: 13, 4: 10, 5: 7, 6: 10, 7: 4, 8: 5, 9: 7}
N_AREAS = 9
N_COUNTIES = 67  # invariant: sum(AREA_COUNTS.values()) == 67
assert sum(AREA_COUNTS.values()) == N_COUNTIES

# Synthetic carriers: footprint, rate per area, lives per area.
# Lives are multiples of 100 so weighted means are exact in Fraction arithmetic.
CARRIERS: List[Dict[str, Any]] = [
    {"carrier": "SYN-A", "areas": list(range(1, 10)),
     "rates": {a: 20.0 + a for a in range(1, 10)},
     "lives": {a: 500.0 for a in range(1, 10)}},
    {"carrier": "SYN-B", "areas": [1, 2, 3, 4, 5],
     "rates": {a: 30.0 for a in [1, 2, 3, 4, 5]},
     "lives": {a: 200.0 for a in [1, 2, 3, 4, 5]}},
    {"carrier": "SYN-G", "areas": [6, 7, 8, 9],
     "rates": {a: -5.0 for a in [6, 7, 8, 9]},
     "lives": {a: 300.0 for a in [6, 7, 8, 9]}},
    {"carrier": "SYN-D", "areas": [2, 4],
     "rates": {a: 40.0 for a in [2, 4]},
     "lives": {a: 100.0 for a in [2, 4]}},
]

def synthetic_filings() -> List[Dict[str, Any]]:
    """Flatten CARRIERS into one filing record per (carrier, area)."""
    out: List[Dict[str, Any]] = []
    for c in CARRIERS:
        for area in c["areas"]:
            out.append({
                "carrier": c["carrier"],
                "serff_id": f"SYN%-{abs(hash((c['carrier'], area))) % 10**9:09d}",
                "rate_change": c["rates"][area],
                "rating_area": area,
                "lives_by_area": {area: c["lives"][area]},
                "covered_lives": c["lives"][area],
                "verified": True,
            })
    return out

def ground_truth_exposure() -> Dict[int, Fraction]:
    """Closed-form covered-lives weighted rate change per area (exact Fractions)."""
    truth: Dict[int, Fraction] = {}
    for area in range(1, 10):
        num = den = Fraction(0)
        for c in CARRIERS:
            if area in c["areas"]:
                num += Fraction(str(c["rates"][area])) * Fraction(str(c["lives"][area]))
                den += Fraction(str(c["lives"][area]))
        truth[area] = num / den
    return truth

def synthetic_crosswalk(seed: int = 42) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Deterministic fake PA: 67 counties, FIPS 900xx (never collides with real '42xxx')."""
    rng = random.Random(seed)
    fips_pool = [f"90{i:03d}" for i in range(1, 68)]
    rng.shuffle(fips_pool)
    entries, fips_to_area = [], {}
    idx = 0
    for area, count in AREA_COUNTS.items():
        for _ in range(count):
            fips = fips_pool[idx]; idx += 1
            entries.append({"fips": fips, "name": f"SynCounty-{fips}", "rating_area": area})
            fips_to_area[fips] = area
    return entries, fips_to_area
