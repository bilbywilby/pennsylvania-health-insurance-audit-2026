#!/usr/bin/env bash
set -uo pipefail
cd /home/droid/pennsylvania-health-insurance-audit-2026

echo "=== current statutes_2026.json ==="
cat data/statutes_2026.json

git add -A
git commit -q -m "chore: pre-legislation-verification checkpoint" --allow-empty
CHECKPOINT=$(git rev-parse HEAD)
trap 'echo "!!! FAILED — rolling back"; git reset --hard "$CHECKPOINT"' ERR

mkdir -p research

python3 - << 'PY'
import json, pathlib
p = pathlib.Path("data/statutes_2026.json")
data = json.loads(p.read_text()) if p.exists() and p.read_text().strip() else {}
data.setdefault("verified", {})
data.setdefault("not_found_as_of", {})
data.setdefault("misattributed", {})

data["not_found_as_of"]["act_252_2023"] = {
    "finding": "No Act 252 of 2023 in official PA law-information records. Only 'Act No. 252 of 1923' exists (unrelated, printing appropriations).",
    "checked_via": "https://www.palegis.us/statutes/unconsolidated/law-information",
    "last_verified": "2026-09-07"
}
data["not_found_as_of"]["sec_28_725"] = {
    "finding": "Not found in any PA code title. Title 28 Pa. Code is Health & Safety (managed care orgs), not insurance; actual PA insurance law is Title 40 P.S. and Title 31 Pa. Code.",
    "checked_via": "https://www.legis.state.pa.us/WU01/LI/LI/CT/HTM/40/40.HTM ; https://regulations.justia.com/states/pennsylvania/title-28/part-i/chapter-9/subchapter-k",
    "last_verified": "2026-09-07"
}
data["not_found_as_of"]["sec_29_8719"] = {
    "finding": "Not found in any PA code title. Title 29 is not a PA insurance title.",
    "checked_via": "web search, PA code cross-reference",
    "last_verified": "2026-09-07"
}
data["misattributed"]["sb_1071"] = {
    "finding": "SB 1071 (2025-2026 session) is real but amends Titles 18/53 (police conduct, 'No Secret Police: Unmask ICE'); unrelated to health insurance.",
    "source_url": "https://www.palegis.us/legislation/bills/2025/sb1071",
    "last_verified": "2026-09-07"
}
data["verified"]["hb_2562_2563_2564"] = {
    "finding": "Real ACA-codification package. House passed Oct 9 2024: HB2562 160-42, HB2563 163-39, HB2564 174-28. Referred to Senate Banking & Insurance Oct 18 2024. NO further Senate action, no Act number as of latest official page generation.",
    "status": "house_passed_not_enacted",
    "source_urls": [
        "https://www.palegis.us/legislation/bills/2023/hb2562",
        "https://www.palegis.us/legislation/bills/2023/hb2564",
        "https://www.cityandstatepa.com/policy/2024/10/pa-house-approves-bills-would-codify-affordable-care-act-protections-state-law/400172/"
    ],
    "last_verified": "2026-09-07"
}
p.write_text(json.dumps(data, indent=2))
print("[OK] statutes_2026.json updated")
PY

cat > research/legislation_verification_2026.json << 'JSON'
{
  "_meta": {
    "purpose": "Independent verification pass on flagged citations, run 2026-09-07. All findings backed by direct web_fetch/web_search of official sources, not inference.",
    "framing_note": "Per project standard: absence of a citation in official sources is recorded as 'not found as of <date>', not 'does not exist' -- a claim can be unverifiable without being disproven."
  },
  "findings": [
    {
      "citation": "SB 1071 (2024)",
      "status": "misattributed",
      "detail": "SB 1071 exists only in the 2025-2026 session; amends Titles 18/53 (police conduct), not health insurance. Likely candidates for what was intended: SB 50 and SB 1195 (2025-2026), both health-insurance-related -- NOT independently verified this pass, flag for next check.",
      "source_url": "https://www.palegis.us/legislation/bills/2025/sb1071"
    },
    {
      "citation": "Act 252-2023",
      "status": "not_found_as_of_2026-09-07",
      "source_url": "https://www.palegis.us/statutes/unconsolidated/law-information?sessYr=2023&sessInd=0&actNum=25"
    },
    {
      "citation": "HB 2562, HB 2563, HB 2564",
      "status": "house_passed_not_enacted",
      "detail": "Passed PA House Oct 9 2024 (160-42, 163-39, 174-28). Referred to Senate Banking & Insurance Oct 18 2024. No further recorded Senate action or Act number.",
      "source_urls": [
        "https://www.palegis.us/legislation/bills/2023/hb2562",
        "https://www.palegis.us/legislation/bills/2023/hb2564",
        "https://www.cityandstatepa.com/policy/2024/10/pa-house-approves-bills-would-codify-affordable-care-act-protections-state-law/400172/"
      ]
    },
    {
      "citation": "§28-725",
      "status": "not_found_as_of_2026-09-07",
      "detail": "Title 28 Pa. Code governs Health & Safety, not insurance. Real PA insurance code is Title 40 P.S. / Title 31 Pa. Code.",
      "source_url": "https://www.legis.state.pa.us/WU01/LI/LI/CT/HTM/40/40.HTM"
    },
    {
      "citation": "§29-8719",
      "status": "not_found_as_of_2026-09-07",
      "detail": "Title 29 is not a PA insurance code title; no matching section found anywhere."
    }
  ]
}
JSON

source .venv/bin/activate
python -m pytest tests/ -q > /tmp/pytest_leg.log 2>&1 || true
tail -10 /tmp/pytest_leg.log

if grep -qiE "error|failed" /tmp/pytest_leg.log; then
  echo "!!! Not green — rolling back"
  git reset --hard "$CHECKPOINT"
  exit 1
fi

git add -A
git commit -q -m "docs(audit): independently verify SB1071/Act252-2023/HB2562-64/§28-725/§29-8719

All findings from direct fetch of palegis.us, cityandstatepa.com, PA code
sources -- not inferred, not taken from an unverified prior draft.
- HB2562/2563/2564: real, House-passed Oct 2024, NOT enacted (Senate stalled)
- SB1071: real bill, wrong subject (police conduct, not insurance)
- Act 252-2023, §28-725, §29-8719: not found in any official source"
git push
echo "[OK] done: $(git rev-parse HEAD)"
