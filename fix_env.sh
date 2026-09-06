#!/usr/bin/env bash
set -euo pipefail
cd /home/droid/pennsylvania-health-insurance-audit-2026

# 1. Checkpoint using Conventional Commit format to satisfy Git hooks
git add -A
git commit -q -m "chore(env): checkpoint pre-env-fix $(date -Iseconds)" --allow-empty
CHECKPOINT=$(git rev-parse HEAD)

rollback() {
  echo "!!! FAILED — rolling back to $CHECKPOINT"
  git reset --hard "$CHECKPOINT"
}
trap rollback ERR

mkdir -p .venv_logs tests src/api

# 2. Rebuild Virtual Environment
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip -q
# Use --no-cache-dir to ensure a clean slate
pip install -r requirements.txt --no-cache-dir 2>&1 | tee .venv_logs/install.log

# 3. Fix Package Structure
# Ensure src is treated as a package
touch src/__init__.py
touch src/api/__init__.py

# 4. Fix Python Pathing for Pytest
cat <<'PY' > tests/conftest.py
import sys, os
# This ensures 'src' is discoverable regardless of how pytest is invoked
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
PY

# 5. Verify Dependencies
python -c "import fastapi, httpx, pytest; print('[OK] deps verified')"

# 6. Run Tests
echo "🧪 Running tests..."
pytest tests/ -q 2>&1 | tee .venv_logs/pytest.log

if grep -qiE "error|failed" .venv_logs/pytest.log; then
  echo "!!! Tests not green."
  echo "Note: If you see 'ModuleNotFoundError: No module named src.api.main', the source code is missing from the src/ folder."
  tac .venv_logs/pytest.log | grep -m1 -B15 -iE "error|failed"
  exit 1
fi

git add -A
git commit -q -m "fix(env): venv rebuilt, paths patched, tests green"
echo "[OK] Committed clean state: $(git rev-parse HEAD)"
