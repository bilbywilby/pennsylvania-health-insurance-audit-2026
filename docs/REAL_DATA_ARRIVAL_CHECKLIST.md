# Real-Data Arrival Checklist: PID Covered-Lives Extract

## 1. Pre-Ingestion Validation
- [ ] File exists at data/carrier-rate-changes.csv, valid UTF-8
- [ ] Headers: required carrier|carrier_name, rate_change|approved_rate_change, rating_area
- [ ] Optional: covered_lives, serff_id, verified (aliases normalized + logged on ingest)
- [ ] rate_change in percentage points (10.0 = 10%)

## 2. Execution
- [ ] bash bootstrap/00_run_all.sh
- [ ] Step 05: no FilingValidationError (collisions / malformed numerics)
- [ ] Step 06: log shows "basis: covered_lives"; verified watermark propagated

## 3. Acceptance
| Check | Target |
|---|---|
| Exposure basis | covered_lives (fallback ONLY if lives column entirely absent) |
| Weighted rate | non-null positive float per populated RA |
| 04_audit ingest | no schema errors |

## 4. Rollback
- Quarantine, never delete (extract may be sole copy):
  mv data/carrier-rate-changes.csv data/private/quarantine_$(date +%Y%m%d_%H%M%S).csv
- Re-run: python3 -m pytest tests/ -q
