"""Resolve decklist names to simulator cards."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources

from .cards import Card, Category, Stage, Subtype
from .decklist import Deck, is_basic_energy_name


@dataclass
class Resolution:
    cards: dict[str, Card]
    unknown: list[str]
    related: dict[str, Card] = field(default_factory=dict)
    """Cards the deck skips but still refers to, such as an unplayed middle stage."""

    def get(self, name: str) -> Card:
        return self.cards[name]

    def info(self, name: str | None) -> Card | None:
        """Look a card up whether or not the deck actually runs it."""
        if name is None:
            return None
        return self.cards.get(name) or self.related.get(name)


def load_builtin() -> dict[str, Card]:
    raw = json.loads(resources.files("pokedeck.data").joinpath("cards.json").read_text("utf-8"))
    return {_key(c["name"]): Card.from_dict(c) for c in raw["cards"]}


def load_overrides(path: str) -> dict[str, Card]:
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    entries = raw["cards"] if isinstance(raw, dict) else raw
    return {_key(c["name"]): Card.from_dict(c) for c in entries}


def resolve(deck: Deck, overrides: dict[str, Card] | None = None) -> Resolution:
    """Map every distinct name in the deck to a :class:`Card`.

    Names missing from the database become blank cards of the right category so
    that a deck still simulates; they are reported so the gap is visible.
    """
    known = load_builtin()
    if overrides:
        known.update(overrides)

    cards: dict[str, Card] = {}
    unknown: list[str] = []
    for entry in deck.entries:
        if entry.name in cards:
            continue
        card = known.get(_key(entry.name))
        if card is None:
            card = _infer(entry.name, entry.category)
            if not card.is_basic_energy:
                unknown.append(entry.name)
        cards[entry.name] = card
    return Resolution(cards=cards, unknown=unknown, related=_related_lines(cards, known))


def _related_lines(cards: dict[str, Card], known: dict[str, Card]) -> dict[str, Card]:
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
        card = known.get(_key(name))
        if card is None:
            continue
        related[name] = card
        pending.append(card.evolves_from)
    return related


def _infer(name: str, category: Category) -> Card:
    """Best guess for a card the database has never seen."""
    if is_basic_energy_name(name):
        return Card(name=name, category=Category.ENERGY, subtype=Subtype.BASIC_ENERGY)
    if category is Category.ENERGY:
        return Card(name=name, category=Category.ENERGY, subtype=Subtype.SPECIAL_ENERGY)
    if category is Category.POKEMON:
        return Card(name=name, category=Category.POKEMON, stage=Stage.BASIC)
    return Card(name=name, category=Category.TRAINER, subtype=Subtype.ITEM)


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()
