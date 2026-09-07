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

    check = report.verification
    if check.rn_number:
        if check.registrant:
            mark = "confirms brand" if check.brand_matches_rn else "DOES NOT match brand"
            lines.append(_bar("RN registrant", f"{check.registrant} ({mark})"))
        elif check.lookup_url:
            lines.append(_bar("verify RN at", check.lookup_url))

    basis = {
        "observed": "priced from observed sales",
        "blended": "observed sales blended with the model",
        "modeled": "modeled - no market data",
    }[value.method]

    lines.append("")
    lines.append("  Value estimate")
    lines.append("  " + "-" * 40)
    lines.append(_bar("basis", basis))
    lines.append(
        _bar("resale range", f"${value.low:,.0f} - ${value.high:,.0f} {value.currency}")
    )
    lines.append(_bar("most likely", f"${value.mid:,.0f} {value.currency}"))
    if value.market_price is not None and value.method != "observed":
        lines.append(_bar("observed sales say", f"${value.market_price:,.0f}"))
    if value.model_price is not None and value.method != "modeled":
        lines.append(_bar("model says", f"${value.model_price:,.0f}"))
    lines.append(_bar("est. original retail", f"${value.retail_estimate:,.0f} {value.currency}"))
    lines.append(_bar("confidence", f"{value.confidence:.0%}"))

    ev = value.evidence
    if ev:
        lines.append("")
        lines.append("  Evidence")
        lines.append(
            _bar("listings used", f"{ev.observation_count} ({ev.sold_count} sold, {ev.ask_count} asking)")
        )
        if ev.first_observed:
            lines.append(_bar("covering", f"{ev.first_observed} to {ev.last_observed}"))
        lines.append(_bar("sample median", f"${ev.raw_median:,.0f}"))
        lines.append(_bar("spread (p20-p80)", f"{ev.dispersion:.0%} of mid"))
        if ev.annual_trend is not None:
            lines.append(_bar("price trend", f"{ev.annual_trend:+.1%} per year"))
        if ev.sources:
            lines.append(
                _bar("sources", ", ".join(f"{k}: {v}" for k, v in sorted(ev.sources.items())))
            )
        if ev.outliers_dropped:
            lines.append(_bar("outliers dropped", str(ev.outliers_dropped)))

    lines.append("")
    lines.append("  How it was priced")
    for f in value.factors:
        lines.append(f"    {f.multiplier:>9,.2f}  {f.name}{f'  ({f.note})' if f.note else ''}")

    if value.comparables:
        lines.append("")
        lines.append("  Comparables")
        for c in value.comparables[:12]:
            price = f"${c.price:,.0f}" if c.price else "n/a"
            mark = "sold" if c.sold else "ask "
            when = c.observed_on or ""
            lines.append(f"    {price:>9}  {mark}  {when:<10}  {c.title[:48]}")
            if c.url:
                lines.append(f"{'':>16}{c.url}")

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
        description="Identify a garment from photos of its tag and itself, and price it "
        "from real sales data.",
    )
    sub = parser.add_subparsers(dest="command")

    identify = sub.add_parser("identify", help="identify and price a garment (default)")
    identify.add_argument("images", nargs="+", help="photos of the tag and the garment")
    identify.add_argument("--notes", help="anything you know about the item (unverified)")
    identify.add_argument(
        "--offline",
        action="store_true",
        help="do not query live marketplaces; price from stored history only",
    )
    identify.add_argument("--db", help="path to the history database")
    identify.add_argument("--model", default=DEFAULT_MODEL, help=f"model id (default {DEFAULT_MODEL})")
    identify.add_argument("--currency", default="USD")
    identify.add_argument("--json", action="store_true", help="print the full report as JSON")

    importer = sub.add_parser("import", help="import real sales records from a CSV")
    importer.add_argument("csv", help="CSV export of sold listings or your own sales log")
    importer.add_argument("--source", default="import", help="label for where these came from")
    importer.add_argument(
        "--kind",
        default="sold",
        choices=["sold", "ask"],
        help="what the rows are, when the file does not say (default sold)",
    )
    importer.add_argument("--db", help="path to the history database")

    stats = sub.add_parser("stats", help="show what price history is on file")
    stats.add_argument("--db", help="path to the history database")
    stats.add_argument("--json", action="store_true")

    return parser


def _split_argv(argv: List[str]) -> List[str]:
    """Allow `clothing-id photo.jpg` as shorthand for `clothing-id identify photo.jpg`."""
    commands = {"identify", "import", "stats"}
    if argv and argv[0] not in commands and not argv[0].startswith("-"):
        return ["identify", *argv]
    if not argv:
        return argv
    return argv


def main(argv: List[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(_split_argv(raw))

    if args.command == "import":
        return _run_import(args)
    if args.command == "stats":
        return _run_stats(args)
    if args.command != "identify":
        build_parser().print_help()
        return 1

    from .pipeline import analyze_paths  # imported late so --help works without deps

    history = None
    try:
        if args.db:
            from .history import SalesHistory

            history = SalesHistory(args.db)
        report = analyze_paths(
            args.images,
            model=args.model,
            notes=args.notes,
            market=not args.offline,
            history=history,
            currency=args.currency,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if history is not None:
            history.close()

    if args.json:
        print(json.dumps(report.model_dump(), indent=2))
    else:
        print(render(report))
    return 0


def _run_import(args) -> int:
    from .history import SalesHistory, import_csv

    history = SalesHistory(args.db) if args.db else SalesHistory()
    try:
        read, added = import_csv(
            args.csv, history=history, source=args.source, default_kind=args.kind
        )
    except FileNotFoundError:
        print(f"error: no such file: {args.csv}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        stats = history.stats()
        history.close()
    print(
        f"Read {read} priced row(s) from {args.csv}; stored {added} new, "
        f"{read - added} already on file."
    )
    print(f"History now holds {stats['observations']} observation(s) at {stats['database']}.")
    return 0


def _run_stats(args) -> int:
    from .history import SalesHistory

    history = SalesHistory(args.db) if args.db else SalesHistory()
    try:
        stats = history.stats()
    finally:
        history.close()

    if getattr(args, "json", False):
        print(json.dumps(stats, indent=2))
        return 0

    print()
    print(f"  Database              {stats['database']}")
    print(f"  Observations          {stats['observations']} "
          f"({stats['sold']} sold, {stats['asks']} asking)")
    if stats["first_seen"]:
        print(f"  Covering              {stats['first_seen']} to {stats['last_seen']}")
    if stats["by_source"]:
        print("  By source")
        for source, n in stats["by_source"].items():
            print(f"    {n:>7}  {source}")
    if stats["top_brands"]:
        print("  Most-recorded brands")
        for brand, n in stats["top_brands"].items():
            print(f"    {n:>7}  {brand}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
