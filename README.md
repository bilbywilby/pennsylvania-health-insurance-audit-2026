# Pennsylvania Health Insurance Audit 2026

Pipeline for auditing Pennsylvania ACA health insurance rate filings. Validates
submitted rates against an authoritative 67-county / FIPS / rating-area crosswalk,
computes weighted-average rates per rating area, ingests county-level termination
telemetry, and exports structured anomaly logs and aggregate reports.

**Status: bootstrap complete — 64/64 integration tests passing. Awaiting real PID
data extracts. All example data in the repo is synthetic and watermarked.**

## Pipeline

Run from the repository root. Scripts live in bootstrap/ and use repo-relative paths.

| Step | Script | Role |
|---|---|---|
| 00 | bootstrap/00_run_all.sh | Orchestrator, halts on first failure |
| 01 | bootstrap/01_directories.py | Scaffolding + .gitignore (protects data/private/) |
| 02 | bootstrap/02_crosswalk.py | Builds crosswalk: 67 PA counties, FIPS, rating areas 1-9 |
| 03 | bootstrap/03_validate_csvs.py | Structural validation of input CSVs |
| 04 | bootstrap/04_audit.py | Core audit: validation, weighting, anomaly log |
| 05 | bootstrap/05_ingest_carrier_extensions.py | Carrier filings + terminations ingestion |

## Quick start (synthetic fixtures)

    bash tests/fixtures/run_fixtures.sh       # pipeline against SYNTHETIC fixtures
    python3 scripts/generate_figures.py       # renders docs/figures/*.svg
    python3 -m unittest discover tests -v     # 31 tests

Output reports land in data/private/ (gitignored). Figures render to docs/figures/
with provenance watermarks.

## Input contracts

| File | Required columns | Optional |
|---|---|---|
| data/approved_rates_2026.csv | county, rate, age, plan_type | weight |
| data/carrier-rate-changes.csv | carrier_name, approved_rate_change, rating_area | covered_lives |
| data/county-termination-rates.csv | county, termination_count | total_enrollees |

Format-tolerant on values (currency, percent signs, thousands commas), strict on
schema — missing columns raise typed exceptions (AuditSchemaError,
CarrierSchemaError) rather than exiting, so the modules are safe to import.

## Key behaviors

- Case-insensitive county matching; unknown counties/areas flagged as anomalies,
  excluded from aggregates, never silently kept.
- Negative rate changes are valid in the carrier ingestor (premium decreases are
  legitimate) but invalid as absolute premiums in 04_audit — intentional asymmetry.
- Anomalous records preserved verbatim (JSON-serialized) in anomaly logs.
- Privacy: data/private/ is fully gitignored; no PII ingestion paths exist.

## Figures

scripts/generate_figures.py (pure stdlib, zero dependencies) renders aggregate CSVs
into static SVGs in docs/figures/, each watermarked with its data provenance.

## Status and roadmap

See HANDOVER.json for the authoritative handover manifest. Outstanding work: real
PID 2026 extracts (schema reconciliation between carrier-level filings and the
county-level audit engine is the first design decision), docs expansion, optional CI.
