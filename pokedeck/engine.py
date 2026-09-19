"""A goldfish engine: one player, no opponent, played by a greedy policy.

The engine models the parts of a turn that decide whether a deck sets up —
drawing, searching, benching, evolving and attaching — and ignores everything
that needs an opponent (attacking, damage, gusting, prize trades).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .cards import Card, Category, Effect, Stage, Subtype
from .decklist import PRIZE_COUNT
from .knowledge import Resolution

BENCH_LIMIT = 5
IN_PLAY_PREFIX = "play:"
MAX_MULLIGANS = 30


@dataclass
class InPlay:
    """A Pokémon in play, with the cards stacked underneath it."""

    stack: list[str]
    turn_played: int
    ability_used_on: int = -1

    @property
    def name(self) -> str:
        return self.stack[-1]


@dataclass
class Config:
    going_first: bool = True
    turns: int = 3
    goals: tuple[tuple[str, ...], ...] = ()
    keep_goal_cards: bool = True  # don't discard goal cards to Professor's Research


@dataclass
class Snapshot:
    turn: int
    hand: list[str]
    board: list[str]
    bench_size: int
    energy_in_play: int
    supporter_played: bool
    deck_size: int


@dataclass
class GameResult:
    mulligans: int
    stuck: bool  # no Basic Pokémon at all — the deck could not start
    opening_hand: list[str]
    opening_basics: int
    opening_supporters: int
    opening_energy: int
    prizes: list[str]
    snapshots: list[Snapshot] = field(default_factory=list)
    goal_turn: dict[str, int | None] = field(default_factory=dict)
    supporter_turns: int = 0


class Game:
    def __init__(self, resolution: Resolution, deck: list[str], config: Config, rng: random.Random):
        self.kb = resolution
        self.config = config
        self.rng = rng
        self.deck = list(deck)
        self.hand: list[str] = []
        self.attached: list[str] = []  # energy attached to Pokémon in play
        self.discard: list[str] = []
        self.prizes: list[str] = []
        self.active: InPlay | None = None
        self.bench: list[InPlay] = []
        self.turn = 0
        self.energy_attached = 0
        self.supporter_played = False
        self.mulligans = 0
        self.stuck = False
        self.goals = {_goal_key(goal): goal for goal in config.goals}
        self.goal_turn: dict[str, int | None] = {key: None for key in self.goals}
        self.goal_names = {
            name[len(IN_PLAY_PREFIX):] if name.startswith(IN_PLAY_PREFIX) else name
            for goal in config.goals
            for name in goal
        }

    # ---------------------------------------------------------------- helpers
    def card(self, name: str) -> Card:
        return self.kb.get(name)

    def in_play(self) -> list[InPlay]:
        return ([self.active] if self.active else []) + self.bench

    def names_in_play(self) -> list[str]:
        return [name for spot in self.in_play() for name in spot.stack]

    def energy_in_play(self) -> int:
        return len(self.attached)

    def has(self, name: str) -> bool:
        """Is this goal piece available?

        ``play:Charizard ex`` asks for the card on the board; a bare name
        counts the hand too, which is what you want for combo pieces.
        """
        if name.startswith(IN_PLAY_PREFIX):
            return name[len(IN_PLAY_PREFIX):] in self.names_in_play()
        return name in self.hand or name in self.names_in_play()

    # ------------------------------------------------------------------ setup
    def setup(self) -> None:
        self.rng.shuffle(self.deck)
        self.hand = self._draw_cards(7)
        while not self._basics_in_hand() and self.mulligans < MAX_MULLIGANS:
            self.mulligans += 1
            self.deck.extend(self.hand)
            self.hand = []
            self.rng.shuffle(self.deck)
            self.hand = self._draw_cards(7)
        if not self._basics_in_hand():
            self.stuck = True
            return

        starter = self._pick_starter(self._basics_in_hand())
        self.hand.remove(starter)
        # Pokémon put down during setup count as played on turn 1, so nothing
        # can evolve on the first turn of the game.
        self.active = InPlay(stack=[starter], turn_played=1)
        for name in list(self._basics_in_hand()):
            if len(self.bench) >= BENCH_LIMIT:
                break
            self.hand.remove(name)
            self._bench_card(name)

        self.prizes = self._draw_cards(PRIZE_COUNT)
        self.check_goals()

    def _basics_in_hand(self) -> list[str]:
        return [n for n in self.hand if self.card(n).is_basic_pokemon]

    def _pick_starter(self, basics: list[str]) -> str:
        """Lead with the least useful basic: keep combo pieces on the bench."""
        def rank(name: str) -> tuple[int, int, str]:
            card = self.card(name)
            is_goal = 1 if name in self.goal_names else 0
            evolves_into = 1 if self._evolutions_of(name) else 0
            return (is_goal + evolves_into, len(card.ability), name)

        return sorted(basics, key=rank)[0]

    def _evolutions_of(self, name: str) -> list[str]:
        return [c.name for c in self.kb.cards.values() if c.evolves_from == name]

    # ------------------------------------------------------------------- turn
    def play_turn(self) -> Snapshot:
        self.turn += 1
        self.energy_attached = 0
        self.supporter_played = False
        self._draw(1)

        for _ in range(40):  # each pass plays at most one card; loop until idle
            self.check_goals()
            if not self._take_action():
                break
        self._attach_energy()
        self.check_goals()
        return self.snapshot()

    def _take_action(self) -> bool:
        return (
            self._use_abilities()
            or self._play_setup_items()
            or self._play_supporter()
            or self._evolve()
            or self._play_utility_items()
        )

    def check_goals(self) -> None:
        """Record the first turn each goal was assembled, even mid-turn."""
        for key, goal in self.goals.items():
            if self.goal_turn[key] is None and all(self.has(name) for name in goal):
                self.goal_turn[key] = self.turn

    def snapshot(self) -> Snapshot:
        return Snapshot(
            turn=self.turn,
            hand=list(self.hand),
            board=[spot.name for spot in self.in_play()],
            bench_size=len(self.bench),
            energy_in_play=self.energy_in_play(),
            supporter_played=self.supporter_played,
            deck_size=len(self.deck),
        )

    # ---------------------------------------------------------------- actions
    def _use_abilities(self) -> bool:
        for spot in self.in_play():
            card = self.card(spot.name)
            if not card.ability or card.ability_trigger != "turn":
                continue
            if spot.ability_used_on == self.turn or spot.turn_played == self.turn:
                continue
            if not self._effects_useful(card.ability):
                continue
            spot.ability_used_on = self.turn
            self._run(card.ability)
            return True
        return False

    def _play_setup_items(self) -> bool:
        """Balls and similar items that put Pokémon onto the board."""
        for name in self._hand_of(Subtype.ITEM):
            card = self.card(name)
            if not any(e.op == "search" and "pokemon" in e.filter for e in card.effects):
                continue
            if not self._effects_useful(card.effects):
                continue
            if self._costs_cards(card) and self._holding_draw_supporter():
                continue  # draw first, then pay the cost with the spare cards
            self._play_from_hand(name)
            self._run(card.effects)
            return True
        return False

    def _costs_cards(self, card: Card) -> bool:
        return any(e.op == "discard_from_hand" for e in card.effects)

    def _holding_draw_supporter(self) -> bool:
        if self.supporter_played:
            return False
        return any(
            self.card(n).is_supporter and self.card(n).draw_value and not self._would_dump_the_hand(self.card(n))
            for n in self.hand
        )

    def _play_supporter(self) -> bool:
        if self.supporter_played:
            return False
        candidates = [n for n in self.hand if self.card(n).is_supporter and self.card(n).draw_value]
        if not candidates:
            return False
        candidates.sort(key=lambda n: (-self.card(n).draw_value, n))
        for name in candidates:
            card = self.card(name)
            if not self._effects_useful(card.effects):
                continue
            if self._would_dump_the_hand(card):
                continue
            self.supporter_played = True
            self._play_from_hand(name)
            self._run(card.effects)
            return True
        return False

    def _would_dump_the_hand(self, card: Card) -> bool:
        """Hold a hand-dumping supporter only when the hand is already working.

        Discarding two combo pieces hurts, but so does passing the turn with no
        draw at all, so the hand has to be big enough to be worth keeping.
        """
        if not self.config.keep_goal_cards:
            return False
        if not any(e.op in ("discard_hand", "shuffle_hand_into_deck") for e in card.effects):
            return False
        keepers = sum(1 for n in self.hand if n in self.goal_names and n != card.name)
        return keepers >= 2 and len(self.hand) >= 6

    def _evolve(self) -> bool:
        for name in list(self.hand):
            card = self.card(name)
            if card.category is not Category.POKEMON or card.stage is Stage.BASIC:
                continue
            target = self._evolution_target(card)
            if target is None:
                continue
            self._play_from_hand(name, to_discard=False)
            target.stack.append(name)
            target.ability_used_on = -1
            self._trigger_on_play(target)
            return True
        return False

    def _evolution_target(self, card: Card) -> InPlay | None:
        """A Pokémon this card may evolve, honouring the one-turn wait."""
        ready = [spot for spot in self.in_play() if spot.turn_played < self.turn]
        for spot in ready:
            if spot.name == card.evolves_from:
                return spot
        if card.stage is not Stage.STAGE2 or "Rare Candy" not in self.hand:
            return None
        middle = self.kb.info(card.evolves_from)
        if middle is None:
            return None
        for spot in ready:
            if spot.name == middle.evolves_from:
                self.hand.remove("Rare Candy")
                self.discard.append("Rare Candy")
                return spot
        return None

    def _play_utility_items(self) -> bool:
        for name in self._hand_of(Subtype.ITEM):
            card = self.card(name)
            if not card.effects or not self._effects_useful(card.effects):
                continue
            self._play_from_hand(name)
            self._run(card.effects)
            return True
        return False

    def _attach_energy(self) -> bool:
        if self.energy_attached or not self.in_play():
            return False
        for name in self.hand:
            if self.card(name).category is Category.ENERGY:
                self._play_from_hand(name, to_discard=False)
                self.attached.append(name)
                self.energy_attached += 1
                return True
        return False

    # ---------------------------------------------------------------- effects
    def _run(self, effects: tuple[Effect, ...]) -> None:
        for effect in effects:
            self._apply(effect)

    def _apply(self, effect: Effect) -> None:
        op = effect.op
        if op == "draw":
            self._draw(effect.n)
        elif op == "draw_to":
            self._draw(max(0, effect.n - len(self.hand)))
        elif op == "draw_prizes":
            self._draw(len(self.prizes))
        elif op == "discard_hand":
            self.discard.extend(self.hand)
            self.hand = []
        elif op == "shuffle_hand_into_deck":
            self.deck.extend(self.hand)
            self.hand = []
            self.rng.shuffle(self.deck)
        elif op == "discard_from_hand":
            for name in self._pick_discards(effect.n):
                self.hand.remove(name)
                self.discard.append(name)
        elif op == "search":
            self._search(effect)
        elif op == "recover":
            self._recover(effect.n)

    def _search(self, effect: Effect) -> None:
        for _ in range(effect.n):
            name = self._best_target(effect)
            if name is None:
                return
            self.deck.remove(name)
            if effect.dest == "bench" and self.card(name).is_basic_pokemon:
                if len(self.bench) >= BENCH_LIMIT:
                    self.hand.append(name)
                else:
                    self._bench_card(name)
            elif effect.dest == "bench" and self.card(name).category is Category.ENERGY:
                self.attached.append(name)
            else:
                self.hand.append(name)
        self.rng.shuffle(self.deck)

    def _best_target(self, effect: Effect) -> str | None:
        matches = [n for n in set(self.deck) if self._matches(n, effect.filter)]
        if not matches:
            return None
        if effect.dest == "bench":
            matches = [n for n in matches if self.card(n).is_basic_pokemon] or matches

        def rank(name: str) -> tuple[int, int, str]:
            wanted = 0 if self._wanted(name) else 1
            plentiful = -self.deck.count(name)
            return (wanted, plentiful, name)

        return sorted(matches, key=rank)[0]

    def _wanted(self, name: str) -> bool:
        """Is this card part of a goal, or a step towards one?"""
        if name in self.goal_names:
            return True
        card = self.card(name)
        seen: set[str] = set()
        while card.evolves_from and card.evolves_from not in seen:
            seen.add(card.evolves_from)
            if card.evolves_from in self.goal_names:
                return True
            card = self.kb.info(card.evolves_from) or card
        return any(
            self.kb.cards[goal].evolves_from == name
            for goal in self.goal_names
            if goal in self.kb.cards
        )

    def _recover(self, n: int) -> None:
        for _ in range(n):
            pool = [c for c in self.discard if self._wanted(c)] or self.discard
            if not pool:
                return
            name = pool[0]
            self.discard.remove(name)
            self.deck.append(name)
        self.rng.shuffle(self.deck)

    def _effects_useful(self, effects: tuple[Effect, ...]) -> bool:
        """Would this script actually do something right now?"""
        for effect in effects:
            if effect.op in ("draw", "draw_prizes", "shuffle_hand_into_deck") and self.deck:
                return True
            if effect.op == "draw_to" and len(self.hand) < effect.n and self.deck:
                return True
            if effect.op == "discard_hand" and self.deck:
                return True
            if effect.op == "search" and self._best_target(effect) is not None:
                if effect.dest == "bench" and len(self.bench) >= BENCH_LIMIT:
                    continue
                return True
            if effect.op == "recover" and self.discard:
                return True
            if effect.op == "discard_from_hand" and len(self.hand) <= effect.n:
                return False
        return False

    def _pick_discards(self, n: int) -> list[str]:
        """Pitch the least useful cards first: blanks, then spare copies."""
        def rank(name: str) -> tuple[int, int, str]:
            card = self.card(name)
            if self._wanted(name):
                tier = 5
            elif card.is_supporter and card.draw_value:
                tier = 4
            elif card.category is Category.POKEMON:
                tier = 3
            elif card.effects:
                tier = 2
            elif card.is_basic_energy:
                tier = 1
            else:
                tier = 0
            return (tier, -self.hand.count(name), name)

        return sorted(self.hand, key=rank)[:n]

    # ----------------------------------------------------------------- moving
    def _bench_card(self, name: str) -> None:
        spot = InPlay(stack=[name], turn_played=max(self.turn, 1))
        self.bench.append(spot)
        self._trigger_on_play(spot)

    def _trigger_on_play(self, spot: InPlay) -> None:
        card = self.card(spot.name)
        if card.ability and card.ability_trigger == "on_play" and self._effects_useful(card.ability):
            spot.ability_used_on = self.turn
            self._run(card.ability)

    def _play_from_hand(self, name: str, to_discard: bool = True) -> None:
        self.hand.remove(name)
        if to_discard:
            self.discard.append(name)

    def _hand_of(self, subtype: Subtype) -> list[str]:
        return [n for n in self.hand if self.card(n).subtype is subtype]

    def _draw(self, n: int) -> None:
        self.hand.extend(self._draw_cards(n))

    def _draw_cards(self, n: int) -> list[str]:
        drawn = self.deck[:n]
        del self.deck[:n]
        return drawn

    def _matches(self, name: str, filter_: str) -> bool:
        card = self.card(name)
        return {
            "any": True,
            "pokemon": card.category is Category.POKEMON,
            "basic_pokemon": card.is_basic_pokemon,
            "item": card.subtype is Subtype.ITEM,
            "tool": card.subtype is Subtype.TOOL,
            "supporter": card.is_supporter,
            "stadium": card.subtype is Subtype.STADIUM,
            "energy": card.category is Category.ENERGY,
            "basic_energy": card.is_basic_energy,
        }.get(filter_, False)


def play_game(resolution: Resolution, deck: list[str], config: Config, rng: random.Random) -> GameResult:
    game = Game(resolution, deck, config, rng)
    game.setup()

    opening = list(game.hand) + ([game.active.name] if game.active else []) + [s.name for s in game.bench]
    result = GameResult(
        mulligans=game.mulligans,
        stuck=game.stuck,
        opening_hand=opening,
        opening_basics=sum(1 for n in opening if game.card(n).is_basic_pokemon),
        opening_supporters=sum(1 for n in opening if game.card(n).is_supporter),
        opening_energy=sum(1 for n in opening if game.card(n).category is Category.ENERGY),
        prizes=list(game.prizes),
    )
    if game.stuck:
        return result

    result.goal_turn = dict(game.goal_turn)

    for _ in range(config.turns):
        result.snapshots.append(game.play_turn())
        if game.supporter_played:
            result.supporter_turns += 1
        result.goal_turn = dict(game.goal_turn)
    return result


def _goal_key(goal: tuple[str, ...]) -> str:
    return " + ".join(goal)
