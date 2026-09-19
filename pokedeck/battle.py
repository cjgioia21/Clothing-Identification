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
from .effects import is_once_per_turn
from .knowledge import Resolution

BENCH_LIMIT = 5
HAND_SIZE = 7
MAX_MULLIGANS = 20
DEFAULT_TURN_LIMIT = 60

ASLEEP, PARALYZED, CONFUSED = "asleep", "paralyzed", "confused"

_ANY_TYPE = frozenset({
    "Grass", "Fire", "Water", "Lightning", "Psychic",
    "Fighting", "Darkness", "Metal", "Dragon", "Colorless",
})

_TYPE_FOR_SYMBOL = {
    "G": "Grass", "R": "Fire", "W": "Water", "L": "Lightning", "P": "Psychic",
    "F": "Fighting", "D": "Darkness", "M": "Metal", "C": "Colorless",
    "N": "Dragon", "Y": "Fairy",
}


def _type_for(symbol: str) -> str:
    """Card text writes types as {P}; the rest of the engine spells them out."""
    symbol = (symbol or "").strip("{}")
    return _TYPE_FOR_SYMBOL.get(symbol.upper(), symbol.title())


def _symbol_matches(symbol: str, types) -> bool:
    return _type_for(symbol) in types
SPECIAL_CONDITIONS = (ASLEEP, PARALYZED, CONFUSED)


@dataclass(eq=False)
class Spot:
    """One Pokémon in play, with its stack, Energy, tool and damage.

    Compared by identity, not by contents. Two Dunsparce sitting on the Bench
    with no Energy and no damage are equal field for field but are not the same
    Pokémon — and ``bench.remove(spot)`` would otherwise take whichever one it
    met first, leaving the Pokémon that was meant to move both Active and
    benched at once.
    """

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
    switched_in_on: int = -1  # the turn it moved to the Active Spot

    def copy(self) -> "Spot":
        clone = Spot(stack=list(self.stack), turn_played=self.turn_played)
        clone.energy = list(self.energy)
        clone.tool = self.tool
        clone.damage = self.damage
        clone.condition = self.condition
        clone.poisoned = self.poisoned
        clone.burned = self.burned
        clone.condition_turn = self.condition_turn
        clone.ability_used_turn = self.ability_used_turn
        clone.shield = self.shield
        clone.shield_until = self.shield_until
        clone.blocked_until = self.blocked_until
        clone.switched_in_on = self.switched_in_on
        return clone

    @property
    def card(self) -> Card:
        return self.stack[-1]

    @property
    def name(self) -> str:
        return self.card.name

    @property
    def max_hp(self) -> int:
        bonus = 0
        for effect in self.tool.effects if self.tool else ():
            if effect.op == "hp_boost":
                # Bravery Charm only helps a Basic; Hero's Cape helps anything.
                text = (self.tool.ability_text or "").lower()
                if "basic pok" in text and self.card.stage is not Stage.BASIC:
                    continue
                bonus += effect.n
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

    def energy_units(self, behind: bool = False) -> list[frozenset[str]]:
        """Each attached Energy as the set of types it can pay for.

        A rainbow Energy is one unit that counts as anything, not ten units —
        which is the difference between paying a cost and not. ``behind`` says
        whether this player has more prizes left than the opponent, which is
        half of what Reversal Energy asks for.
        """
        units: list[frozenset[str]] = []
        for card in self.energy:
            wild = card.energy_wild_if
            applies = (
                wild == "always"
                or (wild == "basic" and self.card.stage is Stage.BASIC)
                or (wild == "stage2" and self.card.stage is Stage.STAGE2)
                or (wild == "evolution_behind" and behind
                    and self.card.stage is not Stage.BASIC
                    and not self.card.rule_box)
            )
            if applies:
                units.extend([_ANY_TYPE] * max(1, card.energy_wild_count))
                continue
            provided = frozenset(card.energy_provides or ("Colorless",))
            units.extend([provided] * max(1, self._provides(card)))
        return units

    def _provides(self, card: Card) -> int:
        """How many Energy this card counts as on *this* Pokémon.

        Ignition Energy is one symbol on a Basic and three on an Evolution.
        """
        bonus = card.energy_bonus_if
        stage = self.card.stage
        if not bonus:
            return card.energy_count
        if bonus == "evolution" and stage is not Stage.BASIC:
            return card.energy_bonus_count
        if bonus == "basic" and stage is Stage.BASIC:
            return card.energy_bonus_count
        if bonus == "stage2" and stage is Stage.STAGE2:
            return card.energy_bonus_count
        return card.energy_count

    def energy_types(self) -> list[str]:
        """A flat list of what is attached, for counting rather than paying."""
        return [sorted(unit)[0] if unit is not _ANY_TYPE else "Colorless"
                for unit in self.energy_units()]

    def retreat_cost(self, tool=None) -> int:
        """Printed cost, less whatever the attached Tool takes off it.

        The caller passes the Tool that is actually working — a Stadium can
        switch every Tool in play off.
        """
        cost = self.card.retreat
        tool = self.tool if tool is None else tool
        for effect in tool.effects if tool else ():
            if effect.op == "retreat_less":
                cost -= effect.n
            elif effect.op == "no_retreat_cost" and effect.filter == "hurt_holder":
                if self.remaining_hp <= effect.n:
                    return 0
        return max(0, cost)

    def passives(self, op: str):
        """Effects this Pokémon's Ability contributes while it sits in play."""
        return [e for e in self.card.ability if e.op == op]


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
    lost_on_turn: int = -1
    turn_over: bool = False
    extra_prizes: int = 0
    items_locked_until: int = -1
    trainer_tax_until: int = -1
    trainer_tax: int = 0
    locked_attack: str = ""
    locked_attack_until: int = -1

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

    def bench_pokemon(self, card: Card, turn: int) -> Spot | None:  # noqa: D401
        """Put a Basic onto the Bench. Setup counts as turn one, so nothing
        benched before the game starts can evolve on the first turn."""
        if len(self.bench) >= BENCH_LIMIT:
            return None
        spot = Spot(stack=[card], turn_played=max(turn, 1))
        self.bench.append(spot)
        return spot

    def copy(self) -> "Side":
        clone = Side(name=self.name, deck=list(self.deck), resolution=self.resolution)
        clone.hand = list(self.hand)
        clone.discard = list(self.discard)
        clone.prizes = list(self.prizes)
        clone.active = self.active.copy() if self.active else None
        clone.bench = [spot.copy() for spot in self.bench]
        clone.prizes_taken = self.prizes_taken
        clone.mulligans = self.mulligans
        clone.supporter_used = self.supporter_used
        clone.energy_attached = self.energy_attached
        clone.retreated = self.retreated
        clone.stadium_used = self.stadium_used
        clone.lost_pokemon = self.lost_pokemon
        clone.lost_on_turn = self.lost_on_turn
        clone.turn_over = self.turn_over
        clone.extra_prizes = self.extra_prizes
        clone.items_locked_until = self.items_locked_until
        clone.trainer_tax_until = self.trainer_tax_until
        clone.trainer_tax = self.trainer_tax
        clone.locked_attack = self.locked_attack
        clone.locked_attack_until = self.locked_attack_until
        return clone

    def discard_spot(self, spot: Spot) -> None:
        self.discard.extend(spot.stack)
        self.discard.extend(spot.energy)
        if spot.tool:
            self.discard.append(spot.tool)
        self.remove_spot(spot)

    def remove_spot(self, spot: Spot) -> None:
        """Take a Pokémon off the board without sending anything anywhere."""
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
    def clone(self, policies=None, determinize_for: int | None = None, seed: int = 0) -> "Battle":
        """A copy of this game for a player to think on.

        ``determinize_for`` reshuffles everything that player cannot see — their
        own deck and prizes, and the opponent's hand, deck and prizes — so the
        search plans against the game it can observe rather than reading the
        opponent's hand off the table.
        """
        clone = Battle.__new__(Battle)
        clone.decks = self.decks
        clone.policies = policies if policies is not None else self.policies
        clone.rng = random.Random(seed)
        clone.turn_limit = self.turn_limit
        clone.keep_log = False
        clone.log = []
        clone.sides = [side.copy() for side in self.sides]
        clone.first = self.first
        clone.turn = self.turn
        clone.current = self.current
        clone.stadium = self.stadium
        clone.stadium_owner = self.stadium_owner
        clone.finished = self.finished
        clone.winner = self.winner
        clone.reason = self.reason
        if determinize_for is not None:
            clone._determinize(determinize_for)
        return clone

    def _determinize(self, index: int) -> None:
        """Re-deal the cards this player has no business knowing."""
        mine = self.sides[index]
        hidden = mine.deck + mine.prizes
        self.rng.shuffle(hidden)
        mine.deck = hidden[len(mine.prizes):]
        mine.prizes = hidden[:len(mine.prizes)]

        theirs = self.sides[1 - index]
        unseen = theirs.deck + theirs.prizes + theirs.hand
        self.rng.shuffle(unseen)
        hand_size, prize_size = len(theirs.hand), len(theirs.prizes)
        theirs.hand = unseen[:hand_size]
        theirs.prizes = unseen[hand_size:hand_size + prize_size]
        theirs.deck = unseen[hand_size + prize_size:]

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
        side.turn_over = False
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
        if not side.turn_over and self.can_attack(index):
            policy.attack(self, index)
        self.discard_spent_energy(index)

    def discard_spent_energy(self, index: int) -> None:
        """Ignition Energy and friends go to the discard when the turn ends."""
        side = self.sides[index]
        for spot in side.in_play():
            keep = [card for card in spot.energy if not card.energy_ends_turn]
            if len(keep) != len(spot.energy):
                side.discard.extend(c for c in spot.energy if c.energy_ends_turn)
                spot.energy = keep

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
        if self.attacks_barred(index, spot):
            return False
        return spot.blocked_until < self.turn

    def attacks_barred(self, index: int, spot: Spot) -> bool:
        """Abilities that say when this Pokémon is allowed to attack at all."""
        if self.abilities_locked(index):
            return False
        for effect in spot.card.ability:
            if effect.op == "attack_needs_rule_box":
                if not any(o.card.rule_box for o in self.opponent(index).in_play()):
                    return True
            elif effect.op == "attack_needs_team":
                friends = sum(1 for o in self.sides[index].in_play()
                              if effect.filter in o.name.casefold())
                if friends < effect.n:
                    return True
        return False

    def can_evolve(self, index: int, spot: Spot) -> bool:
        """Evolution normally waits a turn; an Ability can waive that."""
        if spot.turn_played < self.turn:
            return True
        if self.stadium is not None and any(
                e.op == "evolve_early" for e in self.stadium.effects):
            return True
        if self.abilities_locked(index):
            return False
        for effect in spot.card.ability:
            if effect.op != "evolve_early":
                continue
            if effect.filter != "vs_rule_box":
                return True
            foe = self.opponent(index).active
            if foe is not None and foe.card.rule_box:
                return True
        return False

    # ------------------------------------------------------------- turn end
    def between_turns(self, index: int) -> None:
        """Pokémon Checkup: poison, burn, sleep and paralysis."""
        for owner in (0, 1):
            for source, effect in self.team_passives(owner, "checkup_counters"):
                for side_index in (0, 1):
                    for spot in list(self.sides[side_index].in_play()):
                        if spot is source or spot.name == source.name:
                            continue
                        if effect.filter == "has_ability" and not spot.card.ability:
                            continue
                        self.damage_spot(side_index, spot, effect.n, source=source.name)

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
        bonus = any(e.dest == "bonus" for e in scalers)
        available = self._discardable_energy(index, source)
        if per <= 0 or not available:
            plan.update(per=per, discard_k=0, source=source, bonus=bonus)
            return plan
        multiplier = 2 if target.card.weakness and target.card.weakness in spot.card.types else 1
        headroom = max(0, target.remaining_hp - (attack.damage if bonus else 0))
        needed = -(-headroom // (per * multiplier)) if headroom else 0
        plan.update(per=per, source=source, bonus=bonus,
                    discard_k=min(len(available), max(0 if bonus else 1, needed)))
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

        self._attacking_cost = attack.cost
        if any(e.op == "requires_stadium" for e in attack.effects) and self.stadium is None:
            return 0
        for effect in attack.effects:
            if effect.op == "requires_opening_turn" and not (
                self.turn <= 2 and attacker_index != self.first
            ):
                return 0
            if effect.op == "requires_status":
                afflicted = target.condition == effect.filter or (
                    effect.filter == "poisoned" and target.poisoned) or (
                    effect.filter == "burned" and target.burned)
                if not afflicted:
                    return 0
        coin = next((e for e in attack.effects if e.op == "coins"), None)
        self._heads_flipped = self._flip_coins(coin, spot) if coin is not None else 0

        if "discard_k" in plan:
            scaled = plan["per"] * plan["discard_k"]
            return attack.damage + scaled if plan.get("bonus") else scaled
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
            elif effect.op == "bonus_vs_rule_box" and target.card.rule_box:
                damage += effect.n
            elif effect.op == "bonus_if" and self._condition_met(effect.filter, side, spot, target):
                damage += effect.n
            elif effect.op == "penalty_per":
                damage -= effect.n * self._counter(effect.filter, side, foe, spot)
        damage = max(0, damage)
        if attack.scaling == "x":
            damage = attack.damage * max(1, self._scaling_count(attack, side, foe, spot))
        return damage

    _heads_flipped = 0

    def _flip_coins(self, effect: Effect, spot: Spot | None = None) -> int:
        """A fixed number of coins, one per Energy, or "until you get tails"."""
        if effect.filter == "until_tails":
            heads = 0
            while self.flip() and heads < 20:   # bounded, but only in the far tail
                heads += 1
            return heads
        count = len(spot.energy) if effect.filter == "own_energy" and spot else effect.n
        return sum(1 for _ in range(count) if self.flip())

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

    def _condition_met(self, kind: str, side: Side, spot: Spot, target: Spot) -> bool:
        """The "if ..." half of a rider the compiler read off the card."""
        if kind == "target_damaged":
            return bool(target.damage)
        if kind == "target_afflicted":
            return bool(target.condition or target.poisoned or target.burned)
        if kind == "lost_a_pokemon":
            return side.lost_on_turn >= self.turn - 1
        if kind.startswith("spare_energy:"):
            spare = int(kind.split(":", 1)[1])
            cost = len(self._attacking_cost or ())
            return len(spot.energy_units(behind=self.behind_on_prizes(spot))) >= cost + spare
        if kind == "self_damaged":
            return bool(spot.damage)
        if kind == "bench_damaged":
            return any(other.damage for other in side.bench)
        if kind == "switched_in":
            return spot.switched_in_on == self.turn
        if kind == "energy_on_self":
            return bool(spot.energy)
        if kind.startswith("thin_deck:"):
            return len(side.deck) <= int(kind.split(":", 1)[1])
        return False

    _attacking_cost: tuple = ()

    def _counter(self, source: str, side: Side, foe: Side, spot: Spot) -> int:
        if source == "heads":
            return self._heads_flipped
        if source.startswith("named_in_play:"):
            wanted = source.split(":", 1)[1]
            return sum(1 for s in side.in_play() if wanted in s.name.casefold())
        if source.startswith("named_bench:"):
            wanted = source.split(":", 1)[1]
            return sum(1 for s in side.bench if wanted in s.name.casefold())
        if source.startswith("attack:"):
            wanted = source.split(":", 1)[1].casefold()
            return sum(
                1 for s in side.in_play()
                if any(a.name.casefold() == wanted for a in s.card.attacks)
            )
        return {
            "opponent_prizes_taken": foe.prizes_taken,
            "own_prizes_taken": side.prizes_taken,
            "energy_on_self": len(spot.energy),
            "damage_counters_on_self": spot.damage // 10,
            "own_bench": len(side.bench),
            "opponent_bench": len(foe.bench),
            "energy_in_discard": sum(1 for c in side.discard if c.category is Category.ENERGY),
            "team_energy": sum(len(s.energy) for s in side.in_play()),
            "opponent_item_discard": sum(1 for c in foe.discard if c.subtype is Subtype.ITEM),
            "opponent_team_energy": sum(len(s.energy) for s in foe.in_play()),
            "damage_counters_on_target": (foe.active.damage // 10) if foe.active else 0,
            "target_energy": len(foe.active.energy) if foe.active else 0,
            "own_in_play": len(side.in_play()),
            "target_retreat": self.retreat_cost(1 - self.sides.index(side), foe.active)
                              if foe.active else 0,
            "opponent_energy_discard": sum(1 for c in foe.discard if c.is_basic_energy),
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

        if any(e.op == "fails_on_tails" for e in attack.effects) and not self.flip():
            self.note(f"{side.name} {spot.name} misses with {attack.name}")
            return
        if self.attack_blocked(attacker_index, attack):
            return

        for effect in attack.effects:
            if effect.op == "strip_attachments":
                self._strip(attacker_index, target, effect.filter)

        plan = self.attack_plan(attacker_index, attack, spot, target)
        raw = self.attack_damage(attacker_index, attack, spot, target, plan)
        ignore = any(e.op == "ignore_weakness" for e in attack.effects)
        blind = any(e.op == "ignore_defences" for e in attack.effects)
        dealt = self.final_damage(raw, spot, target, attacker_index,
                                  ignore_weakness=ignore, ignore_defences=blind)
        if dealt and self._dodges(target):
            self.note(f"{foe.name} {target.name} shrugs off {attack.name}")
            dealt = 0
        self.note(f"{side.name} {spot.name} uses {attack.name} for {dealt}")
        if dealt:
            self.damage_spot(1 - attacker_index, target, dealt, source=attack.name)
            self._retaliate(attacker_index, spot, target)
        self._dealt = dealt

        blanked = self.effect_immune(target)
        for effect in attack.effects:
            if blanked and effect.op not in ("coins", "ignore_weakness", "ignore_defences"):
                continue  # Banette shrugs off the riders, not just the damage
            self.apply_attack_effect(attacker_index, effect, spot, target, plan)
        self.check_knockouts()

    @staticmethod
    def effect_immune(target: Spot) -> bool:
        """Is this Pokémon untouched by the effects of attacks and Abilities?"""
        return any(e.op == "effect_immune" for e in target.card.ability)

    _dealt = 0

    def _dodges(self, target: Spot) -> bool:
        """Kecleon and friends: a coin flip that turns the hit into nothing."""
        for effect in target.card.ability:
            if effect.op == "dodge" and self.flip():
                return True
        return False

    def _retaliate(self, index: int, spot: Spot, target: Spot) -> None:
        """Roserade's thorns: the attacker walks away with a Special Condition."""
        for effect in target.card.ability:
            if effect.op != "retaliate_status":
                continue
            if effect.filter == "poisoned":
                spot.poisoned = True
            elif effect.filter == "burned":
                spot.burned = True
            elif effect.filter in SPECIAL_CONDITIONS:
                spot.condition = effect.filter
                spot.condition_turn = self.turn

    def _strip(self, index: int, target: Spot, kind: str) -> None:
        """Knock the Tool (and sometimes the Special Energy) off the defender."""
        foe = self.opponent(index)
        if target.tool is not None:
            foe.discard.append(target.tool)
            target.tool = None
        if kind != "tool_and_energy":
            return
        keep = [c for c in target.energy if c.subtype is not Subtype.SPECIAL_ENERGY]
        foe.discard.extend(c for c in target.energy if c.subtype is Subtype.SPECIAL_ENERGY)
        target.energy = keep

    def team_passives(self, index: int, op: str):
        """Passive Ability effects from every Pokémon that player has in play."""
        found = []
        for spot in self.sides[index].in_play():
            if self.abilities_locked(index):
                break
            for effect in spot.card.ability:
                if effect.op == op:
                    found.append((spot, effect))
        return found

    def abilities_locked(self, index: int) -> bool:
        """Is this player's Ability use switched off by the board?"""
        if self.stadium is not None and any(e.op == "lock_abilities" for e in self.stadium.effects):
            return True
        for spot in self.opponent(index).in_play():
            if any(e.op == "lock_abilities" for e in spot.card.ability):
                return True
        return False

    def items_locked(self, index: int) -> bool:
        return self.sides[index].items_locked_until >= self.turn

    def trainer_taxed(self, index: int) -> bool:
        """Quaking Fist: flip for the Trainer being played. Tails, it is lost.

        Called as the card leaves the hand, so a tails result discards it
        without running its effects — and still spends the Supporter for the
        turn, because the card was played.
        """
        side = self.sides[index]
        if side.trainer_tax_until < self.turn or side.trainer_tax <= 0:
            return False
        return self.rng.randrange(100) < side.trainer_tax

    def attack_blocked(self, index: int, attack: Attack) -> bool:
        side = self.sides[index]
        return side.locked_attack == attack.name and side.locked_attack_until >= self.turn

    def damage_boost(self, index: int, spot: Spot, target: Spot) -> int:
        """Extra damage from the attacker's Tool and from Abilities in play."""
        bonus = 0
        holder_tool = self.tool_of(spot)
        for effect in holder_tool.effects if holder_tool else ():
            if effect.op != "boost_damage":
                continue
            if effect.filter == "holder_vs_rule_box" and not target.card.rule_box:
                continue
            bonus += effect.n
        for source, effect in self.team_passives(index, "boost_damage"):
            if effect.filter in ("holder", "holder_vs_rule_box"):
                continue
            if effect.filter and effect.filter not in spot.name.casefold():
                continue
            if source is spot and "except" in (source.card.ability_text or "").lower():
                continue  # "except any <this Pokémon>"
            bonus += effect.n
        return bonus

    def damage_reduction(self, index: int, target: Spot, attacker: Spot) -> int:
        """Damage the defending Pokémon shrugs off, from its Tool or Ability."""
        reduction = 0
        target_tool = self.tool_of(target)
        for effect in target_tool.effects if target_tool else ():
            if effect.op == "reduce_damage":
                reduction += effect.n
        if not self.abilities_locked(index):
            for effect in target.card.ability:
                if effect.op == "reduce_damage":
                    reduction += effect.n
        return reduction

    def weakness_of(self, index: int, target: Spot) -> str:
        """The defender's Weakness, after any Ability that rewrites it.

        The Ability belongs to the attacking side — it rewrites the Weakness of
        "your opponent's" Pokémon, which is whoever is being attacked.
        """
        for _, effect in self.team_passives(index, "set_weakness"):
            if _symbol_matches(effect.filter, target.card.types):
                return _type_for(effect.dest)
        return target.card.weakness

    def tools_locked(self) -> bool:
        """Jamming Tower: every Pokémon Tool in play is blank while it stands."""
        return self.stadium is not None and any(
            e.op == "lock_tools" for e in self.stadium.effects)

    def tool_of(self, spot: Spot):
        """The Tool actually doing anything on this Pokémon right now."""
        return None if self.tools_locked() else spot.tool

    def retreat_cost(self, index: int, spot: Spot) -> int:
        """Retreat cost, after Abilities and Stadiums have had their say."""
        cost = spot.retreat_cost(tool=self.tool_of(spot))
        free = list(self.team_passives(index, "no_retreat_cost"))
        if self.stadium is not None:
            free += [(None, e) for e in self.stadium.effects if e.op == "no_retreat_cost"]
        for _, effect in free:
            if effect.filter == "basic_pokemon" and spot.card.is_basic_pokemon:
                return 0
            if effect.filter.startswith("named:"):
                if effect.filter.split(":", 1)[1] in spot.name.casefold():
                    return 0
                continue
            if effect.filter == "any":
                return 0
        for _, effect in self.team_passives(1 - index, "retreat_more"):
            if spot is self.sides[index].active:
                cost += effect.n
        return cost

    def immune(self, target: Spot, attacker: Spot, defender_index: int) -> bool:
        """An Ability that blanks attacks from a particular kind of Pokémon.

        The card pool carries no Tera flag, so a shield printed against Tera
        Pokémon matches nothing — the audit reports that as a data gap rather
        than pretending the shield fires.
        """
        if self.abilities_locked(defender_index):
            return False
        for effect in target.card.ability:
            if effect.op != "prevent_damage":
                continue
            want = effect.filter
            if want in ("any", ""):
                return True
            if want in (t.casefold() for t in attacker.card.types):
                return True
            if want == "basic" and attacker.card.is_basic_pokemon:
                return True
        return False

    def sheltered(self, attacker: Spot, target: Spot) -> bool:
        """Is the target behind a Stadium that blanks rule-box attackers?"""
        if self.stadium is None:
            return False
        if not any(e.op == "shelter_rule_boxless" for e in self.stadium.effects):
            return False
        return not target.card.rule_box and bool(attacker.card.rule_box)

    def final_damage(
        self,
        raw: int,
        spot: Spot,
        target: Spot,
        index: int | None = None,
        ignore_weakness: bool = False,
        ignore_defences: bool = False,
    ) -> int:
        """Work the damage out in the printed order.

        Boosts land before Weakness and Resistance; the defender's own
        reductions come last, the way the rulebook does it.
        """
        if raw <= 0:
            return 0
        if self.sheltered(spot, target) and not ignore_defences:
            return 0
        if index is None:
            index = 0 if spot in self.sides[0].in_play() else 1
        if self.immune(target, spot, 1 - index) and not ignore_defences:
            return 0

        damage = raw + self.damage_boost(index, spot, target)
        if not ignore_weakness:
            weakness = self.weakness_of(index, target)
            if weakness and weakness in spot.card.types:
                damage *= 2
            if target.card.resistance and target.card.resistance in spot.card.types:
                damage -= target.card.resistance_value
        if not ignore_defences:
            damage -= self.damage_reduction(1 - index, target, spot)
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
            who = spot if effect.dest == "self" else target
            if self.status_proof(who):
                return
            if effect.filter in SPECIAL_CONDITIONS:
                who.condition = effect.filter
                who.condition_turn = self.turn
            elif effect.filter == "poisoned":
                who.poisoned = True
            elif effect.filter == "burned":
                who.burned = True
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
        elif op == "discard_energy_target":
            for _ in range(min(effect.n, len(target.energy))):
                foe.discard.append(target.energy.pop())
        elif op == "heal_bench":
            for benched in side.bench:
                benched.damage = max(0, benched.damage - effect.n)
        elif op == "extra_prize":
            side.extra_prizes = effect.n
        elif op == "hit_rule_boxes":
            for other in list(foe.in_play()):
                if other.card.rule_box:
                    self.damage_spot(1 - index, other, effect.n, source="spread")
        elif op == "ko_target_if":
            hit = (target.damage == effect.n) if effect.filter == "exact_counters" else bool(
                target.condition or target.poisoned or target.burned)
            if hit:
                target.damage = target.max_hp
        elif op == "recall_self":
            zone = side.deck if effect.dest == "deck" else side.hand
            zone.extend(spot.stack)
            zone.extend(spot.energy)
            if spot.tool is not None:
                zone.append(spot.tool)
            side.remove_spot(spot)
            if effect.dest == "deck":
                side.shuffle(self.rng)
        elif op == "bounce_energy_target":
            for _ in range(min(effect.n, len(target.energy))):
                foe.hand.append(target.energy.pop())
        elif op == "recycle_energy":
            for _ in range(min(effect.n, len(spot.energy))):
                side.deck.append(spot.energy.pop())
            side.shuffle(self.rng)
        elif op == "switch_to_self" and spot in side.bench:
            self.switch_active(index, spot)
        elif op == "end_turn":
            side.turn_over = True
        elif op == "self_mill":
            for _ in range(min(effect.n, len(side.deck))):
                side.discard.append(side.deck.pop(0))
        elif op == "energy_to_hand" and spot.energy:
            side.hand.append(spot.energy.pop())
        elif op == "mill":
            count = self._heads_flipped if effect.filter == "heads" else effect.n
            for _ in range(min(count, len(foe.deck))):
                foe.discard.append(foe.deck.pop(0))
        elif op == "heal_dealt":
            spot.damage = max(0, spot.damage - self._dealt)
        elif op == "block_target":
            target.blocked_until = self.turn + 1
        elif op == "discard_stadium" and self.stadium is not None:
            if self.stadium_owner is not None:
                self.sides[self.stadium_owner].discard.append(self.stadium)
            self.stadium = None
            self.stadium_owner = None
        elif op == "lock_items":
            foe.items_locked_until = self.turn + 1
        elif op == "tax_trainers":
            foe.trainer_tax_until = self.turn + 1
            foe.trainer_tax = effect.n
        elif op == "lock_attack":
            best = max(target.card.attacks, key=lambda a: a.damage, default=None)
            if best is not None:
                foe.locked_attack = best.name
                foe.locked_attack_until = self.turn + 1
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
                side.lost_on_turn = self.turn
                bonus = taker.extra_prizes if spot.card.is_basic_pokemon else 0
                shield_tool = self.tool_of(spot)
                shield = sum(e.n for e in (shield_tool.effects if shield_tool else ())
                             if e.op == "prize_reduction")
                owed = max(1, spot.prize_value + bonus - shield)
                self.take_prizes(winner, owed)
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
        spot.switched_in_on = self.turn
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

    def can_pay(self, spot: Spot, attack: Attack, index: int | None = None) -> bool:
        """Does the Pokémon's Energy cover the attack cost?

        Typed requirements are matched first, spending the least flexible
        Energy that fits, so a rainbow is kept back for whatever needs it.
        """
        units = spot.energy_units(behind=self.behind_on_prizes(spot, index))
        needed = [c for c in attack.cost if c != "Colorless"]
        colorless = len(attack.cost) - len(needed)
        colorless = max(0, colorless - self.cost_discount(spot, attack))

        for requirement in needed:
            options = [unit for unit in units if requirement in unit]
            if not options:
                return False
            units.remove(min(options, key=len))
        return len(units) >= colorless

    def behind_on_prizes(self, spot: Spot, index: int | None = None) -> bool:
        """Does this Pokémon's owner have more prizes left than the opponent?

        That is the "if you have more Prize cards remaining" half of Reversal
        Energy — it turns on when you are losing, not whenever it is attached.
        """
        if index is None:
            index = next((i for i, side in enumerate(self.sides)
                          if spot in side.in_play()), None)
        if index is None:
            return False
        return self.sides[index].prizes_left() > self.opponent(index).prizes_left()

    def cost_discount(self, spot: Spot, attack: Attack) -> int:
        """Abilities that make a named attack cheaper, such as Bloodmoon's."""
        discount = 0
        for effect in spot.card.ability:
            if effect.op != "cost_less":
                continue
            if effect.filter and effect.filter != attack.name.casefold():
                continue
            foe_index = 0 if spot in self.sides[1].in_play() else 1
            discount += effect.n * self.sides[foe_index].prizes_taken
        return discount

    def usable_attacks(self, index: int) -> list[Attack]:
        """Attacks the Active can pay for, including any it is allowed to copy."""
        side = self.sides[index]
        if side.active is None:
            return []
        attacks = list(side.active.card.attacks)
        borrow = self.copies_bench_attacks(side.active)
        if borrow is not None:
            for spot in side.bench:
                if borrow and borrow not in spot.name.casefold():
                    continue
                attacks.extend(spot.card.attacks)
        return [a for a in attacks
                if self.can_pay(side.active, a) and not self.attack_blocked(index, a)]

    @staticmethod
    def copies_bench_attacks(spot: Spot) -> str | None:
        """Whose attacks this Pokémon may borrow: "" for any, a name, or None.

        Mew ex takes any Benched Pokémon's attack; N's Zoroark ex only an N's
        Pokémon's, so the filter the compiler read comes back with it.
        """
        for effect in spot.card.ability:
            if effect.op == "copy_bench_attack":
                return effect.filter if effect.filter != "any" else ""
        text = (spot.card.ability_text or "").lower()
        return "" if "use the attacks of any of your benched" in text else None

    def on_benched(self, index: int, spot: Spot) -> None:
        """What the board does to a Pokémon the moment it arrives on the Bench."""
        if self.stadium is None:
            return
        for effect in self.stadium.effects:
            if effect.op == "bench_tax" and spot.card.is_basic_pokemon:
                self.damage_spot(index, spot, effect.n, source=self.stadium.name)
        self.check_knockouts()

    def counters_shielded(self, spot: Spot, index: int) -> bool:
        """Battle Cage: damage counters do not land on a Bench while it stands."""
        if self.stadium is None or spot is self.sides[index].active:
            return False
        return any(e.op == "shield_bench_counters" for e in self.stadium.effects)

    def status_proof(self, spot: Spot) -> bool:
        """Festival Grounds: anything with Energy on it shrugs off Conditions."""
        if self.stadium is None:
            return False
        for effect in self.stadium.effects:
            if effect.op == "status_immunity":
                if effect.filter != "has_energy" or spot.energy:
                    return True
        return False

    def stadium_ability(self, index: int):
        """The Stadium effect this player may still use this turn, if any."""
        side = self.sides[index]
        if self.stadium is None or side.stadium_used:
            return None
        if not self.stadium.effects or not is_once_per_turn(self.stadium.ability_text):
            return None
        return self.stadium.effects

    def can_play_stadium(self, card: Card) -> bool:
        """A Stadium may not be replaced by another copy of itself."""
        return self.stadium is None or self.stadium.name != card.name

    def play_stadium(self, index: int, card: Card) -> None:
        side = self.sides[index]
        side.hand.remove(card)
        if self.stadium is not None and self.stadium_owner is not None:
            self.sides[self.stadium_owner].discard.append(self.stadium)
        self.stadium = card
        self.stadium_owner = index
