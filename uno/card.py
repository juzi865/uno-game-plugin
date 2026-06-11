from __future__ import annotations

from enum import Enum
from typing import Optional


class CardColor(str, Enum):
    RED = "red"
    YELLOW = "yellow"
    BLUE = "blue"
    GREEN = "green"
    WILD = "wild"

    @property
    def display(self) -> str:
        return {
            "red": "红",
            "yellow": "黄",
            "blue": "蓝",
            "green": "绿",
            "wild": "万能",
        }[self.value]

    @property
    def emoji(self) -> str:
        return {
            "red": "🔴",
            "yellow": "🟡",
            "blue": "🔵",
            "green": "🟢",
            "wild": "🌟",
        }[self.value]


class CardValue(str, Enum):
    ZERO = "0"
    ONE = "1"
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    SKIP = "skip"
    REVERSE = "reverse"
    DRAW_TWO = "draw2"
    WILD = "wild"
    WILD_DRAW_FOUR = "wild_draw4"

    @property
    def display(self) -> str:
        return {
            "0": "0", "1": "1", "2": "2", "3": "3", "4": "4",
            "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
            "skip": "跳过",
            "reverse": "反转",
            "draw2": "+2",
            "wild": "变色",
            "wild_draw4": "+4",
        }[self.value]

    @property
    def is_action(self) -> bool:
        return self in {
            CardValue.SKIP, CardValue.REVERSE, CardValue.DRAW_TWO,
            CardValue.WILD, CardValue.WILD_DRAW_FOUR,
        }

    @property
    def is_wild(self) -> bool:
        return self in {CardValue.WILD, CardValue.WILD_DRAW_FOUR}

    @property
    def score(self) -> int:
        return {
            "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
            "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
            "skip": 20, "reverse": 20, "draw2": 20,
            "wild": 50, "wild_draw4": 50,
        }[self.value]


class Card:
    def __init__(self, color: CardColor, value: CardValue) -> None:
        self.color = color
        self.value = value

    @property
    def is_wild(self) -> bool:
        return self.color == CardColor.WILD

    @property
    def is_action(self) -> bool:
        return self.value.is_action

    def can_play_on(self, top_card: Card, current_color: CardColor) -> bool:
        if self.color == CardColor.WILD:
            return True
        if self.color == current_color:
            return True
        if self.value == top_card.value and not top_card.is_wild:
            return True
        return False

    def __str__(self) -> str:
        if self.is_wild:
            return f"{self.color.emoji} {self.value.display}"
        return f"{self.color.emoji}{self.color.display} {self.value.display}"

    def __repr__(self) -> str:
        return f"Card({self.color.value}, {self.value.value})"

    def to_dict(self) -> dict:
        return {"color": self.color.value, "value": self.value.value}

    @classmethod
    def from_dict(cls, data: dict) -> Card:
        return cls(CardColor(data["color"]), CardValue(data["value"]))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Card):
            return NotImplemented
        return self.color == other.color and self.value == other.value

    def __hash__(self) -> int:
        return hash((self.color.value, self.value.value))
