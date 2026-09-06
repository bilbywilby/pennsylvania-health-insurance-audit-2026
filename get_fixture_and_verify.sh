#!/usr/bin/env bash
set -uo pipefail
cd /home/droid/pennsylvania-health-insurance-audit-2026

echo "=== GOLDEN FIXTURE (full, this is the contract) ==="
cat tests/fixtures/key_statistics_golden.json

echo ""
echo "=== git status ==="
git status --short

echo ""
echo "=== git log (last 5) ==="
git log --oneline -5

echo ""
echo "=== is origin/main up to date? ==="
git fetch -q
git log --oneline origin/main..HEAD
echo "(empty above = fully pushed)"

echo ""
echo "=== cleanup: remove leftover script + dir, recommit if needed ==="
rm -f commit_cleanup_and_inspect.sh
rmdir .venv_logs 2>/dev/null || rm -rf .venv_logs
git add -A
git commit -q -m "chore(repo): remove leftover helper script and log dir" && git push || echo "nothing to commit/push"
