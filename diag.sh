#!/usr/bin/env bash
set -uo pipefail
cd /home/droid/pennsylvania-health-insurance-audit-2026 || exit 1
OUT="/tmp/pa_audit_diag.log"

{
  echo "=== PWD ==="; pwd
  echo "=== GIT STATUS ==="; git status --short
  echo "=== GIT LOG (last 10) ==="; git log --oneline -10
  echo "=== .venv EXISTS? ==="; ls -la .venv 2>&1 | head -5
  echo "=== PYTHON/PIP BEFORE ACTIVATE ==="; which python3 pip3
  source .venv/bin/activate 2>&1
  echo "=== PYTHON/PIP AFTER ACTIVATE ==="; which python pip; python --version
  echo "=== INSTALLED PACKAGES ==="; pip list --format=freeze
  echo "=== requirements.txt ==="; cat requirements.txt 2>&1
  echo "=== MISSING PACKAGES (required not installed) ==="
  comm -23 <(sed 's/[<>=!~].*//' requirements.txt | sort -u) <(pip list --format=freeze | sed 's/==.*//' | sort -u)
  echo "=== PYTEST (last error block, newest first via tac) ==="
  pytest tests/ -q > /tmp/pytest_raw.log 2>&1
  tac /tmp/pytest_raw.log | grep -m1 -B15 -iE "error|failed" || echo "no error block found"
  echo "=== FULL PYTEST TAIL ==="; tail -30 /tmp/pytest_raw.log
  echo "=== TREE (3 levels, no .git/.venv) ==="
  find . -maxdepth 3 -not -path '*/.git*' -not -path '*/.venv*' | sort
} > "$OUT" 2>&1

cat "$OUT"
echo ""
echo ">>> Full log also saved to $OUT — paste the whole thing back if truncated."
