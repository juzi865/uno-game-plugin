from __future__ import annotations

import random
from typing import Dict, List, Optional

from .card import Card, CardColor, CardValue
from .player import Player


class BotAI:
    @staticmethod
    def choose_card(player: Player, top_card: Card, current_color: CardColor) -> Optional[int]:
        playable_indices = player.find_playable_cards(top_card, current_color)
        if not playable_indices:
            return None

        action_indices = [
            i for i in playable_indices
            if player.hand[i].value.is_action
        ]
        numeric_indices = [
            i for i in playable_indices
            if not player.hand[i].value.is_action and player.hand[i].value != CardValue.ZERO
        ]
        zero_indices = [
            i for i in playable_indices
            if player.hand[i].value == CardValue.ZERO
        ]

        if player.hand_count() == 2:
            for i in action_indices:
                if player.hand[i].value == CardValue.WILD_DRAW_FOUR:
                    return i

        candidates = action_indices or numeric_indices or zero_indices

        if candidates:
            return random.choice(candidates)

        return None

    @staticmethod
    def choose_color(player: Player) -> CardColor:
        color_count: Dict[str, int] = {}
        for card in player.hand:
            if not card.is_wild:
                color_count[card.color.value] = color_count.get(card.color.value, 0) + 1

        if not color_count:
            return random.choice([CardColor.RED, CardColor.YELLOW, CardColor.BLUE, CardColor.GREEN])

        most_common_color = max(color_count, key=color_count.get)
        return CardColor(most_common_color)

    @staticmethod
    def should_say_uno(player: Player) -> bool:
        return player.hand_count() == 1 and not player.said_uno

    @staticmethod
    def choose_greedy_card(player: Player, top_card: Card, current_color: CardColor) -> Optional[int]:
        playable_indices = player.find_playable_cards(top_card, current_color)
        if not playable_indices:
            return None

        action_cards = [
            i for i in playable_indices
            if player.hand[i].value in {
                CardValue.SKIP, CardValue.REVERSE, CardValue.DRAW_TWO,
                CardValue.WILD_DRAW_FOUR,
            }
        ]
        if action_cards:
            return random.choice(action_cards)

        return random.choice(playable_indices)
