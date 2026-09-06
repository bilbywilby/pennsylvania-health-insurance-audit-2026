"""Differential tests: real pipeline vs known-by-construction synthetic universe."""
import sys
from pathlib import Path
from fractions import Fraction
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import schema_reconciliation as sr
import synthetic_pa as sp

class TestSyntheticPennsylvania:
    def test_area_exposure_matches_ground_truth(self):
        """The core theorem: pipeline reproduces closed-form weighted means exactly."""
        truth = sp.ground_truth_exposure()
        validated = sr.validate_filings(sp.synthetic_filings())
        exposure = sr.compute_rating_area_exposure(validated)
        for area, expected in truth.items():
            assert abs(exposure[area]["weighted_rate_change"] - float(expected)) < 0.005, (
                f"RA {area}: pipeline {exposure[area]['weighted_rate_change']} vs truth {float(expected)}")
        assert all(exposure[a]["basis"] == "covered_lives" for a in truth)
        assert all(exposure[a]["verified"] is True for a in range(1, 10))

    def test_crosswalk_integrity_on_synthetic_universe(self, tmp_path):
        entries, _ = sp.synthetic_crosswalk()
        f = Path("/tmp") / "syn_crosswalk.json"
        f.write_text(__import__("json").dumps({"counties": entries}))
        cw = sr.load_crosswalk(path=f)
        assert len(cw) == 67 and set(cw) == {f"90{i:03d}" for i in range(1, 68)}

    def test_county_matrix_binds_correct_area(self):
        entries, fips_to_area = sp.synthetic_crosswalk(seed=7)
        validated = sr.validate_filings(sp.synthetic_filings())
        real_load = sr.load_crosswalk
        import json as _json
        f = Path("/tmp") / "syn_crosswalk7.json"
        f.write_text(_json.dumps({"counties": entries}))
        sr.load_crosswalk = lambda: real_load(path=f)
        try:
            matrix = sr.build_county_rate_matrix(filings=validated)
        finally:
            sr.load_crosswalk = real_load
        for fips, area in fips_to_area.items():
            assert matrix[fips]["rating_area"] == area
        # RA 7 has SYN-A only -> weighted equals its lone rate exactly
        assert matrix["90007"]["weighted_rate_change"] == 20.0 + 7

    def test_harness_detects_tampering(self, monkeypatch):
        """Mutation check: corrupt one rate and the pipeline MUST diverge from truth."""
        truth = sp.ground_truth_exposure()
        filings = sp.synthetic_filings()
        filings[0] = dict(filings[0], rate_change=filings[0]["rate_change"] + 99.0)
        validated = sr.validate_filings(filings)
        exposure = sr.compute_rating_area_exposure(validated)
        diverged = [a for a, exp in truth.items()
                    if abs(exposure[a]["weighted_rate_change"] - float(exp)) > 0.005]
        assert diverged, "Harness failed to detect a corrupted filing — it cannot be trusted"
