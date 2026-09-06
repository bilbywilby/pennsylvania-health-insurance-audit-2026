#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Starting repository bootstrap sequence..."
for script in bootstrap/[0-9][0-9]_*.py; do
  echo "== Running $script =="
  python3 "$script"
done
echo "Bootstrap complete. Next: make -n audit && make audit"
