#!/usr/bin/env python3
"""
Integration tests for the Pennsylvania Health Insurance Audit.
Verifies anomaly export and rating-area aggregation logic against
isolated temp-directory fixtures (no reliance on real project data).
"""
import csv
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "bootstrap" / "04_audit.py"

spec = importlib.util.spec_from_file_location("audit_module", MODULE_PATH)
audit_module = importlib.util.module_from_spec(spec)
sys.modules["audit_module"] = audit_module
spec.loader.exec_module(audit_module)

class BaseAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.temp_dir) / "data"
        self.public_dir = self.data_dir / "public"
        self.private_dir = self.data_dir / "private"
        self.public_dir.mkdir(parents=True)
        self.private_dir.mkdir(parents=True)

        crosswalk_data = {
            "1": [{"county": "Allegheny", "fips": "42003"}],
            "2": [{"county": "Cameron", "fips": "42023"}],
        }
        with open(self.public_dir / "pa_county_fips_crosswalk.json", "w") as f:
            json.dump(crosswalk_data, f)

        self._orig = {
            "APPROVED_RATES_FILE": audit_module.APPROVED_RATES_FILE,
            "CROSSWALK_FILE": audit_module.CROSSWALK_FILE,
            "REPORT_FILE": audit_module.REPORT_FILE,
            "AGGREGATE_REPORT_FILE": audit_module.AGGREGATE_REPORT_FILE,
        }
        audit_module.APPROVED_RATES_FILE = self.data_dir / "approved_rates_2026.csv"
        audit_module.CROSSWALK_FILE = self.public_dir / "pa_county_fips_crosswalk.json"
        audit_module.REPORT_FILE = self.private_dir / "audit_anomalies_2026.csv"
        audit_module.AGGREGATE_REPORT_FILE = self.private_dir / "audit_aggregates_2026.csv"

    def tearDown(self):
        for key, value in self._orig.items():
            setattr(audit_module, key, value)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write_rates(self, content: str):
        with open(audit_module.APPROVED_RATES_FILE, "w", encoding="utf-8") as f:
            f.write(content)

class TestAnomalyExporter(BaseAuditTest):
    def test_missing_county_is_logged_as_anomaly(self):
        self.write_rates(
            "county,rate,age,plan_type\n"
            "Allegheny,100,30,Platinum\n"
            "UnknownCounty,50,40,Silver\n"
        )
        result = audit_module.run_audit()

        self.assertEqual(result.missing_counties, 1)
        self.assertEqual(result.valid_records, 1)
        self.assertTrue(audit_module.REPORT_FILE.exists())

        with open(audit_module.REPORT_FILE, "r") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "County not found in crosswalk")
        self.assertEqual(rows[0]["county"], "UnknownCounty")
        # raw_record must round-trip as valid JSON, not a bare python repr
        self.assertEqual(json.loads(rows[0]["raw_record"])["county"], "UnknownCounty")

    def test_case_insensitive_county_match_is_not_an_anomaly(self):
        self.write_rates("county,rate,age,plan_type\nALLEGHENY,100,30,Platinum\n")
        result = audit_module.run_audit()
        self.assertEqual(result.missing_counties, 0)
        self.assertEqual(result.valid_records, 1)

    def test_currency_and_percent_formatted_rates_are_sanitized(self):
        self.write_rates(
            "county,rate,age,plan_type\n"
            "Allegheny,\"$1,200.00\",30,Platinum\n"
            "Cameron,18.6%,40,Silver\n"
        )
        result = audit_module.run_audit()
        self.assertEqual(result.invalid_rates, 0)
        self.assertEqual(result.valid_records, 2)

    def test_invalid_rate_is_logged_as_anomaly(self):
        self.write_rates("county,rate,age,plan_type\nAllegheny,not-a-number,30,Platinum\n")
        result = audit_module.run_audit()
        self.assertEqual(result.invalid_rates, 1)
        self.assertEqual(result.valid_records, 0)

    def test_no_anomaly_file_written_when_all_records_valid(self):
        self.write_rates("county,rate,age,plan_type\nAllegheny,100,30,Platinum\n")
        audit_module.run_audit()
        self.assertFalse(audit_module.REPORT_FILE.exists())

class TestRatingAreaAggregation(BaseAuditTest):
    def test_weighted_average_per_area_unweighted_default(self):
        self.write_rates(
            "county,rate,age,plan_type\n"
            "Allegheny,100,30,Platinum\n"
            "Cameron,50,40,Silver\n"
        )
        audit_module.run_audit()

        self.assertTrue(audit_module.AGGREGATE_REPORT_FILE.exists())
        with open(audit_module.AGGREGATE_REPORT_FILE, "r") as f:
            rows = {r["rating_area"]: r for r in csv.DictReader(f)}

        self.assertEqual(rows["1"]["total_records"], "1")
        self.assertEqual(rows["1"]["weighted_avg_rate"], "100.0000")
        self.assertEqual(rows["2"]["total_records"], "1")
        self.assertEqual(rows["2"]["weighted_avg_rate"], "50.0000")

    def test_weighted_average_respects_explicit_weight_column(self):
        self.write_rates(
            "county,rate,age,plan_type,weight\n"
            "Allegheny,100,30,Platinum,3\n"
            "Allegheny,200,50,Gold,1\n"
        )
        audit_module.run_audit()

        with open(audit_module.AGGREGATE_REPORT_FILE, "r") as f:
            rows = {r["rating_area"]: r for r in csv.DictReader(f)}

        # (100*3 + 200*1) / (3+1) = 125.0
        self.assertEqual(rows["1"]["total_records"], "2")
        self.assertEqual(rows["1"]["total_weight"], "4.0")
        self.assertEqual(rows["1"]["weighted_avg_rate"], "125.0000")

    def test_records_excluded_from_aggregation_when_anomalous(self):
        self.write_rates(
            "county,rate,age,plan_type\n"
            "Allegheny,100,30,Platinum\n"
            "UnknownCounty,999,40,Silver\n"
        )
        audit_module.run_audit()

        with open(audit_module.AGGREGATE_REPORT_FILE, "r") as f:
            rows = {r["rating_area"]: r for r in csv.DictReader(f)}

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows["1"]["total_records"], "1")

class TestEdgeCases(BaseAuditTest):
    def test_bom_encoded_csv_is_read_correctly(self):
        # utf-8-sig must strip a leading BOM instead of corrupting the first header
        content = "county,rate,age,plan_type\nAllegheny,100,30,Platinum\n"
        with open(audit_module.APPROVED_RATES_FILE, "w", encoding="utf-8-sig") as f:
            f.write(content)
        result = audit_module.run_audit()
        self.assertEqual(result.total_records, 1)
        self.assertEqual(result.valid_records, 1)

    def test_missing_required_column_aborts_via_sys_exit(self):
        self.write_rates("county,age,plan_type\nAllegheny,30,Platinum\n")  # no 'rate' column
        with self.assertRaises(audit_module.AuditSchemaError) as ctx:
            audit_module.run_audit()
        self.assertIn("rate", str(ctx.exception))

    def test_whitespace_only_county_is_treated_as_missing(self):
        self.write_rates('county,rate,age,plan_type\n"   ",100,30,Platinum\n')
        result = audit_module.run_audit()
        self.assertEqual(result.missing_counties, 1)
        self.assertEqual(result.valid_records, 0)

    def test_negative_rate_is_invalid(self):
        self.write_rates("county,rate,age,plan_type\nAllegheny,-50,30,Platinum\n")
        result = audit_module.run_audit()
        self.assertEqual(result.invalid_rates, 1)

    def test_zero_or_negative_weight_falls_back_to_unweighted(self):
        self.write_rates(
            "county,rate,age,plan_type,weight\n"
            "Allegheny,100,30,Platinum,0\n"
            "Allegheny,200,50,Gold,-3\n"
        )
        audit_module.run_audit()
        with open(audit_module.AGGREGATE_REPORT_FILE, "r") as f:
            rows = {r["rating_area"]: r for r in csv.DictReader(f)}
        # both weights invalid -> both default to 1.0 -> simple average of 100 and 200
        self.assertEqual(rows["1"]["total_weight"], "2.0")
        self.assertEqual(rows["1"]["weighted_avg_rate"], "150.0000")

    def test_empty_rates_file_produces_no_records_without_crashing(self):
        self.write_rates("county,rate,age,plan_type\n")  # header only, no data rows
        result = audit_module.run_audit()
        self.assertEqual(result.total_records, 0)
        self.assertEqual(result.valid_records, 0)
        self.assertFalse(audit_module.REPORT_FILE.exists())

    def test_header_whitespace_and_case_variation_is_normalized(self):
        self.write_rates(" County , RATE ,Age,PLAN_TYPE\nAllegheny,100,30,Platinum\n")
        result = audit_module.run_audit()
        self.assertEqual(result.valid_records, 1)

    def test_embedded_comma_in_quoted_rate_field_is_sanitized(self):
        self.write_rates('county,rate,age,plan_type\nAllegheny,"1,234.56",30,Platinum\n')
        result = audit_module.run_audit()
        self.assertEqual(result.valid_records, 1)
        with open(audit_module.AGGREGATE_REPORT_FILE, "r") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["weighted_avg_rate"], "1234.5600")

if __name__ == "__main__":
    unittest.main()
