"""A two-player Pokémon TCG battle engine.

It plays real games with printed cards: setup and mulligans, prizes, evolution,
Energy attachment and costs, retreat, Abilities, Trainers, attacks with
weakness and resistance, Special Conditions, knockouts and all three win
conditions (prizes, bench-out, deck-out).

Card text that the compiler in :mod:`pokedeck.effects` could not read is simply
not applied — an attack still deals its printed damage — and the coverage is
reported so you know how much of a deck was taken literally.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .cards import Attack, Card, Category, Effect, Stage, Subtype
from .decklist import PRIZE_COUNT
from .knowledge import Resolution

BENCH_LIMIT = 5
HAND_SIZE = 7
MAX_MULLIGANS = 20
DEFAULT_TURN_LIMIT = 60

ASLEEP, PARALYZED, CONFUSED = "asleep", "paralyzed", "confused"
SPECIAL_CONDITIONS = (ASLEEP, PARALYZED, CONFUSED)


@dataclass
class Spot:
    """One Pokémon in play, with its stack, Energy, tool and damage."""

    stack: list[Card]
    turn_played: int
    energy: list[Card] = field(default_factory=list)
    tool: Card | None = None
    damage: int = 0
    condition: str | None = None
    poisoned: bool = False
    burned: bool = False
    condition_turn: int = 0
    ability_used_turn: int = -1
    shield: int = 0
    shield_until: int = -1
    blocked_until: int = -1  # set by "can't attack during your next turn"

    @property
    def card(self) -> Card:
        return self.stack[-1]

    @property
    def name(self) -> str:
        return self.card.name

    @property
    def max_hp(self) -> int:
        bonus = 0
        if self.tool is not None and "+50 HP" in (self.tool.ability_text or ""):
            bonus = 50 if self.card.stage is Stage.BASIC else 0
        if self.tool is not None and "+100 HP" in (self.tool.ability_text or ""):
            bonus = 100
        return (self.card.hp or 60) + bonus

    @property
    def remaining_hp(self) -> int:
        return self.max_hp - self.damage

    @property
    def knocked_out(self) -> bool:
        return self.damage >= self.max_hp

    @property
    def prize_value(self) -> int:
        return max(1, self.card.prize_value)

    def energy_types(self) -> list[str]:
        types: list[str] = []
        for card in self.energy:
            provided = card.energy_provides or ("Colorless",)
            for _ in range(max(1, card.energy_count)):
                types.extend(provided[:1] if card.energy_count == 1 else provided)
        return types

    def retreat_cost(self) -> int:
        cost = self.card.retreat
        if self.tool is not None:
            for effect in self.tool.effects:
                if effect.op == "retreat_less":
                    cost -= effect.n
        return max(0, cost)


@dataclass
class Side:
    """One player's board, deck and resources."""

    name: str
    deck: list[Card]
    resolution: Resolution
    hand: list[Card] = field(default_factory=list)
    discard: list[Card] = field(default_factory=list)
    prizes: list[Card] = field(default_factory=list)
    active: Spot | None = None
    bench: list[Spot] = field(default_factory=list)
    prizes_taken: int = 0
    mulligans: int = 0
    supporter_used: bool = False
    energy_attached: int = 0
    retreated: bool = False
    stadium_used: bool = False
    lost_pokemon: int = 0

    # ------------------------------------------------------------------ board
    def in_play(self) -> list[Spot]:
        return ([self.active] if self.active else []) + list(self.bench)

    def basics_in_hand(self) -> list[Card]:
        return [c for c in self.hand if c.is_basic_pokemon]

    def prizes_left(self) -> int:
        return len(self.prizes)

    def draw(self, n: int = 1) -> int:
        """Draw up to ``n`` cards, returning how many were actually drawn."""
        drawn = min(n, len(self.deck))
        self.hand.extend(self.deck[:drawn])
        del self.deck[:drawn]
        return drawn

    def shuffle(self, rng: random.Random) -> None:
        rng.shuffle(self.deck)

    def bench_pokemon(self, card: Card, turn: int) -> Spot | None:
        """Put a Basic onto the Bench. Setup counts as turn one, so nothing
        benched before the game starts can evolve on the first turn."""
        if len(self.bench) >= BENCH_LIMIT:
            return None
        spot = Spot(stack=[card], turn_played=max(turn, 1))
        self.bench.append(spot)
        return spot

    def discard_spot(self, spot: Spot) -> None:
        self.discard.extend(spot.stack)
        self.discard.extend(spot.energy)
        if spot.tool:
            self.discard.append(spot.tool)
        if spot is self.active:
            self.active = None
        elif spot in self.bench:
            self.bench.remove(spot)


@dataclass
class BattleDeck:
    name: str
    cards: list[Card]
    resolution: Resolution

    @classmethod
    def build(cls, deck, resolution: Resolution) -> "BattleDeck":
        return cls(
            name=deck.name,
            cards=[resolution.get(entry.name) for entry in deck.entries for _ in range(entry.count)],
            resolution=resolution,
        )

    def copy_cards(self) -> list[Card]:
        return list(self.cards)


@dataclass
class BattleResult:
    winner: int | None
    reason: str
    turns: int
    prizes_taken: tuple[int, int]
    first: int
    log: list[str] = field(default_factory=list)


class Battle:
    """One game between two decks, driven by a policy for each side."""

    def __init__(
        self,
        decks: tuple[BattleDeck, BattleDeck],
        policies,
        rng: random.Random,
        first: int | None = None,
        turn_limit: int = DEFAULT_TURN_LIMIT,
        keep_log: bool = False,
    ):
        self.decks = decks
        self.policies = policies
        self.rng = rng
        self.turn_limit = turn_limit
        self.keep_log = keep_log
        self.log: list[str] = []
        self.sides = [
            Side(name=decks[0].name, deck=decks[0].copy_cards(), resolution=decks[0].resolution),
            Side(name=decks[1].name, deck=decks[1].copy_cards(), resolution=decks[1].resolution),
        ]
        self.first = rng.randrange(2) if first is None else first
        self.turn = 0
        self.current = self.first
        self.stadium: Card | None = None
        self.stadium_owner: int | None = None
        self.finished = False
        self.winner: int | None = None
        self.reason = ""

    # ---------------------------------------------------------------- helpers
    def note(self, message: str) -> None:
        if self.keep_log:
            self.log.append(f"T{self.turn} {message}")

    def opponent(self, index: int) -> Side:
        return self.sides[1 - index]

    def flip(self) -> bool:
        return self.rng.random() < 0.5

    # ------------------------------------------------------------------ setup
    def setup(self) -> bool:
        """Deal opening hands and prizes. False means a side could not start."""
        for side in self.sides:
            side.shuffle(self.rng)
            side.draw(HAND_SIZE)
            while not side.basics_in_hand() and side.mulligans < MAX_MULLIGANS:
                side.mulligans += 1
                side.deck.extend(side.hand)
                side.hand = []
                side.shuffle(self.rng)
                side.draw(HAND_SIZE)
            if not side.basics_in_hand():
                self.finished = True
                self.reason = "no-basics"
                return False

        for index, side in enumerate(self.sides):
            extra = self.opponent(index).mulligans
            if extra:
                side.draw(min(extra, len(side.deck)))

        for index, side in enumerate(self.sides):
            self.policies[index].setup(self, index)
            side.prizes = side.deck[:PRIZE_COUNT]
            del side.deck[:PRIZE_COUNT]
        return True

    # ------------------------------------------------------------------- play
    def play(self) -> BattleResult:
        if not self.setup():
            return self._result()
        while not self.finished and self.turn < self.turn_limit:
            self.turn += 1
            self.take_turn(self.current)
            if self.finished:
                break
            self.between_turns(self.current)
            self.current = 1 - self.current
        if not self.finished:
            self.reason = "turn-limit"
        return self._result()

    def _result(self) -> BattleResult:
        return BattleResult(
            winner=self.winner,
            reason=self.reason or "unfinished",
            turns=self.turn,
            prizes_taken=(self.sides[0].prizes_taken, self.sides[1].prizes_taken),
            first=self.first,
            log=self.log,
        )

    def take_turn(self, index: int) -> None:
        side = self.sides[index]
        side.supporter_used = False
        side.energy_attached = 0
        side.retreated = False
        side.stadium_used = False

        if not side.draw(1):
            self.end_game(1 - index, "deck-out")
            return
        if side.active is None and not self.promote(index):
            return

        policy = self.policies[index]
        policy.play_turn(self, index)
        if self.finished:
            return
        if self.can_attack(index):
            policy.attack(self, index)

    def can_play_supporter(self, index: int, card: Card) -> bool:
        """Supporters are banned on the first turn of the player going first."""
        side = self.sides[index]
        if side.supporter_used:
            return False
        if self.turn == 1 and index == self.first and not card.plays_first_turn:
            return False
        return True

    def can_attack(self, index: int) -> bool:
        side = self.sides[index]
        if side.active is None:
            return False
        if self.turn == 1 and index == self.first:
            return False  # the player going first does not attack on turn one
        spot = side.active
        if spot.condition in (ASLEEP, PARALYZED):
            return False
        return spot.blocked_until < self.turn

    # ------------------------------------------------------------- turn end
    def between_turns(self, index: int) -> None:
        """Pokémon Checkup: poison, burn, sleep and paralysis."""
        for side_index in (index, 1 - index):
            side = self.sides[side_index]
            spot = side.active
            if spot is None:
                continue
            if spot.poisoned:
                self.damage_spot(side_index, spot, 10, source="poison")
            if spot.burned:
                self.damage_spot(side_index, spot, 20, source="burn")
                if self.flip():
                    spot.burned = False
            if spot.condition == ASLEEP and self.flip():
                spot.condition = None
            elif spot.condition == PARALYZED and spot.condition_turn < self.turn:
                spot.condition = None
        self.check_knockouts()

    # ---------------------------------------------------------------- damage
    def damage_spot(self, owner: int, spot: Spot, amount: int, source: str = "") -> None:
        if amount <= 0:
            return
        spot.damage += amount
        self.note(f"{self.sides[owner].name} {spot.name} takes {amount} ({source})")

    def attack_plan(self, index: int, attack: Attack, spot: Spot, target: Spot) -> dict:
        """Decide the choices an attack offers before its damage is worked out.

        The "discard as much Energy as you like" attacks need to know how much
        to pitch, and the answer depends on what it takes to score the knockout.
        """
        plan: dict = {}
        scalers = [e for e in attack.effects if e.op == "discard_energy_scale"]
        if not scalers:
            return plan
        per = max(e.n for e in scalers)
        source = "hand" if any(e.filter == "hand" for e in scalers) else "pokemon"
        available = self._discardable_energy(index, source)
        if per <= 0 or not available:
            plan.update(per=per, discard_k=0, source=source)
            return plan
        multiplier = 2 if target.card.weakness and target.card.weakness in spot.card.types else 1
        needed = -(-target.remaining_hp // (per * multiplier))
        plan.update(per=per, source=source, discard_k=min(len(available), max(1, needed)))
        return plan

    def _discardable_energy(self, index: int, source: str) -> list:
        side = self.sides[index]
        if source == "hand":
            return [c for c in side.hand if c.category is Category.ENERGY]
        return [(s, c) for s in side.in_play() for c in s.energy]

    def attack_damage(
        self,
        attacker_index: int,
        attack: Attack,
        spot: Spot,
        target: Spot,
        plan: dict | None = None,
    ) -> int:
        """Printed damage plus whatever riders the compiler understood."""
        plan = plan if plan is not None else self.attack_plan(attacker_index, attack, spot, target)
        side = self.sides[attacker_index]
        foe = self.opponent(attacker_index)

        if "discard_k" in plan:
            return plan["per"] * plan["discard_k"]
        scale = next((e for e in attack.effects if e.op == "scale"), None)
        if scale is not None:
            return scale.n * self._counter(scale.filter, side, foe, spot)

        damage = attack.damage
        for effect in attack.effects:
            if effect.op == "bonus_per":
                damage += effect.n * self._counter(effect.filter, side, foe, spot)
            elif effect.op == "coin_bonus" and self.flip():
                damage += effect.n
            elif effect.op == "stadium_bonus" and self.stadium is not None:
                damage += effect.n
        if attack.scaling == "x":
            damage = attack.damage * max(1, self._scaling_count(attack, side, foe, spot))
        return damage

    def _scaling_count(self, attack: Attack, side: Side, foe: Side, spot: Spot) -> int:
        """How many times a printed "30×" attack multiplies."""
        text = attack.text.lower()
        if "energy attached to all of your opponent" in text:
            return sum(len(s.energy) for s in foe.in_play())
        if "energy attached to this pok" in text:
            return len(spot.energy)
        if "damage counter" in text:
            return spot.damage // 10
        if "benched pok" in text:
            return len(side.bench)
        if "heads" in text:
            return sum(1 for _ in range(4) if self.flip())
        return 1

    def _counter(self, source: str, side: Side, foe: Side, spot: Spot) -> int:
        return {
            "opponent_prizes_taken": foe.prizes_taken,
            "own_prizes_taken": side.prizes_taken,
            "energy_on_self": len(spot.energy),
            "damage_counters_on_self": spot.damage // 10,
            "own_bench": len(side.bench),
            "opponent_bench": len(foe.bench),
            "energy_in_discard": sum(1 for c in side.discard if c.category is Category.ENERGY),
            "team_energy": sum(len(s.energy) for s in side.in_play()),
        }.get(source, 0)

    def apply_attack(self, attacker_index: int, attack: Attack) -> None:
        side = self.sides[attacker_index]
        foe = self.opponent(attacker_index)
        spot = side.active
        target = foe.active
        if spot is None or target is None:
            return

        if spot.condition == CONFUSED and not self.flip():
            self.damage_spot(attacker_index, spot, 30, source="confusion")
            self.check_knockouts()
            return

        plan = self.attack_plan(attacker_index, attack, spot, target)
        raw = self.attack_damage(attacker_index, attack, spot, target, plan)
        dealt = self.final_damage(raw, spot, target)
        self.note(f"{side.name} {spot.name} uses {attack.name} for {dealt}")
        if dealt:
            self.damage_spot(1 - attacker_index, target, dealt, source=attack.name)

        for effect in attack.effects:
            self.apply_attack_effect(attacker_index, effect, spot, target, plan)
        self.check_knockouts()

    def final_damage(self, raw: int, spot: Spot, target: Spot) -> int:
        if raw <= 0:
            return 0
        damage = raw
        if target.card.weakness and target.card.weakness in spot.card.types:
            damage *= 2
        if target.card.resistance and target.card.resistance in spot.card.types:
            damage -= target.card.resistance_value
        if target.shield and target.shield_until >= self.turn:
            damage -= target.shield
        return max(0, damage)

    def apply_attack_effect(
        self, index: int, effect: Effect, spot: Spot, target: Spot, plan: dict | None = None
    ) -> None:
        side = self.sides[index]
        foe = self.opponent(index)
        op = effect.op
        if op == "bench_damage":
            for benched in list(foe.bench):
                self.damage_spot(1 - index, benched, effect.n, source="bench damage")
        elif op == "snipe" and foe.bench:
            pick = max(foe.bench, key=lambda s: (s.remaining_hp <= effect.n, s.prize_value))
            self.damage_spot(1 - index, pick, effect.n, source="snipe")
        elif op == "status":
            if effect.filter in SPECIAL_CONDITIONS:
                target.condition = effect.filter
                target.condition_turn = self.turn
            elif effect.filter == "poisoned":
                target.poisoned = True
            elif effect.filter == "burned":
                target.burned = True
        elif op == "discard_energy_self":
            for _ in range(min(effect.n, len(spot.energy))):
                side.discard.append(spot.energy.pop())
        elif op == "heal_self":
            spot.damage = max(0, spot.damage - effect.n)
        elif op == "self_damage":
            self.damage_spot(index, spot, effect.n, source="recoil")
        elif op == "no_attack_next_turn":
            spot.blocked_until = self.turn + 2
        elif op == "switch_self" and side.bench:
            self.switch_active(index, side.bench[0])
        elif op == "switch_opponent" and foe.bench:
            self.switch_active(1 - index, foe.bench[0], forced=True)
        elif op == "shield":
            spot.shield = effect.n
            spot.shield_until = self.turn + 1
        elif op == "draw":
            side.draw(effect.n)
        elif op == "draw_to":
            side.draw(max(0, effect.n - len(side.hand)))
        elif op == "clear_conditions":
            spot.condition = None
            spot.poisoned = False
            spot.burned = False
        elif op == "ko_target":
            target.damage = target.max_hp
        elif op == "bench_counters":
            self.spread_damage(1 - index, effect.n)
        elif op == "snipe_multi":
            self.snipe_many(index, effect.n, int(effect.dest or 1))
        elif op == "discard_energy_scale" and plan:
            self.pay_scaled_discard(index, plan)
        elif op == "search":
            from .scripts import run

            run(self, index, (effect,), spot)

    def spread_damage(self, owner: int, total: int) -> None:
        """Place damage counters on the bench, taking knockouts where possible."""
        side = self.sides[owner]
        left = total
        while left >= 10 and side.bench:
            targets = [s for s in side.bench if not s.knocked_out]
            if not targets:
                break
            finishable = [s for s in targets if s.remaining_hp <= left]
            pick = max(finishable, key=lambda s: s.prize_value) if finishable else max(
                targets, key=lambda s: (s.prize_value, -s.remaining_hp)
            )
            amount = min(left, pick.remaining_hp if pick in finishable else left)
            amount = max(10, amount - amount % 10)
            self.damage_spot(owner, pick, amount, source="damage counters")
            left -= amount

    def snipe_many(self, index: int, amount: int, count: int) -> None:
        """Hit several of the opponent's Pokémon, bench damage ignoring weakness."""
        foe = self.opponent(index)
        targets = sorted(
            foe.in_play(),
            key=lambda s: (s.remaining_hp <= amount, s.prize_value, -s.remaining_hp),
            reverse=True,
        )[:count]
        for target in targets:
            self.damage_spot(1 - index, target, amount, source="spread")

    def pay_scaled_discard(self, index: int, plan: dict) -> None:
        """Discard the Energy the attack just spent."""
        side = self.sides[index]
        count = plan.get("discard_k", 0)
        if plan.get("source") == "hand":
            energy = [c for c in side.hand if c.category is Category.ENERGY]
            for card in energy[:count]:
                side.hand.remove(card)
                side.discard.append(card)
            return
        for spot, card in self._discardable_energy(index, "pokemon")[:count]:
            if card in spot.energy:
                spot.energy.remove(card)
                side.discard.append(card)

    # ------------------------------------------------------------- knockouts
    def check_knockouts(self) -> None:
        for index, side in enumerate(self.sides):
            for spot in list(side.in_play()):
                if not spot.knocked_out:
                    continue
                winner = 1 - index
                taker = self.sides[winner]
                self.note(f"{side.name} {spot.name} is knocked out")
                side.discard_spot(spot)
                side.lost_pokemon += 1
                self.take_prizes(winner, spot.prize_value)
                if self.finished:
                    return
                if side.active is None and not self.promote(index):
                    return

    def take_prizes(self, index: int, count: int) -> None:
        side = self.sides[index]
        for _ in range(count):
            if not side.prizes:
                break
            side.hand.append(side.prizes.pop())
            side.prizes_taken += 1
        if not side.prizes:
            self.end_game(index, "prizes")

    def promote(self, index: int) -> bool:
        """Move a benched Pokémon up. False means that player has lost."""
        side = self.sides[index]
        if side.active is not None:
            return True
        if not side.bench:
            self.end_game(1 - index, "bench-out")
            return False
        spot = self.policies[index].choose_promotion(self, index)
        side.bench.remove(spot)
        side.active = spot
        return True

    def switch_active(self, index: int, spot: Spot, forced: bool = False) -> None:
        side = self.sides[index]
        if side.active is None or spot not in side.bench:
            return
        current = side.active
        side.bench.remove(spot)
        side.bench.append(current)
        side.active = spot
        current.condition = None  # conditions clear when a Pokémon leaves the Active Spot
        current.poisoned = False
        current.burned = False

    def end_game(self, winner: int, reason: str) -> None:
        if self.finished:
            return
        self.finished = True
        self.winner = winner
        self.reason = reason
        self.note(f"{self.sides[winner].name} wins by {reason}")

    # --------------------------------------------------------------- actions
    def attach_energy(self, index: int, card: Card, spot: Spot) -> None:
        side = self.sides[index]
        side.hand.remove(card)
        spot.energy.append(card)
        side.energy_attached += 1

    def can_pay(self, spot: Spot, attack: Attack) -> bool:
        """Does the Pokémon's Energy cover the attack cost?"""
        available = spot.energy_types()
        needed = [c for c in attack.cost if c not in ("Colorless",)]
        colorless = len(attack.cost) - len(needed)
        pool = list(available)
        for requirement in needed:
            match = next((e for e in pool if e == requirement), None)
            if match is None:
                # Pokémon with a single type accept their own basic Energy only;
                # anything printed as {C} is covered below.
                return False
            pool.remove(match)
        return len(pool) >= colorless

    def usable_attacks(self, index: int) -> list[Attack]:
        side = self.sides[index]
        if side.active is None:
            return []
        return [a for a in side.active.card.attacks if self.can_pay(side.active, a)]

    def play_stadium(self, index: int, card: Card) -> None:
        side = self.sides[index]
        side.hand.remove(card)
        if self.stadium is not None and self.stadium_owner is not None:
            self.sides[self.stadium_owner].discard.append(self.stadium)
        self.stadium = card
        self.stadium_owner = index
