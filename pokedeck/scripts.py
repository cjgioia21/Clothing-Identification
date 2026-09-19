"""Execution of effect scripts during a battle (Trainers, Abilities, Energy)."""

from __future__ import annotations

from .cards import Card, Category, Effect, Stage, Subtype

MATCHERS = {
    "any": lambda c: True,
    "pokemon": lambda c: c.category is Category.POKEMON,
    "basic_pokemon": lambda c: c.is_basic_pokemon and not c.fossil,
    "item": lambda c: c.subtype is Subtype.ITEM,
    "tool": lambda c: c.subtype is Subtype.TOOL,
    "supporter": lambda c: c.is_supporter,
    "stadium": lambda c: c.subtype is Subtype.STADIUM,
    "energy": lambda c: c.category is Category.ENERGY,
    "basic_energy": lambda c: c.is_basic_energy,
    "evolution": lambda c: c.category is Category.POKEMON and not c.is_basic_pokemon,
    "fossil": lambda c: c.fossil,
}


def matches(card: Card, filter_: str) -> bool:
    return MATCHERS.get(filter_, lambda c: False)(card)


def run(battle, index: int, effects, spot=None) -> None:
    """Apply an effect script for the player at ``index``."""
    for effect in effects:
        if effect.chance < 100 and battle.rng.randrange(100) >= effect.chance:
            continue  # the coin came down the other way
        _apply(battle, index, effect, spot)


def useful(battle, index: int, effects, spot=None) -> bool:
    """Would this script do anything right now?"""
    side = battle.sides[index]
    policy = battle.policies[index]
    for effect in effects:
        op = effect.op
        if op in ("draw", "shuffle_hand_into_deck", "discard_hand"):
            if policy.wants_draw(battle, index, effect.n or 5):
                return True
            continue
        if op == "draw_prizes":
            if policy.wants_draw(battle, index, side.prizes_left()):
                return True
            continue
        if op == "draw_to":
            if len(side.hand) < effect.n and policy.wants_draw(battle, index, effect.n):
                return True
            continue
        if op == "search":
            if battle.policies[index].wants_search(battle, index, effect):
                return True
            continue
        if op == "recover" and any(
            matches(c, effect.filter) if effect.filter != "any" else True for c in side.discard
        ):
            return True
        if op == "dig" and any(matches(c, effect.filter) for c in side.deck[:effect.n]):
            return True
        if op == "attach_energy" and _energy_source(battle, index, effect):
            return True
        if op in ("switch_self", "heal_team") and side.bench:
            return True
        if op == "opponent_discard_to" and len(battle.opponent(index).hand) > effect.n:
            return True
        if op == "opponent_discard_filter" and any(
            matches(c, effect.filter) for c in battle.opponent(index).hand
        ):
            return True
        if op == "switch_opponent" and battle.opponent(index).bench:
            return True
        if op == "discard_from_hand" and len(side.hand) <= effect.n:
            return False
    return False


def _apply(battle, index: int, effect: Effect, spot) -> None:
    side = battle.sides[index]
    op = effect.op
    if op == "draw":
        side.draw(effect.n)
    elif op == "draw_to":
        side.draw(max(0, effect.n - len(side.hand)))
    elif op == "draw_prizes":
        side.draw(side.prizes_left())
    elif op == "discard_hand":
        side.discard.extend(side.hand)
        side.hand = []
    elif op == "shuffle_hand_into_deck":
        side.deck.extend(side.hand)
        side.hand = []
        side.shuffle(battle.rng)
    elif op == "discard_from_hand":
        for card in pick_discards(battle, index, effect.n):
            side.hand.remove(card)
            side.discard.append(card)
    elif op == "search":
        _search(battle, index, effect)
    elif op == "recover":
        _recover(battle, index, effect)
    elif op == "dig":
        _dig(battle, index, effect)
    elif op == "attach_energy":
        _accelerate(battle, index, effect, spot)
    elif op == "switch_self" and side.bench:
        battle.switch_active(index, battle.policies[index].best_bench(battle, index))
    elif op == "switch_opponent":
        foe = battle.opponent(index)
        if foe.bench:
            battle.switch_active(1 - index, battle.policies[index].gust_target(battle, index), forced=True)
    elif op == "opponent_discard_to":
        foe = battle.opponent(index)
        while len(foe.hand) > effect.n:
            foe.discard.append(foe.hand.pop())
    elif op == "opponent_discard_filter":
        foe = battle.opponent(index)
        targets = [c for c in foe.hand if matches(c, effect.filter)][: effect.n]
        for card in targets:
            foe.hand.remove(card)
            foe.discard.append(card)
    elif op == "heal_team":
        hurt = [s for s in side.in_play() if s.damage]
        if hurt:
            worst = max(hurt, key=lambda s: s.damage)
            worst.damage = max(0, worst.damage - effect.n)


def _search(battle, index: int, effect: Effect) -> None:
    side = battle.sides[index]
    for _ in range(effect.n):
        card = _search_target(battle, index, effect)
        if card is None:
            break
        side.deck.remove(card)
        if effect.dest == "bench" and card.is_basic_pokemon and len(side.bench) < 5:
            side.bench_pokemon(card, battle.turn)
            battle.policies[index].on_bench(battle, index, side.bench[-1])
        else:
            side.hand.append(card)
    side.shuffle(battle.rng)


def _search_target(battle, index: int, effect: Effect) -> Card | None:
    side = battle.sides[index]
    options = [c for c in side.deck if matches(c, effect.filter)]
    if not options:
        return None
    policy = battle.policies[index]
    return max(options, key=lambda c: policy.card_value(battle, index, c))


def _recover(battle, index: int, effect: Effect) -> None:
    """Pull cards back out of the discard pile, into the deck or the hand."""
    side = battle.sides[index]
    policy = battle.policies[index]
    if effect.filter and effect.filter != "any":
        pool = [c for c in side.discard if matches(c, effect.filter)]
    else:
        pool = [c for c in side.discard if c.category in (Category.POKEMON, Category.ENERGY)]
    for _ in range(min(effect.n, len(pool))):
        card = max(pool, key=lambda c: policy.card_value(battle, index, c))
        pool.remove(card)
        side.discard.remove(card)
        if effect.dest == "hand":
            side.hand.append(card)
        else:
            side.deck.append(card)
    if effect.dest != "hand":
        side.shuffle(battle.rng)


def _dig(battle, index: int, effect: Effect) -> None:
    """Look at the top few cards and take the one the deck wants."""
    side = battle.sides[index]
    top = side.deck[:effect.n]
    options = [c for c in top if matches(c, effect.filter)]
    if not options:
        return
    policy = battle.policies[index]
    card = max(options, key=lambda c: policy.card_value(battle, index, c))
    side.deck.remove(card)
    side.hand.append(card)


def _energy_source(battle, index: int, effect: Effect) -> list[Card]:
    side = battle.sides[index]
    zone = side.discard if effect.dest == "discard" else side.deck
    return [c for c in zone if matches(c, effect.filter or "basic_energy")]


def _accelerate(battle, index: int, effect: Effect, spot) -> None:
    """Attach Energy straight from the deck or discard pile."""
    side = battle.sides[index]
    zone = side.discard if effect.dest == "discard" else side.deck
    policy = battle.policies[index]
    for _ in range(effect.n if effect.n < 90 else 3):
        options = [c for c in zone if matches(c, effect.filter or "basic_energy")]
        if not options:
            break
        target = policy.energy_target(battle, index) or spot
        if target is None:
            break
        card = max(options, key=lambda c: policy.energy_fit(battle, index, c, target))
        zone.remove(card)
        target.energy.append(card)
    if effect.dest != "discard":
        side.shuffle(battle.rng)


def pick_discards(battle, index: int, n: int) -> list[Card]:
    side = battle.sides[index]
    policy = battle.policies[index]
    ranked = sorted(side.hand, key=lambda c: policy.card_value(battle, index, c))
    return ranked[:n]
