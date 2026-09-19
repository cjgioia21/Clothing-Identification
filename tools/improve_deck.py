"""Find the card swaps that actually win more games.

Every Standard-legal card the engine can play is tried in the deck, one at a
time, and judged on the only thing that matters: does the deck win more games
against the field with it than without it.

    python tools/improve_deck.py examples/round-toad.txt --workers 4

Three stages, each one narrower and more expensive than the last:

  scan      every candidate against a short paired gauntlet
  semi      the survivors against a longer one
  final     the best handful against the full field, with the matchup deltas

Every stage plays both the baseline and the variant on the *same* seeds against
the *same* field, so most games are identical and the difference between two
decks is measured far more precisely than either deck's win rate is. That is
what makes a few hundred games enough to rank a swap; it is not enough to state
a variant's absolute win rate, and the report does not pretend otherwise.

What comes out is a ranked list of "-1 X, +1 Y" with the change in win rate and
how the worst matchups moved.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokedeck.cards import Category, Deck, DeckEntry, Stage, Subtype  # noqa: E402
from pokedeck.decklist import parse_file  # noqa: E402
from pokedeck.effects import compile_text  # noqa: E402
from pokedeck.gauntlet import load_field, run_gauntlet  # noqa: E402
from pokedeck.knowledge import resolve  # noqa: E402
from pokedeck.legality import ACE_SPEC_LIMIT, card_is_legal  # noqa: E402
from pokedeck.pool import SET_CODES, load_pool  # noqa: E402

CODE_FOR_SET = {v: k for k, v in SET_CODES.items()}
MAX_COPIES = 4
BASIC_ENERGY_LIMIT = 60  # basic Energy is exempt from the four-copy rule


# --------------------------------------------------------------- deck surgery
def variant(deck: Deck, cut: str, add: str, pool, count: int = 1) -> Deck | None:
    """The deck with ``count`` copies of ``cut`` swapped for ``add``.

    None when the swap would break a deck-building rule, so an illegal
    suggestion never reaches the report.
    """
    entries = [DeckEntry(e.count, e.name, e.set_code, e.number, e.category)
               for e in deck.entries]

    removed = 0
    for entry in entries:
        if entry.name == cut:
            take = min(count - removed, entry.count)
            entry.count -= take
            removed += take
    if removed < count:
        return None
    entries = [e for e in entries if e.count > 0]

    card = _legal_print(pool, add)
    if card is None:
        return None
    limit = BASIC_ENERGY_LIMIT if card.is_basic_energy else MAX_COPIES
    existing = next((e for e in entries if e.name == add), None)
    if existing is not None:
        if existing.count + count > limit:
            return None
        existing.count += count
    else:
        if count > limit:
            return None
        entries.append(DeckEntry(count, add, *_print_of(card), card.category))

    if _ace_specs(entries, pool) > ACE_SPEC_LIMIT:
        return None
    built = Deck(entries=entries, name=f"-{count} {cut} +{count} {add}")
    return built if built.size == deck.size else None


def _legal_print(pool, name: str):
    """The Standard-legal print of a card, if it has one.

    pool.lookup returns whichever print sorts first, which can be a rotated
    one — so a scan that qualified a card on a legal print could still write
    an illegal print into the deck it suggests.
    """
    prints = pool.prints(name)
    if not prints:
        return None
    return next((c for c in prints if card_is_legal(c)), None)


def _print_of(card) -> tuple[str | None, str | None]:
    code = CODE_FOR_SET.get(card.set_id)
    if not code:
        return None, None
    return code, card.card_id.split("-")[-1].lstrip("0") or "0"


def _ace_specs(entries: list[DeckEntry], pool) -> int:
    total = 0
    for entry in entries:
        card = pool.lookup(entry.name)
        if card is not None and card.ace_spec:
            total += entry.count
    return total


# ------------------------------------------------------------ what can go in
def playable(card) -> bool:
    """Can the engine play this card as printed, in Standard, today?

    A card whose text the compiler cannot read would be recommended on the
    strength of a rules approximation, so it is left out of the scan and
    counted in the skipped tally instead.
    """
    if not card.known or not card_is_legal(card):
        return False
    if card.category is Category.POKEMON and not card.hp:
        return False
    texts = [card.ability_text or ""] + [a.text for a in card.attacks]
    return not any(compile_text(t)[1] for t in texts)


def candidates(deck: Deck, resolution, pool) -> tuple[list[str], Counter]:
    """Every card worth trying in this deck, and why the rest were skipped."""
    in_deck = {e.name for e in deck.entries}
    basics_in_deck = {name for name in in_deck
                      if (c := resolution.info(name)) and c.is_basic_pokemon}
    lines = set(basics_in_deck)
    # An evolution is only a candidate if this deck already plays what it
    # evolves from — or what evolves from that, for a Stage 2.
    for _ in range(2):
        for card in pool.by_print.values():
            if card.evolves_from in lines:
                lines.add(card.name)

    skipped: Counter = Counter()
    names: dict[str, None] = {}
    for card in pool.by_print.values():
        if card.name in names:
            continue
        if not playable(card):
            skipped["text the engine cannot read, or not Standard-legal"] += 1
            continue
        if card.category is Category.POKEMON and not card.is_basic_pokemon:
            if card.name not in lines:
                skipped["evolves from something this deck does not play"] += 1
                continue
        names[card.name] = None
    return list(names), skipped


# ------------------------------------------------------------------ measuring
@dataclass
class Trial:
    label: str
    cut: str
    add: str
    count: int = 1
    win_rate: float = 0.0
    delta: float = 0.0
    games: int = 0
    per_matchup: dict = dataclass_field(default_factory=dict)


def measure(deck: Deck, field_decks, games: int, seed: int, workers: int, policy: str):
    """Win rate and per-matchup record, on a fixed field with fixed seeds."""
    report = run_gauntlet(deck, resolve(deck), field_decks, games_per_deck=games,
                          seed=seed, policy=policy, workers=workers)
    return report.win_rate, {m.opponent: m.win_rate for m in report.matchups}, report.games


def margin(rate: float, games: int) -> float:
    """95% margin on a win rate — how much of a difference is just noise."""
    if games <= 0:
        return 1.0
    return 1.96 * math.sqrt(max(rate * (1 - rate), 0.01) / games)


def per_deck(total_games: int, field_decks) -> int:
    """Games per opponent needed to reach roughly this many games overall."""
    return max(1, round(total_games / max(1, len(field_decks))))


# ------------------------------------------------------------------- the scan
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("decklist", type=Path)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--policy", default="greedy", help="greedy (fast) or champion")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--cuts", type=int, default=4,
                    help="how many of the deck's own cards to try replacing")
    ap.add_argument("--worth-games", type=int, default=1000,
                    help="games per card in the leave-one-out pass")
    ap.add_argument("--scan-games", type=int, default=1000,
                    help="games per candidate in the first pass")
    ap.add_argument("--semi-games", type=int, default=3000)
    ap.add_argument("--final-games", type=int, default=10000)
    ap.add_argument("--shortlist", type=int, default=40, help="survivors into the semi")
    ap.add_argument("--finalists", type=int, default=10)
    ap.add_argument("--confirm", type=int, default=0,
                    help="re-check the top N with --confirm-policy (slow)")
    ap.add_argument("--confirm-policy", default="champion")
    ap.add_argument("--confirm-games", type=int, default=1000)
    ap.add_argument("--limit", type=int, default=0, help="stop after N candidates")
    args = ap.parse_args()

    def note(text=""):
        print(text, flush=True)

    pool = load_pool()
    deck = parse_file(args.decklist)
    resolution = resolve(deck)
    field = load_field()

    adds, skipped = candidates(deck, resolution, pool)
    note(f"{args.decklist} — {deck.size} cards, {len(deck.entries)} distinct")
    note(f"{len(adds)} playable candidate cards in Standard")
    for reason, count in skipped.most_common():
        note(f"  {count:5} skipped: {reason}")
    if args.limit:
        adds = adds[:args.limit]
        note(f"  (limited to {len(adds)} for this run)")

    filler = _filler(deck, resolution)

    # ---- what each card is worth, measured by taking it out
    worth_n = per_deck(args.worth_games, field)
    base_worth, _, worth_games = measure(deck, field, worth_n, args.seed,
                                         args.workers, args.policy)
    note(f"\nLeave-one-out — swap each card for a {filler} and see what happens")
    note(f"{worth_games} games each, baseline {base_worth:.1%} "
         f"±{margin(base_worth, worth_games):.1%}")
    losses: list[tuple[float, str]] = []
    seen: set[str] = set()
    for entry in deck.entries:
        # A list can name the same card on two lines, for two printings of it.
        if entry.name == filler or entry.name in seen:
            continue
        seen.add(entry.name)
        thinner = variant(deck, entry.name, filler, pool)
        if thinner is None:
            continue
        rate, _, _ = measure(thinner, field, worth_n, args.seed, args.workers, args.policy)
        losses.append((rate - base_worth, entry.name))
    losses.sort(reverse=True)
    worth_noise = margin(base_worth, worth_games)
    note("\n  the deck misses these least")
    for delta, name in losses[:args.cuts]:
        flag = "" if abs(delta) > worth_noise else "   (inside the noise)"
        note(f"  {delta:+6.1%}  without 1 {name}{flag}")
    note("  ... and these most")
    for delta, name in losses[-3:]:
        flag = "" if abs(delta) > worth_noise else "   (inside the noise)"
        note(f"  {delta:+6.1%}  without 1 {name}{flag}")
    cuts = [name for _, name in losses[:args.cuts]]

    # ---- stage one: every candidate, against the weakest card
    scan_n = per_deck(args.scan_games, field)
    base_scan, _, scan_games = measure(deck, field, scan_n, args.seed + 1,
                                       args.workers, args.policy)
    lead_cut = cuts[0]
    note(f"\nScan — every candidate in place of 1 {lead_cut}")
    note(f"{scan_games} games each, baseline {base_scan:.1%} "
         f"±{margin(base_scan, scan_games):.1%}")
    found: list[Trial] = []
    for position, add in enumerate(adds, start=1):
        built = variant(deck, lead_cut, add, pool)
        if built is None:
            continue
        rate, rates, played = measure(built, field, scan_n, args.seed + 1,
                                      args.workers, args.policy)
        found.append(Trial(label=f"-1 {lead_cut}  +1 {add}", cut=lead_cut, add=add,
                           win_rate=rate, delta=rate - base_scan, games=played,
                           per_matchup=rates))
        if position % 50 == 0:
            ahead = sum(1 for t in found if t.delta > 0)
            note(f"  {position}/{len(adds)} tried — {ahead} ahead of the baseline")
    found.sort(key=lambda t: -t.delta)
    ahead = sum(1 for t in found if t.delta > 0)
    if ahead > len(found) * 0.6:
        note(f"  note: {ahead}/{len(found)} beat the baseline, which is too many to be "
             f"the cards —\n  cutting 1 {lead_cut} is an improvement on its own, and every "
             f"variant starts there.\n  The ranking is still sound; the final table splits "
             f"the cut from the card.")
    shortlist = [t for t in found if t.delta > 0][:args.shortlist]
    if not shortlist:
        note("\nNothing beat the deck as it stands.")
        return 0

    # ---- stage two: the survivors, every cut, longer
    semi_n = per_deck(args.semi_games, field)
    base_semi, _, semi_games = measure(deck, field, semi_n, args.seed + 2,
                                       args.workers, args.policy)
    note(f"\nSemi — {len(shortlist)} cards × {len(cuts)} cuts, {semi_games} games each")
    note(f"baseline {base_semi:.1%} ±{margin(base_semi, semi_games):.1%}")
    semi: list[Trial] = []
    for trial in shortlist:
        best: Trial | None = None
        for cut in cuts:
            if cut == trial.add:
                continue
            built = variant(deck, cut, trial.add, pool)
            if built is None:
                continue
            rate, rates, played = measure(built, field, semi_n, args.seed + 2,
                                          args.workers, args.policy)
            candidate = Trial(label=f"-1 {cut}  +1 {trial.add}", cut=cut, add=trial.add,
                              win_rate=rate, delta=rate - base_semi, games=played,
                              per_matchup=rates)
            if best is None or candidate.delta > best.delta:
                best = candidate
        if best is not None:
            semi.append(best)
            note(f"  {best.delta:+6.1%}  {best.label}")
    semi.sort(key=lambda t: -t.delta)
    finalists = [t for t in semi if t.delta > margin(base_semi, semi_games) / 2]
    finalists = finalists[:args.finalists]
    if not finalists:
        note("\nNothing survived the longer sample — every gain was inside the noise.")
        return 0

    # ---- stage three: the full field, enough games to mean something
    final_n = per_deck(args.final_games, field)
    base_full, base_rates, base_games = measure(deck, field, final_n, args.seed + 3,
                                                args.workers, args.policy)
    note(f"\nFinal — {len(finalists)} swaps, {base_games} games each")
    note(f"baseline {base_full:.1%} ±{margin(base_full, base_games):.1%}\n")

    rows: list[Trial] = []
    for trial in finalists:
        built = variant(deck, trial.cut, trial.add, pool)
        rate, rates, played = measure(built, field, final_n, args.seed + 3,
                                      args.workers, args.policy)
        trial.win_rate, trial.delta, trial.games, trial.per_matchup = (
            rate, rate - base_full, played, rates)
        rows.append(trial)
    rows.sort(key=lambda t: -t.delta)

    # How much of each swap is the cut rather than the card being added? Every
    # variant starts from "the deck minus that card", and if the cut is itself
    # an improvement then a candidate that does nothing still looks good.
    cut_only: dict[str, float] = {}
    for cut in {t.cut for t in rows}:
        thinned = variant(deck, cut, filler, pool)
        if thinned is None:
            continue
        rate, _, _ = measure(thinned, field, final_n, args.seed + 3,
                             args.workers, args.policy)
        cut_only[cut] = rate

    noise = margin(base_full, base_games)
    note(f"  {'swap':>7}  {'card':>6}  {'after':>6}   change")
    for trial in rows:
        alone = cut_only.get(trial.cut)
        share = f"{trial.win_rate - alone:+6.1%}" if alone is not None else "     ?"
        flag = "" if abs(trial.delta) > noise else "   (inside the noise)"
        note(f"  {trial.delta:+7.1%}  {share}  {trial.win_rate:6.1%}   {trial.label}{flag}")
    note("\n  swap = against the deck as it stands;  "
         "card = against the same deck with that\n  cut already made and a "
         f"{filler} in its place, which is what the added card is\n  actually worth")
    for cut, rate in sorted(cut_only.items(), key=lambda kv: -kv[1]):
        note(f"    -1 {cut} for a {filler} alone: {rate:.1%} ({rate - base_full:+.1%})")

    # Print what each winner actually says. Twice now a recommendation has been
    # the compiler misreading a rider rather than the card being good, and the
    # printed text beside the number is what makes that visible.
    real = [t for t in rows if t.delta > noise]
    if real:
        note("\n  what these cards say")
        for trial in real:
            card = pool.lookup(trial.add)
            if card is None:
                continue
            lines = [card.ability_text or ""] + [f"{a.name}: {a.text}" for a in card.attacks]
            head = f"{card.hp} HP, {card.prize_value} prize" if card.hp else "Energy"
            note(f"    {trial.add}  ({head})")
            for line in [x for x in lines if x.strip()]:
                note(f"      {line.strip()[:110]}")
    if real:
        best = real[0]
        note(f"\nWhere {best.label.strip()} moved the matchups")
        per_matchup_games = final_n * 2  # both sides of the coin flip
        floor = margin(0.5, per_matchup_games)
        moved = sorted(((best.per_matchup.get(n, 0.0) - was, n, was)
                        for n, was in base_rates.items()), reverse=True)
        shown = [m for m in moved if abs(m[0]) > floor]
        for delta, name, was in shown[:6]:
            if delta <= 0:
                break
            note(f"  {delta:+6.1%}  {name:36} {was:.0%} → {best.per_matchup[name]:.0%}")
        for delta, name, was in reversed(shown[-6:]):
            if delta >= 0:
                break
            note(f"  {delta:+6.1%}  {name:36} {was:.0%} → {best.per_matchup[name]:.0%}")
        note(f"  (only matchups that moved more than ±{floor:.0%}, "
             f"which is the noise on {per_matchup_games} games)")
    else:
        note("\nNothing cleared the noise floor. The deck's problems are not "
             "a single card.")

    # ---- optional: re-check under the searching player
    if args.confirm and real:
        confirm_n = per_deck(args.confirm_games, field)
        note(f"\nConfirming the top {min(args.confirm, len(real))} with the "
             f"{args.confirm_policy} player")
        base_c, _, games_c = measure(deck, field, confirm_n, args.seed + 4,
                                     args.workers, args.confirm_policy)
        note(f"baseline {base_c:.1%} ±{margin(base_c, games_c):.1%} ({games_c} games)")
        for trial in real[:args.confirm]:
            built = variant(deck, trial.cut, trial.add, pool)
            rate, _, played = measure(built, field, confirm_n, args.seed + 4,
                                      args.workers, args.confirm_policy)
            note(f"  {rate - base_c:+7.1%}  {rate:6.1%}   {trial.label}")

    note("\nA swap is only worth acting on if it clears the margin printed beside "
         "the baseline.\nEvery stage plays the variant and the baseline against the "
         "same decks on the same\nseeds, but changing one card reshuffles the deck, "
         "so the games are not identical\nand the difference carries the full "
         "binomial noise.")
    return 0


def _filler(deck: Deck, resolution) -> str:
    """The most-played basic Energy — the least interesting card to add."""
    best, count = "Basic Water Energy", 0
    for entry in deck.entries:
        card = resolution.info(entry.name)
        if card is not None and card.is_basic_energy and entry.count > count:
            best, count = entry.name, entry.count
    return best


if __name__ == "__main__":
    raise SystemExit(main())
