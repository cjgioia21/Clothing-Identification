"""The player: a heuristic policy that both sides of a battle use.

It is not a champion, but it plays a recognisable game — bench early, evolve on
curve, attach to the attacker that needs it, draw when the hand runs dry, gust
for a knockout when the gust is worth it, and take the best attack available.
"""

from __future__ import annotations

from .cards import Card, Category, Stage, Subtype
from .scripts import matches, pick_discards, run, useful

MAX_ACTIONS = 60
TARGET_BENCH = 4


class Policy:
    """Heuristic play for one side."""

    # ------------------------------------------------------------------ setup
    def setup(self, battle, index: int) -> None:
        side = battle.sides[index]
        basics = side.basics_in_hand()
        starter = min(basics, key=lambda c: self.starter_rank(battle, index, c))
        side.hand.remove(starter)
        side.active = _spot(starter, battle.turn)
        for card in list(side.basics_in_hand()):
            if len(side.bench) >= 5:
                break
            side.hand.remove(card)
            side.bench_pokemon(card, battle.turn)

    def starter_rank(self, battle, index: int, card: Card) -> tuple:
        """Lead with something cheap: low prize value, ideally an attacker."""
        has_attack = any(a.cost for a in card.attacks)
        return (card.prize_value, 0 if has_attack else 1, -card.hp, card.name)

    def choose_promotion(self, battle, index: int):
        side = battle.sides[index]
        return max(side.bench, key=lambda s: self.spot_value(battle, index, s))

    def best_bench(self, battle, index: int):
        side = battle.sides[index]
        return max(side.bench, key=lambda s: (self.reach(battle, index, s),
                                              self.spot_value(battle, index, s)))

    def wants_switch(self, battle, index: int) -> bool:
        """Is there a benched Pokémon that would hit harder from the Active Spot?

        A free Ability switch costs nothing, so the bar is lower than retreat,
        but shuffling the board every turn for its own sake just puts an empty
        Pokémon in front of the attacker that was about to swing.
        """
        side = battle.sides[index]
        if side.active is None or not side.bench:
            return False
        current = self.reach(battle, index, side.active)
        best = max(self.reach(battle, index, other) for other in side.bench)
        if best > current:
            return True
        # Or to get out from under a knockout the Active cannot survive.
        threat = self.incoming(battle, index)
        if threat < side.active.remaining_hp:
            return False
        return any(other.remaining_hp > threat for other in side.bench)

    def incoming(self, battle, index: int) -> int:
        """The biggest hit the opponent's Active could land on us right now."""
        foe = battle.opponent(index)
        spot, target = foe.active, battle.sides[index].active
        if spot is None or target is None:
            return 0
        worst = 0
        for attack in spot.card.attacks:
            if not battle.can_pay(spot, attack):
                continue
            plan = battle.attack_plan(1 - index, attack, spot, target)
            raw = battle.attack_damage(1 - index, attack, spot, target, plan)
            ignore = any(e.op == "ignore_weakness" for e in attack.effects)
            worst = max(worst, battle.final_damage(raw, spot, target, 1 - index,
                                                   ignore_weakness=ignore))
        return worst

    def spot_value(self, battle, index: int, spot) -> tuple:
        ready = any(battle.can_pay(spot, a) for a in spot.card.attacks)
        return (1 if ready else 0, -spot.card.prize_value, spot.remaining_hp)

    def gust_target(self, battle, index: int):
        """Which of the opponent's benched Pokémon we would rather face."""
        foe = battle.opponent(index)
        best = self.best_attack(battle, index)
        damage = best[1] if best else 0
        return max(
            foe.bench,
            key=lambda s: (
                1 if damage >= s.remaining_hp else 0,
                s.prize_value if damage >= s.remaining_hp else 0,
                -s.remaining_hp,
            ),
        )

    # ------------------------------------------------------------------- turn
    def play_turn(self, battle, index: int) -> None:
        for _ in range(MAX_ACTIONS):
            if battle.finished or battle.sides[index].turn_over:
                return
            if not self.take_action(battle, index):
                break
        self.consider_retreat(battle, index)

    def take_action(self, battle, index: int) -> bool:
        return (
            self.use_abilities(battle, index)
            or self.bench_basics(battle, index)
            or self.play_setup_items(battle, index)
            or self.play_supporter(battle, index)
            or self.evolve(battle, index)
            or self.attach_energy(battle, index)
            or self.attach_tool(battle, index)
            or self.play_items(battle, index)
            or self.use_stadium(battle, index)
            or self.play_stadium(battle, index)
            or self.play_any_supporter(battle, index)
        )

    def use_abilities(self, battle, index: int) -> bool:
        side = battle.sides[index]
        if battle.abilities_locked(index):
            return False
        for spot in side.in_play():
            card = spot.card
            if not card.ability or card.ability_trigger != "turn":
                continue
            if spot.ability_used_turn == battle.turn:
                continue  # an Ability works the turn it hits the board, but only once
            if not useful(battle, index, card.ability, spot):
                continue
            spot.ability_used_turn = battle.turn
            run(battle, index, card.ability, spot)
            return True
        return False

    def bench_basics(self, battle, index: int) -> bool:
        side = battle.sides[index]
        if len(side.bench) >= TARGET_BENCH:
            return False
        basics = [c for c in side.hand if c.is_basic_pokemon]
        if not basics:
            return False
        card = max(basics, key=lambda c: self.card_value(battle, index, c))
        side.hand.remove(card)
        spot = side.bench_pokemon(card, battle.turn)
        if spot is not None:
            self.on_bench(battle, index, spot)
        return True

    def on_bench(self, battle, index: int, spot) -> None:
        battle.on_benched(index, spot)
        if spot.knocked_out:
            return
        card = spot.card
        if battle.abilities_locked(index):
            return
        if card.ability and card.ability_trigger == "on_play" and useful(battle, index, card.ability, spot):
            spot.ability_used_turn = battle.turn
            run(battle, index, card.ability, spot)

    def play_setup_items(self, battle, index: int) -> bool:
        side = battle.sides[index]
        if battle.items_locked(index):
            return False
        for card in [c for c in side.hand if c.subtype is Subtype.ITEM]:
            if not any(e.op == "search" and "pokemon" in e.filter for e in card.effects):
                continue
            if not useful(battle, index, card.effects):
                continue
            if any(e.op == "discard_from_hand" for e in card.effects) and self.holding_supporter(battle, index):
                continue
            side.hand.remove(card)
            side.discard.append(card)
            if not battle.trainer_taxed(index):
                run(battle, index, card.effects)
            return True
        return False

    def holding_supporter(self, battle, index: int) -> bool:
        side = battle.sides[index]
        return any(
            c.is_supporter and c.draw_value and battle.can_play_supporter(index, c)
            for c in side.hand
        )

    def play_supporter(self, battle, index: int) -> bool:
        side = battle.sides[index]
        if side.supporter_used:
            return False
        for card in sorted(
            (c for c in side.hand if c.is_supporter),
            key=lambda c: -self.supporter_value(battle, index, c),
        ):
            if not battle.can_play_supporter(index, card):
                continue
            if self.supporter_value(battle, index, card) <= 0:
                continue
            side.hand.remove(card)
            side.discard.append(card)
            side.supporter_used = True
            if not battle.trainer_taxed(index):
                run(battle, index, card.effects)
            return True
        return False

    def play_any_supporter(self, battle, index: int) -> bool:
        """Last resort: a Supporter in hand beats passing with nothing done."""
        side = battle.sides[index]
        if side.supporter_used:
            return False
        playable = [
            c for c in side.hand
            if c.is_supporter and c.effects and battle.can_play_supporter(index, c)
            and useful(battle, index, c.effects)
            and self.supporter_value(battle, index, c) >= 0
        ]
        if not playable:
            return False
        card = max(playable, key=lambda c: self.supporter_value(battle, index, c))
        side.hand.remove(card)
        side.discard.append(card)
        side.supporter_used = True
        run(battle, index, card.effects)
        return True

    def supporter_value(self, battle, index: int, card: Card) -> int:
        """How much this Supporter is worth playing right now.

        Draw is only worth a card when the hand has run low: firing a seven-card
        refill off a full hand burns the deck, and decking out loses the game.
        """
        side = battle.sides[index]
        foe = battle.opponent(index)
        hand_size = len(side.hand)
        value = 0
        for effect in card.effects:
            if effect.op == "switch_opponent" and foe.bench:
                best = self.best_attack(battle, index)
                damage = best[1] if best else 0
                target = self.gust_target(battle, index)
                value += 40 if damage >= target.remaining_hp else 2
            elif effect.op in ("draw", "draw_to"):
                value += self._draw_value(hand_size, effect.n)
            elif effect.op == "draw_prizes":
                value += self._draw_value(hand_size, side.prizes_left())
            elif effect.op == "discard_hand":
                value -= sum(1 for c in side.hand if self.card_value(battle, index, c) >= 9)
            elif effect.op == "search":
                value += 3 if self.wants_search(battle, index, effect) else 0
            elif effect.op == "attach_energy":
                value += 5 if self.energy_shortfall(battle, index) else 1
            elif effect.op == "opponent_discard_to":
                value += 3 * max(0, len(foe.hand) - effect.n)
            elif effect.op == "opponent_discard_filter":
                value += 3 * sum(1 for c in foe.hand if matches(c, effect.filter))
        if len(side.deck) < 12:
            value -= 6
        if not side.deck:
            value -= 20
        # Digging while a knockout is already lined up spends a deck to win a
        # game that is already being won.
        if len(side.deck) < 20 and len(side.hand) >= 3 and self.can_knock_out(battle, index):
            value -= 8
        return value

    @staticmethod
    def _draw_value(hand_size: int, drawn: int) -> int:
        net = drawn - hand_size
        return net if hand_size <= 4 else net - 4

    def evolve(self, battle, index: int) -> bool:
        side = battle.sides[index]
        for card in list(side.hand):
            if card.category is not Category.POKEMON or card.stage is Stage.BASIC:
                continue
            target = self.evolution_target(battle, index, card)
            if target is None:
                continue
            side.hand.remove(card)
            target.stack.append(card)  # damage counters stay on through evolution
            target.condition = None
            target.ability_used_turn = -1
            if card.ability and card.ability_trigger in ("on_play", "on_evolve"):
                if useful(battle, index, card.ability, target):
                    target.ability_used_turn = battle.turn
                    run(battle, index, card.ability, target)
            return True
        return False

    def evolution_target(self, battle, index: int, card: Card):
        side = battle.sides[index]
        ready = [s for s in side.in_play() if battle.can_evolve(index, s)]
        for spot in ready:
            if spot.name == card.evolves_from:
                return spot
        if card.stage is not Stage.STAGE2:
            return None
        candy = next((c for c in side.hand if c.name == "Rare Candy"), None)
        if candy is None:
            return None
        middle = side.resolution.info(card.evolves_from)
        if middle is None:
            return None
        for spot in ready:
            if spot.name == middle.evolves_from:
                side.hand.remove(candy)
                side.discard.append(candy)
                return spot
        return None

    def attach_energy(self, battle, index: int) -> bool:
        side = battle.sides[index]
        if side.energy_attached:
            return False
        energy = [c for c in side.hand if c.category is Category.ENERGY]
        if not energy:
            return False
        target = self.energy_target(battle, index)
        if target is None:
            return False
        card = max(energy, key=lambda c: self.energy_fit(battle, index, c, target))
        battle.attach_energy(index, card, target)
        run(battle, index, card.effects, target)
        return True

    def energy_target(self, battle, index: int):
        """The Pokémon that most wants the next Energy.

        Judged by its real attack, not the cheap one it can already pay for,
        which is what stops Energy being sprinkled one card per Pokémon.
        """
        side = battle.sides[index]
        spots = [s for s in side.in_play() if any(a.cost for a in s.card.attacks)]
        if not spots:
            return None

        def rank(spot):
            best = self.main_attack(spot)
            if best is None:
                return (-5, 0)
            need = max(0, len(best.cost) - len(spot.energy))
            ready = battle.can_pay(spot, best)
            score = 1 if ready else 10 - need
            if spot is side.active:
                score += 2
            return (score, best.damage)

        return max(spots, key=rank)

    @staticmethod
    def main_attack(spot):
        """The attack this Pokémon is actually trying to use."""
        attacks = [a for a in spot.card.attacks if a.cost]
        if not attacks:
            return None
        damaging = [
            a for a in attacks
            if a.damage > 0
            or a.scaling
            or any(e.op in ("scale", "discard_energy_scale", "snipe", "bench_damage", "ko_target")
                   for e in a.effects)
        ]
        return max(damaging or attacks, key=lambda a: (a.damage, len(a.cost)))

    def energy_fit(self, battle, index: int, card: Card, spot) -> int:
        """How well an Energy card suits the Pokémon it would go on."""
        best = self.main_attack(spot)
        provides = card.energy_provides or ("Colorless",)
        if best is None:
            return card.energy_count
        have = list(spot.energy_types())
        missing = []
        for requirement in best.cost:
            if requirement == "Colorless":
                continue
            if requirement in have:
                have.remove(requirement)
            else:
                missing.append(requirement)
        if any(p in missing for p in provides):
            return 4 + card.energy_count
        if any(p in best.cost for p in provides):
            return 2 + card.energy_count
        return card.energy_count

    def attach_tool(self, battle, index: int) -> bool:
        side = battle.sides[index]
        tools = [c for c in side.hand if c.subtype is Subtype.TOOL]
        if not tools:
            return False
        for spot in side.in_play():
            if spot.tool is None:
                card = tools[0]
                side.hand.remove(card)
                if battle.trainer_taxed(index):
                    side.discard.append(card)
                else:
                    spot.tool = card
                return True
        return False

    def play_items(self, battle, index: int) -> bool:
        side = battle.sides[index]
        if battle.items_locked(index):
            return False
        for card in [c for c in side.hand if c.subtype is Subtype.ITEM]:
            if not card.effects or not useful(battle, index, card.effects):
                continue
            side.hand.remove(card)
            side.discard.append(card)
            if not battle.trainer_taxed(index):
                run(battle, index, card.effects)
            return True
        return False

    def play_stadium(self, battle, index: int) -> bool:
        side = battle.sides[index]
        if battle.stadium is not None and battle.stadium_owner == index:
            return False
        stadiums = [c for c in side.hand
                    if c.subtype is Subtype.STADIUM and battle.can_play_stadium(c)]
        if not stadiums:
            return False
        if battle.trainer_taxed(index):
            side.hand.remove(stadiums[0])
            side.discard.append(stadiums[0])
            return True
        battle.play_stadium(index, stadiums[0])
        return True

    def use_stadium(self, battle, index: int) -> bool:
        """Stadiums with a once-a-turn ability are free value; take it."""
        effects = battle.stadium_ability(index)
        if effects is None or not useful(battle, index, effects):
            return False
        battle.sides[index].stadium_used = True
        run(battle, index, effects)
        return True

    def consider_retreat(self, battle, index: int) -> None:
        """Retreat when the bench can hit harder than the Active can.

        A starter that pokes for 10 should not keep the Active Spot while the
        deck's real attacker sits behind it fully charged — that is how a game
        gets ground out into a deck-out instead of won on prizes.
        """
        side = battle.sides[index]
        spot = side.active
        if spot is None or side.retreated or not side.bench:
            return
        if spot.condition in ("asleep", "paralyzed"):
            return

        cost = battle.retreat_cost(index, spot)
        if cost > len(spot.energy):
            return

        current = self.reach(battle, index, spot)
        replacement = max(side.bench, key=lambda other: self.reach(battle, index, other))
        best = self.reach(battle, index, replacement)
        if best <= 0:
            return
        if current > 0 and best < max(current * 1.5, current + 40):
            return  # the Active is pulling its weight

        for _ in range(cost):
            side.discard.append(spot.energy.pop())
        battle.switch_active(index, replacement)
        side.retreated = True

    def reach(self, battle, index: int, spot) -> int:
        """The most damage this Pokémon could do right now, if it were Active."""
        foe = battle.opponent(index)
        target = foe.active
        if target is None:
            return 0
        best = 0
        for attack in spot.card.attacks:
            if not battle.can_pay(spot, attack):
                continue
            plan = battle.attack_plan(index, attack, spot, target)
            raw = battle.attack_damage(index, attack, spot, target, plan)
            ignore = any(e.op == "ignore_weakness" for e in attack.effects)
            best = max(best, battle.final_damage(raw, spot, target, index, ignore_weakness=ignore))
        return best

    # ----------------------------------------------------------------- attack
    def attack(self, battle, index: int) -> None:
        choice = self.best_attack(battle, index)
        if choice is None:
            return
        attack, score = choice
        if score <= 0 and not self.worth_using(battle, index, attack):
            return  # a blank attack that only burns your own resources
        battle.apply_attack(index, attack)

    def worth_using(self, battle, index: int, attack) -> bool:
        """Is a zero-damage attack still worth it?"""
        side = battle.sides[index]
        for effect in attack.effects:
            if effect.op in ("draw", "draw_to", "discard_hand"):
                return len(side.hand) <= 2 and len(side.deck) > 20
            if effect.op in ("status", "search", "attach_energy", "ko_target",
                             "bench_damage", "bench_counters", "snipe", "snipe_multi"):
                return True
        return False

    def best_attack(self, battle, index: int):
        """The attack that does the most useful damage, with its damage."""
        side = battle.sides[index]
        foe = battle.opponent(index)
        if side.active is None or foe.active is None:
            return None
        options = battle.usable_attacks(index)
        if not options:
            return None
        scored = []
        for attack in options:
            plan = battle.attack_plan(index, attack, side.active, foe.active)
            raw = battle.attack_damage(index, attack, side.active, foe.active, plan)
            damage = battle.final_damage(raw, side.active, foe.active)
            knockout = damage >= foe.active.remaining_hp
            scored.append((
                knockout,
                foe.active.prize_value if knockout else 0,
                damage + self.attack_bonus(battle, index, attack, damage),
                attack,
            ))
        knockout, _, _, attack = max(scored, key=lambda s: (s[0], s[1], s[2]))
        return attack, max(s[2] for s in scored if s[3] is attack)

    def attack_bonus(self, battle, index: int, attack, damage: int) -> int:
        """Small nudges for attacks whose text is worth more than its damage."""
        side = battle.sides[index]
        bonus = 0
        for effect in attack.effects:
            if effect.op == "discard_hand":
                bonus -= 20 * min(3, len(side.hand))
            elif effect.op in ("draw", "draw_to"):
                if len(side.deck) <= 20:
                    bonus -= 40  # attacking for cards is how a deck runs itself out
                elif len(side.hand) <= 1:
                    bonus += 20
            elif effect.op in ("bench_damage", "bench_counters", "snipe", "snipe_multi"):
                bonus += effect.n
            elif effect.op == "no_attack_next_turn":
                bonus -= damage // 4
        return bonus

    # ------------------------------------------------------------------ value
    def wants_search(self, battle, index: int, effect) -> bool:
        """Is this search worth the card it costs to play?"""
        side = battle.sides[index]
        options = [c for c in side.deck if matches(c, effect.filter)]
        if not options:
            return False
        best = max(self.card_value(battle, index, c) for c in options)
        if effect.dest == "bench":
            return len(side.bench) < TARGET_BENCH and any(c.is_basic_pokemon for c in options)
        if effect.filter in ("pokemon", "basic_pokemon"):
            if best >= 9:
                return True
            return len(side.bench) < TARGET_BENCH and best >= 7
        if effect.filter in ("energy", "basic_energy"):
            return self.energy_shortfall(battle, index) > 0
        return best >= 5

    def wants_draw(self, battle, index: int, n: int) -> bool:
        """Draw only with a hand that needs it and a deck that can afford it.

        Chaining every draw Ability every turn is how a deck runs itself out of
        cards, which loses the game just as surely as losing the prize race.
        """
        side = battle.sides[index]
        if len(side.deck) <= max(6, n + 2):
            return False
        if len(side.hand) >= 6:
            return False
        # With a knockout already lined up there is nothing to dig for, and a
        # deck spent grinding out a game it is winning is a game it can lose.
        if len(side.deck) < 20 and len(side.hand) >= 3 and self.can_knock_out(battle, index):
            return False
        return True

    def can_knock_out(self, battle, index: int) -> bool:
        """Can this player take a knockout with what is already in play?"""
        side = battle.sides[index]
        foe = battle.opponent(index)
        if side.active is None or foe.active is None:
            return False
        return self.reach(battle, index, side.active) >= foe.active.remaining_hp

    def energy_shortfall(self, battle, index: int) -> int:
        """How much Energy the board still needs for its best attacks."""
        side = battle.sides[index]
        shortfall = 0
        for spot in side.in_play():
            costs = [len(a.cost) for a in spot.card.attacks]
            if not costs:
                continue
            shortfall += max(0, max(costs) - len(spot.energy))
        return shortfall

    def card_value(self, battle, index: int, card: Card) -> int:
        """A rough 0-10 ranking used for searches, discards and benching."""
        side = battle.sides[index]
        if card.category is Category.POKEMON:
            spots = side.in_play()
            if card.is_basic_pokemon and len(spots) <= 2:
                return 10  # running out of Pokémon loses the game on the spot
            if card.evolves_from and any(s.name == card.evolves_from for s in spots):
                return 10
            if card.stage is Stage.STAGE2 and self.candy_ready(battle, index, card):
                return 10
            if card.is_basic_pokemon:
                if card.name in side.resolution.evolution_sources:
                    return 9
                power = max((a.damage for a in card.attacks), default=0)
                return 6 + min(2, power // 120)
            return 7
        if card.name == "Rare Candy":
            ready = any(
                c.stage is Stage.STAGE2 and self.candy_ready(battle, index, c)
                for c in side.hand
            )
            return 9 if ready else 4
        if card.is_supporter:
            return 7 if card.draw_value else 4
        if card.subtype is Subtype.ITEM:
            return 5
        if card.category is Category.ENERGY:
            if self._energy_wanted(battle, index, card):
                return 7 if self.energy_shortfall(battle, index) else 5
            return 3
        return 2

    def candy_ready(self, battle, index: int, stage2: Card) -> bool:
        """Could Rare Candy turn something already in play into this card?"""
        side = battle.sides[index]
        middle = side.resolution.info(stage2.evolves_from)
        if middle is None:
            return False
        basic = middle.evolves_from
        return any(s.name == basic and s.turn_played < battle.turn for s in side.in_play())

    def _energy_wanted(self, battle, index: int, card: Card) -> bool:
        """Would any attacker in play actually use this Energy?

        A {C} in an attack cost is paid by any Energy at all, so a board that
        wants Colorless wants whatever is in hand.
        """
        side = battle.sides[index]
        needs = {c for s in side.in_play() for a in s.card.attacks for c in a.cost}
        if "Colorless" in needs:
            return True
        return bool(needs & set(card.energy_provides or ()))


def _spot(card: Card, turn: int):
    from .battle import Spot

    return Spot(stack=[card], turn_played=max(turn, 1))
