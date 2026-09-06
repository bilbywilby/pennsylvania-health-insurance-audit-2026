"""Repo-root path resolution — the ONE place paths are anchored.

Inputs may be env-overridden (COUNTY_CSV_PATH); outputs may NEVER be.
Raw files: data/raw/<sourced extracts>. Validated outputs: data/public/.
Quarantine (data/quarantine/) is reserved for unverified inputs — do
not move output paths there.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

def data_input(env_var: str, *rel_parts: str) -> Path:
    return Path(os.getenv(env_var, str(REPO_ROOT.joinpath(*rel_parts))))

def data_output(*rel_parts: str) -> Path:
    return REPO_ROOT.joinpath(*rel_parts)
