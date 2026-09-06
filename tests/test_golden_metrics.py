"""Golden-file regression harness.

Contract: every numeric top-level field served by /metrics/summary must
match the August 2026 status report's Key Statistics table (transcribed
to key_statistics_golden.json). This converts the report from passive
prose into an enforceable merge gate:

  * Changed value without a report citation -> FAIL
  * New API number without a golden row     -> FAIL (unknown key)
  * Removal of a verified figure            -> FAIL (missing key)
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

FIXTURE = Path(__file__).parent / "fixtures" / "key_statistics_golden.json"

# Non-numeric / meta fields exempt from the golden comparison.
EXEMPT_KEYS = {"roi_note", "provenance", "act54_pennie_published_50m_impact"}


def load_golden():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data["golden"], data["_meta"]


def test_every_metric_matches_reported_value():
    golden, meta = load_golden()
    client = TestClient(app)
    metrics = client.get("/metrics/summary").json()

    mismatches = []
    for key, spec in golden.items():
        assert key in metrics, (
            f"Reported figure '{key}' dropped from API — restoring a "
            f"verified figure requires it to stay exposed: {spec['citation']}"
        )
        if metrics[key] != spec["value"]:
            mismatches.append(
                f"{key}: API={metrics[key]!r} but report says {spec['value']!r} "
                f"({spec['citation']}). Update the golden row WITH a new "
                f"citation before changing this value."
            )
    assert not mismatches, "Golden-file drift detected:\n" + "\n".join(mismatches)


def test_no_uncited_new_metrics():
    """Any new numeric field on /metrics/summary must have a golden row."""
    golden, _ = load_golden()
    client = TestClient(app)
    metrics = client.get("/metrics/summary").json()

    orphans = [
        k for k, v in metrics.items()
        if k not in golden and k not in EXEMPT_KEYS
        and isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    assert not orphans, (
        f"Uncited metrics shipped to /metrics/summary: {orphans}. "
        f"Add a golden row with a citation from the status report first."
    )


def test_act54_block_matches_pennie_published():
    """Nested Act 54 payload must equal Pennie's published figures (PHIEA 2026a)."""
    client = TestClient(app)
    act54 = client.get("/metrics/summary").json()["act54_pennie_published_50m_impact"]
    assert act54["restored_enrollees"] == 44000
    assert act54["premium_reduction_low_pct"] == 9.0
    assert act54["premium_reduction_high_pct"] == 12.0
    assert act54["enrollees_with_reduced_costs"] == 280000
    assert act54["appropriated_as_of_may_2026_usd"] == 0
    assert act54["ep_tc_lost_annual_usd"] == 600000000


def test_golden_fixture_integrity():
    """Guards the harness itself: fixture must be well-formed and complete."""
    golden, meta = load_golden()
    assert golden, "Golden table is empty"
    assert "Status_Report" in meta["source_document"]
    for key, spec in golden.items():
        assert "citation" in spec and spec["citation"], (
            f"Golden row '{key}' lacks a citation — unverified data cannot "
            f"enter the contract"
        )
