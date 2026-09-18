"""Parse and validate decklists in PTCG Live / PTCGO export format."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .cards import Category, Deck, DeckEntry

DECK_SIZE = 60
PRIZE_COUNT = 6
MAX_COPIES = 4

_HEADERS = {
    "pokemon": Category.POKEMON,
    "pokémon": Category.POKEMON,
    "trainer": Category.TRAINER,
    "trainers": Category.TRAINER,
    "energy": Category.ENERGY,
}

_LINE = re.compile(
    r"""^\s*
    (?P<count>\d+)         \s+
    (?P<name>.+?)
    (?:\s+(?P<set>[A-Z]{2,4}|PR-[A-Z]{2,4})\s+(?P<number>[A-Za-z0-9]+))?
    \s*$""",
    re.VERBOSE,
)

_BASIC_ENERGY = re.compile(r"^basic\s+(.+?)\s+energy$", re.IGNORECASE)


class DecklistError(ValueError):
    pass


@dataclass
class Issue:
    level: str  # "error" or "warning"
    message: str


def parse(text: str, name: str = "deck") -> Deck:
    """Parse a decklist export into a :class:`Deck`.

    Category headers ("Pokémon: 12") are used when present; otherwise the
    category is guessed from the card name.
    """
    deck = Deck(name=name)
    current = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        header = _match_header(line)
        if header is not None:
            current = header
            continue
        if line.lower().startswith("total cards"):
            continue
        match = _LINE.match(line)
        if not match:
            raise DecklistError(f"could not parse line: {raw_line!r}")
        card_name = _normalise_name(match.group("name"))
        deck.entries.append(
            DeckEntry(
                count=int(match.group("count")),
                name=card_name,
                set_code=match.group("set"),
                number=match.group("number"),
                category=current or _guess_category(card_name),
            )
        )
    if not deck.entries:
        raise DecklistError("decklist is empty")
    return deck


def parse_file(path: str) -> Deck:
    with open(path, encoding="utf-8") as handle:
        return parse(handle.read(), name=path)


def format_deck(deck: Deck) -> str:
    """Render a deck back out in PTCG Live export format."""
    lines: list[str] = []
    for category, label in (
        (Category.POKEMON, "Pokémon"),
        (Category.TRAINER, "Trainer"),
        (Category.ENERGY, "Energy"),
    ):
        entries = [e for e in deck.entries if e.category is category]
        if not entries:
            continue
        lines.append(f"{label}: {sum(e.count for e in entries)}")
        lines.extend(e.label() for e in entries)
        lines.append("")
    lines.append(f"Total Cards: {deck.size}")
    return "\n".join(lines)


def validate(deck: Deck) -> list[Issue]:
    """Check the deck against the standard construction rules."""
    issues: list[Issue] = []
    if deck.size != DECK_SIZE:
        issues.append(Issue("error", f"deck has {deck.size} cards, expected {DECK_SIZE}"))

    totals: dict[str, int] = {}
    for entry in deck.entries:
        totals[entry.name] = totals.get(entry.name, 0) + entry.count
    for name, count in totals.items():
        if count > MAX_COPIES and not is_basic_energy_name(name):
            issues.append(Issue("error", f"{count} copies of {name} (limit {MAX_COPIES})"))

    duplicates = [n for n, _ in totals.items() if sum(1 for e in deck.entries if e.name == n) > 1]
    for name in sorted(set(duplicates)):
        issues.append(Issue("warning", f"{name} is listed on more than one line"))

    if not any(e.category is Category.POKEMON for e in deck.entries):
        issues.append(Issue("error", "deck contains no Pokémon"))
    return issues


def is_basic_energy_name(name: str) -> bool:
    return bool(_BASIC_ENERGY.match(name.strip()))


def _match_header(line: str) -> Category | None:
    """Recognise category headers such as "Pokémon: 12" or "Energy (14)"."""
    head = re.sub(r"[:\-]?\s*\(?\d*\)?\s*$", "", line).strip().lower()
    return _HEADERS.get(head)


def _normalise_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"\s+", " ", name)
    return name


def _guess_category(name: str) -> Category:
    if is_basic_energy_name(name) or name.lower().endswith("energy"):
        return Category.ENERGY
    return Category.TRAINER
