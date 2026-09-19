"""Check that every card in a deck actually does something when it is played.

    python tools/audit_cards.py                       # the gauntlet field
    python tools/audit_cards.py --decks my-deck.txt   # your own list

Each card is put into a controlled game and used: a Trainer is played, an
Ability is switched on, an attack is made. If nothing about the game changes,
the card is reported as inert — it is in the deck, but the simulation is
playing it as a blank.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokedeck.battle import Battle, BattleDeck, Side, Spot  # noqa: E402
from pokedeck.cards import Card, Category, Subtype  # noqa: E402
from pokedeck.decklist import parse_file  # noqa: E402
from pokedeck.effects import compile_text  # noqa: E402
from pokedeck.knowledge import Resolution, resolve  # noqa: E402
from pokedeck.policy import Policy  # noqa: E402
from pokedeck.pool import load_pool  # noqa: E402
from pokedeck.scripts import run  # noqa: E402

# Cards whose behaviour lives in the engine rather than in an effect script.
ENGINE_HANDLED = {
    "Rare Candy": "evolution skips the middle stage",
    "Antique Cover Fossil": "played as a Basic Pokémon",
}


def snapshot(battle: Battle) -> tuple:
    """Everything a card could plausibly change, in one comparable blob."""
    def side_state(side: Side) -> tuple:
        return (
            len(side.hand), len(side.deck), len(side.discard), len(side.prizes),
            side.prizes_taken, len(side.bench),
            side.active.name if side.active else "",      # a gust changes this
            side.active.damage if side.active else 0,
            tuple(sorted((s.name, s.damage, len(s.energy), s.condition or "",
                          s.tool.name if s.tool else "") for s in side.in_play())),
            tuple(c.name for c in side.deck[:3]),   # a card put on top moves these
            side.items_locked_until, side.locked_attack,
        )
    return (
        side_state(battle.sides[0]),
        side_state(battle.sides[1]),
        battle.stadium.name if battle.stadium else "",
    )


def staged_battle(resolution: Resolution, deck: BattleDeck) -> Battle:
    """A mid-game position: both sides set up, cards in every zone."""
    battle = Battle((deck, deck), (Policy(), Policy()), random.Random(7), first=0)
    battle.setup()
    battle.turn = 5
    # A card that recovers something needs something to recover, and a card
    # that counts Items in a discard pile needs a discard pile.
    for side in battle.sides:
        side.discard.extend(side.deck[:4])
        del side.deck[:4]
    for side in battle.sides:
        # A switch needs somewhere to switch to, so make sure both benches exist.
        while len(side.bench) < 2:
            spare = next((c for c in side.deck if c.is_basic_pokemon), None)
            if spare is None:
                break
            side.deck.remove(spare)
            side.bench_pokemon(spare, 1)
    pool = load_pool()
    tool = pool.lookup("Bravery Charm", "PAL", "173")
    special = pool.lookup("Prism Energy", "ASC", "216")
    for side in battle.sides:
        side.supporter_used = False
        side.energy_attached = 0
        side.stadium_used = False
        side.retreated = False
        # A knockout last turn and a late-game prize count, so a card that may
        # only be played in those spots is judged on what it does rather than
        # on a condition the staging forgot to set up.
        side.lost_on_turn = battle.turn - 1
        del side.prizes[:3]
        if side.active is not None:
            side.active.damage = 30
        for spot in side.in_play():
            spot.turn_played = 1
            spot.ability_used_turn = -1
            # Energy to move, strip or count, and a Tool to knock off.
            energy = next((c for c in side.deck if c.category is Category.ENERGY), None)
            if energy is not None:
                side.deck.remove(energy)
                spot.energy.extend([energy, special])
            if spot.tool is None:
                spot.tool = tool
        # Something worth recovering, for the cards that reach into the discard.
        for wanted in (lambda c: c.category is Category.POKEMON,
                       lambda c: c.category is Category.ENERGY,
                       lambda c: c.subtype is Subtype.SUPPORTER,
                       lambda c: c.subtype is Subtype.ITEM):
            found = next((c for c in side.deck if wanted(c)), None)
            if found is not None:
                side.deck.remove(found)
                side.discard.append(found)
    # The top of the deck gets one of everything, so a card that looks at the
    # top few and takes what it likes has something to take.
    for side in battle.sides:
        for wanted in (lambda c: c.category is Category.POKEMON,
                       lambda c: c.category is Category.ENERGY,
                       lambda c: c.is_supporter,
                       lambda c: c.subtype is Subtype.ITEM):
            found = next((c for c in side.deck if wanted(c)), None)
            if found is not None:
                side.deck.remove(found)
                side.deck.insert(0, found)
    return battle


def exercise(battle: Battle, card: Card) -> bool:
    """Use the card the way its type says it is used. True if anything moved."""
    side = battle.sides[0]
    before = snapshot(battle)

    if card.category is Category.TRAINER and card.subtype in (Subtype.ITEM, Subtype.SUPPORTER):
        side.hand.append(card)
        run(battle, 0, card.effects)
        if card in side.hand:
            side.hand.remove(card)
    elif card.subtype is Subtype.STADIUM:
        battle.stadium, battle.stadium_owner = card, 0
        side.stadium_used = False
        effects = battle.stadium_ability(0)
        if effects:
            run(battle, 0, effects)
    elif card.subtype is Subtype.TOOL:
        spot = side.active
        if spot is None:
            return False
        spot.tool = card
        return bool(card.effects) or spot.max_hp != (spot.card.hp or 60)
    elif card.category is Category.ENERGY:
        spot = side.active
        if spot is None:
            return False
        spot.energy.append(card)
        return bool(card.energy_provides) or bool(card.effects)
    elif card.category is Category.POKEMON:
        spot = Spot(stack=[card], turn_played=1)
        side.bench.append(spot)
        moved = False
        if card.ability:
            run(battle, 0, card.ability, spot)
            moved = snapshot(battle) != before
        for attack in card.attacks:
            target = battle.sides[1].active
            if target is None:
                break
            plan = battle.attack_plan(0, attack, spot, target)
            damage = battle.attack_damage(0, attack, spot, target, plan)
            if damage or attack.effects:
                moved = True
        if spot in side.bench:
            side.bench.remove(spot)   # it may have knocked itself out
        return moved

    return snapshot(battle) != before


def audit(paths: list[str]) -> int:
    seen: dict[str, Card] = {}
    for path in paths:
        deck = parse_file(path)
        resolution = resolve(deck)
        for name, card in resolution.cards.items():
            seen.setdefault(name, card)

    deck = parse_file(paths[0])
    resolution = resolve(deck)
    built = BattleDeck.build(deck, resolution)

    verdicts: Counter = Counter()
    inert: list[str] = []
    partial: list[str] = []
    for name, card in sorted(seen.items()):
        battle = staged_battle(resolution, built)
        try:
            works = exercise(battle, card)
        except Exception as error:  # a card that crashes the engine is a failure
            print(f"  ERROR {name}: {type(error).__name__}: {error}")
            verdicts["error"] += 1
            continue
        leftover = compile_text(card.ability_text or "")[1] if card.ability_text else []
        leftover += [s for attack in card.attacks for s in compile_text(attack.text)[1]]
        if not works and name in ENGINE_HANDLED:
            verdicts["works"] += 1
        elif not works:
            inert.append(name)
            verdicts["inert"] += 1
        elif leftover:
            partial.append(f"{name}: {leftover[0][:70]}")
            verdicts["partial"] += 1
        else:
            verdicts["works"] += 1

    total = sum(verdicts.values())
    print(f"\n{total} distinct cards audited")
    for verdict in ("works", "partial", "inert", "error"):
        if verdicts[verdict]:
            print(f"  {verdict:8} {verdicts[verdict]:4}  ({verdicts[verdict] / total:.0%})")
    if inert:
        print("\nInert — played, nothing happened:")
        for name in inert:
            print(f"  {name}")
    if partial:
        print("\nPartly modelled — works, but some text is not read:")
        for line in partial[:20]:
            print(f"  {line}")
    return 1 if verdicts["error"] or verdicts["inert"] else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decks", nargs="*")
    args = parser.parse_args()
    paths = args.decks or sorted(str(p) for p in Path("pokedeck/data/gauntlet").glob("*.txt"))
    return audit(paths)


if __name__ == "__main__":
    raise SystemExit(main())
