from __future__ import annotations

from typing import List, Optional

from .card import Card, CardColor


class Player:
    def __init__(self, player_id: str, name: str, is_bot: bool = False) -> None:
        self.player_id = player_id
        self.name = name
        self.hand: List[Card] = []
        self.is_bot = is_bot
        self.said_uno = False
        self.is_eliminated = False

    def add_card(self, card: Card) -> None:
        self.hand.append(card)

    def add_cards(self, cards: List[Card]) -> None:
        self.hand.extend(cards)

    def remove_card(self, index: int) -> Optional[Card]:
        if 0 <= index < len(self.hand):
            return self.hand.pop(index)
        return None

    def hand_summary(self) -> str:
        return "\n".join(
            f"{i}. {card}" for i, card in enumerate(self.hand, 1)
        )

    def hand_count(self) -> int:
        return len(self.hand)

    def total_score(self) -> int:
        return sum(card.value.score for card in self.hand)

    def find_playable_cards(self, top_card: Card, current_color: CardColor) -> List[int]:
        return [
            i for i, card in enumerate(self.hand)
            if card.can_play_on(top_card, current_color)
        ]

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "hand": [card.to_dict() for card in self.hand],
            "is_bot": self.is_bot,
            "said_uno": self.said_uno,
            "is_eliminated": self.is_eliminated,
        }

    def __str__(self) -> str:
        return f"{self.name} ({self.hand_count()}张)"
