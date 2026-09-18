"""Format legality: is every card in the deck one you are allowed to play?

Standard rotates once a year by regulation mark. The April 2026 rotation
dropped G, so Standard is currently H, I and J — plus basic Energy, which has
no mark and never rotates.
"""

from __future__ import annotations

from .cards import Category, Deck
from .decklist import Issue
from .knowledge import Resolution

STANDARD_MARKS = frozenset({"H", "I", "J"})
ALL_MARKS = frozenset({"E", "F", "G", "H", "I", "J"})
ACE_SPEC_LIMIT = 1
FORMATS = {"standard": STANDARD_MARKS, "any": ALL_MARKS}


def marks_for(format_name: str) -> frozenset[str]:
    try:
        return FORMATS[format_name.lower()]
    except KeyError:
        raise ValueError(f"unknown format {format_name!r} (try: {', '.join(sorted(FORMATS))})") from None


def card_is_legal(card, marks: frozenset[str] = STANDARD_MARKS) -> bool:
    """Basic Energy is always legal; everything else needs a legal mark."""
    if card.is_basic_energy:
        return True
    return card.regulation.upper() in marks


def check(deck: Deck, resolution: Resolution, format_name: str = "standard") -> list[Issue]:
    """Legality problems, as errors, plus warnings for cards we cannot verify."""
    marks = marks_for(format_name)
    issues: list[Issue] = []

    ace_specs: list[str] = []
    for entry in deck.entries:
        card = resolution.get(entry.name)
        if not card.known or not card.regulation:
            if not card.is_basic_energy:
                issues.append(Issue("warning", f"{entry.name}: no printed card found, legality unverified"))
            continue
        if not card_is_legal(card, marks):
            issues.append(Issue(
                "error",
                f"{entry.name} ({card.card_id}) is regulation mark {card.regulation} — "
                f"not legal in {format_name}",
            ))
        if card.ace_spec:
            ace_specs.append(f"{entry.count} {entry.name}")

    total_ace = sum(
        entry.count for entry in deck.entries if resolution.get(entry.name).ace_spec
    )
    if total_ace > ACE_SPEC_LIMIT:
        issues.append(Issue(
            "error",
            f"{total_ace} ACE SPEC cards ({', '.join(ace_specs)}) — a deck may contain only one",
        ))
    return issues


def is_legal(deck: Deck, resolution: Resolution, format_name: str = "standard") -> bool:
    return not [i for i in check(deck, resolution, format_name) if i.level == "error"]
