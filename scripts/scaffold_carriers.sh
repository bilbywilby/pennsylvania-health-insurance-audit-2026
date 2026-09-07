#!/usr/bin/env bash
# Scaffolds per-carrier filing tracking docs in docs/carriers/ from the rates CSV.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CSV="${ROOT}/data/approved_rates_2026.csv"
OUTDIR="${ROOT}/docs/carriers"

[ -f "${CSV}" ] || { echo "[ERR] ${CSV} not found" >&2; exit 1; }
mkdir -p "${OUTDIR}"

count=0
while IFS=, read -r carrier rate segment areas; do
    [ "${carrier}" = "carrier_name" ] && continue     # skip header
    [ -z "${carrier}" ] && continue

    slug="$(printf '%s' "${carrier}" \
        | tr '[:upper:]' '[:lower:]' \
        | sed -e 's/[(),.]//g' -e 's/&/and/g' -e 's/ /_/g')"

    cat > "${OUTDIR}/${slug}.md" <<TMPL
# Carrier Filing Audit: ${carrier}

## 1. Approved Rate Overview (2026)

* **Carrier Name:** ${carrier}
* **Approved Rate Change:** ${rate}
* **Market Segment:** ${segment}
* **Primary Rating Areas:** ${areas}

## 2. Regulatory Status & Line-Item Verification

- [ ] SERFF public filing documentation verified
- [ ] PID final decision letter cross-referenced
- [ ] Rating area breakdown validated against \`data/rating_areas_2026.csv\`
- [ ] Actuarial memo morbidity assumptions audited

## 3. Audit Notes & Filing Discrepancies

*Initial log auto-generated via scripts/scaffold_carriers.sh.*
TMPL

    echo "[OK] docs/carriers/${slug}.md"
    count=$((count + 1))
done < "${CSV}"

echo ""
echo "Scaffolded ${count} carrier filing logs in docs/carriers/"
