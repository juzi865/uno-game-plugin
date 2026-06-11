from __future__ import annotations

from typing import List, Optional, Tuple

from .card import Card, CardColor, CardValue


class RuleValidator:
    MIN_PLAYERS = 2
    MAX_PLAYERS = 10
    INITIAL_HAND_SIZE = 7

    @staticmethod
    def can_play_card(card: Card, top_card: Card, current_color: CardColor) -> bool:
        return card.can_play_on(top_card, current_color)

    @staticmethod
    def validate_color_choice(choice: str) -> Optional[CardColor]:
        normalized = choice.strip().lower()
        color_map = {
            "红": CardColor.RED, "红色": CardColor.RED, "red": CardColor.RED,
            "黄": CardColor.YELLOW, "黄色": CardColor.YELLOW, "yellow": CardColor.YELLOW,
            "蓝": CardColor.BLUE, "蓝色": CardColor.BLUE, "blue": CardColor.BLUE,
            "绿": CardColor.GREEN, "绿色": CardColor.GREEN, "green": CardColor.GREEN,
        }
        return color_map.get(normalized)

    @staticmethod
    def validate_player_count(count: int) -> Tuple[bool, str]:
        if count < RuleValidator.MIN_PLAYERS:
            return False, f"至少需要{RuleValidator.MIN_PLAYERS}名玩家才能开始"
        if count > RuleValidator.MAX_PLAYERS:
            return False, f"最多支持{RuleValidator.MAX_PLAYERS}名玩家"
        return True, ""

    @staticmethod
    def get_available_colors() -> List[CardColor]:
        return [CardColor.RED, CardColor.YELLOW, CardColor.BLUE, CardColor.GREEN]
