import json
from datetime import date, timedelta

import pytest

from src.provenance import (
    Claim, ProvenanceLedger, ArtifactValidator,
    ProvenanceError, UnknownClaimError, StaleClaimError, InvalidLedgerError,
    extract_claim_ids, scan_text_for_placeholders, seed_from_golden_fixture,
)


def make_claim(**over):
    base = dict(
        claim_id="test_claim", value=42,
        source_citation="PID Annual Report 2026, p.14",
        source_url="https://test.local/report",
        last_verified=date(2026, 9, 7), verified_by="test",
    )
    base.update(over)
    return Claim(**base)


class TestDigest:
    def test_digest_computed_on_construction(self):
        c = make_claim()
        assert c.digest and len(c.digest) == 64

    def test_field_order_does_not_affect_digest(self):
        c1 = make_claim()
        c2 = Claim(
            verified_by="test", claim_id="test_claim",
            source_url="https://test.local/report", value=42,
            last_verified=date(2026, 9, 7),
            source_citation="PID Annual Report 2026, p.14",
        )
        assert c1.digest == c2.digest

    def test_tampered_value_rejected_on_reload(self, tmp_path):
        ledger = ProvenanceLedger({"a": make_claim(claim_id="a")})
        p = tmp_path / "log.json"
        ledger.save(p)
        raw = json.loads(p.read_text())
        raw["a"]["value"] = 999  # edited without recomputing digest
        p.write_text(json.dumps(raw))
        with pytest.raises(InvalidLedgerError, match="digest mismatch"):
            ProvenanceLedger.load(p)

    def test_tampered_citation_rejected_on_reload(self, tmp_path):
        ledger = ProvenanceLedger({"a": make_claim(claim_id="a")})
        p = tmp_path / "log.json"
        ledger.save(p)
        raw = json.loads(p.read_text())
        raw["a"]["source_citation"] = "Fabricated Report, p.1"
        p.write_text(json.dumps(raw))
        with pytest.raises(InvalidLedgerError, match="digest mismatch"):
            ProvenanceLedger.load(p)

    def test_untouched_round_trip_reloads_clean(self, tmp_path):
        ledger = ProvenanceLedger({"a": make_claim(claim_id="a")})
        p = tmp_path / "log.json"
        ledger.save(p)
        reloaded = ProvenanceLedger.load(p)
        assert reloaded.get("a").value == 42
        assert reloaded.get("a").digest == ledger.get("a").digest


class TestLedger:
    def test_register_new_claim(self):
        ledger = ProvenanceLedger({"a": make_claim(claim_id="a")})
        ledger.register(make_claim(claim_id="b", value=7))
        assert len(ledger) == 2
        assert ledger.get("b").value == 7

    def test_register_duplicate_without_overwrite_raises(self):
        ledger = ProvenanceLedger({"a": make_claim(claim_id="a")})
        with pytest.raises(ProvenanceError):
            ledger.register(make_claim(claim_id="a", value=99))

    def test_unknown_claim_raises(self):
        ledger = ProvenanceLedger({"a": make_claim(claim_id="a")})
        with pytest.raises(UnknownClaimError):
            ledger.get("nonexistent")

    def test_refresh_updates_date_and_verifier(self):
        ledger = ProvenanceLedger({"a": make_claim(claim_id="a")})
        ledger.refresh("a", date(2026, 12, 1), verified_by="human:bw")
        c = ledger.get("a")
        assert c.last_verified == date(2026, 12, 1)
        assert c.verified_by == "human:bw"

    def test_empty_ledger_file_refused(self, tmp_path):
        p = tmp_path / "log.json"
        p.write_text("{}")
        with pytest.raises(InvalidLedgerError, match="empty"):
            ProvenanceLedger.load(p)

    def test_forbidden_source_host_rejected(self):
        with pytest.raises(Exception):
            make_claim(source_url="https://example.com/fake")


class TestStaleness:
    def test_boundary_day_not_stale(self):
        c = make_claim(staleness_days=90,
                       last_verified=date.today() - timedelta(days=90))
        assert not c.is_stale()

    def test_one_day_over_is_stale(self):
        c = make_claim(staleness_days=90,
                       last_verified=date.today() - timedelta(days=91))
        assert c.is_stale()

    def test_require_claims_raises_on_stale(self):
        ledger = ProvenanceLedger({"s": make_claim(
            claim_id="s", last_verified=date.today() - timedelta(days=200))})
        v = ArtifactValidator(ledger)
        with pytest.raises(StaleClaimError):
            v.require_claims(["s"])

    def test_require_claims_returns_fresh(self):
        ledger = ProvenanceLedger({"s": make_claim(claim_id="s")})
        v = ArtifactValidator(ledger, as_of=date(2026, 9, 8))
        result = v.require_claims(["s"])
        assert result[0].claim_id == "s"


class TestStatutesGate:
    def test_missing_statutes_file_fails_closed(self):
        ledger = ProvenanceLedger({"a": make_claim(claim_id="a")})
        v = ArtifactValidator(ledger, statutes_path=None)
        violations = v.validate_artifact({"template": {"statute": "Sec. 28-725"}})
        assert any("verified column" in s for s in violations)

    def test_unverified_statute_rejected(self, tmp_path):
        sp = tmp_path / "statutes.json"
        sp.write_text(json.dumps({"verified": {"Act 68 of 1998": {}}}))
        ledger = ProvenanceLedger({"a": make_claim(claim_id="a")})
        v = ArtifactValidator(ledger, statutes_path=sp)
        violations = v.validate_artifact({"a": {"statute": "Sec. 28-725"}})
        assert any("Sec. 28-725" in s for s in violations)

    def test_verified_statute_passes(self, tmp_path):
        sp = tmp_path / "statutes.json"
        sp.write_text(json.dumps({"verified": {"Act 68 of 1998": {}}}))
        ledger = ProvenanceLedger({"a": make_claim(claim_id="a")})
        v = ArtifactValidator(ledger, statutes_path=sp)
        assert v.validate_artifact({"a": {"statute": "Act 68 of 1998"}}) == []


class TestClaimExtraction:
    def test_extract_dict_claim_id(self):
        assert extract_claim_ids({"a": {"claim_id": "x"}}) == {"x"}

    def test_extract_prefixed_string(self):
        assert extract_claim_ids({"a": "claim_id:y"}) == {"y"}

    def test_extract_nested(self):
        node = {"a": [{"claim_id": "x"}, {"b": "claim_id:y"}]}
        assert extract_claim_ids(node) == {"x", "y"}


class TestPlaceholders:
    def test_detects_todo(self):
        assert "TODO" in scan_text_for_placeholders("value: TODO fill in")

    def test_clean_text_has_none(self):
        assert scan_text_for_placeholders("value: 42, verified 2026-09-07") == []


class TestGoldenSeed:
    def test_seed_requires_citation(self, tmp_path):
        fp = tmp_path / "golden.json"
        fp.write_text(json.dumps({"golden": {"x": {"value": 1, "citation": ""}}}))
        with pytest.raises(InvalidLedgerError):
            seed_from_golden_fixture(fp, "https://test.local", "test")

    def test_seed_success(self, tmp_path):
        fp = tmp_path / "golden.json"
        fp.write_text(json.dumps({
            "golden": {"x": {"value": 1, "citation": "Some Report (2026)"}}
        }))
        ledger = seed_from_golden_fixture(fp, "https://test.local", "test",
                                          as_of=date(2026, 9, 7))
        assert ledger.get("x").value == 1
        assert ledger.get("x").digest
