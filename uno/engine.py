from __future__ import annotations

import random
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

from .card import Card, CardColor, CardValue
from .deck import Deck
from .player import Player
from .rules import RuleValidator
from .bot_ai import BotAI


class GamePhase(str, Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    ENDED = "ended"


class GameEngine:
    def __init__(self, room_id: str) -> None:
        self.room_id = room_id
        self.players: List[Player] = []
        self.draw_pile = Deck()
        self.discard_pile: List[Card] = []
        self.current_player_index = 0
        self.direction = 1
        self.current_color: CardColor = CardColor.RED
        self.pending_draw = 0
        self.phase = GamePhase.WAITING
        self.winner: Optional[Player] = None
        self.last_action = ""
        self._chosen_color: Optional[CardColor] = None

    @property
    def current_player(self) -> Optional[Player]:
        if 0 <= self.current_player_index < len(self.players):
            return self.players[self.current_player_index]
        return None

    @property
    def top_card(self) -> Optional[Card]:
        if self.discard_pile:
            return self.discard_pile[-1]
        return None

    def add_player(self, player_id: str, name: str, is_bot: bool = False) -> Player:
        player = Player(player_id, name, is_bot)
        self.players.append(player)
        return player

    def remove_player(self, player_id: str) -> bool:
        for i, p in enumerate(self.players):
            if p.player_id == player_id:
                if self.current_player_index >= i:
                    self.current_player_index = max(0, self.current_player_index - 1)
                self.players.pop(i)
                return True
        return False

    def start_game(self) -> str:
        valid, msg = RuleValidator.validate_player_count(len(self.players))
        if not valid:
            return msg

        self.draw_pile.build_standard_deck()
        self.draw_pile.shuffle()

        for player in self.players:
            player.hand.clear()
            cards = self.draw_pile.draw(RuleValidator.INITIAL_HAND_SIZE)
            player.add_cards(cards)

        top = self.draw_pile.draw_one()
        while top is not None and top.is_wild:
            self.draw_pile.add(top)
            self.draw_pile.shuffle()
            top = self.draw_pile.draw_one()

        if top is None:
            return "洗牌失败，请重试"

        self.discard_pile = [top]
        self.current_color = top.color
        self.direction = 1
        self.current_player_index = 0
        self.pending_draw = 0
        self.phase = GamePhase.PLAYING
        self.winner = None

        if top.value == CardValue.SKIP:
            self._advance_turn()
        elif top.value == CardValue.REVERSE:
            self.direction = -1
            self._advance_turn()
        elif top.value == CardValue.DRAW_TWO:
            self.pending_draw = 2

        return "游戏开始！"

    def _refill_draw_pile(self) -> None:
        if self.draw_pile.remaining > 0:
            return
        if len(self.discard_pile) <= 1:
            return

        top = self.discard_pile.pop()
        self.draw_pile.add_all(self.discard_pile)
        self.discard_pile.clear()
        self.discard_pile.append(top)
        self.draw_pile.shuffle()

    def play_card(self, player_id: str, card_index: int, chosen_color: Optional[str] = None) -> str:
        if self.phase != GamePhase.PLAYING:
            return "游戏未开始"

        player = self.current_player
        if player is None or player.player_id != player_id:
            return f"当前轮到 {self.current_player.name if self.current_player else '?'}，不是你的回合"

        if card_index < 0 or card_index >= len(player.hand):
            return "无效的卡牌索引"

        card = player.hand[card_index]
        top = self.top_card
        if top is None:
            return "牌堆为空"

        if not RuleValidator.can_play_card(card, top, self.current_color):
            return f"不能打出 {card}，当前牌面：{top}，当前颜色：{self.current_color.display}"

        if self.pending_draw > 0 and card.value not in (CardValue.DRAW_TWO, CardValue.WILD_DRAW_FOUR):
            return f"你需要先摸 {self.pending_draw} 张牌（/uno 摸牌），或打出 +2/+4"

        if card.is_wild:
            if chosen_color:
                color = RuleValidator.validate_color_choice(chosen_color)
                if color is None:
                    return "无效的颜色，请选择：红/黄/蓝/绿"
                self.current_color = color
            else:
                if player.is_bot:
                    self.current_color = BotAI.choose_color(player)
                else:
                    return "请指定颜色，例如：/uno 出 5 红"
        else:
            self.current_color = card.color

        hand_before = player.hand_count()
        player.remove_card(card_index)
        self.discard_pile.append(card)

        penalty_messages: List[str] = []
        if hand_before == 2 and player.hand_count() == 1 and not player.said_uno:
            self._refill_draw_pile()
            penalty_cards = self.draw_pile.draw(2)
            if penalty_cards:
                player.add_cards(penalty_cards)
                penalty_messages.append(f"{player.name} 未喊UNO，罚摸2张！")

        player.said_uno = False

        if player.hand_count() == 0:
            self.phase = GamePhase.ENDED
            self.winner = player
            return f"{player.name} 出完了所有牌！获胜！"

        effects = self._apply_card_effect(card)
        msg = f"{player.name} 打出了 {card}"
        if penalty_messages:
            msg += "\n" + "\n".join(penalty_messages)
        if effects:
            msg += "\n" + effects
        self._advance_turn()
        return msg

    def draw_card(self, player_id: str) -> str:
        if self.phase != GamePhase.PLAYING:
            return "游戏未开始"

        player = self.current_player
        if player is None or player.player_id != player_id:
            return f"当前轮到 {self.current_player.name if self.current_player else '?'}，不是你的回合"

        draw_count = self.pending_draw if self.pending_draw > 0 else 1
        self._refill_draw_pile()

        cards = self.draw_pile.draw(draw_count)
        if not cards:
            return "牌堆已空"

        player.add_cards(cards)
        drawn_msg = f"{player.name} 摸了 {len(cards)} 张牌"
        self.pending_draw = 0
        player.said_uno = False

        self._advance_turn()
        return drawn_msg

    def _apply_card_effect(self, card: Card) -> str:
        effects: List[str] = []

        if card.value == CardValue.SKIP:
            self._advance_turn()
            next_player = self.current_player
            if next_player:
                effects.append(f"跳过 {next_player.name}")

        elif card.value == CardValue.REVERSE:
            if len(self.players) == 2:
                self._advance_turn()
                next_player = self.current_player
                if next_player:
                    effects.append(f"跳过 {next_player.name}")
            else:
                self.direction *= -1
                effects.append("方向反转")

        elif card.value == CardValue.DRAW_TWO:
            self.pending_draw = 2

        elif card.value == CardValue.WILD_DRAW_FOUR:
            self.pending_draw = 4

        return "，".join(effects)

    def _advance_turn(self) -> None:
        self.current_player_index = (self.current_player_index + self.direction) % len(self.players)

    def say_uno(self, player_id: str) -> str:
        player = self._find_player(player_id)
        if player is None:
            return "玩家不存在"

        if player.said_uno:
            return "已经喊过UNO了"

        if player.hand_count() > 2:
            return "手牌数大于2，无需喊UNO"

        if player.hand_count() == 0:
            return "手牌已出完"

        player.said_uno = True
        return f"{player.name} 喊了 UNO！"

    def catch_uno(self, caller_id: str, target_id: str) -> str:
        target = self._find_player(target_id)
        if target is None:
            return "目标玩家不存在"

        if target.hand_count() != 1:
            return f"{target.name} 手牌数不为1"

        if target.said_uno:
            return f"{target.name} 已经喊过UNO了"

        self._refill_draw_pile()
        penalty_cards = self.draw_pile.draw(2)
        target.add_cards(penalty_cards)
        return f"{target.name} 没喊UNO！被罚摸2张牌"

    def _find_player(self, player_id: str) -> Optional[Player]:
        for p in self.players:
            if p.player_id == player_id:
                return p
        return None

    def restart_game(self) -> str:
        if self.phase != GamePhase.ENDED:
            return "游戏未结束，无法重新开始"

        self.draw_pile = Deck()
        self.draw_pile.build_standard_deck()
        self.draw_pile.shuffle()

        for player in self.players:
            player.hand.clear()
            cards = self.draw_pile.draw(RuleValidator.INITIAL_HAND_SIZE)
            player.add_cards(cards)
            player.said_uno = False

        top = self.draw_pile.draw_one()
        while top is not None and top.is_wild:
            self.draw_pile.add(top)
            self.draw_pile.shuffle()
            top = self.draw_pile.draw_one()

        if top is None:
            return "洗牌失败，请重试"

        self.discard_pile = [top]
        self.current_color = top.color
        self.direction = 1
        self.current_player_index = 0
        self.pending_draw = 0
        self.phase = GamePhase.PLAYING
        self.winner = None

        if top.value == CardValue.SKIP:
            self._advance_turn()
        elif top.value == CardValue.REVERSE:
            self.direction = -1
            self._advance_turn()
        elif top.value == CardValue.DRAW_TWO:
            self.pending_draw = 2

        return "游戏重新开始！"

    def calculate_game_scores(self) -> Dict[str, int]:
        if self.winner is None:
            return {}
        scores: Dict[str, int] = {}
        winner_total = 0
        for p in self.players:
            hand_value = p.total_score()
            scores[p.player_id] = hand_value
            if p.player_id != self.winner.player_id:
                winner_total += hand_value
        scores[self.winner.player_id] = winner_total
        return scores

    def skip_current(self, player_id: str) -> str:
        if self.current_player and self.current_player.player_id != player_id:
            return f"当前轮到 {self.current_player.name}"
        self._advance_turn()
        return "已跳过回合"

    def get_status(self) -> dict:
        return {
            "room_id": self.room_id,
            "phase": self.phase.value,
            "players": [
                {
                    "player_id": p.player_id,
                    "name": p.name,
                    "hand_count": p.hand_count(),
                    "is_bot": p.is_bot,
                    "is_eliminated": p.is_eliminated,
                }
                for p in self.players
            ],
            "current_turn": self.current_player.name if self.current_player else "",
            "current_turn_index": self.current_player_index,
            "direction": self.direction,
            "current_color": self.current_color.value,
            "pending_draw": self.pending_draw,
            "top_card": self.top_card.to_dict() if self.top_card else None,
            "remaining_cards": self.draw_pile.remaining + len(self.discard_pile),
        }

    def get_player_hand(self, player_id: str) -> Optional[List[Card]]:
        player = self._find_player(player_id)
        if player is None:
            return None
        return player.hand

    def next_turn_info(self) -> str:
        if self.current_player is None:
            return ""
        return f"当前轮到 {self.current_player.name}"

    def process_ai_turn(self, uno_forget_prob: float = 0.0) -> str:
        player = self.current_player
        if player is None or not player.is_bot:
            return ""

        top = self.top_card
        if top is None:
            return ""

        if player.hand_count() == 2 and not player.said_uno:
            if random.random() >= uno_forget_prob:
                player.said_uno = True

        if self.pending_draw > 0:
            chosen = None
            for i, card in enumerate(player.hand):
                if card.value in (CardValue.DRAW_TWO, CardValue.WILD_DRAW_FOUR):
                    if RuleValidator.can_play_card(card, top, self.current_color):
                        chosen = i
                        break
            if chosen is not None:
                return self.play_card(player.player_id, chosen)

            return self.draw_card(player.player_id)

        card_index = BotAI.choose_card(player, top, self.current_color)
        if card_index is not None:
            card = player.hand[card_index]
            if card.is_wild:
                color = BotAI.choose_color(player)
                self.current_color = color
            return self.play_card(player.player_id, card_index)

        return self.draw_card(player.player_id)
