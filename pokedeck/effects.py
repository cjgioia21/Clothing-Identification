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
    r"pok.mon ex, pok.mon v, etc",
    r"have rule boxes",
    r"if you go first, you may use this card during your first turn",
    r"shuffle the other cards back into your deck",
    r"choose 1 of your basic pok.mon in play",
    r"if you have a stage 2 card in your hand that evolves from that pok.mon",
    r"you can't use this card during your first turn or on a basic pok.mon",
    r"you still need the energy to use",
    r"reveal (it|them),? and put",
    r"^flip a coin\.?$",
    r"draw \d+ cards instead",
    r"if either player put any cards on the bottom of their deck",
    r"apply weakness as",
    r"and can't retreat",
    r"at any time during your turn, you may discard this card from play",
    r"you can't use more than 1",
    r"doesn't stack",
    r"if you do, the new active pok.mon is now poisoned",
    r"put the other card on the bottom of your deck",
    r"attach the other to 1 of your pok.mon",
    r"isn't affected by resistance",
    r"once during your turn, you may use this ability",
    r"your opponent reveals their hand",
    r"put this pok.mon into play only with the effect",
    r"takes? 1 fewer prize card",
    r"in any order",
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


@_pattern(r"search (?:your|their) deck for (?:up to )?(\d+|a|an|two|three) (basic pok.mon|pok.mon|item|supporter|basic energy|energy)")
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
def _shuffle_to_bottom(m):
    return [Effect(op="shuffle_hand_into_deck")]


@_pattern(r"draws? a card for each of (?:their|your) remaining prize cards", priority=20)
def _draw_per_prize(m):
    return [Effect(op="draw_prizes")]


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


@_pattern(r"search (?:your|their) deck for (?:up to )?(\d+|a|an|two|three) (?:basic )?pok.mon[^.]*?and put (?:it|them) onto your bench", priority=10)
def _bench_search(m):
    return [Effect(op="search", n=_count(m.group(1)), filter="basic_pokemon", dest="bench")]


@_pattern(r"search (?:your|their) deck for an item card and a pok.mon tool card", priority=10)
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


@_pattern(r"search (?:your|their) deck for a card and put it into your hand", priority=20)
def _search_any(m):
    return [Effect(op="search", n=1, filter="any")]


@_pattern(r"search (?:your|their) deck for (?:up to )?(\d+|a|an|two|three) basic (?:\{?\w+\}? )?energy cards? and attach", priority=25)
def _search_attach(m):
    return [Effect(op="attach_energy", n=_count(m.group(1)), filter="basic_energy", dest="deck")]


@_pattern(r"for each of your benched pok.mon,? search your deck for a basic (?:\{?\w+\}? )?energy card and attach it", priority=20)
def _spread_energy(m):
    return [Effect(op="attach_energy", n=3, filter="basic_energy", dest="deck")]


@_pattern(r"draw (\d+) cards instead", priority=30)
def _conditional_instead(m):
    return []  # the base draw already happened; the upside is situational


@_pattern(r"^shuffle your hand into your deck", priority=8)
def _shuffle_hand(m):
    return [Effect(op="shuffle_hand_into_deck")]


@_pattern(r"each player shuffles their hand into their deck and draws (\d+) cards", priority=20)
def _judge_all(m):
    return [Effect(op="shuffle_hand_into_deck"), Effect(op="draw", n=int(m.group(1)))]


@_pattern(r"if heads,? (?:that player |you )?draws? (\d+) cards", priority=20)
def _coin_draw(m):
    return [Effect(op="draw", n=int(m.group(1)), chance=50)]


@_pattern(r"look at the top (\d+) cards of your deck", priority=20)
def _dig(m):
    return [Effect(op="dig", n=int(m.group(1)), filter="any")]


@_pattern(r"you may reveal an? (supporter|item|pok.mon|basic energy|energy|stadium) card you find there", priority=20)
def _dig_take(m):
    targets = {"supporter": "supporter", "item": "item", "pokémon": "pokemon",
               "pokemon": "pokemon", "basic energy": "basic_energy", "energy": "energy",
               "stadium": "stadium"}
    return [Effect(op="dig_take", filter=targets.get(m.group(1).lower(), "any"))]


@_pattern(r"put up to (\d+) in any combination of .* from your discard pile into your hand", priority=20)
def _recover_to_hand(m):
    return [Effect(op="recover", n=int(m.group(1)), dest="hand")]


@_pattern(r"put up to (\d+) basic energy cards from your discard pile into your hand", priority=20)
def _energy_retrieval(m):
    return [Effect(op="recover", n=int(m.group(1)), filter="basic_energy", dest="hand")]


@_pattern(r"shuffle up to (\d+) (basic energy cards|pok.mon) from your discard pile into your deck", priority=20)
def _recycle(m):
    target = "basic_energy" if "energy" in m.group(2).lower() else "pokemon"
    return [Effect(op="recover", n=int(m.group(1)), filter=target)]


@_pattern(r"search (?:your|their) deck for any number of basic energy cards", priority=20)
def _energy_pro(m):
    return [Effect(op="search", n=2, filter="basic_energy")]


@_pattern(r"search (?:your|their) deck for any number of basic pok.mon and put them onto your bench", priority=25)
def _trolley(m):
    return [Effect(op="search", n=2, filter="basic_pokemon", dest="bench")]


@_pattern(r"the retreat cost of the pok.mon this card is attached to is (\{c\}(?:\{c\})?) less", priority=20)
def _retreat_less(m):
    return [Effect(op="retreat_less", n=m.group(1).lower().count("{c}"))]


@_pattern(r"put (?:up to )?(\d+) (?:supporter|item) cards? from your discard pile into your hand", priority=20)
def _headset(m):
    return [Effect(op="recover", n=int(m.group(1)), filter="supporter", dest="hand")]


@_pattern(r"this attack does (\d+) damage for each of your pok.mon in play that has the (\w+) attack", priority=25)
def _scale_named_attack(m):
    return [Effect(op="scale", n=int(m.group(1)), filter=f"attack:{m.group(2)}")]


@_pattern(r"this attack does (\d+) damage for each item card in your opponent's discard pile", priority=25)
def _scale_opponent_items(m):
    return [Effect(op="scale", n=int(m.group(1)), filter="opponent_item_discard")]


@_pattern(r"prevent all damage done to pok.mon that don't have a rule box .*by attacks from the opponent's pok.mon ex and pok.mon v", priority=25)
def _stadium_shelter(m):
    return [Effect(op="shelter_rule_boxless")]


@_pattern(r"play this card as if it were a (\d+)-hp basic", priority=25)
def _fossil(m):
    return [Effect(op="play_as_pokemon", n=int(m.group(1)))]


@_pattern(r"your opponent discards cards from their hand until they have (\d+) cards", priority=25)
def _hand_squeeze(m):
    return [Effect(op="opponent_discard_to", n=int(m.group(1)))]


@_pattern(r"your opponent reveals their hand,? and you discard up to (\d+) item cards", priority=25)
def _item_strip(m):
    return [Effect(op="opponent_discard_filter", n=int(m.group(1)), filter="item")]


@_pattern(r"discard up to (\d+) pok.mon[^.]*from your hand,? and draw (\d+) cards? for each card you discarded", priority=25)
def _discard_for_draw(m):
    count, per = int(m.group(1)), int(m.group(2))
    return [Effect(op="discard_from_hand", n=count, filter="pokemon"), Effect(op="draw", n=count * per)]


@_pattern(r"search (?:your|their) deck for up to (\d+) item cards that have .?antique.? in their name and put them onto their bench", priority=30)
def _fossil_quarry(m):
    return [Effect(op="search", n=int(m.group(1)), filter="fossil", dest="bench")]


@_pattern(r"search (?:your|their) deck for an evolution pok.mon and an energy card", priority=25)
def _hilda(m):
    return [Effect(op="search", n=1, filter="evolution"), Effect(op="search", n=1, filter="energy")]


# ---------------------------------------------------------------- attack riders
@_pattern(r"does (\d+) more damage for each energy attached to both active pok.mon", priority=25)
def _bonus_both_actives(m):
    return [Effect(op="bonus_per", n=int(m.group(1)), filter="energy_on_both_actives")]


@_pattern(r"does (\d+) more damage for each benched pok.mon \(both yours and your opponent's\)", priority=25)
def _bonus_all_benched(m):
    return [Effect(op="bonus_per", n=int(m.group(1)), filter="all_benched")]


@_pattern(r"this attack does (\d+) damage for each prize card your opponent has taken", priority=25)
def _scale_opponent_prizes(m):
    return [Effect(op="scale", n=int(m.group(1)), filter="opponent_prizes_taken")]


@_pattern(r"this attack does (\d+) damage for each heads", priority=25)
def _scale_heads(m):
    return [Effect(op="scale", n=int(m.group(1)), filter="heads")]


@_pattern(r"flip (\d+) coins", priority=24)
def _coin_count(m):
    return [Effect(op="coins", n=int(m.group(1)))]


@_pattern(r"if tails,? this attack does nothing", priority=25)
def _fails_on_tails(m):
    return [Effect(op="fails_on_tails")]


@_pattern(r"if there is no stadium in play,? this attack does nothing", priority=25)
def _needs_stadium(m):
    return [Effect(op="requires_stadium")]


@_pattern(r"this attack's damage isn't affected by weakness or resistance", priority=25)
def _ignores_weakness(m):
    return [Effect(op="ignore_weakness")]


@_pattern(r"this attack does (\d+) damage to each of your opponent's pok.mon ex", priority=25)
def _hit_every_ex(m):
    return [Effect(op="hit_rule_boxes", n=int(m.group(1)))]


@_pattern(r"you may discard up to (\d+) basic energy from your benched pok.mon", priority=25)
def _bench_energy_cost(m):
    return [Effect(op="discard_energy_scale", n=0, filter="pokemon")]


@_pattern(r"during your opponent's next turn,? they can't play any item cards", priority=25)
def _item_lock(m):
    return [Effect(op="lock_items")]


@_pattern(r"during your opponent's next turn,? that pok.mon can't use that attack", priority=25)
def _attack_lock(m):
    return [Effect(op="lock_attack")]


# -------------------------------------------------------------------- passives
@_pattern(r"attacks used by your ([\w' ]+?) pok.mon(?:, except [^,]+,)? do (\d+) more damage to your opponent's active pok.mon", priority=25)
def _boost_team(m):
    return [Effect(op="boost_damage", n=int(m.group(2)), filter=m.group(1).strip().casefold())]


@_pattern(r"attacks used by the pok.mon this card is attached to do (\d+) more damage to your opponent's active pok.mon ex", priority=27)
def _boost_holder_vs_ex(m):
    return [Effect(op="boost_damage", n=int(m.group(1)), filter="holder_vs_rule_box")]


@_pattern(r"attacks used by the pok.mon this card is attached to do (\d+) more damage to your opponent's active pok.mon", priority=26)
def _boost_holder(m):
    return [Effect(op="boost_damage", n=int(m.group(1)), filter="holder")]


@_pattern(r"(?:gets|has) \+(\d+) hp", priority=25)
def _hp_boost(m):
    return [Effect(op="hp_boost", n=int(m.group(1)))]


@_pattern(r"takes (\d+) less damage from attacks", priority=25)
def _damage_reduction(m):
    return [Effect(op="reduce_damage", n=int(m.group(1)))]


@_pattern(r"your basic pok.mon in play have no retreat cost", priority=25)
def _free_retreat(m):
    return [Effect(op="no_retreat_cost", filter="basic_pokemon")]


@_pattern(r"if that pok.mon's remaining hp is (\d+) or less,? it has no retreat cost", priority=25)
def _free_retreat_when_hurt(m):
    return [Effect(op="no_retreat_cost", n=int(m.group(1)), filter="hurt_holder")]


@_pattern(r"the weakness of each of your opponent's (\{?\w+\}?) pok.mon in play is now (\{?\w+\}?)", priority=25)
def _set_weakness(m):
    return [Effect(op="set_weakness", filter=m.group(1).strip("{}"), dest=m.group(2).strip("{}"))]


@_pattern(r"once during your turn,? you may attach a basic (\{?\w+\}?) energy card from your hand to this pok.mon", priority=25)
def _extra_attach(m):
    return [Effect(op="attach_from_hand", n=1, filter="basic_energy")]


@_pattern(r"once during your turn,? if this pok.mon has any (?:\{?\w+\}? )?energy attached,? you may move up to (\d+) damage counters", priority=25)
def _move_counters(m):
    return [Effect(op="move_damage", n=int(m.group(1)) * 10)]


@_pattern(r"pok.mon in play \(both yours and your opponent's\) have no abilities", priority=25)
def _ability_lock(m):
    return [Effect(op="lock_abilities")]


@_pattern(r"once during your turn,? you may put (\d+) damage counters on 1 of your opponent's pok.mon", priority=26)
def _place_counters(m):
    return [Effect(op="place_counters", n=int(m.group(1)) * 10)]


@_pattern(r"place (\d+) damage counters on your opponent's active pok.mon", priority=26)
def _place_counters_active(m):
    return [Effect(op="place_counters", n=int(m.group(1)) * 10, dest="active")]


@_pattern(r"if you use this ability,? this pok.mon is knocked out", priority=26)
def _self_ko(m):
    return [Effect(op="ko_self")]


@_pattern(r"this attack also does (\d+) damage to 1 of your opponent's benched pok.mon", priority=26)
def _also_snipe(m):
    return [Effect(op="snipe", n=int(m.group(1)), dest="opponent")]


@_pattern(r"this attack does (\d+) more damage for each card you discarded in this way", priority=26)
def _discard_more_scale(m):
    return [Effect(op="discard_energy_scale", n=int(m.group(1)), filter="pokemon", dest="bonus")]


@_pattern(r"attach a basic energy card from your hand to 1 of your pok.mon", priority=26)
def _attack_attach(m):
    return [Effect(op="attach_from_hand", n=1, filter="basic_energy")]


@_pattern(r"once during your turn,? you may move a basic energy from 1 of your pok.mon to another", priority=26)
def _move_energy(m):
    return [Effect(op="move_energy", n=1)]


@_pattern(r"put up to (\d+) [\w' ]+ from your discard pile onto your bench", priority=26)
def _recover_to_bench(m):
    return [Effect(op="recover", n=int(m.group(1)), filter="basic_pokemon", dest="bench")]


@_pattern(r"once during your first turn,? you may search your deck for up to (\d+) (?:\{?\w+\}? )?pok.mon with (\d+) hp or less", priority=27)
def _fan_call(m):
    return [Effect(op="search", n=int(m.group(1)), filter="basic_pokemon")]


@_pattern(r"([\w' ]+) used by this pok.mon costs \{c\} less for each prize card your opponent has taken", priority=26)
def _cheaper_per_prize(m):
    return [Effect(op="cost_less", n=1, filter=m.group(1).strip().casefold())]


@_pattern(r"once during your turn,? you may switch 1 of your benched (?:\{?\w+\}? )?pok.mon[^.]*with your active pok.mon", priority=26)
def _ability_switch(m):
    return [Effect(op="switch_self")]


@_pattern(r"search (?:your|their) deck for (\d+) cards,? shuffle your deck,? then put those cards on top", priority=27)
def _codebreaking(m):
    return [Effect(op="search", n=int(m.group(1)), filter="any", dest="top")]


@_pattern(r"this attack does (\d+) damage for each damage counter on this pok.mon", priority=26)
def _scale_own_counters(m):
    return [Effect(op="scale", n=int(m.group(1)), filter="damage_counters_on_self")]


@_pattern(r"this attack does (\d+) damage for each energy attached to all of your opponent's pok.mon", priority=26)
def _scale_opponent_energy(m):
    return [Effect(op="scale", n=int(m.group(1)), filter="opponent_team_energy")]


@_pattern(r"discard an energy from your opponent's active pok.mon", priority=26)
def _strip_energy(m):
    return [Effect(op="discard_energy_target", n=1)]


@_pattern(r"if your opponent's active pok.mon is a pok.mon ex,? this attack does (\d+) more damage", priority=27)
def _bonus_vs_ex(m):
    return [Effect(op="bonus_vs_rule_box", n=int(m.group(1)))]


@_pattern(r"heal (\d+) damage from each of your benched pok.mon", priority=26)
def _heal_bench(m):
    return [Effect(op="heal_bench", n=int(m.group(1)))]


@_pattern(r"if your opponent's basic pok.mon is knocked out by damage from an attack used by this pok.mon,? take (\d+) more prize", priority=26)
def _extra_prize(m):
    return [Effect(op="extra_prize", n=int(m.group(1)), filter="basic_pokemon")]


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
                effects.extend(_maybe_coin(sentence, build(found)))
                matched = True
                break
        if matched:
            continue
        if any(re.search(pattern, sentence, re.IGNORECASE) for pattern in _IGNORABLE):
            continue
        unmodelled.append(sentence)
    return _merge_dig(effects), unmodelled


def _maybe_coin(sentence: str, effects: list[Effect]) -> list[Effect]:
    """A sentence hanging off a coin flip only happens half the time."""
    lowered = sentence.lower()
    if not re.match(r"(flip a coin\.\s*)?if (heads|tails)", lowered):
        return effects
    return [
        Effect(op=e.op, n=e.n, filter=e.filter, dest=e.dest, chance=min(e.chance, 50))
        for e in effects
    ]


def _merge_dig(effects: list[Effect]) -> list[Effect]:
    """"Look at the top 7 cards" plus "reveal a Supporter" is one dig."""
    dig = next((e for e in effects if e.op == "dig"), None)
    take = next((e for e in effects if e.op == "dig_take"), None)
    if dig is None:
        return [e for e in effects if e.op != "dig_take"]
    depth = dig.n
    target = take.filter if take is not None else dig.filter
    merged = [e for e in effects if e.op not in ("dig", "dig_take")]
    merged.append(Effect(op="dig", n=depth, filter=target))
    return merged


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


def is_once_per_turn(text: str) -> bool:
    """Stadium text that each player may use once on their own turn."""
    return bool(re.search(r"once during each player's turn", text or "", re.IGNORECASE))


def lifts_first_turn_ban(text: str) -> bool:
    """Carmine and friends may be played on the first turn going first."""
    return bool(re.search(r"if you go first, you may use this card during your first turn",
                          text or "", re.IGNORECASE))


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
