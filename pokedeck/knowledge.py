"""Resolve decklist names to simulator cards.

Three layers, each overriding the one before it:

1. the printed card pool (real HP, attacks, costs, text),
2. ``pokedeck/data/cards.json``, hand-written scripts for cards whose text the
   compiler cannot read precisely enough,
3. ``--cards overrides.json`` supplied by the user.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources

from .cards import Card, Category, Stage, Subtype
from .decklist import Deck, is_basic_energy_name
from .effects import compile_text
from .pool import load_pool


@dataclass
class Resolution:
    cards: dict[str, Card]
    unknown: list[str]
    related: dict[str, Card] = field(default_factory=dict)
    """Cards the deck skips but still refers to, such as an unplayed middle stage."""
    partial: list[str] = field(default_factory=list)
    """Cards whose printed text is only partly modelled."""
    no_battle_data: list[str] = field(default_factory=list)
    """Pokémon with no printed stats — they fight as 60 HP blanks."""

    def get(self, name: str) -> Card:
        return self.cards[name]

    def info(self, name: str | None) -> Card | None:
        """Look a card up whether or not the deck actually runs it."""
        if name is None:
            return None
        return self.cards.get(name) or self.related.get(name)

    @property
    def evolution_sources(self) -> frozenset[str]:
        """Names that something in this deck evolves from, worked out once."""
        cached = getattr(self, "_evolution_sources", None)
        if cached is None:
            cached = frozenset(
                card.evolves_from for card in self.cards.values() if card.evolves_from
            )
            object.__setattr__(self, "_evolution_sources", cached)
        return cached

    def coverage(self) -> float:
        """Share of the deck's distinct cards whose text is fully modelled."""
        if not self.cards:
            return 1.0
        rough = set(self.unknown) | set(self.partial) | set(self.no_battle_data)
        return 1.0 - len(rough) / len(self.cards)


def load_builtin_raw() -> dict[str, dict]:
    raw = json.loads(resources.files("pokedeck.data").joinpath("cards.json").read_text("utf-8"))
    return {_key(c["name"]): c for c in raw["cards"]}


def load_builtin() -> dict[str, Card]:
    return {key: Card.from_dict(raw) for key, raw in load_builtin_raw().items()}


def load_overrides(path: str) -> dict[str, dict]:
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    entries = raw["cards"] if isinstance(raw, dict) else raw
    return {_key(c["name"]): c for c in entries}


def resolve(
    deck: Deck,
    overrides: dict[str, dict] | None = None,
    use_pool: bool = True,
) -> Resolution:
    """Map every distinct name in the deck to a playable card."""
    curated = load_builtin_raw()
    if overrides:
        curated = {**curated, **overrides}
    pool = load_pool() if use_pool else None

    cards: dict[str, Card] = {}
    unknown: list[str] = []
    partial: list[str] = []
    gaps: list[str] = []
    for entry in deck.entries:
        if entry.name in cards:
            continue
        key = _key(entry.name)
        printed = pool.lookup(entry.name, entry.set_code, entry.number) if pool else None
        script = curated.get(key)

        if printed is not None:
            card = printed.merged_with(script) if script else printed
        elif script is not None:
            card = Card.from_dict(script)
        else:
            card = _infer(entry.name, entry.category)
            if not card.is_basic_energy:
                unknown.append(entry.name)

        cards[entry.name] = card
        if card.known and script is None and _is_partial(card):
            partial.append(entry.name)
        if card.category is Category.POKEMON and (not card.hp or not card.attacks):
            gaps.append(entry.name)

    return Resolution(
        cards=cards,
        unknown=unknown,
        partial=partial,
        no_battle_data=gaps,
        related=_related_lines(cards, pool, curated),
    )


def _is_partial(card: Card) -> bool:
    """True when some of the card's printed text was not turned into rules."""
    if any(not attack.scripted for attack in card.attacks):
        return True
    if card.category is Category.POKEMON and card.ability_text and not card.ability:
        return True
    if card.category is Category.TRAINER and card.ability_text:
        _, unmodelled = compile_text(card.ability_text)
        return bool(unmodelled)
    return False


def _related_lines(cards: dict[str, Card], pool, curated: dict[str, dict]) -> dict[str, Card]:
    """Pull in evolution stages the decklist itself does not contain.

    A Rare Candy line often skips the Stage 1 entirely, but the simulator still
    needs to know which Basic the Stage 2 sits on top of.
    """
    related: dict[str, Card] = {}
    pending = [c.evolves_from for c in cards.values() if c.evolves_from]
    while pending:
        name = pending.pop()
        if name is None or name in cards or name in related:
            continue
        card = pool.lookup(name) if pool else None
        script = curated.get(_key(name))
        if card is None and script is not None:
            card = Card.from_dict(script)
        elif card is not None and script is not None:
            card = card.merged_with(script)
        if card is None:
            continue
        related[name] = card
        pending.append(card.evolves_from)
    return related


def _infer(name: str, category: Category) -> Card:
    """Best guess for a card that is in neither the pool nor the scripts."""
    if is_basic_energy_name(name):
        return Card(
            name=name,
            category=Category.ENERGY,
            subtype=Subtype.BASIC_ENERGY,
            energy_provides=(name.split()[1],) if len(name.split()) > 2 else ("Colorless",),
        )
    if category is Category.ENERGY:
        return Card(name=name, category=Category.ENERGY, subtype=Subtype.SPECIAL_ENERGY,
                    energy_provides=("Colorless",))
    if category is Category.POKEMON:
        return Card(name=name, category=Category.POKEMON, stage=Stage.BASIC, hp=120, retreat=1)
    return Card(name=name, category=Category.TRAINER, subtype=Subtype.ITEM)


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()
