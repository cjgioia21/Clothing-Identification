"""The local card pool: real printed cards, indexed for decklist lookups.

``pokedeck/data/cardpool.json.gz`` is a trimmed dump of the TCGdex database
(see ``tools/fetch_pool.py``). Everything the battle engine needs — HP, types,
weakness, retreat, attack costs and damage, ability and Trainer text — comes
from here, so the simulation runs on printed cards rather than guesses.
"""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from importlib import resources

from .cards import Attack, Card, Category, Stage, Subtype
from .effects import compile_ability, compile_attack, lifts_first_turn_ban

POOL_FILE = "cardpool.json.gz"

# PTCG Live set codes -> TCGdex set ids.
SET_CODES = {
    "SVI": "sv01", "PAL": "sv02", "OBF": "sv03", "MEW": "sv03.5", "PAR": "sv04",
    "PAF": "sv04.5", "TEF": "sv05", "TWM": "sv06", "SFA": "sv06.5", "SCR": "sv07",
    "SSP": "sv08", "PRE": "sv08.5", "JTG": "sv09", "DRI": "sv10", "WHT": "sv10.5w",
    "BLK": "sv10.5b", "SVP": "svp", "SVE": "sve", "MFB": "mfb",
    "MEG": "me01", "PFL": "me02", "ASC": "me02.5", "POR": "me03", "CHR": "me04",
    "PBL": "me05", "MEE": "mee", "MEP": "mep", "30C": "30th", "30TH": "30th",
    # Earlier guesses at the Mega Evolution codes, kept so older lists still parse.
    "PHF": "me02", "ASH": "me02.5", "PFO": "me03",
}

_STAGES = {
    "Basic": Stage.BASIC,
    "Stage1": Stage.STAGE1,
    "Stage2": Stage.STAGE2,
    "VMAX": Stage.STAGE1,
    "VSTAR": Stage.STAGE1,
    "BREAK": Stage.STAGE1,
    "MEGA": Stage.STAGE2,
}

_TRAINER_SUBTYPES = {
    "Supporter": Subtype.SUPPORTER,
    "Item": Subtype.ITEM,
    "Tool": Subtype.TOOL,
    "Stadium": Subtype.STADIUM,
    "Pokemon Tool": Subtype.TOOL,
}

_PRIZES = {"V": 2, "ex": 2, "EX": 2, "GX": 2, "VSTAR": 2, "VMAX": 3, "Legend": 2}

_REG_ORDER = {mark: i for i, mark in enumerate("ABCDEFGHIJKLMNOP")}


@dataclass
class Pool:
    by_name: dict[str, list[Card]]
    by_print: dict[tuple[str, str], Card]

    def lookup(self, name: str, set_code: str | None = None, number: str | None = None) -> Card | None:
        """Find a printed card, preferring the exact print the decklist names."""
        return self.lookup_print(name, set_code, number)[0]

    def lookup_print(
        self, name: str, set_code: str | None = None, number: str | None = None
    ) -> tuple[Card | None, bool]:
        """The card, and whether the exact print the list asked for was found.

        A list can name a set code this pool has never heard of — an older
        format, or an abbreviation we do not know — and the caller deserves to
        be told which print it got instead.
        """
        if set_code and number:
            set_id = SET_CODES.get(set_code.upper(), set_code.lower())
            card = self.by_print.get((set_id, str(number).lstrip("0")))
            if card is not None and _key(card.name) == _key(name):
                return card, True
        prints = self.by_name.get(_key(name))
        if not prints:
            return None, False
        return prints[0], not (set_code and number)

    def prints(self, name: str) -> list[Card]:
        return list(self.by_name.get(_key(name), ()))

    def __len__(self) -> int:
        return len(self.by_name)


@lru_cache(maxsize=1)
def load_pool() -> Pool:
    raw = resources.files("pokedeck.data").joinpath(POOL_FILE).read_bytes()
    payload = json.loads(gzip.decompress(raw).decode("utf-8"))
    by_name: dict[str, list[Card]] = {}
    by_print: dict[tuple[str, str], Card] = {}
    for record in payload["cards"]:
        card = to_card(record)
        by_name.setdefault(_key(card.name), []).append(card)
        set_id = record.get("set")
        local = str(record.get("localId", "")).lstrip("0")
        if set_id and local:
            by_print[(set_id, local)] = card
    for prints in by_name.values():
        prints.sort(key=_print_rank)
    _fill_evolution_gaps(by_name, by_print)
    return Pool(by_name=by_name, by_print=by_print)


def _fill_evolution_gaps(by_name: dict[str, list[Card]],
                         by_print: dict[tuple[str, str], Card]) -> None:
    """Give an evolution print the pre-evolution its other prints name.

    Some sets — the anniversary ones above all — ship without the "Evolves
    from" field, and an Evolution with nothing to evolve from can never be
    played: the 30th Anniversary Seismitoad could not be reached from the
    Palpitoad sitting under it. Every print of a card is the same Pokémon, so
    the line is taken from whichever print does carry it. Nothing is invented —
    a card whose prints all lack the field is left alone.
    """
    repaired: dict[int, Card] = {}
    for prints in by_name.values():
        source = next((p.evolves_from for p in prints if p.evolves_from), None)
        if source is None:
            continue
        for index, card in enumerate(prints):
            if (card.category is Category.POKEMON and card.stage is not Stage.BASIC
                    and not card.evolves_from):
                fixed = replace(card, evolves_from=source)
                repaired[id(card)] = fixed
                prints[index] = fixed
    if not repaired:
        return
    for key, card in list(by_print.items()):
        fixed = repaired.get(id(card))
        if fixed is not None:
            by_print[key] = fixed


def to_card(record: dict) -> Card:
    """Convert one TCGdex record into a simulator card."""
    category = {
        "Pokemon": Category.POKEMON,
        "Trainer": Category.TRAINER,
        "Energy": Category.ENERGY,
    }.get(record.get("category", "Trainer"), Category.TRAINER)

    if category is Category.POKEMON:
        return _pokemon(record)
    if category is Category.ENERGY:
        return _energy(record)
    return _trainer(record)


def _pokemon(record: dict) -> Card:
    attacks = tuple(compile_attack(a) for a in record.get("attacks", ()) or ())
    ability_effects: tuple = ()
    ability_name = None
    ability_trigger = "turn"
    ability_text = ""
    abilities = [a for a in record.get("abilities", ()) or () if a.get("type") in (None, "Ability", "Poke-POWER")]
    if abilities:
        ability_effects, ability_trigger, _ = compile_ability(abilities[0])
        ability_name = abilities[0].get("name")
        ability_text = abilities[0].get("effect") or ""

    suffix = record.get("suffix") or ""
    prizes = _PRIZES.get(suffix, 1)
    if suffix == "ex" and record["name"].startswith("Mega "):
        prizes = 3  # Mega Evolution ex are worth three

    weaknesses = record.get("weaknesses") or []
    resistances = record.get("resistances") or []
    return Card(
        name=record["name"],
        category=Category.POKEMON,
        stage=_STAGES.get(record.get("stage", "Basic"), Stage.BASIC),
        evolves_from=record.get("evolveFrom"),
        ability=ability_effects,
        ability_name=ability_name,
        ability_trigger=ability_trigger,
        ability_text=ability_text,
        known=True,
        hp=int(record.get("hp") or 0),
        types=tuple(record.get("types", ()) or ()),
        weakness=(weaknesses[0].get("type") if weaknesses else ""),
        resistance=(resistances[0].get("type") if resistances else ""),
        resistance_value=_resistance_value(resistances),
        retreat=int(record.get("retreat") or 0),
        attacks=attacks,
        prize_value=prizes,
        rule_box=suffix,
        card_id=record.get("id", ""),
        regulation=str(record.get("regulationMark") or ""),
        set_id=str(record.get("set") or ""),
    )


ALL_ENERGY_TYPES = (
    "Grass", "Fire", "Water", "Lightning", "Psychic",
    "Fighting", "Darkness", "Metal", "Dragon", "Colorless",
)


def _energy(record: dict) -> Card:
    is_basic = (record.get("energyType") == "Normal") or record["name"].startswith("Basic ")
    text = record.get("effect") or ""
    provides = tuple(record.get("types", ()) or ())
    effects, _ = ((), []) if is_basic else compile_ability({"effect": text})[:2]
    wild_if, wild_count = _wildcard_rule(text)
    bonus_if, bonus_count = _bonus_rule(text)
    if not provides:
        provides = _provided_types(text)
    return Card(
        name=record["name"],
        category=Category.ENERGY,
        subtype=Subtype.BASIC_ENERGY if is_basic else Subtype.SPECIAL_ENERGY,
        known=True,
        effects=tuple(effects) if not is_basic else (),
        energy_provides=provides,
        energy_count=2 if "provides 2 {" in text else 1,
        energy_wild_if=wild_if,
        energy_wild_count=wild_count,
        energy_bonus_if=bonus_if,
        energy_bonus_count=bonus_count,
        energy_ends_turn=_ends_turn(text),
        card_id=record.get("id", ""),
        regulation=str(record.get("regulationMark") or ""),
        set_id=str(record.get("set") or ""),
        ability_text=record.get("effect") or "",
    )


def _trainer(record: dict) -> Card:
    text = record.get("effect") or ""
    effects, _, _ = compile_ability({"effect": text})
    ace = "ACE SPEC" in str(record.get("rarity") or "").upper()
    return Card(
        name=record["name"],
        category=Category.TRAINER,
        subtype=_TRAINER_SUBTYPES.get(record.get("trainerType", "Item"), Subtype.ITEM),
        effects=tuple(effects),
        ability_text=text,
        known=True,
        ace_spec=ace,
        plays_first_turn=lifts_first_turn_ban(text),
        card_id=record.get("id", ""),
        regulation=str(record.get("regulationMark") or ""),
        set_id=str(record.get("set") or ""),
    )


def _wildcard_rule(text: str) -> tuple[str, int]:
    """When (and how much) a Special Energy counts as every type.

    Prism Energy is a rainbow only on a Basic, Neo Upper only on a Stage 2 —
    and then for two Energy at once. Reversal Energy asks for more: an
    Evolution with no Rule Box, and only while you are behind on prizes.
    Reading that last one as "always" hands the card three Energy it has not
    earned, which is how a deck-improvement scan ends up recommending it.
    """
    lowered = (text or "").lower()
    # The parenthetical "(Pokémon ex, Pokémon V, etc. have Rule Boxes)" puts a
    # full stop in the middle of the sentence, so this reads the conditions as
    # phrases rather than trying to span them.
    amount = re.search(r"provides only (\d+) energy", lowered)
    if (amount
            and "more prize cards remaining than your opponent" in lowered
            and "evolution pok" in lowered
            and "rule box" in lowered):
        return "evolution_behind", int(amount.group(1))
    match = re.search(
        r"if this card is attached to a (basic|stage 2) pok.mon, this card provides every type"
        r"[^.]*?provides only (\d+) energy",
        lowered,
    )
    if match:
        return ("basic" if match.group(1) == "basic" else "stage2"), int(match.group(2))
    plain = re.search(r"provides every type of energy[^.]*?provides only (\d+) energy", lowered)
    if plain:
        return "always", int(plain.group(1))
    return "", 1


def _bonus_rule(text: str) -> tuple[str, int]:
    """Energy that provides more than one symbol on the right Pokémon.

    Ignition Energy is one Energy on a Basic and three on an Evolution.
    """
    match = re.search(
        r"if this card is attached to an? (basic|evolution|stage 2) pok.mon,"
        r"[^.]*?provides (\{\w\})+ energy instead",
        (text or "").lower(),
    )
    if not match:
        return "", 1
    span = match.group(0)
    kind = {"stage 2": "stage2"}.get(match.group(1), match.group(1))
    return kind, max(1, len(re.findall(r"\{\w\}", span.split("provides", 1)[1])))


def _ends_turn(text: str) -> bool:
    """Energy that goes to the discard pile at the end of the turn it lands."""
    return bool(re.search(r"discard it at the end of your turn", (text or "").lower()))


def _provided_types(text: str) -> tuple[str, ...]:
    """What a Special Energy counts as, read off the card.

    The rainbow case is handled by :func:`_wildcard_rule`; this is the plain
    symbol it provides otherwise.
    """
    lowered = text.lower()
    symbols = re.findall(r"provides \{(\w)\}", lowered)
    if symbols:
        from .battle import _type_for  # local import: battle imports the pool's cards

        return tuple(dict.fromkeys(_type_for(symbol) for symbol in symbols))
    return ("Colorless",)


def _resistance_value(resistances: list[dict]) -> int:
    if not resistances:
        return 30
    digits = re.findall(r"\d+", str(resistances[0].get("value", "-30")))
    return int(digits[0]) if digits else 30


def _print_rank(card: Card) -> tuple:
    """Newest regulation mark first — that is the print a current list means."""
    return (
        -_REG_ORDER.get(card.regulation.upper(), 0),
        -len(card.attacks),
        -card.hp,
        card.card_id,
    )


def _key(name: str) -> str:
    return " ".join(str(name).split()).casefold()
