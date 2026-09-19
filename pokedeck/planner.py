"""A searching player: every option is tried out before one is chosen.

The greedy policy in :mod:`pokedeck.policy` plays by rules of thumb. This one
plays by looking: for each action it could take, it clones the game, finishes
the turn, lets the opponent answer, and scores the position that comes out. The
clone is determinized first, so the search plans against what a player can see
rather than reading the opponent's hand off the table.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .cards import Card, Category, Stage, Subtype
from .scoring import evaluate
from .policy import MAX_ACTIONS, Policy
from .scripts import run, useful

BENCH_LIMIT = 5


@dataclass(frozen=True)
class Action:
    """One thing a player can do during the main phase."""

    kind: str
    hand: int = -1
    spot: int = -1


def legal_actions(battle, index: int) -> list[Action]:
    """Every distinct main-phase action, with duplicate cards collapsed."""
    side = battle.sides[index]
    actions: list[Action] = []
    seen: set[tuple] = set()

    def offer(kind: str, hand: int = -1, spot: int = -1, key=None) -> None:
        signature = key if key is not None else (kind, hand, spot)
        if signature in seen:
            return
        seen.add(signature)
        actions.append(Action(kind=kind, hand=hand, spot=spot))

    abilities_off = battle.abilities_locked(index)
    for position, spot in enumerate(side.in_play()):
        card = spot.card
        if (
            not abilities_off
            and card.ability
            and card.ability_trigger == "turn"
            and spot.ability_used_turn != battle.turn
            and spot.turn_played < battle.turn
            and useful(battle, index, card.ability, spot)
        ):
            offer("ability", spot=position, key=("ability", card.name, position))

    for position, card in enumerate(side.hand):
        if card.category is Category.POKEMON:
            if card.is_basic_pokemon and len(side.bench) < BENCH_LIMIT:
                offer("bench", hand=position, key=("bench", card.name))
            elif not card.is_basic_pokemon:
                for target, spot in enumerate(side.in_play()):
                    if _can_evolve_onto(battle, index, card, spot):
                        offer("evolve", hand=position, spot=target,
                              key=("evolve", card.name, spot.name, target))
        elif card.category is Category.ENERGY:
            if not side.energy_attached:
                for target, spot in enumerate(side.in_play()):
                    offer("energy", hand=position, spot=target,
                          key=("energy", card.name, spot.name, target))
        elif card.is_supporter:
            if battle.can_play_supporter(index, card) and card.effects:
                offer("supporter", hand=position, key=("supporter", card.name))
        elif card.subtype is Subtype.ITEM:
            if card.effects and not battle.items_locked(index) and useful(battle, index, card.effects):
                offer("item", hand=position, key=("item", card.name))
        elif card.subtype is Subtype.TOOL:
            for target, spot in enumerate(side.in_play()):
                if spot.tool is None:
                    offer("tool", hand=position, spot=target, key=("tool", card.name, target))
        elif card.subtype is Subtype.STADIUM:
            if battle.can_play_stadium(card) and (
                battle.stadium is None or battle.stadium_owner != index
            ):
                offer("stadium", hand=position, key=("stadium", card.name))

    stadium = battle.stadium_ability(index)
    if stadium is not None and useful(battle, index, stadium):
        offer("stadium_ability", key=("stadium_ability",))

    if side.active is not None and not side.retreated:
        cost = battle.retreat_cost(index, side.active)
        if cost <= len(side.active.energy) and side.active.condition not in ("asleep", "paralyzed"):
            for target, spot in enumerate(side.bench, start=1):
                offer("retreat", spot=target, key=("retreat", spot.name, target))
    return actions


def _can_evolve_onto(battle, index: int, card: Card, spot) -> bool:
    if card.category is not Category.POKEMON or card.stage is Stage.BASIC:
        return False
    if spot.turn_played >= battle.turn:
        return False
    if spot.name == card.evolves_from:
        return True
    if card.stage is not Stage.STAGE2:
        return False
    side = battle.sides[index]
    if not any(c.name == "Rare Candy" for c in side.hand):
        return False
    middle = side.resolution.info(card.evolves_from)
    return middle is not None and spot.name == middle.evolves_from


def apply_action(battle, index: int, action: Action) -> bool:
    """Carry out an action. The same code runs in search and in the real game."""
    side = battle.sides[index]
    policy = battle.policies[index]
    spots = side.in_play()

    if action.kind == "ability":
        spot = spots[action.spot]
        spot.ability_used_turn = battle.turn
        run(battle, index, spot.card.ability, spot)
        return True

    if action.kind == "stadium_ability":
        effects = battle.stadium_ability(index)
        if effects is None:
            return False
        side.stadium_used = True
        run(battle, index, effects)
        return True

    if action.kind == "retreat":
        target = spots[action.spot]
        cost = battle.retreat_cost(index, side.active)
        for _ in range(cost):
            side.discard.append(side.active.energy.pop())
        battle.switch_active(index, target)
        side.retreated = True
        return True

    card = side.hand[action.hand]

    if action.kind == "bench":
        side.hand.pop(action.hand)
        spot = side.bench_pokemon(card, battle.turn)
        if spot is not None:
            policy.on_bench(battle, index, spot)
        return True

    if action.kind == "evolve":
        target = spots[action.spot]
        if target.name != card.evolves_from:
            candy = next(c for c in side.hand if c.name == "Rare Candy")
            side.hand.remove(candy)
            side.discard.append(candy)
            card = side.hand[side.hand.index(card)]
        side.hand.remove(card)
        target.stack.append(card)  # damage counters stay on through evolution
        target.condition = None
        target.ability_used_turn = -1
        if card.ability and card.ability_trigger in ("on_play", "on_evolve"):
            if not battle.abilities_locked(index) and useful(battle, index, card.ability, target):
                target.ability_used_turn = battle.turn
                run(battle, index, card.ability, target)
        return True

    if action.kind == "energy":
        battle.attach_energy(index, card, spots[action.spot])
        run(battle, index, card.effects, spots[action.spot])
        return True

    if action.kind == "tool":
        side.hand.pop(action.hand)
        spots[action.spot].tool = card
        return True

    if action.kind == "stadium":
        battle.play_stadium(index, card)
        return True

    if action.kind in ("item", "supporter"):
        side.hand.pop(action.hand)
        side.discard.append(card)
        if action.kind == "supporter":
            side.supporter_used = True
        run(battle, index, card.effects)
        return True

    return False


class ChampionPolicy(Policy):
    """Searches its turn instead of following a checklist.

    ``rollouts`` samples of the hidden information are played out per candidate
    action, each one taking the opponent's answer and this player's follow-up,
    and the action with the best average position is the one actually taken.

    Each action is judged on its own rather than with the rest of the turn
    played out behind it. That is what stops the search emptying its hand for
    marginal value: a card it does not need to play stays a card it still has.
    """

    def __init__(self, rollouts: int = 4, width: int = 14, seed: int = 0,
                 tolerance: float = 0.0, depth: int = 2, finalists: int = 5,
                 finish_turn: bool = False):
        self.rollouts = rollouts
        self.depth = depth
        self.width = width
        self.finalists = finalists
        self.finish_turn = finish_turn
        self.tolerance = tolerance
        self.rng = random.Random(seed)

    # ------------------------------------------------------------- main phase
    def play_turn(self, battle, index: int) -> None:
        for _ in range(MAX_ACTIONS):
            if battle.finished:
                return
            actions = legal_actions(battle, index)
            if not actions:
                break
            actions = self._shortlist(battle, index, actions)
            actions = self._sift(battle, index, actions)
            seeds = self._seeds()
            baseline = self._score(battle, index, None, seeds)
            best, best_score = None, float("-inf")
            for action in actions:
                score = self._score(battle, index, action, seeds)
                if score > best_score:
                    best, best_score = action, score
            # Every option is compared against passing, but a line only has to
            # be no worse: doing nothing with a card in hand wins no games.
            if best is None or best_score < baseline - self.tolerance:
                break
            apply_action(battle, index, best)

    def _shortlist(self, battle, index: int, actions: list[Action]) -> list[Action]:
        """Rank actions cheaply and keep the plausible ones."""
        if len(actions) <= self.width:
            return actions
        order = {"ability": 0, "evolve": 1, "item": 2, "supporter": 3, "bench": 4,
                 "energy": 5, "tool": 6, "stadium": 7, "retreat": 8}
        return sorted(actions, key=lambda a: order.get(a.kind, 9))[: self.width]

    def _sift(self, battle, index: int, actions: list[Action]) -> list[Action]:
        """One cheap rollout each, to spend the real search on the front-runners."""
        if len(actions) <= self.finalists:
            return actions
        seeds = self._seeds(1)
        scored = [(self._score(battle, index, action, seeds), position, action)
                  for position, action in enumerate(actions)]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [action for _, _, action in scored[: self.finalists]]

    def _seeds(self, count: int | None = None) -> list[int]:
        """One set of shuffles per decision, reused for every candidate.

        Comparing lines against the same hidden information is what stops the
        search from picking whichever option got the luckiest deal.
        """
        return [self.rng.randrange(1 << 30) for _ in range(count or self.rollouts)]

    def _score(self, battle, index: int, action: Action | None, seeds: list[int]) -> float:
        total = 0.0
        for seed in seeds:
            clone = battle.clone(
                policies=(_ROLLOUT_POLICY, _ROLLOUT_POLICY),
                determinize_for=index,
                seed=seed,
            )
            if action is not None and not apply_action(clone, index, action):
                return float("-inf")
            total += _rollout(clone, index, self.depth, self.finish_turn)
        return total / max(1, self.rollouts)

    # ---------------------------------------------------------------- attack
    def attack(self, battle, index: int) -> None:
        side = battle.sides[index]
        if side.active is None:
            return
        options = battle.usable_attacks(index)
        if not options:
            return

        seeds = self._seeds()
        best, best_score = None, self._attack_score(battle, index, None, seeds)
        for position, attack in enumerate(options):
            score = self._attack_score(battle, index, position, seeds)
            if score > best_score + 1e-9:
                best, best_score = attack, score
        if best is not None:
            battle.apply_attack(index, best)

    def _attack_score(self, battle, index: int, position: int | None, seeds: list[int]) -> float:
        total = 0.0
        for seed in seeds:
            clone = battle.clone(
                policies=(_ROLLOUT_POLICY, _ROLLOUT_POLICY),
                determinize_for=index,
                seed=seed,
            )
            if position is not None:
                attacks = clone.usable_attacks(index)
                if position >= len(attacks):
                    return float("-inf")
                clone.apply_attack(index, attacks[position])
            total += _reply(clone, index, self.depth)
        return total / max(1, self.rollouts)


_ROLLOUT_POLICY = Policy()


def _rollout(clone, index: int, depth: int = 1, finish: bool = True) -> float:
    """Play the turn out, let the opponent answer, and score what is left.

    With ``finish`` the rest of the turn is played by the greedy policy, which
    is a guess at what this player would do next; without it the action is
    judged on its own, which keeps a card in hand worth something.
    """
    if finish:
        _ROLLOUT_POLICY.play_turn(clone, index)
    if not clone.finished and clone.can_attack(index):
        _ROLLOUT_POLICY.attack(clone, index)
    return _reply(clone, index, depth)


def _reply(clone, index: int, depth: int = 1) -> float:
    """Play out the opponent's answer — and, at depth 2, our follow-up."""
    if not clone.finished:
        clone.between_turns(index)
    if not clone.finished:
        clone.turn += 1
        clone.take_turn(1 - index)
    if not clone.finished:
        clone.between_turns(1 - index)
    if depth > 1 and not clone.finished:
        clone.turn += 1
        clone.take_turn(index)
        if not clone.finished:
            clone.between_turns(index)
    return evaluate(clone, index)
