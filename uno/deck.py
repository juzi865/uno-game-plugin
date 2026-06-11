from __future__ import annotations

import random
from typing import List, Optional

from .card import Card, CardColor, CardValue


class Deck:
    def __init__(self) -> None:
        self._cards: List[Card] = []

    def build_standard_deck(self) -> None:
        self._cards.clear()
        for color in (CardColor.RED, CardColor.YELLOW, CardColor.BLUE, CardColor.GREEN):
            self._cards.append(Card(color, CardValue.ZERO))
            for value in (
                CardValue.ONE, CardValue.TWO, CardValue.THREE, CardValue.FOUR,
                CardValue.FIVE, CardValue.SIX, CardValue.SEVEN, CardValue.EIGHT,
                CardValue.NINE, CardValue.SKIP, CardValue.REVERSE, CardValue.DRAW_TWO,
            ):
                self._cards.append(Card(color, value))
                self._cards.append(Card(color, value))
        for _ in range(4):
            self._cards.append(Card(CardColor.WILD, CardValue.WILD))
            self._cards.append(Card(CardColor.WILD, CardValue.WILD_DRAW_FOUR))

    def shuffle(self) -> None:
        random.shuffle(self._cards)

    def draw(self, count: int = 1) -> List[Card]:
        drawn: List[Card] = []
        for _ in range(count):
            if not self._cards:
                break
            drawn.append(self._cards.pop())
        return drawn

    def draw_one(self) -> Optional[Card]:
        if not self._cards:
            return None
        return self._cards.pop()

    def add(self, card: Card) -> None:
        self._cards.insert(0, card)

    def add_all(self, cards: List[Card]) -> None:
        self._cards = cards + self._cards

    @property
    def remaining(self) -> int:
        return len(self._cards)

    @property
    def is_empty(self) -> bool:
        return len(self._cards) == 0
