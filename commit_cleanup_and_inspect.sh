#!/usr/bin/env bash
set -uo pipefail
cd /home/droid/pennsylvania-health-insurance-audit-2026

echo "=== committing pending cleanup (.gitignore, removed scaffold scripts) ==="
git add -A
git commit -q -m "chore(repo): remove scaffold scripts, harden .gitignore" && echo "[OK] committed" || echo "nothing to commit"
git push

echo ""
echo "=== golden fixture (the contract main.py must satisfy) ==="
cat tests/fixtures/key_statistics_golden.json

echo ""
echo "=== existing aggregate computation (does a pipeline already produce these numbers?) ==="
cat bootstrap/04_audit.py

echo ""
echo "=== schema_reconciliation.py (likely source of computed exposure/rate figures) ==="
cat scripts/schema_reconciliation.py

echo ""
echo "=== computed data files main.py would read from ==="
head -5 data/private/*.csv

echo ""
echo "=== current src tree ==="
find src -type f
