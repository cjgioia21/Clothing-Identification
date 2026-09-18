"""Plain-text rendering of deck checks, odds tables and simulation results."""

from __future__ import annotations

from .cards import Category, Deck, Subtype
from .decklist import DECK_SIZE, Issue
from .knowledge import Resolution
from .odds import at_least, cards_seen, mulligan_rate, prized
from .simulate import SimReport


def pct(value: float) -> str:
    return f"{value * 100:5.1f}%"


def composition(deck: Deck, resolution: Resolution) -> dict[str, int]:
    counts = {
        "pokemon": 0,
        "basics": 0,
        "evolutions": 0,
        "trainers": 0,
        "supporters": 0,
        "draw supporters": 0,
        "items": 0,
        "ball/search items": 0,
        "tools": 0,
        "stadiums": 0,
        "energy": 0,
        "basic energy": 0,
    }
    for entry in deck.entries:
        card = resolution.get(entry.name)
        n = entry.count
        if card.category is Category.POKEMON:
            counts["pokemon"] += n
            counts["basics" if card.is_basic_pokemon else "evolutions"] += n
        elif card.category is Category.ENERGY:
            counts["energy"] += n
            if card.is_basic_energy:
                counts["basic energy"] += n
        else:
            counts["trainers"] += n
            if card.is_supporter:
                counts["supporters"] += n
                if card.draw_value:
                    counts["draw supporters"] += n
            elif card.subtype is Subtype.ITEM:
                counts["items"] += n
                if any(e.op == "search" and "pokemon" in e.filter for e in card.effects):
                    counts["ball/search items"] += n
            elif card.subtype is Subtype.TOOL:
                counts["tools"] += n
            elif card.subtype is Subtype.STADIUM:
                counts["stadiums"] += n
    return counts


def render_check(
    deck: Deck,
    resolution: Resolution,
    issues: list[Issue],
    format_issues: list[Issue] | None = None,
    format_name: str = "standard",
) -> str:
    counts = composition(deck, resolution)
    lines = [f"{deck.name} — {deck.size} cards", ""]
    lines.append("Composition")
    for key, value in counts.items():
        if value:
            lines.append(f"  {key:<20}{value:>3}")

    lines += ["", "Opening-hand maths (no draw support)"]
    basics = counts["basics"]
    lines.append(f"  mulligan rate (no Basic in 7)      {pct(mulligan_rate(basics, deck.size or DECK_SIZE))}")
    draw = counts["draw supporters"]
    if draw:
        lines.append(f"  draw supporter in opening 7        {pct(at_least(draw, 7, deck.size))}")
        lines.append(f"  draw supporter by turn 2           {pct(at_least(draw, cards_seen(2), deck.size))}")

    fours = sorted({e.name for e in deck.entries if e.count == 4})
    if fours:
        lines += ["", "Four-ofs: 1+ in opening 7 / prized"]
        for name in fours:
            lines.append(f"  {name:<32}{pct(at_least(4, 7, deck.size))}  {pct(prized(4, deck.size))}")

    if issues:
        lines += ["", "Construction"]
        for issue in issues:
            lines.append(f"  [{issue.level}] {issue.message}")
    else:
        lines += ["", "Construction: 60 cards, no card over its copy limit"]

    if format_issues is not None:
        errors = [i for i in format_issues if i.level == "error"]
        warnings = [i for i in format_issues if i.level == "warning"]
        lines += ["", f"Format ({format_name})"]
        if not errors and not warnings:
            lines.append("  legal — every card is in the current regulation marks")
        for issue in errors + warnings:
            lines.append(f"  [{issue.level}] {issue.message}")

    if resolution.unknown:
        lines += [
            "",
            "Cards the simulator does not know (treated as blanks):",
            "  " + ", ".join(sorted(resolution.unknown)),
            "  Add them with --cards overrides.json to model their effects.",
        ]
    return "\n".join(lines)


def render_sim(report: SimReport) -> str:
    going = "first" if report.going_first else "second"
    lines = [
        f"{report.deck_name} — {report.games} games, going {going}, {report.turns} turns",
        "",
        "Opening",
        f"  mulligan rate                      {pct(report.mulligan_rate)}"
        f"  (avg {report.average_mulligans:.2f} per game)",
        f"  hands with no Basic at all         {pct(report.unplayable_rate)}",
        f"  avg Basics in opening hand         {report.opening_basics:.2f}",
        f"  avg draw supporters in hand        {report.opening_supporters:.2f}",
        f"  avg energy in hand                 {report.opening_energy:.2f}",
        f"  opening hands with no supporter    {pct(report.no_supporter_opening)}",
    ]

    if report.turn_stats:
        lines += ["", "Turn by turn", "  turn  supporter  bench  energy  hand"]
        for stat in report.turn_stats:
            lines.append(
                f"  {stat.turn:>4}  {pct(stat.supporter_rate)}     "
                f"{stat.average_bench:>4.1f}   {stat.average_energy:>4.1f}   {stat.average_hand:>4.1f}"
            )

    if report.goals:
        width = max(len(g.name) for g in report.goals)
        header = "  " + "goal".ljust(width) + "".join(f"  T{t}".rjust(8) for t in range(report.turns + 1))
        lines += ["", "Setup odds (cumulative, card in hand or in play)", header + "     avg   prized"]
        for goal in report.goals:
            row = "  " + goal.name.ljust(width)
            row += "".join(f"{pct(goal.by_turn[t]):>8}" for t in range(report.turns + 1))
            avg = f"{goal.average_turn:.2f}" if goal.average_turn is not None else "  — "
            row += f"  {avg:>6}  {pct(goal.prized)}"
            lines.append(row)
        worst = max(report.goals, key=lambda g: g.never)
        lines.append(
            f"  ±{report.margin(0.5) * 100:.1f}% at 95% confidence; "
            f"worst goal misses {pct(worst.never)} of games ({worst.name})"
        )

    if report.unknown_cards:
        lines += [
            "",
            "Simulated as blank cards: " + ", ".join(sorted(report.unknown_cards)),
        ]
    return "\n".join(lines)


def render_hands(hands: list[list[str]]) -> str:
    lines = []
    for i, hand in enumerate(hands, 1):
        lines.append(f"Hand {i}")
        for name in sorted(hand):
            lines.append(f"  {name}")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_odds_table(deck: Deck, names: list[str], turns: int) -> str:
    lines = [f"{deck.name} — exact odds with no draw support (hypergeometric)", ""]
    header = "  card".ljust(34) + "copies" + "".join(f"  T{t}".rjust(8) for t in range(turns + 1)) + "   prized"
    lines.append(header)
    for name in names:
        copies = deck.count_of(name)
        row = "  " + name.ljust(32) + f"{copies:>4}  "
        row += "".join(f"{pct(at_least(copies, cards_seen(t), deck.size)):>8}" for t in range(turns + 1))
        row += f"  {pct(prized(copies, deck.size)):>7}"
        lines.append(row)
    lines += ["", "T0 is the opening 7; each later turn adds one draw."]
    return "\n".join(lines)


def render_gauntlet(report, rows: int = 0) -> str:
    """The gauntlet result: record, splits, and the matchup table."""
    lines = [
        f"{report.deck_name} vs the gauntlet — {report.opponents} decks × "
        f"{report.games_per_deck} games ({report.games} games)",
        "",
        f"  record            {report.wins}-{report.losses}-{report.ties}"
        f"   ({pct(report.win_rate).strip()} ±{report.margin() * 100:.1f}%)",
        f"  going first       {pct(report.win_rate_first)}   ({report.first_games} games)",
        f"  going second      {pct(report.win_rate_second)}   ({report.second_games} games)",
        f"  prize margin      {report.prize_margin:+.2f} per game"
        f"   ({report.prizes_for / max(1, report.games):.2f} taken,"
        f" {report.prizes_against / max(1, report.games):.2f} given)",
        f"  game length       {report.average_turns / 2:.1f} turns each",
        "  decided by        " + ", ".join(
            f"{reason} {count / max(1, report.games) * 100:.0f}%"
            for reason, count in report.reasons.most_common()
        ),
        f"  card text modelled {pct(report.coverage)}",
    ]
    if report.illegal_cards:
        lines.append(
            "  NOT STANDARD-LEGAL:   " + ", ".join(sorted(report.illegal_cards)[:8])
            + "  (the field is all legal decks)"
        )
    if report.unknown_cards:
        lines.append("  not in the card pool: " + ", ".join(sorted(report.unknown_cards)))
    if report.partial_cards:
        lines.append("  partly modelled:      " + ", ".join(sorted(report.partial_cards)[:8]))

    ordered = report.sorted_matchups()
    if not ordered:
        return "\n".join(lines)

    width = min(34, max(len(m.opponent) for m in ordered))
    header = "  win%   " + "matchup".ljust(width) + "  record    prizes  turns"

    def row(m) -> str:
        return (
            f"  {pct(m.win_rate)}  {m.opponent[:width].ljust(width)}"
            f"  {m.wins}-{m.losses}-{m.ties}".ljust(len(str(m.games)) + 8)
            + f"  {m.prize_margin:+5.1f}  {m.average_turns / 2:5.1f}"
        )

    if rows and rows * 2 < len(ordered):
        lines += ["", f"Worst {rows} matchups", header]
        lines += [row(m) for m in ordered[:rows]]
        lines += ["", f"Best {rows} matchups", header]
        lines += [row(m) for m in reversed(ordered[-rows:])]
    else:
        lines += ["", "Every matchup, worst first", header]
        lines += [row(m) for m in ordered]
    return "\n".join(lines)


def render_comparison(reports: list[SimReport]) -> str:
    goals = [g.name for g in reports[0].goals]
    turns = min(r.turns for r in reports)
    width = max(len(r.deck_name) for r in reports)
    lines = [f"Comparison over {reports[0].games} games each", ""]
    lines.append("  deck".ljust(width + 2) + "  mull".rjust(8) + "".join(f"  T{t}".rjust(8) for t in range(turns + 1)))
    for goal in goals:
        lines.append(f"  goal: {goal}")
        for report in reports:
            stat = next(g for g in report.goals if g.name == goal)
            row = "  " + report.deck_name.ljust(width) + f"{pct(report.mulligan_rate):>8}"
            row += "".join(f"{pct(stat.by_turn[t]):>8}" for t in range(turns + 1))
            lines.append(row)
        lines.append("")
    return "\n".join(lines).rstrip()
