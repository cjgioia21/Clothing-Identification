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
from dataclasses import dataclass
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
    "MEG": "me01", "PHF": "me02", "ASH": "me02.5", "PFO": "me03", "CHR": "me04",
    "PBL": "me05", "MEE": "mee", "MEP": "mep",
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
        if set_code and number:
            card = self.by_print.get((SET_CODES.get(set_code.upper(), set_code.lower()), str(number).lstrip("0")))
            if card is not None and _key(card.name) == _key(name):
                return card
        prints = self.by_name.get(_key(name))
        if not prints:
            return None
        return prints[0]

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
    return Pool(by_name=by_name, by_print=by_print)


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


def _energy(record: dict) -> Card:
    is_basic = (record.get("energyType") == "Normal") or record["name"].startswith("Basic ")
    provides = tuple(record.get("types", ()) or ())
    effects, _ = ((), []) if is_basic else compile_ability({"effect": record.get("effect", "")})[:2]
    if not provides:
        provides = ("Colorless",)
    return Card(
        name=record["name"],
        category=Category.ENERGY,
        subtype=Subtype.BASIC_ENERGY if is_basic else Subtype.SPECIAL_ENERGY,
        known=True,
        effects=tuple(effects) if not is_basic else (),
        energy_provides=provides,
        energy_count=2 if "provides 2" in (record.get("effect") or "") else 1,
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
