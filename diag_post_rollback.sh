#!/usr/bin/env bash
set -uo pipefail
cd /home/droid/pennsylvania-health-insurance-audit-2026

echo "=== git log (last 6) ==="
git log --oneline -6

echo ""
echo "=== what actually landed in the last 3 commits ==="
git show --stat HEAD
git show --stat HEAD~1
git show --stat HEAD~2

echo ""
echo "=== does src/provenance.py currently contain compute_digest or a digest field? ==="
grep -n "digest" src/provenance.py || echo "(no match — digest patch is NOT present)"

echo ""
echo "=== current HANDOVER.json ==="
cat HANDOVER.json

echo ""
echo "=== current pyproject.toml (if it survived) ==="
cat pyproject.toml 2>/dev/null || echo "(not present)"

echo ""
echo "=== the actual commit-msg hook rule (so we stop guessing) ==="
for f in .git/hooks/commit-msg .husky/commit-msg commitlint.config.js commitlint.config.cjs .commitlintrc .commitlintrc.json .commitlintrc.js package.json; do
  if [ -f "$f" ]; then
    echo "--- $f ---"
    cat "$f"
    echo ""
  fi
done

echo ""
echo "=== leftover backup file from the failed patch attempt ==="
ls -la src/provenance.py.pre-digest.bak 2>/dev/null || echo "(none)"

echo ""
echo "=== working tree status ==="
git status --short
