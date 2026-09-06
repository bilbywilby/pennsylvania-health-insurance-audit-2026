"""Repo scan: the 'na_applicable' typo class must never resurface.

Scans every non-test Python file for response keys ending in
'_applicable' and requires them to be exactly 'nsa_applicable'.
New compliance endpoints inherit this guard automatically.
"""
import re
from pathlib import Path

ALLOWED_KEY = re.compile(r'"(nsa)_applicable"')
FORBIDDEN = re.compile(r'"(?!nsa)[a-z]+_applicable"')
BASE = Path(__file__).resolve().parent.parent


def test_no_misspelled_applicable_keys():
    offenders = []
    scanned = 0
    for py_file in BASE.rglob("*.py"):
        rel = py_file.relative_to(BASE).as_posix()
        if rel.startswith(("tests/", ".venv/", "venv/")) or "__pycache__" in rel:
            continue
        scanned += 1
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), start=1):
            if FORBIDDEN.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, "Misspelled '_applicable' keys found:\n" + "\n".join(offenders)
