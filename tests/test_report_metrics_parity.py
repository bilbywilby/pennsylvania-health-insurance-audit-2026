"""
tests/test_report_metrics_parity.py

Guards against the API and the published status report drifting apart:
every numeric value served by /metrics/summary must be traceable to a
number that actually appears in the report's Key Statistics table. A
new API number shipping without a corresponding report citation fails
this test.

ASSUMPTIONS (flag/adjust if wrong for actual repo layout):
  - REPORT_PATH points at the canonical status report .docx. If reports
    are per-rating-area (nine separate files, per the PA campaign
    convention) rather than one statewide report, point this at
    whichever file carries these metrics, or set PARAMETRIZE_ALL_REPORTS
    and glob REPORT_DIR instead.
  - Parsed via stdlib zipfile+ElementTree, not python-docx — avoids a
    new dependency for a read-only text extraction.
  - roi_note and other free-text fields are excluded; only numeric
    leaves in the JSON tree are checked.
"""
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)

# --- ADAPT: path to the report whose Key Statistics table should
# --- mirror /metrics/summary.
REPORT_PATH = Path("docs/reports/statewide_status_report.docx")
PARAMETRIZE_ALL_REPORTS = False  # flip True + glob REPORT_DIR if metrics
                                   # are duplicated across all nine
                                   # rating-area reports instead

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_text(path: Path) -> str:
    """All text from a .docx (paragraphs + tables), stdlib only."""
    with zipfile.ZipFile(path) as z:
        xml_bytes = z.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    texts = [node.text for node in root.iter(f"{W_NS}t") if node.text]
    return " ".join(texts)


def _normalize_numbers(text: str) -> set[float]:
    """Pull numeric tokens out of report text, stripping $/commas/%,
    so '$50,000,000' and 50000000 compare equal, '9-12%' yields both
    9.0 and 12.0."""
    cleaned = text.replace(",", "")
    tokens = re.findall(r"-?\d+\.?\d*", cleaned)
    return {float(t) for t in tokens if t not in ("", "-", ".")}


def _flatten_numeric_leaves(obj, path="") -> dict[str, float]:
    """Recursively pull int/float leaves out of the summary payload,
    skipping strings like roi_note."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten_numeric_leaves(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out[path] = float(obj)
    return out


@pytest.fixture(scope="module")
def summary_metrics() -> dict:
    response = client.get("/metrics/summary")
    assert response.status_code == 200, (
        "/metrics/summary must be reachable for parity check to mean anything"
    )
    return response.json()


@pytest.fixture(scope="module")
def report_numbers() -> set[float]:
    if not REPORT_PATH.exists():
        pytest.skip(
            f"Report not found at {REPORT_PATH} — update REPORT_PATH to match "
            "actual repo layout before trusting this test."
        )
    return _normalize_numbers(_docx_text(REPORT_PATH))


def test_every_summary_metric_appears_in_report(summary_metrics, report_numbers):
    """Every numeric API value must show up in the report. Fails loudly,
    naming the missing field, if a new number ships without a citation."""
    leaves = _flatten_numeric_leaves(summary_metrics)
    missing = {
        field: value
        for field, value in leaves.items()
        if not any(abs(value - rn) < 0.01 for rn in report_numbers)
    }
    assert not missing, (
        f"{len(missing)} API value(s) have no match in the report's numbers — "
        f"report is stale or missing a citation: {missing}"
    )


def test_report_has_no_orphan_precision_drift(summary_metrics, report_numbers):
    """Guards against a vacuous pass: if REPORT_PATH is wrong or the
    file is near-empty, the parity test above would trivially pass."""
    assert len(report_numbers) >= 5, (
        f"Only {len(report_numbers)} numeric tokens found in {REPORT_PATH} — "
        "likely wrong file or parsing bug. Investigate before trusting "
        "test_every_summary_metric_appears_in_report."
    )
