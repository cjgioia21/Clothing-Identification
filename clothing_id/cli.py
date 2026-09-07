"""Command line entry point: clothing-id photo1.jpg photo2.jpg"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from .identify import DEFAULT_MODEL
from .models import Report


def _bar(label: str, value: str) -> str:
    return f"  {label:<22} {value}"


def render(report: Report) -> str:
    ident, tag, visual, value = (
        report.identification,
        report.tag,
        report.visual,
        report.value,
    )
    lines: List[str] = []
    lines.append("")
    lines.append(f"  {ident.item_name}")
    lines.append("  " + "-" * max(len(ident.item_name), 40))
    lines.append(_bar("brand", ident.brand or "unidentified"))
    if ident.sub_label:
        lines.append(_bar("line", ident.sub_label))
    lines.append(_bar("category", f"{ident.category}{f' / {visual.subtype}' if visual.subtype else ''}"))
    lines.append(_bar("era", ident.era))
    lines.append(_bar("size", f"{tag.size or 'unknown'} {tag.size_system or ''}".strip()))
    if tag.fiber_content:
        fibers = ", ".join(
            f"{int(f.percent)}% {f.fiber}" if f.percent is not None else f.fiber
            for f in tag.fiber_content
        )
        lines.append(_bar("fabric", fibers))
    if tag.country_of_origin:
        lines.append(_bar("made in", tag.country_of_origin))
    if tag.rn_number:
        lines.append(_bar("RN", tag.rn_number))
    lines.append(_bar("color", visual.primary_color or "unknown"))
    lines.append(_bar("condition", visual.condition_grade))
    if visual.flaws:
        lines.append(_bar("flaws", "; ".join(visual.flaws)))
    if ident.rarity_signals:
        lines.append(_bar("rarity signals", ", ".join(ident.rarity_signals)))
    lines.append(_bar("id confidence", f"{ident.confidence:.0%}"))

    lines.append("")
    lines.append("  Value estimate")
    lines.append("  " + "-" * 40)
    lines.append(_bar("est. original retail", f"${value.retail_estimate:,.0f} {value.currency}"))
    lines.append(
        _bar("resale range", f"${value.low:,.0f} - ${value.high:,.0f} {value.currency}")
    )
    lines.append(_bar("most likely", f"${value.mid:,.0f} {value.currency}"))
    lines.append(_bar("confidence", f"{value.confidence:.0%}"))

    lines.append("")
    lines.append("  How it was priced")
    for f in value.factors:
        lines.append(f"    {f.multiplier:>9,.2f}  {f.name}{f'  ({f.note})' if f.note else ''}")

    if value.comparables:
        lines.append("")
        lines.append("  Comparables")
        for c in value.comparables:
            price = f"${c.price:,.0f}" if c.price else "n/a"
            lines.append(f"    {price:>9}  {c.title[:60]}{f'  [{c.source}]' if c.source else ''}")

    if value.notes:
        lines.append("")
        lines.append("  Notes")
        for note in value.notes:
            lines.append(f"    - {note}")

    if ident.reasoning:
        lines.append("")
        lines.append("  Reasoning")
        lines.append(f"    {ident.reasoning}")

    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clothing-id",
        description="Identify a garment from photos of its tag and itself, "
        "and estimate a rough resale value.",
    )
    parser.add_argument("images", nargs="+", help="photos of the tag and the garment")
    parser.add_argument("--notes", help="anything you know about the item (unverified)")
    parser.add_argument(
        "--market-check",
        action="store_true",
        help="search live resale listings and anchor the estimate to them",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"model id (default {DEFAULT_MODEL})")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from .pipeline import analyze_paths  # imported late so --help works without deps

    try:
        report = analyze_paths(
            args.images,
            model=args.model,
            notes=args.notes,
            market_check=args.market_check,
            currency=args.currency,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report.model_dump(), indent=2))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
