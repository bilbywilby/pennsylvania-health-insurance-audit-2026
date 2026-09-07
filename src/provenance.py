"""src/provenance.py — provenance enforcement for all public-facing artifacts.

Contract:
  * No numeric claim reaches a rendered artifact without a ledger entry.
  * No ledger entry exists without a real citation, a real source_url,
    and a last_verified date.
  * Statutory references additionally require presence in the verified
    column of statutes_2026.json.
  * Stale claims are refused, not silently rendered.

Companion module: src/hardened_renderer.py consumes ArtifactValidator
and Claim via require_claims(); this module is the sole authority on
what is verifiable.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_STALENESS_DAYS = 90
CLAIM_ID_RE = re.compile(r"[a-z0-9]+(_[a-z0-9]+)*")

# Placeholder markers that MUST never reach a rendered artifact.
# Templates use these tokens while drafting; the render gate rejects them.
PLACEHOLDER_MARKERS = (
    "{{", "}}",
    "PENDING_VERIFICATION",
    "TODO",
    "XXX",
    "[PLACEHOLDER",
)

# Sources that look authoritative but aren't — refused at ledger load.
FORBIDDEN_SOURCE_HOSTS = (
    "example.com",
    "example.org",
    "yourdomain",
    "insert-url",
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ProvenanceError(Exception):
    """Base error for all provenance violations."""


class UnknownClaimError(ProvenanceError):
    """An artifact referenced a claim_id absent from the ledger."""


class StaleClaimError(ProvenanceError):
    """A claim exceeded its staleness window."""


class InvalidLedgerError(ProvenanceError):
    """The ledger itself is malformed or contains unverifiable entries."""


# ---------------------------------------------------------------------------
# Claim model
# ---------------------------------------------------------------------------

class Claim(BaseModel):
    """One verifiable factual assertion with full sourcing."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(..., description="Stable unique identifier, snake_case")
    value: Any = Field(..., description="The asserted value (number, string, or object)")
    source_citation: str = Field(..., description="Human-readable citation")
    source_url: str = Field(..., description="Real, resolvable source URL or repo path")
    last_verified: date = Field(..., description="ISO date of last verification")
    staleness_days: int = Field(
        default=DEFAULT_STALENESS_DAYS,
        ge=1,
        description="Days this claim may go unverified before it is refused",
    )
    verified_by: str = Field(..., description="Who or what performed verification")
    notes: str | None = Field(default=None, description="Caveats / known discrepancies")

    @field_validator("claim_id")
    @classmethod
    def _claim_id_pattern(cls, v: str) -> str:
        if not CLAIM_ID_RE.fullmatch(v):
            raise ValueError(f"claim_id must be snake_case ([a-z0-9_]), got: {v!r}")
        return v

    @field_validator("source_url")
    @classmethod
    def _no_placeholder_urls(cls, v: str) -> str:
        for host in FORBIDDEN_SOURCE_HOSTS:
            if host in v:
                raise ValueError(
                    f"source_url {v!r} points at {host} — placeholders are "
                    f"forbidden in the ledger. Verify a real source."
                )
        if not (v.startswith(("http://", "https://")) or Path(v).exists()):
            raise ValueError(
                f"source_url {v!r} is neither an http(s) URL nor an existing repo path"
            )
        return v

    @field_validator("verified_by")
    @classmethod
    def _verified_by_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("verified_by must identify a real verifier (person, "
                             "script+commit, or automated check)")
        return v

    @property
    def stale_after(self) -> date:
        """Date after which this claim is considered stale."""
        return self.last_verified + timedelta(days=self.staleness_days)

    def is_stale(self, as_of: date | None = None) -> bool:
        """True if last_verified is older than the claim's own staleness window."""
        ref = as_of or date.today()
        return ref > self.stale_after


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

class ProvenanceLedger(Mapping[str, Claim]):
    """Loads, indexes, validates, and re-serializes the verification ledger.

    Implements Mapping so callers can do ``"x" in ledger``, ``len(ledger)``,
    and ``ledger["x"]``; iteration yields (claim_id, Claim) pairs, sorted
    for determinism.
    """

    def __init__(self, claims: dict[str, Claim]):
        self._claims = claims

    # -- construction -------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> "ProvenanceLedger":
        """Load and self-validate a ledger file. Raises InvalidLedgerError."""
        if not path.exists():
            raise InvalidLedgerError(f"Ledger not found: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise InvalidLedgerError(f"Ledger {path} is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise InvalidLedgerError(f"Ledger {path} must be a JSON object keyed by claim_id")

        claims: dict[str, Claim] = {}
        for key, entry in raw.items():
            if not isinstance(entry, dict) or key != entry.get("claim_id"):
                raise InvalidLedgerError(
                    f"Ledger key {key!r} does not match its entry's claim_id"
                )
            try:
                claims[key] = Claim(**entry)
            except Exception as exc:
                raise InvalidLedgerError(
                    f"Malformed ledger entry {key!r} in {path}: {exc}"
                ) from exc
        if not claims:
            raise InvalidLedgerError(
                f"Ledger {path} is empty — seed it with real, verified claims"
            )
        return cls(claims)

    def save(self, path: Path) -> None:
        """Serialize deterministically (sorted keys, stable diffs)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {cid: c.model_dump(mode="json") for cid, c in sorted(self._claims.items())}
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    # -- mapping protocol ----------------------------------------------------

    def __getitem__(self, claim_id: str) -> Claim:
        try:
            return self._claims[claim_id]
        except KeyError:
            raise UnknownClaimError(
                f"Claim {claim_id!r} is not in the ledger. A claim must be "
                f"registered with a citation BEFORE it appears in an artifact."
            ) from None

    def __contains__(self, claim_id: object) -> bool:
        return claim_id in self._claims

    def __len__(self) -> int:
        return len(self._claims)

    def __iter__(self) -> Iterator[str]:
        yield from sorted(self._claims)

    # -- mutation --------------------------------------------------------------

    def get(self, claim_id: str) -> Claim:
        """Same as __getitem__ — raises UnknownClaimError if missing."""
        return self[claim_id]

    def register(self, claim: Claim, *, overwrite: bool = False) -> None:
        """Add a claim. Refuses silent replacement unless overwrite=True."""
        if claim.claim_id in self._claims and not overwrite:
            raise ProvenanceError(
                f"Claim {claim.claim_id!r} already registered. Replacing a value "
                f"requires explicit overwrite=True AND a fresh last_verified date."
            )
        self._claims[claim.claim_id] = claim

    def register_many(self, claims: Iterable[Claim], *, overwrite: bool = False) -> None:
        for claim in claims:
            self.register(claim, overwrite=overwrite)

    def refresh(self, claim_id: str, as_of: date, *, verified_by: str) -> None:
        """Mark a claim re-verified as of `as_of` (after an actual re-check)."""
        self[claim_id]  # raises if unknown
        self._claims[claim_id] = self._claims[claim_id].model_copy(
            update={"last_verified": as_of, "verified_by": verified_by}
        )

    def stale_claims(self, as_of: date | None = None) -> list[Claim]:
        return [c for c in self._claims.values() if c.is_stale(as_of)]


def seed_from_golden_fixture(
    fixture_path: Path,
    source_url: str,
    verified_by: str,
    as_of: date | None = None,
) -> ProvenanceLedger:
    """Migrate tests/fixtures/key_statistics_golden.json into a ledger.

    The golden fixture shape is:
      {"golden": {"<claim_id>": {"value": ..., "citation": ...}}, "_meta": {...}}

    The value and citation carry over; source_url and verified_by are NOT
    derivable from the fixture and must be supplied by the caller — this
    function refuses to guess them. Claims the caller knows are volatile
    (e.g. appropriated dollar figures) should be re-registered afterwards
    with shorter staleness_days.
    """
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    golden = raw.get("golden", {})
    if not golden:
        raise InvalidLedgerError(f"No golden rows found in {fixture_path}")

    ledger = ProvenanceLedger({})
    as_of = as_of or date.today()
    for cid, spec in sorted(golden.items()):
        citation = spec.get("citation", "")
        if not citation:
            raise InvalidLedgerError(
                f"Golden row {cid!r} has no citation — it cannot enter the ledger"
            )
        ledger.register(Claim(
            claim_id=cid,
            value=spec["value"],
            source_citation=citation,
            source_url=source_url,
            last_verified=as_of,
            verified_by=verified_by,
        ))
    return ledger


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def extract_claim_ids(node: Any, _depth: int = 0) -> set[str]:
    """Recursively collect every claim_id referenced anywhere in a structure.

    Recognizes:
      * ``{"claim_id": "..."}`` objects, at any nesting depth
      * ``"claim_id:<cid>"`` prefix-strings, at any depth (the convention
        the hardened renderer uses for claim references inside prose)

    Bare strings are deliberately NOT auto-detected — heuristics there
    produce false positives on ordinary text.
    """
    PREFIX = "claim_id:"
    found: set[str] = set()
    if _depth > 200:  # defensive; renderer enforces tighter bounds upstream
        raise ValueError("extract_claim_ids: nesting exceeds 200 levels")
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "claim_id" and isinstance(value, str):
                found.add(value)
            else:
                found |= extract_claim_ids(value, _depth + 1)
    elif isinstance(node, (list, tuple)):
        for item in node:
            found |= extract_claim_ids(item, _depth + 1)
    elif isinstance(node, str) and node.startswith(PREFIX):
        found.add(node[len(PREFIX):].strip())
    return found


def scan_text_for_placeholders(text: str) -> list[str]:
    """Find placeholder markers that must not survive into rendered output."""
    lowered = text.lower()
    return [m for m in PLACEHOLDER_MARKERS if m.lower() in lowered]


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class ArtifactValidator:
    """Validates loaded artifacts against a ledger.

    validate_artifact() collects ALL violations (for CI reports);
    require_claims() raises on the first (for render paths).
    """

    def __init__(
        self,
        ledger: ProvenanceLedger,
        statutes_path: Path | None = None,
        as_of: date | None = None,
    ):
        self.ledger = ledger
        self.as_of = as_of or date.today()
        self.statutes_path = statutes_path
        self._verified_statutes: set[str] | None = None

    # -- statutes gate ---------------------------------------------------------

    @property
    def verified_statutes(self) -> set[str]:
        """The verified column of statutes_2026.json, lazily loaded. Fail-closed."""
        if self._verified_statutes is None:
            if self.statutes_path is None or not self.statutes_path.exists():
                logger.warning(
                    "statutes_2026.json not found at %r — ALL statutory "
                    "references will fail until it exists (fail-closed).",
                    self.statutes_path,
                )
                self._verified_statutes = set()
            else:
                raw = json.loads(self.statutes_path.read_text(encoding="utf-8"))
                # Expected shape: {"verified": {"<citation>": {...}}, ...}
                self._verified_statutes = set(raw.get("verified", {}))
        return self._verified_statutes

    def check_statute(self, citation: str) -> None:
        """Raises ProvenanceError unless the citation is verified."""
        if citation not in self.verified_statutes:
            raise ProvenanceError(
                f"Statutory citation {citation!r} is not in the verified column "
                f"of statutes_2026.json — refusing to render. "
                f"(This is the fabricated-citation guard.)"
            )

    # -- validation --------------------------------------------------------------

    def validate_artifact(self, artifact: Any) -> list[str]:
        """Return ALL violations (does not raise) so CI reports are complete."""
        violations: list[str] = []

        for cid in sorted(extract_claim_ids(artifact)):
            try:
                claim = self.ledger.get(cid)
                if claim.is_stale(self.as_of):
                    violations.append(
                        f"STALE claim {cid!r}: last verified {claim.last_verified} "
                        f"(window {claim.staleness_days}d) — re-verify or drop it"
                    )
            except UnknownClaimError as exc:
                violations.append(str(exc))

        self._collect_statute_refs(artifact, violations)

        for hit in scan_text_for_placeholders(json.dumps(artifact, ensure_ascii=False)):
            violations.append(f"PLACEHOLDER marker {hit!r} present in artifact")

        return violations

    def _collect_statute_refs(self, node: Any, violations: list[str]) -> None:
        if isinstance(node, dict):
            if "statute" in node and isinstance(node["statute"], str):
                try:
                    self.check_statute(node["statute"])
                except ProvenanceError as exc:
                    violations.append(str(exc))
            for value in node.values():
                self._collect_statute_refs(value, violations)
        elif isinstance(node, (list, tuple)):
            for item in node:
                self._collect_statute_refs(item, violations)

    # -- render guard (hard fail) --------------------------------------------------

    def require_claims(self, claim_ids: Iterable[str]) -> list[Claim]:
        """Resolve claims for rendering; raises on unknown or stale.

        Used by renderers (e.g. HardenedProvenanceRenderer): they receive
        resolved Claims only, so an unresolvable reference can never be
        silently substituted with an unlabeled value.
        """
        resolved: list[Claim] = []
        for cid in claim_ids:
            claim = self.ledger.get(cid)  # raises UnknownClaimError
            if claim.is_stale(self.as_of):
                raise StaleClaimError(
                    f"Refusing to render {cid!r}: last verified "
                    f"{claim.last_verified}, staleness window {claim.staleness_days}d"
                )
            resolved.append(claim)
        return resolved


# ---------------------------------------------------------------------------
# CI entry point
# ---------------------------------------------------------------------------

def validate_tree(
    education_root: Path,
    ledger_path: Path,
    statutes_path: Path | None = None,
) -> int:
    """Validate every .json artifact under education_root. Returns exit code."""
    ledger = ProvenanceLedger.load(ledger_path)
    validator = ArtifactValidator(ledger, statutes_path=statutes_path)

    artifacts = [
        p for p in sorted(education_root.rglob("*.json"))
        if p.name != ledger_path.name
    ]
    if not artifacts:
        logger.error("No artifacts found under %s — nothing to validate", education_root)
        return 1

    failures = 0
    for path in artifacts:
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"FAIL {path.relative_to(education_root)}: invalid JSON ({exc})")
            failures += 1
            continue

        violations = validator.validate_artifact(artifact)
        for v in violations:
            print(f"FAIL {path.relative_to(education_root)}: {v}")
            failures += 1
        if not violations:
            print(f" ok   {path.relative_to(education_root)}")

    for claim in ledger.stale_claims():
        print(f"WARN ledger claim {claim.claim_id!r} is stale "
              f"(verified {claim.last_verified}) — needs re-verification")

    if failures:
        print(f"\n{failures} violation(s) across {len(artifacts)} artifact(s)")
        return 1
    print(f"\nAll {len(artifacts)} artifacts pass the provenance gate.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provenance gate for education artifacts")
    parser.add_argument("--education-root", type=Path, default=Path("education"))
    parser.add_argument("--ledger", type=Path,
                        default=Path("education/verification_log.json"))
    parser.add_argument("--statutes", type=Path, default=Path("statutes_2026.json"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    return validate_tree(args.education_root, args.ledger, args.statutes)


if __name__ == "__main__":
    sys.exit(main())
