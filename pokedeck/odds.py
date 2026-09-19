"""Exact draw odds (hypergeometric), independent of the simulator."""

from __future__ import annotations

from math import comb

from .decklist import DECK_SIZE, PRIZE_COUNT


def at_least(copies: int, drawn: int, deck_size: int = DECK_SIZE, wanted: int = 1) -> float:
    """P(at least ``wanted`` of ``copies`` in ``drawn`` cards off the top)."""
    if wanted <= 0:
        return 1.0
    if copies < wanted or drawn <= 0 or deck_size <= 0:
        return 0.0
    drawn = min(drawn, deck_size)
    total = comb(deck_size, drawn)
    misses = sum(
        comb(copies, k) * comb(deck_size - copies, drawn - k)
        for k in range(0, wanted)
        if 0 <= drawn - k <= deck_size - copies
    )
    return 1.0 - misses / total


def exactly(copies: int, drawn: int, deck_size: int = DECK_SIZE, hits: int = 1) -> float:
    """P(exactly ``hits`` of ``copies`` in ``drawn`` cards)."""
    if hits > copies or hits > drawn or drawn > deck_size:
        return 0.0
    return comb(copies, hits) * comb(deck_size - copies, drawn - hits) / comb(deck_size, drawn)


def cards_seen(turn: int, going_first: bool = True, extra_draw: int = 0) -> int:
    """Cards seen by the end of ``turn`` with no draw support at all.

    Turn 0 is the opening hand. Both players draw at the start of every turn
    under current rules, so each turn adds one card.
    """
    return 7 + max(0, turn) + extra_draw


def prized(copies: int, deck_size: int = DECK_SIZE, prizes: int = PRIZE_COUNT, hits: int = 1) -> float:
    """P(at least ``hits`` copies sit in the prize cards)."""
    return at_least(copies, prizes, deck_size, hits)


def mulligan_rate(basics: int, deck_size: int = DECK_SIZE) -> float:
    """P(an opening hand of 7 contains no Basic Pokémon)."""
    return 1.0 - at_least(basics, 7, deck_size, 1)


def copies_for(target: float, drawn: int, deck_size: int = DECK_SIZE, wanted: int = 1) -> int:
    """Fewest copies whose ``at_least`` odds reach ``target`` (0 if impossible)."""
    for copies in range(wanted, deck_size + 1):
        if at_least(copies, drawn, deck_size, wanted) >= target:
            return copies
    return 0
