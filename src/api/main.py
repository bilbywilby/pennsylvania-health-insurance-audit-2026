"""FastAPI app serving verified PA ACA marketplace key statistics.

All figures in /metrics/summary are loaded from data/public/key_statistics_2026.json
— a cited, version-controlled data file. This module contains no hardcoded
statistics; changing a number here means changing that file (with a citation).
"""
import json
from pathlib import Path
from fastapi import FastAPI

DATA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "public" / "key_statistics_2026.json"
)

app = FastAPI(title="PA ACA Marketplace Key Statistics API")


def _load_stats() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


@app.get("/metrics/summary")
def metrics_summary():
    data = _load_stats()
    out = {k: v["value"] for k, v in data["metrics"].items()}
    out["act54_pennie_published_50m_impact"] = data["act54_pennie_published_50m_impact"]
    out["roi_note"] = data.get("roi_note", "")
    out["provenance"] = data.get("provenance", "")
    return out
