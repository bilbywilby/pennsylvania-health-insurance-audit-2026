#!/usr/bin/env python3
"""
Integration tests for bootstrap/05_ingest_carrier_extensions.py.
Verifies carrier rate weighting, county termination aggregation, rating-area
cross-validation against the crosswalk, and exception boundaries.
"""
import csv
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "bootstrap" / "05_ingest_carrier_extensions.py"

spec = importlib.util.spec_from_file_location("carrier_module", MODULE_PATH)
carrier_module = importlib.util.module_from_spec(spec)
sys.modules["carrier_module"] = carrier_module
spec.loader.exec_module(carrier_module)

class BaseCarrierTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.temp_dir) / "data"
        self.public_dir = self.data_dir / "public"
        self.private_dir = self.data_dir / "private"
        self.public_dir.mkdir(parents=True)
        self.private_dir.mkdir(parents=True)

        crosswalk_data = {
            "1": [{"county": "Erie", "fips": "42049"}],
            "4": [{"county": "Allegheny", "fips": "42003"}],
        }
        with open(self.public_dir / "pa_county_fips_crosswalk.json", "w") as f:
            json.dump(crosswalk_data, f)

        self._orig = {
            "CROSSWALK_FILE": carrier_module.CROSSWALK_FILE,
            "CARRIER_RATES_FILE": carrier_module.CARRIER_RATES_FILE,
            "COUNTY_TERMINATIONS_FILE": carrier_module.COUNTY_TERMINATIONS_FILE,
            "CARRIER_ANOMALY_FILE": carrier_module.CARRIER_ANOMALY_FILE,
            "CARRIER_AGGREGATE_FILE": carrier_module.CARRIER_AGGREGATE_FILE,
            "TERMINATION_AGGREGATE_FILE": carrier_module.TERMINATION_AGGREGATE_FILE,
        }

        carrier_module.CROSSWALK_FILE = self.public_dir / "pa_county_fips_crosswalk.json"
        carrier_module.CARRIER_RATES_FILE = self.data_dir / "carrier-rate-changes.csv"
        carrier_module.COUNTY_TERMINATIONS_FILE = self.data_dir / "county-termination-rates.csv"
        carrier_module.CARRIER_ANOMALY_FILE = self.private_dir / "carrier_anomalies_2026.csv"
        carrier_module.CARRIER_AGGREGATE_FILE = self.private_dir / "carrier_aggregates_2026.csv"
        carrier_module.TERMINATION_AGGREGATE_FILE = self.private_dir / "county_termination_aggregates_2026.csv"

    def tearDown(self):
        for key, value in self._orig.items():
            setattr(carrier_module, key, value)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write_carrier_rates(self, content: str):
        with open(carrier_module.CARRIER_RATES_FILE, "w", encoding="utf-8") as f:
            f.write(content)

    def write_terminations(self, content: str):
        with open(carrier_module.COUNTY_TERMINATIONS_FILE, "w", encoding="utf-8") as f:
            f.write(content)

class TestCarrierRateIngestion(BaseCarrierTest):
    def test_weighted_carrier_rate_aggregation(self):
        self.write_carrier_rates(
            "carrier_name,approved_rate_change,rating_area,covered_lives\n"
            "Highmark,10.0%,4,1000\n"
            "Highmark,20.0%,4,3000\n"
        )
        self.write_terminations("county,termination_count,total_enrollees\nAllegheny,500,10000\n")

        summary = carrier_module.run_carrier_ingestion()
        self.assertEqual(summary["anomalies_count"], 0)

        with open(carrier_module.CARRIER_AGGREGATE_FILE, "r") as f:
            rows = list(csv.DictReader(f))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["carrier_name"], "Highmark")
        # (10.0*1000 + 20.0*3000) / 4000 = 17.5
        self.assertEqual(rows[0]["weighted_avg_rate_change"], "17.5000")

    def test_negative_rate_change_is_preserved_not_flagged(self):
        # A carrier lowering premiums is a valid, legitimate rate change.
        self.write_carrier_rates(
            "carrier_name,approved_rate_change,rating_area\nOscar,-5.2%,1\n"
        )
        self.write_terminations("county,termination_count\nErie,10\n")

        summary = carrier_module.run_carrier_ingestion()
        self.assertEqual(summary["anomalies_count"], 0)

        with open(carrier_module.CARRIER_AGGREGATE_FILE, "r") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["weighted_avg_rate_change"], "-5.2000")

    def test_unweighted_rows_default_to_simple_average(self):
        self.write_carrier_rates(
            "carrier_name,approved_rate_change,rating_area\n"
            "Geisinger,10.0,4\n"
            "Geisinger,30.0,4\n"
        )
        self.write_terminations("county,termination_count\nAllegheny,10\n")

        carrier_module.run_carrier_ingestion()
        with open(carrier_module.CARRIER_AGGREGATE_FILE, "r") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["weighted_avg_rate_change"], "20.0000")

    def test_unknown_rating_area_is_flagged_not_silently_kept(self):
        # Area "99" doesn't exist in this test's crosswalk fixture (only 1 and 4 do).
        self.write_carrier_rates(
            "carrier_name,approved_rate_change,rating_area\nHighmark,10.0,99\n"
        )
        self.write_terminations("county,termination_count\nAllegheny,10\n")

        summary = carrier_module.run_carrier_ingestion()
        self.assertEqual(summary["anomalies_count"], 1)
        self.assertEqual(summary["carrier_areas"], 0)

        with open(carrier_module.CARRIER_ANOMALY_FILE, "r") as f:
            rows = list(csv.DictReader(f))
        self.assertIn("not found in crosswalk", rows[0]["reason"])

    def test_invalid_rate_change_is_flagged(self):
        self.write_carrier_rates(
            "carrier_name,approved_rate_change,rating_area\nHighmark,not-a-number,4\n"
        )
        self.write_terminations("county,termination_count\nAllegheny,10\n")

        summary = carrier_module.run_carrier_ingestion()
        self.assertEqual(summary["anomalies_count"], 1)

    def test_missing_carrier_header_raises_schema_error(self):
        self.write_carrier_rates("approved_rate_change,rating_area\n10.0%,4\n")
        self.write_terminations("county,termination_count\nAllegheny,100\n")

        with self.assertRaises(carrier_module.CarrierSchemaError):
            carrier_module.run_carrier_ingestion()

    def test_missing_carrier_file_raises_schema_error(self):
        self.write_terminations("county,termination_count\nAllegheny,100\n")
        with self.assertRaises(carrier_module.CarrierSchemaError):
            carrier_module.run_carrier_ingestion()

class TestCountyTerminationIngestion(BaseCarrierTest):
    def test_county_termination_rate_calculation(self):
        self.write_carrier_rates("carrier_name,approved_rate_change,rating_area\nHighmark,12.5%,1\n")
        self.write_terminations("county,termination_count,total_enrollees\nErie,250,2500\n")

        carrier_module.run_carrier_ingestion()

        with open(carrier_module.TERMINATION_AGGREGATE_FILE, "r") as f:
            rows = list(csv.DictReader(f))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rating_area"], "1")
        self.assertEqual(rows[0]["total_terminations"], "250")
        self.assertEqual(rows[0]["termination_rate_pct"], "10.00%")

    def test_termination_rate_defaults_to_zero_without_enrollee_column(self):
        # total_enrollees is optional; its absence must not crash the pipeline.
        self.write_carrier_rates("carrier_name,approved_rate_change,rating_area\nHighmark,1.0,1\n")
        self.write_terminations("county,termination_count\nErie,50\n")

        carrier_module.run_carrier_ingestion()
        with open(carrier_module.TERMINATION_AGGREGATE_FILE, "r") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["total_enrollees"], "0")
        self.assertEqual(rows[0]["termination_rate_pct"], "0.00%")

    def test_unknown_county_is_flagged_and_excluded(self):
        self.write_carrier_rates("carrier_name,approved_rate_change,rating_area\nHighmark,1.0,1\n")
        self.write_terminations("county,termination_count\nNowhereville,50\n")

        summary = carrier_module.run_carrier_ingestion()
        self.assertEqual(summary["anomalies_count"], 1)
        self.assertEqual(summary["termination_areas"], 0)

    def test_negative_termination_count_is_invalid(self):
        self.write_carrier_rates("carrier_name,approved_rate_change,rating_area\nHighmark,1.0,1\n")
        self.write_terminations("county,termination_count\nErie,-5\n")

        summary = carrier_module.run_carrier_ingestion()
        self.assertEqual(summary["anomalies_count"], 1)

    def test_missing_termination_header_raises_schema_error(self):
        self.write_carrier_rates("carrier_name,approved_rate_change,rating_area\nHighmark,1.0,1\n")
        self.write_terminations("county\nErie\n")  # no termination_count column

        with self.assertRaises(carrier_module.CarrierSchemaError):
            carrier_module.run_carrier_ingestion()

    def test_missing_termination_file_raises_schema_error(self):
        self.write_carrier_rates("carrier_name,approved_rate_change,rating_area\nHighmark,1.0,1\n")
        with self.assertRaises(carrier_module.CarrierSchemaError):
            carrier_module.run_carrier_ingestion()

class TestAnomalyFileBehavior(BaseCarrierTest):
    def test_no_anomaly_file_written_when_all_records_valid(self):
        self.write_carrier_rates("carrier_name,approved_rate_change,rating_area\nHighmark,1.0,1\n")
        self.write_terminations("county,termination_count\nErie,10\n")

        carrier_module.run_carrier_ingestion()
        self.assertFalse(carrier_module.CARRIER_ANOMALY_FILE.exists())

    def test_anomalies_from_both_sources_are_combined_in_one_file(self):
        self.write_carrier_rates(
            "carrier_name,approved_rate_change,rating_area\nHighmark,bad,1\n"
        )
        self.write_terminations("county,termination_count\nNowhereville,10\n")

        summary = carrier_module.run_carrier_ingestion()
        self.assertEqual(summary["anomalies_count"], 2)

        with open(carrier_module.CARRIER_ANOMALY_FILE, "r") as f:
            sources = {row["source"] for row in csv.DictReader(f)}
        self.assertEqual(sources, {"carrier_rates", "county_terminations"})

if __name__ == "__main__":
    unittest.main()
