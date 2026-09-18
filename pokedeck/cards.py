"""Card model used by the parser, the knowledge base and the simulator."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


class Category(str, Enum):
    POKEMON = "pokemon"
    TRAINER = "trainer"
    ENERGY = "energy"


class Subtype(str, Enum):
    NONE = "none"
    SUPPORTER = "supporter"
    ITEM = "item"
    TOOL = "tool"
    STADIUM = "stadium"
    BASIC_ENERGY = "basic_energy"
    SPECIAL_ENERGY = "special_energy"


class Stage(str, Enum):
    NONE = "none"
    BASIC = "basic"
    STAGE1 = "stage1"
    STAGE2 = "stage2"


@dataclass(frozen=True)
class Effect:
    """A single scripted effect step.

    Recognised ops:
      draw            n
      draw_to         n            draw until the hand holds n cards
      draw_prizes                  draw one card per remaining prize
      discard_hand
      shuffle_hand_into_deck
      discard_from_hand  n         cost paid before the rest of the script
      search          filter, n, dest ("hand" or "bench")
      attach_energy                extra energy attachment for the turn
      recover         n            put n cards from discard back into the deck
      none
    """

    op: str
    n: int = 0
    filter: str = "any"
    dest: str = "hand"
    chance: int = 100  # a coin-flip effect only happens half the time

    @classmethod
    def from_dict(cls, raw: dict) -> "Effect":
        return cls(
            op=raw["op"],
            n=int(raw.get("n", 0)),
            filter=raw.get("filter", "any"),
            dest=raw.get("dest", "hand"),
            chance=int(raw.get("chance", 100)),
        )


_PATCHABLE_STRINGS = frozenset({
    "name", "evolves_from", "ability_name", "ability_trigger", "ability_text",
    "weakness", "resistance", "rule_box", "card_id", "regulation", "set_id",
})


@dataclass(frozen=True)
class Attack:
    """A printed attack, plus whatever of its text the compiler understood."""

    name: str
    cost: tuple[str, ...] = ()
    damage: int = 0
    scaling: str = ""  # "" | "+" | "x" — a printed 180+ or 30x
    text: str = ""
    effects: tuple[Effect, ...] = ()
    scripted: bool = True  # False when the text says more than we modelled

    @property
    def cost_size(self) -> int:
        return len(self.cost)

    @classmethod
    def from_dict(cls, raw: dict) -> "Attack":
        return cls(
            name=raw.get("name", "Attack"),
            cost=tuple(raw.get("cost", ())),
            damage=int(raw.get("damage", 0)),
            scaling=raw.get("scaling", ""),
            text=raw.get("text", ""),
            effects=tuple(Effect.from_dict(e) for e in raw.get("effects", ())),
            scripted=bool(raw.get("scripted", True)),
        )


@dataclass(frozen=True)
class Card:
    name: str
    category: Category = Category.TRAINER
    subtype: Subtype = Subtype.NONE
    stage: Stage = Stage.NONE
    evolves_from: str | None = None
    effects: tuple[Effect, ...] = ()
    ability: tuple[Effect, ...] = ()
    ability_name: str | None = None
    ability_trigger: str = "turn"  # "turn", "on_play" or "on_evolve"
    ability_text: str = ""
    known: bool = False

    # Battle data, filled in from the card pool.
    hp: int = 0
    types: tuple[str, ...] = ()
    weakness: str = ""
    resistance: str = ""
    resistance_value: int = 30
    retreat: int = 0
    attacks: tuple[Attack, ...] = ()
    prize_value: int = 1
    rule_box: str = ""  # "ex", "V", "VSTAR", "VMAX", ...
    card_id: str = ""
    regulation: str = ""
    ace_spec: bool = False
    plays_first_turn: bool = False  # a Supporter whose text lifts the first-turn ban
    set_id: str = ""
    energy_provides: tuple[str, ...] = ()
    energy_count: int = 1

    @property
    def is_basic_pokemon(self) -> bool:
        return self.category is Category.POKEMON and self.stage is Stage.BASIC

    @property
    def is_supporter(self) -> bool:
        return self.subtype is Subtype.SUPPORTER

    @property
    def is_basic_energy(self) -> bool:
        return self.subtype is Subtype.BASIC_ENERGY

    @property
    def is_energy(self) -> bool:
        return self.category is Category.ENERGY

    @property
    def fully_scripted(self) -> bool:
        return all(a.scripted for a in self.attacks)

    @property
    def draw_value(self) -> int:
        """Rough number of cards a supporter puts into hand, for policy ordering."""
        value = 0
        for eff in self.effects:
            if eff.op == "draw":
                value += eff.n
            elif eff.op in ("draw_to", "draw_prizes"):
                value += 5
            elif eff.op == "search":
                value += eff.n
        return value

    @classmethod
    def from_dict(cls, raw: dict) -> "Card":
        return cls(
            name=raw["name"],
            category=Category(raw.get("category", "trainer")),
            subtype=Subtype(raw.get("subtype", "none")),
            stage=Stage(raw.get("stage", "none")),
            evolves_from=raw.get("evolves_from"),
            effects=tuple(Effect.from_dict(e) for e in raw.get("effects", ())),
            ability=tuple(Effect.from_dict(e) for e in raw.get("ability", ())),
            ability_name=raw.get("ability_name"),
            ability_trigger=raw.get("ability_trigger", "turn"),
            ability_text=raw.get("ability_text", ""),
            hp=int(raw.get("hp", 0)),
            types=tuple(raw.get("types", ())),
            weakness=raw.get("weakness", ""),
            resistance=raw.get("resistance", ""),
            resistance_value=int(raw.get("resistance_value", 30)),
            retreat=int(raw.get("retreat", 0)),
            attacks=tuple(Attack.from_dict(a) for a in raw.get("attacks", ())),
            prize_value=int(raw.get("prize_value", 1)),
            rule_box=raw.get("rule_box", ""),
            card_id=raw.get("card_id", ""),
            regulation=raw.get("regulation", ""),
            ace_spec=bool(raw.get("ace_spec", False)),
            plays_first_turn=bool(raw.get("plays_first_turn", False)),
            set_id=raw.get("set_id", ""),
            energy_provides=tuple(raw.get("energy_provides", ())),
            energy_count=int(raw.get("energy_count", 1)),
            known=True,
        )

    def merged_with(self, raw: dict) -> "Card":
        """Return a copy patched by the keys present in ``raw``.

        Pool data supplies the printed stats; a curated entry only has to name
        the fields it corrects, usually the effect script.
        """
        patch: dict = {}
        for key, value in raw.items():
            if key == "category":
                patch["category"] = Category(value)
            elif key == "subtype":
                patch["subtype"] = Subtype(value)
            elif key == "stage":
                patch["stage"] = Stage(value)
            elif key in ("effects", "ability"):
                patch[key] = tuple(Effect.from_dict(e) for e in value)
            elif key == "attacks":
                patch[key] = tuple(Attack.from_dict(a) for a in value)
            elif key in ("hp", "retreat", "prize_value", "resistance_value", "energy_count"):
                patch[key] = int(value)
            elif key in ("ace_spec", "plays_first_turn"):
                patch[key] = bool(value)
            elif key in ("types", "energy_provides"):
                patch[key] = tuple(value)
            elif key in _PATCHABLE_STRINGS:
                patch[key] = value
        return replace(self, known=True, **patch)

    def to_dict(self) -> dict:
        data: dict = {
            "name": self.name,
            "category": self.category.value,
            "subtype": self.subtype.value,
            "stage": self.stage.value,
        }
        if self.evolves_from:
            data["evolves_from"] = self.evolves_from
        if self.effects:
            data["effects"] = [vars(e) for e in self.effects]
        if self.ability:
            data["ability"] = [vars(e) for e in self.ability]
            data["ability_trigger"] = self.ability_trigger
        if self.ability_name:
            data["ability_name"] = self.ability_name
        return data


@dataclass
class DeckEntry:
    count: int
    name: str
    set_code: str | None = None
    number: str | None = None
    category: Category = Category.TRAINER

    def label(self) -> str:
        tail = f" {self.set_code} {self.number}" if self.set_code else ""
        return f"{self.count} {self.name}{tail}"


@dataclass
class Deck:
    entries: list[DeckEntry] = field(default_factory=list)
    name: str = "deck"

    @property
    def size(self) -> int:
        return sum(e.count for e in self.entries)

    def cards(self) -> list[str]:
        """The deck expanded to one card name per physical card."""
        out: list[str] = []
        for entry in self.entries:
            out.extend([entry.name] * entry.count)
        return out

    def count_of(self, name: str) -> int:
        key = name.casefold()
        return sum(e.count for e in self.entries if e.name.casefold() == key)

    def entry_for(self, name: str) -> DeckEntry | None:
        key = name.casefold()
        for entry in self.entries:
            if entry.name.casefold() == key:
                return entry
        return None
