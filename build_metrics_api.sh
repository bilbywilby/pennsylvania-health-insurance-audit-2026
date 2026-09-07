#!/usr/bin/env bash
set -uo pipefail
cd /home/droid/pennsylvania-health-insurance-audit-2026

git add -A
git commit -q -m "chore: pre-metrics-api checkpoint" --allow-empty
CHECKPOINT=$(git rev-parse HEAD)
rollback() { echo "!!! FAILED — rolling back"; git reset --hard "$CHECKPOINT"; }
trap rollback ERR

mkdir -p data/public

cat > data/public/key_statistics_2026.json << 'JSON'
{
  "_meta": {
    "source_document": "Pennsylvania_Health_Insurance_August_2026_Status_Report.pdf",
    "note": "Canonical production data for /metrics/summary. Cross-checked by tests/fixtures/key_statistics_golden.json — do not edit either file without updating the other and the citation."
  },
  "metrics": {
    "peak_enrollment_2025": {"value": 497000, "citation": "PHIEA (2026a); corroborated by Pennie, 'Pennsylvanians dropping health coverage...', Jun 9 2026, agency.pennie.com"},
    "enrollment_july_1_2026": {"value": 431270, "citation": "PHIEA (2026a)"},
    "cumulative_coverage_lost_since_oe2026_start": {"value": 177000, "citation": "PHIEA (2026a)"},
    "post_oe_cancellations_feb_to_jul_2026": {"value": 94000, "citation": "PHIEA (2026a)"},
    "avg_net_premium_increase_retained_enrollees_pct": {"value": 102, "citation": "PHIEA (2026a); corroborated by Pennie 'One in Five...' release, agency.pennie.com"},
    "statewide_approved_gross_rate_increase_pct": {"value": 21.5, "citation": "PID (2026a); corroborated by coveredusa.org PA ACA marketplace overview"},
    "requested_increases_denied_by_pid_usd": {"value": 50100000, "citation": "PID (2026a); corroborated by coveredusa.org PA ACA marketplace overview"},
    "federal_eptc_value_lost_annual_usd": {"value": 600000000, "citation": "PHIEA (2026a); corroborated by pennie.com/affordability/ and forhealthinsurance.com"},
    "act54_appropriated_usd": {"value": 0, "citation": "ForHealthInsurance.com (2026); corroborated by pennie.com/affordability/ ('requires funding')"}
  },
  "act54_pennie_published_50m_impact": {
    "restored_enrollees": 44000,
    "premium_reduction_low_pct": 9.0,
    "premium_reduction_high_pct": 12.0,
    "enrollees_with_reduced_costs": 280000,
    "appropriated_as_of_may_2026_usd": 0,
    "ep_tc_lost_annual_usd": 600000000,
    "citation": "Pennie (2026), pennie.com/affordability/. NOTE: restored_enrollees=44000 is a DERIVED estimate (~1/4 of cumulative_coverage_lost_since_oe2026_start=177000); Pennie's page states 'nearly one-fourth' without a precise headcount. premium_reduction_pct (9-12%) and enrollees_with_reduced_costs (280000) are exact published figures."
  },
  "roi_note": "For every $1 invested via Act 54, an estimated $12 in expired federal EPTC value would be substituted at 1/12 the cost (per pennie.com/affordability/: $50M state investment vs $600M lost federal EPTC).",
  "provenance": "PID/PHIEA verified aggregate figures; Act 54 impact figures verified via pennie.com/affordability/ web fetch, Sep 6 2026."
}
JSON

cat > src/api/main.py << 'PY'
"""FastAPI app serving verified PA ACA marketplace key statistics.

All figures in /metrics/summary are loaded from data/public/key_statistics_2026.json
— a cited, version-controlled data file. This module contains no hardcoded
statistics; changing a number here means changing that file (with a citation).
"""
import json
from pathlib import Path
from fastapi import FastAPI

DATA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "public" / "key_statistics_2026.json"
)

app = FastAPI(title="PA ACA Marketplace Key Statistics API")


def _load_stats() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


@app.get("/metrics/summary")
def metrics_summary():
    data = _load_stats()
    out = {k: v["value"] for k, v in data["metrics"].items()}
    out["act54_pennie_published_50m_impact"] = data["act54_pennie_published_50m_impact"]
    out["roi_note"] = data.get("roi_note", "")
    out["provenance"] = data.get("provenance", "")
    return out
PY

cat > tests/conftest.py << 'PY'
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
PY

mv tests/quarantine_test_golden_metrics.py.txt tests/test_golden_metrics.py

source .venv/bin/activate
python -m pytest tests/ -q > /tmp/pytest_final.log 2>&1 || true
tail -30 /tmp/pytest_final.log

if grep -qiE "error|failed" /tmp/pytest_final.log; then
  echo "!!! Not green — see output above, rolling back"
  git reset --hard "$CHECKPOINT"
  exit 1
fi

python3 - << 'PY'
import json, pathlib
p = pathlib.Path("HANDOVER.json")
d = json.loads(p.read_text())
for item in d.get("open_items", []):
    if item.get("quarantined_file") == "tests/quarantine_test_golden_metrics.py.txt":
        item["status"] = "resolved"
        item["resolution"] = "src/api/main.py implemented, serving data/public/key_statistics_2026.json; verified against pennie.com/affordability/ for Act 54 block"
p.write_text(json.dumps(d, indent=2))
PY

git add -A
git commit -q -m "feat(api): implement /metrics/summary from cited canonical data file

- data/public/key_statistics_2026.json: verified figures, PID/PHIEA cited
- Act 54 impact block cross-checked against pennie.com/affordability/
  (restored_enrollees=44000 flagged as derived, not directly published)
- src/api/main.py reads from JSON, no hardcoded literals
- un-quarantined test_golden_metrics.py, all tests passing"
git push
echo "[OK] done: $(git rev-parse HEAD)"
