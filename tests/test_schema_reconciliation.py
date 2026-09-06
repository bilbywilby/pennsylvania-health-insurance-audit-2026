"""Tests for scripts/schema_reconciliation.py."""
import json, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import schema_reconciliation as sr

AREA_COUNTS = {1: 8, 2: 3, 3: 13, 4: 10, 5: 7, 6: 10, 7: 4, 8: 5, 9: 7}

def write_crosswalk(path):
    values = [{"fips": c["fips"], "name": c["name"], "rating_area": a}
              for a, cs in sr.PA_RATING_AREA_COUNTY_MAP.items() for c in cs]
    path.write_text(json.dumps({"counties": values}))
    return path

@pytest.fixture
def matrix(tmp_path):
    path = write_crosswalk(tmp_path / "crosswalk.json")
    real = sr.load_crosswalk
    sr.load_crosswalk = lambda: real(path=path)
    try:
        yield sr.build_county_rate_matrix()
    finally:
        sr.load_crosswalk = real

class TestCountyIntegrity:
    def test_exactly_67_unique_counties(self, matrix):
        assert len(matrix) == 67
        assert len({r["county_name"] for r in matrix.values()}) == 67

    @pytest.mark.parametrize("area,count", sorted(AREA_COUNTS.items()))
    def test_every_area_has_expected_count(self, matrix, area, count):
        assert sum(1 for r in matrix.values() if r["rating_area"] == area) == count

    @pytest.mark.parametrize("fips,name,area", [
        ("42001", "Adams", 7), ("42003", "Allegheny", 4), ("42101", "Philadelphia", 8),
        ("42049", "Erie", 1), ("42133", "York", 7), ("42099", "Perry", 9),
    ])
    def test_known_county_pins(self, matrix, fips, name, area):
        assert matrix[fips]["county_name"] == name and matrix[fips]["rating_area"] == area

class TestCarrierAttribution:
    def test_every_county_has_active_carriers(self, matrix):
        assert all(r["carriers"] for r in matrix.values())
        assert all(r["weighted_rate_increase"] is not None for r in matrix.values())

    def test_upmc_in_pittsburgh_metro(self, matrix):
        assert "UPMC Health Plan Inc." in {c["carrier"] for c in matrix["42003"]["carriers"]}

    def test_no_attribution_outside_filing_areas(self, matrix):
        perry = {c["carrier"] for c in matrix["42099"]["carriers"]}
        assert "Ambetter (Centene)" in perry
        assert "Capital Advantage Assurance" in perry      # Areas 6, 7, 9
        assert "Keystone Health Plan East" not in perry    # Area 8 only

    def test_partners_negative_change_preserved(self, matrix):
        rec = next(c for c in matrix["42101"]["carriers"] if c["carrier"] == "Partners Insurance Co.")
        assert rec["approved_rate_change"] == -10.12

    def test_weighted_engine_applies_shares(self, matrix):
        covering = [f for f in sr.CARRIER_RATE_FILINGS if 4 in f["rating_areas"]]
        expected = round(sum(f["rate_change"] * f["share"] for f in covering)
                         / sum(f["share"] for f in covering), 2)
        assert matrix["42003"]["weighted_rate_increase"] == expected
        unweighted = round(sum(f["rate_change"] for f in covering) / len(covering), 2)
        assert expected != unweighted

class TestValidationGuards:
    def test_duplicate_fips_raises(self, tmp_path):
        f = tmp_path / "dup.json"
        row = {"fips": "42001", "name": "A", "rating_area": 1}
        f.write_text(json.dumps({"counties": [row, dict(row)]}))
        with pytest.raises(sr.ReconciliationError, match="Duplicate FIPS"):
            sr.load_crosswalk(path=f)

    def test_non_pa_fips_raises(self, tmp_path):
        f = tmp_path / "np.json"
        f.write_text(json.dumps([{"fips": "33001", "name": "X", "rating_area": 1}]))
        with pytest.raises(sr.ReconciliationError, match="Non-PA FIPS"):
            sr.load_crosswalk(path=f)

    def test_wrong_county_count_raises(self, tmp_path):
        f = tmp_path / "cnt.json"
        values = [{"fips": f"42{i:03d}", "name": f"C{i}", "rating_area": 1} for i in range(1, 67)]
        f.write_text(json.dumps({"counties": values}))
        with pytest.raises(sr.ReconciliationError, match="expected 67"):
            sr.load_crosswalk(path=f)

    def test_cross_carrier_serff_collision_raises(self):
        with pytest.raises(sr.FilingValidationError, match="collision"):
            sr.validate_filings([
                {"carrier": "Keystone Health Plan East", "serff_id": "INAC-134505843", "rating_areas": [8]},
                {"carrier": "Keystone Health Plan Central", "serff_id": "INAC-134505843", "rating_areas": [6]},
            ])

    def test_malformed_serff_raises(self):
        with pytest.raises(sr.FilingValidationError, match="Malformed SERFF"):
            sr.validate_filings([{"carrier": "A", "serff_id": "CARA-001", "rating_areas": [1]}])

    def test_zero_total_share_raises(self, monkeypatch):
        zeroed = [dict(f, share=0.0) for f in sr.CARRIER_RATE_FILINGS]
        monkeypatch.setattr(sr, "CARRIER_RATE_FILINGS", zeroed)
        with pytest.raises(sr.ReconciliationError, match="market share"):
            sr.build_county_rate_matrix()

class TestFilingLoader:
    def test_validated_filings_flow_through_exposure(self):
        validated = sr.validate_filings([
            {"carrier": "Carrier A", "serff_id": "CARA-000000001", "rating_areas": [1],
             "rate_change": 10.0, "lives_by_area": {1: 100.0}, "verified": True},
            {"carrier": "Carrier B", "serff_id": "CARB-000000002", "rating_areas": [1],
             "rate_change": 20.0, "lives_by_area": {1: 300.0}, "verified": True},
        ])
        exposure = sr.compute_rating_area_exposure(validated)
        assert exposure[1]["weighted_rate_change"] == 17.50
        assert exposure[1]["verified"] is True

    def test_unverified_row_poisons_group(self, tmp_path):
        f = tmp_path / "cc.csv"
        f.write_text("carrier,serff_id,rate_change,rating_area,covered_lives,verified\n"
                     "Carrier A,CARA-000000001,10.0,1,100,True\n"
                     "Carrier A,CARA-000000001,12.0,1,200,False\n")
        records = sr.load_filings_from_csv(f)
        assert len(records) == 1 and records[0]["verified"] is False
        exposure = sr.compute_rating_area_exposure(records)
        assert exposure[1]["weighted_rate_change"] == 11.33
        assert exposure[1]["verified"] is False

    def test_legacy_column_names_are_normalized(self, tmp_path):
        f = tmp_path / "legacy.csv"
        f.write_text("carrier_name,approved_rate_change,rating_area\nHighmark,17.75,4\n")
        records = sr.load_filings_from_csv(f)
        assert records and records[0]["carrier"] == "Highmark"
        assert records[0]["rate_change"] == 17.75

    def test_missing_carrier_raises(self, tmp_path):
        f = tmp_path / "bad.csv"
        f.write_text("carrier,serff_id,rate_change,rating_area\n,HGHM-134504750,17.75,4\n")
        with pytest.raises(sr.FilingValidationError, match="missing 'carrier'"):
            sr.load_filings_from_csv(f)

    def test_unparseable_numeric_raises(self, tmp_path):
        f = tmp_path / "badnum.csv"
        f.write_text("carrier,serff_id,rate_change,rating_area\nHighmark,HGHM-134504750,INVALID,4\n")
        with pytest.raises(sr.FilingValidationError, match="Unparseable numeric"):
            sr.load_filings_from_csv(f)

class TestExposureBridge:
    def test_write_county_exposure_csv(self, tmp_path):
        out = tmp_path / "private" / "exposure.csv"
        written = sr.write_county_exposure(out_path=out)
        assert written.exists()
        lines = written.read_text().strip().splitlines()
        assert len(lines) == 68  # header + 67 counties
        assert lines[0] == "fips,county_name,rating_area,carrier_count,weighted_rate_increase"
