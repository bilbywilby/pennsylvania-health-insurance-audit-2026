#!/usr/bin/env bash
# CI data-integrity checks: rating areas, rate-change syntax, doc cross-validation.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AREAS="${ROOT}/data/rating_areas_2026.csv"
RATES="${ROOT}/data/approved_rates_2026.csv"
DOCS="${ROOT}/docs/carriers"

errors=0
fail() { echo "[FAIL] $*" >&2; errors=$((errors + 1)); }

# --- 1. rating areas ---
if [ ! -f "${AREAS}" ]; then
    fail "missing ${AREAS}"
else
    ids="$(tail -n +2 "${AREAS}" | cut -d, -f1 | tr -d '"' | sort -n | tr '\n' ' ')"
    [ "${ids}" = "1 2 3 4 5 6 7 8 9 " ] || fail "rating area IDs wrong: ${ids}"

    dupes="$(tail -n +2 "${AREAS}" | cut -d'"' -f2 | tr ',' '\n' \
        | sed 's/^ *//;s/ *$//' | grep -v '^$' | sort | uniq -d)"
    [ -n "${dupes}" ] && fail "counties in multiple areas: $(echo "${dupes}" | tr '\n' ' ')"

    total="$(tail -n +2 "${AREAS}" | cut -d'"' -f2 | tr ',' '\n' \
        | sed 's/^ *//;s/ *$//' | grep -vc '^$')"
    [ "${total}" -eq 67 ] || fail "expected 67 counties, found ${total}"
fi

# --- 2. rates CSV syntax + area refs resolve (process substitution applied) ---
if [ ! -f "${RATES}" ]; then
    fail "missing ${RATES}"
else
    while IFS=, read -r carrier rate _seg areas; do
        case "${carrier}" in carrier_name) continue;; esac
        [ -z "${carrier}" ] && continue
        [[ "${rate}" =~ ^[+-][0-9]{1,2}\.[0-9]%$ ]] \
            || fail "${carrier}: malformed rate '${rate}'"
        
        while read -r ref; do
            [ -z "${ref}" ] && continue
            lo="${ref%%-*}"
            case "${lo}" in ''|*[!0-9]*) fail "${carrier}: bad area ref '${ref}'";; esac
        done < <(tr ';' '\n' <<< "${areas}" | sed 's/ //g')
    done < "${RATES}"
fi

# --- 3. carrier docs match CSV ---
if [ -d "${DOCS}" ]; then
    while IFS=, read -r carrier rate _seg _areas; do
        case "${carrier}" in carrier_name) continue;; esac
        [ -z "${carrier}" ] && continue
        slug="$(printf '%s' "${carrier}" | tr '[:upper:]' '[:lower:]' \
            | sed -e 's/[(),.]//g' -e 's/&/and/g' -e 's/ /_/g')"
        doc="${DOCS}/${slug}.md"
        if [ ! -f "${doc}" ]; then
            fail "no carrier doc for ${carrier} (expected ${slug}.md)"
        else
            got="$(grep -m1 '^\* \*\*Approved Rate Change:\*\*' "${doc}" \
                | sed 's/.*\*\*\([^*]*\)$/\1/' | tr -d '* ')"
            [ "${got}" = "${rate}" ] || fail "${slug}.md says '${got}' but CSV says '${rate}'"
        fi
    done < "${RATES}"
fi

if [ "${errors}" -gt 0 ]; then
    echo "${errors} error(s) — CI failing." >&2
    exit 1
fi
echo "All integrity checks passed."
