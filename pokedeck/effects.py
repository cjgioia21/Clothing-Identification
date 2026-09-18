"""Turn printed card text into the small effect scripts the engines run.

Card text is English prose, so this is a best-effort compiler: it reads the
sentences it recognises and marks anything left over as unmodelled, which the
reports surface as coverage rather than quietly pretending the card is blank.
"""

from __future__ import annotations

import re

from .cards import Attack, Effect

STATUSES = ("asleep", "paralyzed", "confused", "burned", "poisoned")

# Sentences that change nothing the simulator tracks.
_IGNORABLE = (
    r"move an energy from this pok.mon",
    r"you may discard a stadium in play",
    r"can't retreat",
    r"this attack can be used even if this pok.mon is on the bench",
    r"if you go second, you can't use this attack during your first turn",
    r"discard a random card from your opponent's hand",
    r"this pok.mon has no weakness",
    r"don't apply weakness and resistance for benched pok.mon",
    r"if your opponent's active pok.mon is knocked out in this way",
    r"then,? shuffle your deck",
    r"shuffle your deck",
    r"you may play only one supporter card during your turn",
    r"you may play any number of item cards during your turn",
    r"if this pok.mon (?:is|was) .* nothing happens",
    r"this card stays in play",
    r"you can't use more than 1 .* ability",
    r"(?:the|this) effect lasts until",
)

_PATTERNS: list[tuple[int, re.Pattern, callable]] = []


def _pattern(regex: str, priority: int = 0):
    """Register a text pattern. Higher priority wins when several could match."""
    def register(func):
        _PATTERNS.append((priority, re.compile(regex, re.IGNORECASE), func))
        _PATTERNS.sort(key=lambda entry: -entry[0])
        return func

    return register


@_pattern(r"does (\d+) more damage for each prize card your opponent has taken")
def _bonus_opp_prizes(m):
    return [Effect(op="bonus_per", n=int(m.group(1)), filter="opponent_prizes_taken")]


@_pattern(r"does (\d+) more damage for each prize card you have taken")
def _bonus_own_prizes(m):
    return [Effect(op="bonus_per", n=int(m.group(1)), filter="own_prizes_taken")]


@_pattern(r"does (\d+) more damage for each (?:basic )?energy attached to (?:this|that) pok.mon")
def _bonus_energy(m):
    return [Effect(op="bonus_per", n=int(m.group(1)), filter="energy_on_self")]


@_pattern(r"does (\d+) more damage for each damage counter on this pok.mon")
def _bonus_damage_counters(m):
    return [Effect(op="bonus_per", n=int(m.group(1)), filter="damage_counters_on_self")]


@_pattern(r"does (\d+) more damage for each of your benched pok.mon")
def _bonus_bench(m):
    return [Effect(op="bonus_per", n=int(m.group(1)), filter="own_bench")]


@_pattern(r"flip a coin\. if heads,? this attack does (\d+) more damage")
def _coin_bonus(m):
    return [Effect(op="coin_bonus", n=int(m.group(1)))]


@_pattern(r"this attack does (\d+) damage to each of your opponent's benched pok.mon")
def _bench_all(m):
    return [Effect(op="bench_damage", n=int(m.group(1)), dest="opponent")]


@_pattern(r"this attack does (\d+) damage to (?:1|one) of your opponent's benched pok.mon")
def _snipe(m):
    return [Effect(op="snipe", n=int(m.group(1)), dest="opponent")]


@_pattern(r"your opponent's active pok.mon is now (asleep|paralyzed|confused|burned|poisoned)")
def _status(m):
    return [Effect(op="status", filter=m.group(1).lower(), dest="opponent")]


@_pattern(r"discard (\d+|a|an|all|two|three) (?:\w+ )?energy (?:card(?:s)? )?(?:attached to |from )this pok.mon")
def _discard_energy(m):
    return [Effect(op="discard_energy_self", n=_count(m.group(1)))]


@_pattern(r"heal (\d+) damage from this pok.mon")
def _heal(m):
    return [Effect(op="heal_self", n=int(m.group(1)))]


@_pattern(r"this pok.mon (?:also )?does (\d+) damage to itself")
def _recoil(m):
    return [Effect(op="self_damage", n=int(m.group(1)))]


@_pattern(r"this pok.mon can't attack during your next turn")
def _no_attack(m):
    return [Effect(op="no_attack_next_turn")]


@_pattern(r"switch this pok.mon with (?:1|one) of your benched pok.mon")
def _switch_self(m):
    return [Effect(op="switch_self")]


@_pattern(r"switch (?:in )?(?:1|one) of your opponent's benched pok.mon (?:with|to)")
def _gust(m):
    return [Effect(op="switch_opponent")]


@_pattern(r"during your opponent's next turn,? .*takes? (\d+) less damage")
def _shield(m):
    return [Effect(op="shield", n=int(m.group(1)))]


@_pattern(r"draw (\d+|a|two|three|four|five|six|seven) cards?")
def _draw(m):
    return [Effect(op="draw", n=_count(m.group(1)))]


@_pattern(r"discard (\d+|a|an|two|three) card(?:s)? from your hand")
def _discard_cost(m):
    return [Effect(op="discard_from_hand", n=_count(m.group(1)))]


@_pattern(r"attach (?:up to )?(\d+|a|an|two|three) basic (?:\{?\w+\}? )?energy card(?:s)? from your (deck|discard pile)")
def _accelerate(m):
    return [Effect(op="attach_energy", n=_count(m.group(1)), filter="basic_energy", dest=m.group(2).split()[0])]


@_pattern(r"search your deck for (?:up to )?(\d+|a|an|two|three) (basic pok.mon|pok.mon|item|supporter|basic energy|energy)")
def _search(m):
    targets = {
        "basic pokémon": "basic_pokemon",
        "basic pokemon": "basic_pokemon",
        "pokémon": "pokemon",
        "pokemon": "pokemon",
        "item": "item",
        "supporter": "supporter",
        "basic energy": "basic_energy",
        "energy": "energy",
    }
    return [Effect(op="search", n=_count(m.group(1)), filter=targets.get(m.group(2).lower(), "any"))]




@_pattern(r"discard your hand and draw (\d+) cards?", priority=10)
def _research(m):
    return [Effect(op="discard_hand"), Effect(op="draw", n=int(m.group(1)))]


@_pattern(r"shuffles? (?:their|your) hand and puts? it on the bottom of (?:their|your) deck", priority=10)
def _iono(m):
    return [Effect(op="shuffle_hand_into_deck"), Effect(op="draw_prizes")]


@_pattern(r"shuffle your hand into your deck\. then,? draw (\d+) cards?", priority=10)
def _judge(m):
    return [Effect(op="shuffle_hand_into_deck"), Effect(op="draw", n=int(m.group(1)))]


@_pattern(r"only if you discard (\d+|a|an|two|three) other cards? from your hand", priority=10)
def _ball_cost(m):
    return [Effect(op="discard_from_hand", n=_count(m.group(1)))]


@_pattern(r"only if you discard (\d+|a|an|two|three) cards? from your hand", priority=10)
def _item_cost(m):
    return [Effect(op="discard_from_hand", n=_count(m.group(1)))]


@_pattern(r"put (?:a|\d+|up to \d+) pok.mon(?: or a basic energy card)?(?:s)? from your discard pile into your hand", priority=10)
def _stretcher(m):
    return [Effect(op="recover", n=1)]


@_pattern(r"shuffle up to (\d+) in any combination of pok.mon and basic energy cards from your discard pile into your deck", priority=10)
def _super_rod(m):
    return [Effect(op="recover", n=int(m.group(1)))]


@_pattern(r"search your deck for (?:up to )?(\d+|a|an|two|three) (?:basic )?pok.mon[^.]*?and put (?:it|them) onto your bench", priority=10)
def _bench_search(m):
    return [Effect(op="search", n=_count(m.group(1)), filter="basic_pokemon", dest="bench")]


@_pattern(r"search your deck for an item card and a pok.mon tool card", priority=10)
def _arven(m):
    return [Effect(op="search", n=1, filter="item"), Effect(op="search", n=1, filter="tool")]


@_pattern(r"switch your active pok.mon with (?:1|one) of your benched pok.mon", priority=10)
def _switch_own(m):
    return [Effect(op="switch_self")]


@_pattern(r"heal (\d+) damage from (?:1|one) of your pok.mon", priority=10)
def _heal_any(m):
    return [Effect(op="heal_team", n=int(m.group(1)))]



@_pattern(r"this attack does (\d+) damage for each card you discarded in this way", priority=20)
def _discard_scale(m):
    return [Effect(op="discard_energy_scale", n=int(m.group(1)), filter="pokemon")]


@_pattern(r"discard any (?:amount|number) of (?:basic )?(?:\{?\w+\}? )?energy cards? from your hand", priority=20)
def _discard_scale_hand(m):
    return [Effect(op="discard_energy_scale", n=0, filter="hand")]


@_pattern(r"discard any (?:amount|number) of (?:basic )?(?:\{?\w+\}? )?energy from your pok.mon", priority=20)
def _discard_scale_board(m):
    return [Effect(op="discard_energy_scale", n=0, filter="pokemon")]


@_pattern(r"this attack does (\d+) damage for each of your benched pok.mon", priority=20)
def _scale_bench(m):
    return [Effect(op="scale", n=int(m.group(1)), filter="own_bench")]


@_pattern(r"this attack does (\d+) damage for each (?:\{?\w+\}? )?energy attached to all of your pok.mon", priority=20)
def _scale_team_energy(m):
    return [Effect(op="scale", n=int(m.group(1)), filter="team_energy")]


@_pattern(r"this attack does (\d+) damage for each (?:\{?\w+\}? )?energy attached to this pok.mon", priority=20)
def _scale_self_energy(m):
    return [Effect(op="scale", n=int(m.group(1)), filter="energy_on_self")]


@_pattern(r"does (\d+) more damage for each of your opponent's benched pok.mon", priority=15)
def _bonus_opp_bench(m):
    return [Effect(op="bonus_per", n=int(m.group(1)), filter="opponent_bench")]


@_pattern(r"does (\d+) more damage for each energy card in your discard pile", priority=15)
def _bonus_discard_energy(m):
    return [Effect(op="bonus_per", n=int(m.group(1)), filter="energy_in_discard")]


@_pattern(r"during your next turn,? this pok.mon can't (?:attack|use)", priority=15)
def _no_attack_next_alt(m):
    return [Effect(op="no_attack_next_turn")]


@_pattern(r"put (\d+) damage counters? on your opponent's benched pok.mon", priority=20)
def _bench_counters(m):
    return [Effect(op="bench_counters", n=int(m.group(1)) * 10)]


@_pattern(r"this attack does (\d+) damage to (\d+) of your opponent's pok.mon", priority=20)
def _snipe_multi(m):
    return [Effect(op="snipe_multi", n=int(m.group(1)), dest=m.group(2))]


@_pattern(r"if you do,? this attack does (\d+) more damage", priority=20)
def _stadium_bonus(m):
    return [Effect(op="stadium_bonus", n=int(m.group(1)))]


@_pattern(r"knock out your opponent's active pok.mon", priority=20)
def _ko_target(m):
    return [Effect(op="ko_target")]


@_pattern(r"prevent all damage done to this pok.mon by attacks", priority=20)
def _prevent(m):
    return [Effect(op="shield", n=999)]


@_pattern(r"this pok.mon recovers from all special conditions", priority=20)
def _recover_conditions(m):
    return [Effect(op="clear_conditions")]


@_pattern(r"draw cards until you have (\d+) cards in your hand", priority=20)
def _draw_until(m):
    return [Effect(op="draw_to", n=int(m.group(1)))]


@_pattern(r"search your deck for a card and put it into your hand", priority=20)
def _search_any(m):
    return [Effect(op="search", n=1, filter="any")]


@_pattern(r"search your deck for (?:up to )?(\d+|a|an|two|three) basic (?:\{?\w+\}? )?energy cards? and attach", priority=25)
def _search_attach(m):
    return [Effect(op="attach_energy", n=_count(m.group(1)), filter="basic_energy", dest="deck")]


@_pattern(r"for each of your benched pok.mon,? search your deck for a basic (?:\{?\w+\}? )?energy card and attach it", priority=20)
def _spread_energy(m):
    return [Effect(op="attach_energy", n=3, filter="basic_energy", dest="deck")]


_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
          "six": 6, "seven": 7, "all": 99}


def _count(token: str) -> int:
    token = token.strip().lower()
    return int(token) if token.isdigit() else _WORDS.get(token, 1)


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!])\s+", text or "")
    return [p.strip() for p in parts if p.strip()]


def compile_text(text: str) -> tuple[list[Effect], list[str]]:
    """Compile card text, returning its effects and the sentences we ignored."""
    effects: list[Effect] = []
    unmodelled: list[str] = []
    for sentence in sentences(text):
        matched = False
        for _, regex, build in _PATTERNS:
            found = regex.search(sentence)
            if found:
                effects.extend(build(found))
                matched = True
                break
        if matched:
            continue
        if any(re.search(pattern, sentence, re.IGNORECASE) for pattern in _IGNORABLE):
            continue
        unmodelled.append(sentence)
    return effects, unmodelled


def parse_damage(raw: str | None) -> tuple[int, str]:
    """"180+" -> (180, "+"), "30x" -> (30, "x"), "" -> (0, "")."""
    if not raw:
        return 0, ""
    text = str(raw).strip().replace("×", "x").replace("X", "x")
    match = re.match(r"^(\d+)\s*([+x])?$", text)
    if not match:
        digits = re.findall(r"\d+", text)
        return (int(digits[0]) if digits else 0), ""
    return int(match.group(1)), match.group(2) or ""


def compile_attack(raw: dict) -> Attack:
    damage, scaling = parse_damage(raw.get("damage"))
    text = raw.get("effect") or ""
    effects, unmodelled = compile_text(text)
    return Attack(
        name=raw.get("name", "Attack"),
        cost=tuple(raw.get("cost", ()) or ()),
        damage=damage,
        scaling=scaling,
        text=text,
        effects=tuple(effects),
        scripted=not unmodelled,
    )


def compile_ability(raw: dict) -> tuple[tuple[Effect, ...], str, bool]:
    """Compile an Ability, returning (effects, trigger, fully_scripted)."""
    text = raw.get("effect") or ""
    effects, unmodelled = compile_text(text)
    if "as often as you like" in text.lower():
        effects = [Effect(op=e.op, n=max(e.n, 3), filter=e.filter, dest=e.dest) for e in effects]
    lowered = text.lower()
    if "when you play this pok" in lowered and "from your hand" in lowered:
        trigger = "on_evolve" if "to evolve" in lowered else "on_play"
    else:
        trigger = "turn"
    return tuple(effects), trigger, not unmodelled
