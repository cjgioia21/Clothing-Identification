"""Turn a written gauntlet document into the 100 decklists the field is played from.

The source is a .docx of the form

    DECK-001  |  Dragapult ex — Balanced
    Tags: ...  •  Profile: ...
    Pokémon
    17 — 4 Dreepy; 4 Drakloak; 3 Dragapult ex; ...
    Trainers
    34 — 1 Unfair Stamp; 2 Risky Ruins; ...
    Energy
    9 — 4 Basic Fire Energy; ...
    Total
    60 cards

which names cards without pinning a printing. Every name is resolved against
the bundled pool, preferring a Standard-legal print, and the set code and number
of whatever print was chosen is written into the decklist — so the field stays
readable and stays reproducible.

    python tools/import_gauntlet.py gauntlet.docx --check   # report, write nothing
    python tools/import_gauntlet.py gauntlet.docx           # rewrite the field
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokedeck.cards import Category  # noqa: E402
from pokedeck.decklist import parse, validate  # noqa: E402
from pokedeck.knowledge import resolve  # noqa: E402
from pokedeck.legality import card_is_legal  # noqa: E402
from pokedeck.legality import check as legality_check  # noqa: E402
from pokedeck.pool import SET_CODES, load_pool  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "pokedeck" / "data" / "gauntlet"
CODE_FOR_SET = {v: k for k, v in SET_CODES.items()}

VARIANTS = {
    "Balanced": "standard",
    "Consistency": "grind",
    "Aggression": "aggro",
    "Disruption": "techy",
}

HEADER = re.compile(r"^DECK-(\d+)\s*\|\s*(.+?)\s+[—–-]\s+(\w+)\s*$")
SECTIONS = {"Pokémon": "Pokémon", "Pokemon": "Pokémon",
            "Trainers": "Trainer", "Trainer": "Trainer", "Energy": "Energy"}


def read_docx(path: Path) -> list[str]:
    """The document's text, one line per paragraph."""
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    xml = re.sub(r"</w:p>|<w:br[^>]*/>", "\n", xml)
    text = html.unescape(re.sub(r"<[^>]+>", "", xml))
    return [line.strip() for line in text.splitlines()]


def parse_document(lines: list[str]) -> list[dict]:
    """Every deck in the document, as {id, archetype, variant, sections}."""
    decks: list[dict] = []
    current: dict | None = None
    section: str | None = None
    for line in lines:
        header = HEADER.match(line)
        if header:
            number, archetype, variant = header.groups()
            current = {"id": int(number), "archetype": archetype.strip(),
                       "variant": variant.strip(), "sections": {}}
            decks.append(current)
            section = None
            continue
        if current is None:
            continue
        if line in SECTIONS:
            section = SECTIONS[line]
            continue
        if section and "—" in line or (section and "-" in line and ";" in line):
            current["sections"][section] = parse_entries(line)
            section = None
    return decks


def parse_entries(line: str) -> list[tuple[int, str]]:
    """"17 — 4 Dreepy; 4 Drakloak" -> [(4, "Dreepy"), (4, "Drakloak")]."""
    body = re.split(r"\s[—–-]\s", line, maxsplit=1)[-1]
    entries = []
    for chunk in body.split(";"):
        match = re.match(r"^\s*(\d+)\s+(.+?)\s*$", chunk)
        if match:
            entries.append((int(match.group(1)), match.group(2)))
    return entries


# The document names a few cards by their plain form inside a deck that plays
# the branded version. Each of these was checked against the deck it appears in
# before being written down; nothing is renamed that the list does not settle.
ALIASES = {
    "Spidops": "Team Rocket's Spidops",
    "Tarountula": "Team Rocket's Tarountula",
}

MARK_ORDER = {"J": 3, "I": 2, "H": 1}


def best_print(pool, name: str):
    """The most playable print of this card: legal, marked, base art.

    A Standard-legal print wins. Failing that an unmarked one — the card data
    has no mark for the anniversary sets, which is a gap in what we know rather
    than a card being illegal — and only then a print we know has rotated.
    """
    prints = pool.prints(name) if hasattr(pool, "prints") else []
    if not prints:
        return None

    def rank(card):
        tier = 0 if card_is_legal(card) else (1 if not card.regulation else 2)
        number = card.card_id.split("-")[-1]
        digits = int(re.sub(r"\D", "", number) or 0)
        return (tier, digits, -MARK_ORDER.get((card.regulation or "").upper(), 0))

    return min(prints, key=rank)


def pin(card) -> str:
    """The "SSP 130" suffix, when the pool knows where the print came from."""
    code = CODE_FOR_SET.get(card.set_id)
    number = card.card_id.split("-")[-1].lstrip("0") or "0"
    return f" {code} {number}" if code else ""


def render(deck: dict, pinned: dict[str, str]) -> str:
    slug = VARIANTS.get(deck["variant"], deck["variant"].casefold())
    out = [f"# {deck['archetype']} ({slug})"]
    for section in ("Pokémon", "Trainer", "Energy"):
        entries = deck["sections"].get(section, [])
        if not entries:
            continue
        out.append("")
        out.append(f"{section}: {sum(count for count, _ in entries)}")
        for count, name in entries:
            resolved = ALIASES.get(name, name)
            out.append(f"{count} {resolved}{pinned.get(name, '')}")
    out.append("")
    out.append("Total Cards: 60")
    return "\n".join(out) + "\n"


def slugify(archetype: str, variant: str) -> str:
    text = unicodedata.normalize("NFKD", archetype).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    return f"{text}-{VARIANTS.get(variant, variant.casefold())}.txt"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("document", type=Path)
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    pool = load_pool()
    decks = parse_document(read_docx(args.document))
    print(f"{len(decks)} decks in the document")

    missing: dict[str, int] = {}
    rotated: dict[str, str] = {}
    pinned: dict[str, str] = {}
    for deck in decks:
        for entries in deck["sections"].values():
            for _, name in entries:
                if name in pinned or name in missing:
                    continue
                card = best_print(pool, ALIASES.get(name, name))
                if card is None:
                    missing[name] = missing.get(name, 0) + 1
                    continue
                pinned[name] = "" if name.startswith("Basic ") else pin(card)
                if not card_is_legal(card):
                    rotated[name] = card.regulation or "no mark"

    if missing:
        print(f"\nNot in the card pool ({len(missing)}):")
        for name in sorted(missing):
            print(f"  {name}")
    if rotated:
        print(f"\nNo Standard-legal print in the pool ({len(rotated)}):")
        for name in sorted(rotated):
            print(f"  {name}  (regulation {rotated[name]})")

    problems = 0
    for deck in decks:
        text = render(deck, pinned)
        parsed = parse(text, name=deck["archetype"])
        issues = [p for p in validate(parsed) if p.level == "error"]
        issues += [p for p in legality_check(parsed, resolve(parsed)) if p.level == "error"]
        if issues:
            problems += 1
            print(f"\nDECK-{deck['id']:03d} {deck['archetype']} ({deck['variant']}):")
            for issue in issues[:6]:
                print(f"  [{issue.level}] {issue.message}")

    print(f"\n{len(decks) - problems}/{len(decks)} decks pass construction and format")
    if args.check:
        return 0

    for old in OUT.glob("*.txt"):
        old.unlink()
    for deck in decks:
        (OUT / slugify(deck["archetype"], deck["variant"])).write_text(
            render(deck, pinned), encoding="utf-8")
    print(f"wrote {len(list(OUT.glob('*.txt')))} decklists to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
