"""Generate the gauntlet: 100 Standard-legal decklists built from the card pool.

Each archetype names its main attacker; the evolution line beneath it, the
Energy types its attack actually costs, and a consistency shell are filled in
automatically, and four variants are written per archetype.

Every card is checked against the current Standard regulation marks before it
goes in, and every finished deck is run through the construction rules, the
format check and the card resolver.

    python tools/build_gauntlet.py            # rewrite pokedeck/data/gauntlet/
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokedeck.cards import Category, Stage  # noqa: E402
from pokedeck.decklist import parse, validate  # noqa: E402
from pokedeck.knowledge import resolve  # noqa: E402
from pokedeck.legality import check as legality_check  # noqa: E402
from pokedeck.legality import card_is_legal  # noqa: E402
from pokedeck.pool import SET_CODES, load_pool  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "pokedeck" / "data" / "gauntlet"
CODE_FOR_SET = {v: k for k, v in SET_CODES.items()}

ENERGY_FOR_TYPE = {
    "Grass": "Basic Grass Energy",
    "Fire": "Basic Fire Energy",
    "Water": "Basic Water Energy",
    "Lightning": "Basic Lightning Energy",
    "Psychic": "Basic Psychic Energy",
    "Fighting": "Basic Fighting Energy",
    "Darkness": "Basic Darkness Energy",
    "Metal": "Basic Metal Energy",
}

# name, max copies — added in order until the deck reaches 60 cards.
SHELL = [
    ("Carmine", 4),
    ("Ultra Ball", 4),
    ("Lacey", 3),
    ("Buddy-Buddy Poffin", 3),
    ("Boss's Orders", 2),
    ("Lucian", 2),
    ("Night Stretcher", 2),
    ("Switch", 2),
    ("Pokégear 3.0", 2),
    ("Rescue Board", 2),
    ("Poké Pad", 2),
    ("Energy Search Pro", 2),
    ("Ciphermaniac's Codebreaking", 2),
    ("Cheren", 2),
    ("Air Balloon", 2),
    ("Friends in Paldea", 2),
    ("Judge", 1),
    ("Crispin", 1),
    ("Lana's Aid", 1),
    ("Max Rod", 1),
    ("Precious Trolley", 1),
    ("Hero's Cape", 1),  # ACE SPEC: exactly one is the legal maximum
    ("Pokémon Catcher", 2),
    ("Energy Retrieval", 2),
    ("Miracle Headset", 1),
    ("Energy Recycler", 1),
]

# Tech Pokémon the variants rotate through, so the field is not 100 of one shell.
TECHS = [
    "Fezandipiti ex", "Munkidori", "Latias ex", "Fan Rotom", "Budew",
    "Lillie's Clefairy ex", "Bloodmoon Ursaluna ex", "Klefki", "Jirachi",
    "Pecharunt ex", "Iron Crown ex", "Teal Mask Ogerpon ex",
]

VARIANTS = [
    ("standard", {}),
    ("aggro", {"attacker": +1, "energy": -1, "techs": 1}),
    ("techy", {"energy": -2, "techs": 2}),
    ("grind", {"energy": +1, "techs": 1, "shell": ("Boss's Orders", 1)}),
]


@dataclass
class Archetype:
    key: str
    name: str
    attacker: str
    copies: int = 3
    support: tuple[tuple[str, int], ...] = ()
    line_counts: tuple[int, int] = (4, 2)  # basics, middle stage
    energy: int = 11


ARCHETYPES = [
    Archetype("dragapult", "Dragapult ex", "Dragapult ex", 3,
              (("Duskull", 2), ("Dusclops", 2), ("Dusknoir", 2)), (4, 2), 10),
    Archetype("hydreigon", "Hydreigon ex", "Hydreigon ex", 3, (("Munkidori", 1),), (4, 2), 12),
    Archetype("slaking", "Slaking ex", "Slaking ex", 3, (("Fezandipiti ex", 1),), (4, 2), 11),
    Archetype("mega-dragonite", "Mega Dragonite ex", "Mega Dragonite ex", 3, (), (4, 2), 12),
    Archetype("mega-lucario", "Mega Lucario ex", "Mega Lucario ex", 4, (("Fezandipiti ex", 1),), (4, 0), 11),
    Archetype("mega-gengar", "Mega Gengar ex", "Mega Gengar ex", 3, (("Munkidori", 1),), (4, 2), 11),
    Archetype("garchomp", "Cynthia's Garchomp ex", "Cynthia's Garchomp ex", 3, (), (4, 2), 11),
    Archetype("luxray", "Luxray ex", "Luxray ex", 3, (("Fan Rotom", 1),), (4, 2), 11),
    Archetype("blaziken", "Blaziken ex", "Blaziken ex", 3, (("Fezandipiti ex", 1),), (4, 2), 11),
    Archetype("palafin", "Palafin ex", "Palafin ex", 4, (("Fezandipiti ex", 1),), (4, 0), 10),
    Archetype("ceruledge", "Ceruledge ex", "Ceruledge ex", 3, (("Fezandipiti ex", 1),), (4, 0), 11),
    Archetype("archaludon", "Archaludon ex", "Archaludon ex", 3, (("Jirachi", 1),), (4, 0), 12),
    Archetype("flareon", "Flareon ex", "Flareon ex", 3, (("Jolteon ex", 2),), (4, 0), 11),
    Archetype("jolteon", "Jolteon ex", "Jolteon ex", 3, (("Vaporeon ex", 2),), (4, 0), 11),
    Archetype("vaporeon", "Vaporeon ex", "Vaporeon ex", 3, (("Leafeon ex", 2),), (4, 0), 11),
    Archetype("blissey", "Blissey ex", "Blissey ex", 3, (("Fezandipiti ex", 1),), (4, 0), 12),
    Archetype("milotic", "Milotic ex", "Milotic ex", 3, (("Latias ex", 1),), (4, 0), 11),
    Archetype("greninja", "Greninja ex", "Greninja ex", 3, (("Fezandipiti ex", 1),), (4, 2), 11),
    Archetype("tyranitar", "Tyranitar ex", "Tyranitar ex", 3, (("Munkidori", 1),), (4, 2), 11),
    Archetype("metagross", "Steven's Metagross ex", "Steven's Metagross ex", 3, (), (4, 2), 12),
    Archetype("grimmsnarl", "Marnie's Grimmsnarl ex", "Marnie's Grimmsnarl ex", 3, (), (4, 2), 11),
    Archetype("miraidon", "Miraidon ex", "Miraidon ex", 4, (("Fan Rotom", 1),), (0, 0), 12),
    Archetype("raging-bolt", "Raging Bolt ex", "Raging Bolt ex", 4,
              (("Teal Mask Ogerpon ex", 2),), (0, 0), 11),
    Archetype("terapagos", "Terapagos ex", "Terapagos ex", 4, (("Fezandipiti ex", 1),), (0, 0), 11),
    Archetype("zacian", "Zacian ex", "Zacian ex", 4, (("Iron Crown ex", 1),), (0, 0), 12),
]


def find(pool, name: str):
    """The newest Standard-legal print of a card, or None."""
    legal = [card for card in pool.prints(name) if card_is_legal(card)]
    return legal[0] if legal else None


def require(pool, name: str):
    card = find(pool, name)
    if card is None:
        raise SystemExit(f"no Standard-legal print of {name!r}")
    return card


def evolution_line(pool, attacker_name: str, counts: tuple[int, int]) -> list[tuple[str, int]]:
    """Walk an attacker back down its evolution line, using legal prints."""
    card = require(pool, attacker_name)
    chain = [card]
    while chain[0].evolves_from:
        chain.insert(0, require(pool, chain[0].evolves_from))
    basics, middles = counts
    line: list[tuple[str, int]] = []
    for depth, member in enumerate(chain[:-1]):
        line.append((member.name, basics if depth == 0 else middles))
    return [entry for entry in line if entry[1] > 0]


def main_attack(card):
    """The attack the simulator's player would actually aim for."""
    attacks = [a for a in card.attacks if a.cost and len(a.cost) <= 3]
    if not attacks:
        attacks = list(card.attacks)
    if not attacks:
        raise SystemExit(f"{card.name} has no attack")
    return max(attacks, key=lambda a: (a.damage, -len(a.cost)))


def energy_split(card, total: int) -> list[tuple[str, int]]:
    """Basic Energy matching what the attacker's own attack costs."""
    types = [c for c in main_attack(card).cost if c in ENERGY_FOR_TYPE]
    if not types:
        types = [t for t in card.types if t in ENERGY_FOR_TYPE] or ["Psychic"]
    wanted: list[str] = []
    for kind in types:
        if kind not in wanted:
            wanted.append(kind)
    share, extra = divmod(total, len(wanted))
    return [
        (ENERGY_FOR_TYPE[kind], share + (1 if index < extra else 0))
        for index, kind in enumerate(wanted)
    ]


def build(pool, archetype: Archetype, variant_name: str, tweak: dict, seed: int = 0) -> str:
    counts: dict[str, int] = {}

    def add(name: str, n: int) -> None:
        if n > 0:
            counts[name] = counts.get(name, 0) + n

    attacker = require(pool, archetype.attacker)
    for name, n in evolution_line(pool, archetype.attacker, archetype.line_counts):
        add(name, n)
    add(archetype.attacker, min(4, archetype.copies + tweak.get("attacker", 0)))
    for name, n in archetype.support:
        require(pool, name)
        add(name, n)
    for offset in range(tweak.get("techs", 0)):
        tech = TECHS[(seed + offset * 5) % len(TECHS)]
        if tech != archetype.attacker and find(pool, tech):
            add(tech, 1)

    # A deck that runs out of Pokémon loses on the spot, and only Basics can be
    # put down from hand, so every list carries a floor of both.
    def pokemon_count(basics_only: bool = False) -> int:
        total = 0
        for name, n in counts.items():
            if name.startswith("Basic ") and name.endswith("Energy"):
                continue
            card = require(pool, name)
            if card.category is not Category.POKEMON:
                continue
            if basics_only and not card.is_basic_pokemon:
                continue
            total += n
        return total

    for offset in range(len(TECHS) * 2):
        if pokemon_count(basics_only=True) >= 8 and pokemon_count() >= 11:
            break
        tech = TECHS[(seed + offset) % len(TECHS)]
        if tech != archetype.attacker and find(pool, tech) and counts.get(tech, 0) < 2:
            add(tech, 1)

    energy_total = max(8, archetype.energy + tweak.get("energy", 0))
    for name, n in energy_split(attacker, energy_total):
        add(name, n)

    remaining = 60 - pokemon_count() - energy_total
    if remaining < 0:
        raise SystemExit(f"{archetype.key}/{variant_name}: {abs(remaining)} cards over")

    shell = list(SHELL)
    needs_candy = any(
        (find(pool, name) or attacker).stage is Stage.STAGE2
        for name in counts
        if not name.startswith("Basic ")
    )
    if needs_candy:
        shell.insert(2, ("Rare Candy", 4))
    if "shell" in tweak:
        shell.insert(0, tweak["shell"])

    ace_used = any((find(pool, name) or attacker).ace_spec for name in counts
                   if not name.startswith("Basic "))
    for name, cap in shell:
        if remaining <= 0:
            break
        card = find(pool, name)
        if card is None:
            continue
        if card.ace_spec:
            if ace_used:
                continue  # a deck may contain only one ACE SPEC card
            cap, ace_used = 1, True
        take = min(cap, remaining)
        add(name, take)
        remaining -= take
    if remaining:
        raise SystemExit(f"{archetype.key}/{variant_name}: {remaining} cards short")

    return render(pool, f"{archetype.name} ({variant_name})", counts)


def render(pool, title: str, counts: dict[str, int]) -> str:
    groups: dict[Category, list[str]] = {c: [] for c in Category}
    totals: dict[Category, int] = {c: 0 for c in Category}
    for name, n in counts.items():
        if name.startswith("Basic ") and name.endswith("Energy"):
            groups[Category.ENERGY].append(f"{n} {name}")
            totals[Category.ENERGY] += n
            continue
        card = require(pool, name)
        number = card.card_id.split("-")[-1].lstrip("0")
        code = CODE_FOR_SET.get(card.set_id, "")
        suffix = f" {code} {number}" if code and number else ""
        groups[card.category].append(f"{n} {name}{suffix}")
        totals[card.category] += n

    lines = [f"# {title}"]
    for category, label in ((Category.POKEMON, "Pokémon"), (Category.TRAINER, "Trainer"),
                            (Category.ENERGY, "Energy")):
        if not groups[category]:
            continue
        lines.append(f"{label}: {totals[category]}")
        lines.extend(sorted(groups[category], key=_sort_key))
        lines.append("")
    lines.append(f"Total Cards: {sum(totals.values())}")
    return "\n".join(lines) + "\n"


def _sort_key(line: str) -> tuple[int, str]:
    count, rest = line.split(" ", 1)
    return (-int(count), rest)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    pool = load_pool()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for existing in out.glob("*.txt"):
        existing.unlink()

    written = 0
    for position, archetype in enumerate(ARCHETYPES):
        for variant_name, tweak in VARIANTS:
            label = f"{archetype.key}/{variant_name}"
            text = build(pool, archetype, variant_name, tweak, seed=position)
            deck = parse(text, name=f"{archetype.name} ({variant_name})")
            resolution = resolve(deck)
            problems = [i for i in validate(deck) if i.level == "error"]
            problems += [i for i in legality_check(deck, resolution) if i.level == "error"]
            if problems:
                raise SystemExit(f"{label}: {problems[0].message}")
            if resolution.unknown:
                raise SystemExit(f"{label}: unknown {resolution.unknown}")
            (out / f"{archetype.key}-{variant_name}.txt").write_text(text, encoding="utf-8")
            written += 1
    print(f"wrote {written} Standard-legal decklists to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
