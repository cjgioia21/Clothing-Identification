"""How good is this position for a player?

The planner needs a number to compare lines against, so this scores a board the
way a player reads one: prizes first, then whether the board can take a
knockout next turn and survive the reply, then development.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .cards import Category
from .decklist import PRIZE_COUNT

WIN = 10_000.0


@dataclass(frozen=True)
class Weights:
    """What the position score cares about, and how much.

    Kept in one place so the numbers can be tuned by playing them against each
    other rather than argued about — see ``tools/tune_scoring.py``.
    """

    prize: float = 120.0        # a prize card is the currency of the game
    ko_threat: float = 45.0     # being able to take a knockout next turn
    ko_risk: float = 40.0       # the opponent being able to take one
    board: float = 1.0          # per point of board development
    hand: float = 1.0           # per card in hand over the opponent's
    survival: float = 1.0       # surviving the swing back
    endgame: float = 1.0        # how close the prize count is to over
    liability: float = 1.0      # extra prizes the bench is quietly owing
    deck_out_watch: int = 25    # cards left before running out starts to matter
    deck_out_panic: float = 220.0

    def replace(self, **changes) -> "Weights":
        return replace(self, **changes)


WEIGHTS = Weights()


def use(weights: Weights) -> Weights:
    """Swap the live weights, returning the ones that were in place."""
    global WEIGHTS
    previous, WEIGHTS = WEIGHTS, weights
    return previous


def evaluate(battle, index: int) -> float:
    """Score the position from ``index``'s point of view."""
    if battle.finished:
        if battle.winner is None:
            return 0.0
        return WIN - battle.turn if battle.winner == index else -WIN + battle.turn

    side = battle.sides[index]
    foe = battle.opponent(index)

    weights = WEIGHTS
    score = weights.prize * (side.prizes_taken - foe.prizes_taken)
    score += weights.board * (board_strength(battle, index) - board_strength(battle, 1 - index))
    score += weights.hand * (len(side.hand) - len(foe.hand))

    score += weights.ko_threat * knockout_reach(battle, index)
    score -= weights.ko_risk * knockout_reach(battle, 1 - index)

    score += chip_damage(battle, index) - chip_damage(battle, 1 - index)
    score += weights.survival * (survivability(battle, index) - survivability(battle, 1 - index))
    score += weights.endgame * (endgame_pressure(side) - endgame_pressure(foe))
    score -= weights.liability * (
        prize_liability(battle, index) - prize_liability(battle, 1 - index)
    )
    score -= deck_out_risk(side)
    score += deck_out_risk(foe)
    return score


def survivability(battle, index: int) -> float:
    """Surviving the swing back is worth nearly as much as landing one."""
    side = battle.sides[index]
    foe = battle.opponent(index)
    if side.active is None or foe.active is None:
        return 0.0
    incoming = 0
    for attack in foe.active.card.attacks:
        if not battle.can_pay(foe.active, attack):
            continue
        plan = battle.attack_plan(1 - index, attack, foe.active, side.active)
        raw = battle.attack_damage(1 - index, attack, foe.active, side.active, plan)
        incoming = max(incoming, battle.final_damage(raw, foe.active, side.active))
    if incoming <= 0:
        return 10.0
    if incoming >= side.active.remaining_hp:
        return -12.0 * side.active.prize_value
    return 8.0 * min(1.0, (side.active.remaining_hp - incoming) / 100.0)


def endgame_pressure(side) -> float:
    """The last prizes are the ones that matter; being one swing away counts."""
    left = prizes_left(side)
    if left <= 1:
        return 90.0
    if left == 2:
        return 45.0
    if left == 3:
        return 15.0
    return 0.0


def prize_liability(battle, index: int) -> float:
    """Every extra two-prize Pokémon on the bench is a prize the opponent is owed."""
    side = battle.sides[index]
    extra = sum(max(0, spot.prize_value - 1) for spot in side.bench)
    return 6.0 * extra


def board_strength(battle, index: int) -> float:
    """Attackers that are set up are worth more than Pokémon sitting there."""
    side = battle.sides[index]
    total = 0.0
    for spot in side.in_play():
        best = max((a.damage for a in spot.card.attacks), default=0)
        ready = any(battle.can_pay(spot, a) for a in spot.card.attacks if a.damage)
        total += spot.remaining_hp / 20.0
        total += len(spot.energy) * 4.0
        total += best / 25.0
        if ready:
            total += 12.0
        if spot.condition:
            total -= 8.0
    if len(side.bench) < 2:
        total -= 20.0 * (2 - len(side.bench))  # one bad turn from losing on the spot
    return total


def knockout_reach(battle, index: int) -> float:
    """Prizes the player could take right now, if it is their turn to swing."""
    side = battle.sides[index]
    foe = battle.opponent(index)
    if side.active is None or foe.active is None:
        return 0.0
    best = 0.0
    for attack in battle.usable_attacks(index):
        plan = battle.attack_plan(index, attack, side.active, foe.active)
        raw = battle.attack_damage(index, attack, side.active, foe.active, plan)
        damage = battle.final_damage(raw, side.active, foe.active)
        if damage >= foe.active.remaining_hp:
            best = max(best, float(foe.active.prize_value))
    return best


def chip_damage(battle, index: int) -> float:
    """Damage already sitting on the opponent's board, as a fraction of its HP."""
    foe = battle.opponent(index)
    return sum(20.0 * spot.damage / max(1, spot.max_hp) for spot in foe.in_play())


def deck_out_risk(side) -> float:
    """Cards left, valued the way a grindy game values them.

    A deck that is running low is losing a race it may not have noticed, so the
    penalty starts early and steepens — otherwise a player draws itself out
    while the position still looks fine.
    """
    remaining = len(side.deck)
    watch = WEIGHTS.deck_out_watch
    if remaining >= watch:
        return 0.0
    return WEIGHTS.deck_out_panic * ((watch - remaining) / watch) ** 2


def prizes_left(side) -> int:
    return PRIZE_COUNT - side.prizes_taken
