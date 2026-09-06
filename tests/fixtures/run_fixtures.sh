#!/usr/bin/env bash
# Runs the full pipeline against SYNTHETIC fixture data (dev onboarding).
# Copies fixtures into data/, runs bootstrap scripts, leaves reports in data/private/.
set -euo pipefail
cd "$(dirname "$0")/../.."   # repo root

echo "NOTE: Using SYNTHETIC fixtures from tests/fixtures/ - output is NOT real audit data."
cp tests/fixtures/sample_approved_rates_2026.csv       data/approved_rates_2026.csv
cp tests/fixtures/sample_carrier_rate_changes.csv      data/carrier-rate-changes.csv
cp tests/fixtures/sample_county_terminations.csv       data/county-termination-rates.csv

python3 bootstrap/02_crosswalk.py
python3 bootstrap/03_validate_csvs.py || true   # input contract differs for carrier/term files
python3 bootstrap/04_audit.py || true           # anomalies expected; exit 1 is fine here
python3 bootstrap/05_ingest_carrier_extensions.py || true

echo "Reports written to data/private/ (synthetic). Inspect, then clean with: git checkout -- data/ ; rm -f data/approved_rates_2026.csv data/carrier-rate-changes.csv data/county-termination-rates.csv"
