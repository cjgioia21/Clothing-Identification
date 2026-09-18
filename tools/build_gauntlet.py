"""Generate the gauntlet: 100 opposing decklists built from the card pool.

Each archetype names its main attacker; the evolution line beneath it, a
standard consistency shell and the Energy count are filled in automatically,
and four variants are written per archetype.

    python tools/build_gauntlet.py            # rewrite pokedeck/data/gauntlet/
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokedeck.cards import Category, Stage  # noqa: E402
from pokedeck.decklist import parse, validate  # noqa: E402
from pokedeck.knowledge import resolve  # noqa: E402
from pokedeck.pool import SET_CODES, load_pool  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "pokedeck" / "data" / "gauntlet"
CODE_FOR_SET = {v: k for k, v in SET_CODES.items()}

# name, max copies — added in order until the deck reaches 60 cards.
SHELL = [
    ("Professor's Research", 4),
    ("Ultra Ball", 4),
    ("Iono", 3),
    ("Nest Ball", 4),
    ("Boss's Orders", 2),
    ("Buddy-Buddy Poffin", 3),
    ("Arven", 1),
    ("Super Rod", 2),
    ("Switch", 2),
    ("Counter Catcher", 2),
    ("Night Stretcher", 1),
    ("Artazon", 2),
    ("Bravery Charm", 2),
    ("Carmine", 1),
    ("Earthen Vessel", 2),
    ("Rescue Board", 2),
    ("Crispin", 1),
    ("Professor Turo's Scenario", 1),
    ("Ciphermaniac's Codebreaking", 2),
    ("Pokégear 3.0", 2),
    ("Judge", 1),
    ("Technical Machine: Evolution", 2),
    ("Hero's Cape", 2),
    ("Lana's Aid", 1),
    ("Town Store", 1),
    ("Pal Pad", 1),
    ("Defiance Band", 2),
]


@dataclass
class Archetype:
    key: str
    name: str
    attacker: str
    copies: int = 3
    energy: tuple[tuple[str, int], ...] = ()
    support: tuple[tuple[str, int], ...] = ()
    line_counts: tuple[int, int] = (4, 1)  # basic, middle stage
    candy: bool = True
    notes: str = ""


ARCHETYPES = [
    Archetype("charizard", "Charizard ex", "Charizard ex", 3, (("Basic Fire Energy", 10),),
              (("Pidgey", 2), ("Pidgeot ex", 2), ("Fezandipiti ex", 1))),
    Archetype("gardevoir", "Gardevoir ex", "Gardevoir ex", 3, (("Basic Psychic Energy", 12),),
              (("Munkidori", 1), ("Fezandipiti ex", 1)), (4, 4)),
    Archetype("dragapult", "Dragapult ex", "Dragapult ex", 3,
              (("Basic Fire Energy", 6), ("Basic Psychic Energy", 5)),
              (("Duskull", 2), ("Dusclops", 2), ("Dusknoir", 2)), (4, 2)),
    Archetype("raging-bolt", "Raging Bolt ex", "Raging Bolt ex", 4,
              (("Basic Lightning Energy", 7), ("Basic Fighting Energy", 5)),
              (("Teal Mask Ogerpon ex", 2), ("Squawkabilly ex", 1)), candy=False),
    Archetype("miraidon", "Miraidon ex", "Miraidon ex", 4, (("Basic Lightning Energy", 11),),
              (("Iron Hands ex", 2), ("Fan Rotom", 1)), candy=False),
    Archetype("gholdengo", "Gholdengo ex", "Gholdengo ex", 3, (("Basic Metal Energy", 12),),
              (("Fezandipiti ex", 1),), (4, 0), candy=False),
    Archetype("terapagos", "Terapagos ex", "Terapagos ex", 3, (("Basic Water Energy", 10),),
              (("Duskull", 2), ("Dusclops", 2), ("Dusknoir", 2), ("Fezandipiti ex", 1)), candy=True),
    Archetype("iron-thorns", "Iron Thorns ex", "Iron Thorns ex", 4, (("Basic Lightning Energy", 11),),
              (("Iron Hands ex", 1), ("Latias ex", 1)), candy=False),
    Archetype("ceruledge", "Ceruledge ex", "Ceruledge ex", 3, (("Basic Fire Energy", 11),),
              (("Fezandipiti ex", 1),), (4, 0), candy=False),
    Archetype("roaring-moon", "Roaring Moon ex", "Roaring Moon ex", 4, (("Basic Darkness Energy", 10),),
              (("Squawkabilly ex", 1), ("Munkidori", 1)), candy=False),
    Archetype("archaludon", "Archaludon ex", "Archaludon ex", 3, (("Basic Metal Energy", 12),),
              (("Fezandipiti ex", 1),), (4, 0), candy=False),
    Archetype("milotic", "Milotic ex", "Milotic ex", 3, (("Basic Water Energy", 11),),
              (("Fezandipiti ex", 1),), (4, 0), candy=False),
    Archetype("chien-pao", "Chien-Pao ex", "Chien-Pao ex", 4, (("Basic Water Energy", 12),),
              (("Frigibax", 3), ("Arctibax", 1), ("Baxcalibur", 3)), candy=True),
    Archetype("blissey", "Blissey ex", "Blissey ex", 3, (("Basic Psychic Energy", 12),),
              (("Fezandipiti ex", 1),), (4, 0), candy=False),
    Archetype("pikachu", "Pikachu ex", "Pikachu ex", 4, (("Basic Lightning Energy", 10),),
              (("Latias ex", 1), ("Fan Rotom", 1)), candy=False),
    Archetype("iron-valiant", "Iron Valiant ex", "Iron Valiant ex", 4, (("Basic Psychic Energy", 10),),
              (("Munkidori", 2), ("Fezandipiti ex", 1)), candy=False),
    Archetype("hydreigon", "Hydreigon ex", "Hydreigon ex", 3, (("Basic Darkness Energy", 12),),
              (("Munkidori", 1),), (4, 2)),
    Archetype("tyranitar", "Tyranitar ex", "Tyranitar ex", 3, (("Basic Darkness Energy", 11),),
              (("Fezandipiti ex", 1),), (4, 2)),
    Archetype("greninja", "Greninja ex", "Greninja ex", 3, (("Basic Water Energy", 11),),
              (("Fezandipiti ex", 1),), (4, 2)),
    Archetype("alakazam", "Alakazam ex", "Alakazam ex", 3, (("Basic Psychic Energy", 11),),
              (("Munkidori", 1),), (4, 2)),
    Archetype("mega-lucario", "Mega Lucario ex", "Mega Lucario ex", 3, (("Basic Fighting Energy", 11),),
              (("Fezandipiti ex", 1),), (4, 0), candy=False),
    Archetype("mega-gardevoir", "Mega Gardevoir ex", "Mega Gardevoir ex", 3,
              (("Basic Psychic Energy", 12),), (("Munkidori", 1),), (4, 3)),
    Archetype("mega-venusaur", "Mega Venusaur ex", "Mega Venusaur ex", 3, (("Basic Grass Energy", 12),),
              (("Fezandipiti ex", 1),), (4, 2)),
    Archetype("flareon", "Flareon ex", "Flareon ex", 3, (("Basic Fire Energy", 11),),
              (("Jolteon ex", 2), ("Vaporeon ex", 1)), (4, 0), candy=False),
    Archetype("genesect", "Genesect ex", "Genesect ex", 4, (("Basic Metal Energy", 11),),
              (("Zacian ex", 2), ("Fezandipiti ex", 1)), candy=False),
]

# Prints that a real list would name, where the newest reprint is not the one.
PINNED = {
    "Charizard ex": "OBF", "Gardevoir ex": "SVI", "Dragapult ex": "TWM",
    "Pidgeot ex": "OBF", "Chien-Pao ex": "PAL", "Baxcalibur": "PAL",
    "Miraidon ex": "SVI", "Iron Hands ex": "PAR", "Roaring Moon ex": "PAR",
    "Raging Bolt ex": "TEF", "Terapagos ex": "SCR", "Gholdengo ex": "PAR",
    "Iron Thorns ex": "TWM", "Ceruledge ex": "SSP", "Archaludon ex": "SSP",
}

# Tech Pokémon the variants rotate through, so the field is not 100 of one shell.
TECHS = [
    "Fan Rotom", "Latias ex", "Squawkabilly ex", "Munkidori", "Mew ex",
    "Jirachi", "Klefki", "Budew", "Bloodmoon Ursaluna ex", "Lillie's Clefairy ex",
    "Fezandipiti ex", "Iron Hands ex",
]

# Four variants per archetype: the stock list, then three tuned versions.
VARIANTS = [
    ("standard", {}),
    ("aggro", {"attacker": +1, "energy": -1, "techs": 1}),
    ("techy", {"energy": -2, "techs": 2}),
    ("grind", {"energy": +1, "techs": 1, "shell": ("Counter Catcher", 2)}),
]


def find(pool, name: str):
    """Look a card up, honouring the print a real list would name."""
    code = PINNED.get(name)
    if code:
        for card in pool.prints(name):
            if CODE_FOR_SET.get(card.set_id) == code:
                return card
    return pool.lookup(name)


def evolution_line(pool, attacker_name: str, counts: tuple[int, int]) -> list[tuple[str, int]]:
    """Walk an attacker back down its evolution line, using printed cards."""
    card = find(pool, attacker_name)
    if card is None:
        raise SystemExit(f"unknown attacker {attacker_name!r}")
    chain = [card]
    while chain[0].evolves_from:
        previous = find(pool, chain[0].evolves_from)
        if previous is None:
            break
        chain.insert(0, previous)
    basics, middles = counts
    line: list[tuple[str, int]] = []
    for depth, member in enumerate(chain[:-1]):
        line.append((member.name, basics if depth == 0 else middles))
    return [entry for entry in line if entry[1] > 0]


def build(pool, archetype: Archetype, variant_name: str, tweak: dict, seed: int = 0) -> str:
    counts: dict[str, int] = {}

    def add(name: str, n: int) -> None:
        if n <= 0:
            return
        counts[name] = counts.get(name, 0) + n

    for name, n in evolution_line(pool, archetype.attacker, archetype.line_counts):
        add(name, n)
    add(archetype.attacker, min(4, archetype.copies + tweak.get("attacker", 0)))
    for name, n in archetype.support:
        add(name, n)
    for offset in range(tweak.get("techs", 0)):
        tech = TECHS[(seed + offset * 5) % len(TECHS)]
        if tech != archetype.attacker:
            add(tech, 1)

    energy_total = 0
    biggest = max(n for _, n in archetype.energy)
    for name, n in archetype.energy:
        amount = max(4, n + tweak.get("energy", 0)) if n == biggest else n
        add(name, amount)
        energy_total += amount

    pokemon = sum(
        n for name, n in counts.items()
        if find(pool, name) and find(pool, name).category is Category.POKEMON
    )
    remaining = 60 - pokemon - energy_total
    if remaining < 0:
        raise SystemExit(f"{archetype.key}/{variant_name}: {abs(remaining)} cards over")

    shell = list(SHELL)
    if archetype.candy:
        shell.insert(2, ("Rare Candy", 4))
    if "shell" in tweak:
        shell.insert(0, tweak["shell"])
    for name, cap in shell:
        if remaining <= 0:
            break
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
        card = find(pool, name)
        category = card.category if card else Category.TRAINER
        set_code = CODE_FOR_SET.get(card.set_id, "") if card else ""
        number = card.card_id.split("-")[-1].lstrip("0") if card and card.card_id else ""
        if card and card.is_basic_energy:
            set_code, number = "", ""
        suffix = f" {set_code} {number}" if set_code and number else ""
        groups[category].append(f"{n} {name}{suffix}")
        totals[category] += n

    lines = [f"# {title}"]
    for category, label in ((Category.POKEMON, "Pokémon"), (Category.TRAINER, "Trainer"), (Category.ENERGY, "Energy")):
        if not groups[category]:
            continue
        lines.append(f"{label}: {totals[category]}")
        lines.extend(sorted(groups[category]))
        lines.append("")
    lines.append(f"Total Cards: {sum(totals.values())}")
    return "\n".join(lines) + "\n"


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
            text = build(pool, archetype, variant_name, tweak, seed=position)
            deck = parse(text, name=f"{archetype.name} ({variant_name})")
            problems = [i for i in validate(deck) if i.level == "error"]
            if problems:
                raise SystemExit(f"{archetype.key}/{variant_name}: {problems[0].message}")
            resolution = resolve(deck)
            if resolution.unknown:
                raise SystemExit(f"{archetype.key}/{variant_name}: unknown {resolution.unknown}")
            (out / f"{archetype.key}-{variant_name}.txt").write_text(text, encoding="utf-8")
            written += 1
    print(f"wrote {written} decklists to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
