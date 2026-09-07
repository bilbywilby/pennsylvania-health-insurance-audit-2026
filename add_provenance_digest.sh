#!/usr/bin/env bash
set -uo pipefail
cd /home/droid/pennsylvania-health-insurance-audit-2026

echo "=== REAL src/provenance.py (never seen this in-session until now) ==="
cat -n src/provenance.py

echo ""
echo "=== REAL HANDOVER.json ==="
cat HANDOVER.json

echo ""
echo "=== pyproject.toml check (project root only — will not touch anything outside repo) ==="
if [ -f pyproject.toml ]; then cat pyproject.toml; else echo "(none at project root)"; fi

git add -A
git commit -q -m "chore: pre-provenance-digest checkpoint" --allow-empty
CHECKPOINT=$(git rev-parse HEAD)
trap 'echo "!!! FAILED — rolling back to $CHECKPOINT"; git reset --hard "$CHECKPOINT"' ERR

echo ""
echo "=== attempting defensive patch of src/provenance.py ==="
python3 - << 'PY'
import re, sys, pathlib

p = pathlib.Path("src/provenance.py")
src = p.read_text()

m = re.search(r'^class Claim\(.*?\):\s*\n', src, re.MULTILINE)
if not m:
    print("!!! Could not find 'class Claim(...):' anchor. "
          "Real class name/signature differs from assumption — "
          "aborting patch WITHOUT touching the file. "
          "See full source above and tell me the actual class definition line.")
    sys.exit(1)

class_start = m.end()
# Find end of class body: next top-level (col-0) 'class ' or 'def ' after class_start
tail = src[class_start:]
end_m = re.search(r'\n(?=class |def )', tail)
insert_at = class_start + (end_m.start() + 1 if end_m else len(tail))

digest_field = '    digest: "str | None" = None\n'

digest_block = '''
    @staticmethod
    def compute_digest(payload: dict) -> str:
        import hashlib, json as _json
        fields = ("claim_id", "value", "source_citation", "source_url",
                  "last_verified", "staleness_days")
        canonical = _json.dumps(
            {k: payload[k] for k in fields if k in payload},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

'''

# Insert field near top of class body (right after class line) and method block before class end
new_src = (
    src[:class_start]
    + digest_field
    + src[class_start:insert_at]
    + digest_block
    + src[insert_at:]
)

# Sanity check: must still be valid Python before we write it
compile(new_src, "src/provenance.py", "exec")

backup = pathlib.Path("src/provenance.py.pre-digest.bak")
backup.write_text(src)
p.write_text(new_src)
print(f"[OK] patched src/provenance.py (backup at {backup})")
print("NOTE: digest field/method added but NOT wired into a @model_validator —")
print("that wiring depends on your actual base class (BaseModel vs dataclass),")
print("which I could not confirm blindly. Enforcement hook left as a manual")
print("follow-up once you review the patched file.")
PY

echo ""
echo "=== resulting src/provenance.py (post-patch, for your review) ==="
cat -n src/provenance.py

source .venv/bin/activate
python -m pytest tests/ -q > /tmp/pytest_prov.log 2>&1 || true
tail -25 /tmp/pytest_prov.log

if grep -qiE "error|failed" /tmp/pytest_prov.log; then
  echo "!!! Not green — rolling back everything, including the patch"
  git reset --hard "$CHECKPOINT"
  exit 1
fi

git add -A
git commit -q -m "feat(provenance): add sha256 digest computation to Claim (unwired, needs manual validator hookup)"

python3 - << 'PY'
import json, pathlib
p = pathlib.Path("HANDOVER.json")
d = json.loads(p.read_text())
d["provenance"] = {
    "status": "digest_helper_added_not_enforced",
    "module": "src/provenance.py",
    "open_items": [
        "compute_digest() added but not yet wired to a validator — enforcement is NOT active",
        "no tests/test_provenance.py yet — do not claim tested until real API (class fields, exceptions) is confirmed from the file above",
        "statutes gate / staleness behavior unverified — same rule applies",
        "digest is tamper-evidence only, unsigned — Ed25519 signing is a future step if authenticity is required"
    ]
}
p.write_text(json.dumps(d, indent=2))
PY
git add -A
git commit -q -m "docs(handover): record provenance digest as unwired, tests as not-yet-written"

if [ ! -f pyproject.toml ]; then
  cat > pyproject.toml << 'TOML'
[tool.pytest.ini_options]
filterwarnings = [
    "ignore::DeprecationWarning:starlette.*",
]
TOML
  git add -A
  git commit -q -m "chore(test): scope-suppress known upstream starlette/fastapi deprecation warnings"
fi

python -m pytest tests/ -q > /tmp/pytest_final2.log 2>&1 || true
tail -10 /tmp/pytest_final2.log
if grep -qiE "error|failed" /tmp/pytest_final2.log; then
  echo "!!! Final check failed — rolling back ALL of this script's commits"
  git reset --hard "$CHECKPOINT"
  exit 1
fi

git push
echo "[OK] done: $(git rev-parse HEAD)"
