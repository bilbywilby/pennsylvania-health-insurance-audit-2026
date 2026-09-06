#!/usr/bin/env python3
"""
Renders aggregate reports (data/private/*.csv) as static SVG figures
into docs/figures/. Pure standard library - no dependencies.
Figures carry a source watermark noting synthetic vs. real data provenance.
"""
import csv
from pathlib import Path

DATA_PRIVATE = Path("data/private")
FIGURES_DIR = Path("docs/figures")

BAR_COLOR = "#6d4aff"
NEG_BAR_COLOR = "#b9a9ff"
AXIS_COLOR = "#333"
BG_COLOR = "#ffffff"


def load_csv(path: Path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_hbar_svg(title, subtitle, items, value_fmt, stem, footer_note):
    """items: list of (label, value). Horizontal bars, largest magnitude first."""
    if not items:
        print(f"[SKIP] No data for: {title}")
        return 0
    items = sorted(items, key=lambda x: abs(x[1]), reverse=True)
    n = len(items)
    bar_h, gap, label_w, pad_r, pad_top = 34, 14, 220, 130, 90
    width, height = 760, pad_top + n * (bar_h + gap) + 20
    max_val = max(abs(v) for _, v in items) or 1.0
    plot_w = width - label_w - pad_r

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="sans-serif">',
        f'<rect width="100%" height="100%" fill="{BG_COLOR}"/>',
        f'<text x="{label_w}" y="34" font-size="20" font-weight="bold" fill="{AXIS_COLOR}">{esc(title)}</text>',
        f'<text x="{label_w}" y="58" font-size="12" fill="#666">{esc(subtitle)}</text>',
    ]
    for i, (label, value) in enumerate(items):
        y = pad_top + i * (bar_h + gap)
        bar_w = max(2.0, abs(value) / max_val * (plot_w - 10))
        color = NEG_BAR_COLOR if value < 0 else BAR_COLOR
        bar_x = label_w if value >= 0 else label_w - bar_w
        parts.append(
            f'<text x="{label_w - 10}" y="{y + bar_h * 0.68}" font-size="13" '
            f'fill="{AXIS_COLOR}" text-anchor="end">{esc(label)}</text>'
        )
        parts.append(
            f'<rect x="{bar_x:.1f}" y="{y}" width="{bar_w:.1f}" height="{bar_h}" '
            f'fill="{color}" rx="3"/>'
        )
        txt_x = (bar_x + bar_w + 8) if value >= 0 else (bar_x - 8)
        anchor = "start" if value >= 0 else "end"
        parts.append(
            f'<text x="{txt_x:.1f}" y="{y + bar_h - 11}" font-size="13" fill="{AXIS_COLOR}" '
            f'text-anchor="{anchor}">{esc(value_fmt.format(value))}</text>'
        )
    parts.append(f'<text x="{label_w}" y="{height - 8}" font-size="11" fill="#999">{esc(footer_note)}</text>')
    parts.append("</svg>")

    svg_path = FIGURES_DIR / f"{stem}.svg"
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text("\n".join(parts), encoding="utf-8")
    print(f"[OK] {svg_path}")
    return 1


def main():
    made = 0

    # Figure 1: weighted avg carrier rate change by rating area
    items = [
        (f"Area {r['rating_area']}", float(r["weighted_avg_rate_change"]))
        for r in load_csv(DATA_PRIVATE / "carrier_aggregates_2026.csv")
    ]
    if items:
        top = max(items, key=lambda x: abs(x[1]))
        made += render_hbar_svg(
            "Weighted Avg Rate Change by Rating Area",
            f"Largest move: {top[0]} at {top[1]:+.1f}% (weighted by covered lives)",
            items, "{:+.1f}%", "carrier_rate_change_by_area",
            "SOURCE: data/private/carrier_aggregates_2026.csv - synthetic fixtures unless real data loaded.",
        )

    # Figure 2: termination rate by rating area (requires enrollee denominators)
    items = []
    for r in load_csv(DATA_PRIVATE / "county_termination_aggregates_2026.csv"):
        try:
            rate = float(r["termination_rate_pct"].rstrip("%"))
        except (ValueError, KeyError):
            continue
        try:
            enrollees = float(r.get("total_enrollees", 0) or 0)
        except ValueError:
            enrollees = 0.0
        if enrollees > 0:
            items.append((f"Area {r['rating_area']}", rate))
    if items:
        top = max(items, key=lambda x: x[1])
        made += render_hbar_svg(
            "Termination Rate by Rating Area",
            f"Highest: {top[0]} at {top[1]:.2f}%",
            items, "{:.2f}%", "termination_rate_by_area",
            "Termination rate = terminations / total enrollees. SOURCE: county_termination_aggregates_2026.csv.",
        )

    # Figure 3: weighted avg absolute monthly rate by rating area (audit engine)
    items = [
        (f"Area {r['rating_area']}", float(r["weighted_avg_rate"]))
        for r in load_csv(DATA_PRIVATE / "audit_aggregates_2026.csv")
    ]
    if items:
        top = max(items, key=lambda x: x[1])
        made += render_hbar_svg(
            "Weighted Avg Monthly Rate by Rating Area",
            f"Highest: {top[0]} at ${top[1]:,.2f}",
            items, "${:,.2f}", "audit_rates_by_area",
            "SOURCE: data/private/audit_aggregates_2026.csv - synthetic fixtures unless real data loaded.",
        )

    print(f"\n{made} figure(s) written to docs/figures/")
    if made == 0:
        print("No aggregates found. Generate reports first: bash tests/fixtures/run_fixtures.sh")


if __name__ == "__main__":
    main()
