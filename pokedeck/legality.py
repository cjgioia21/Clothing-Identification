"""Format legality: is every card in the deck one you are allowed to play?

Standard rotates once a year by regulation mark. The April 2026 rotation
dropped G, so Standard is currently H, I and J — plus basic Energy, which has
no mark and never rotates.

Some sets carry no regulation mark at all in the card data — the anniversary
sets and the Energy-only products. That is a gap in what we know, not evidence
that the card is illegal, so those are reported as unverified rather than
rejected.
"""

from __future__ import annotations

from .cards import Category, Deck
from .decklist import Issue
from .knowledge import Resolution
from .pool import load_pool

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


def mark_is_known(card) -> bool:
    """Does the card data actually say what regulation mark this print has?"""
    return bool(card.regulation)


def check(deck: Deck, resolution: Resolution, format_name: str = "standard") -> list[Issue]:
    """Legality problems, as errors, plus warnings for cards we cannot verify.

    Each line is checked against the print it names, so a list running two
    printings of the same card is told which one is the problem.
    """
    marks = marks_for(format_name)
    pool = load_pool()
    issues: list[Issue] = []
    ace_specs: list[str] = []

    for entry in deck.entries:
        card = resolution.get(entry.name)
        printed, _ = pool.lookup_print(entry.name, entry.set_code, entry.number)
        if printed is not None:
            card = printed
        label = f"{entry.name} {entry.set_code} {entry.number}".strip()

        if card.ace_spec:
            ace_specs.append(f"{entry.count} {entry.name}")
        if card.is_basic_energy:
            continue
        if not card.known:
            issues.append(Issue("warning", f"{label}: no printed card found, legality unverified"))
            continue
        if not mark_is_known(card):
            issues.append(Issue(
                "warning",
                f"{label} ({card.card_id}) carries no regulation mark in the card data — "
                f"legality in {format_name} unverified",
            ))
            continue
        if not card_is_legal(card, marks):
            issues.append(Issue(
                "error",
                f"{label} ({card.card_id}) is regulation mark {card.regulation} — "
                f"not legal in {format_name}",
            ))

    total_ace = sum(
        entry.count for entry in deck.entries
        if (pool.lookup(entry.name, entry.set_code, entry.number) or resolution.get(entry.name)).ace_spec
    )
    if total_ace > ACE_SPEC_LIMIT:
        issues.append(Issue(
            "error",
            f"{total_ace} ACE SPEC cards ({', '.join(ace_specs)}) — a deck may contain only one",
        ))
    return issues


def is_legal(deck: Deck, resolution: Resolution, format_name: str = "standard") -> bool:
    return not [i for i in check(deck, resolution, format_name) if i.level == "error"]
