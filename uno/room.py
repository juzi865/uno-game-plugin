from __future__ import annotations

import random
import string
from typing import Dict, List, Optional

from .engine import GameEngine, GamePhase
from .player import Player


def _generate_room_id(length: int = 6) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


class Room:
    def __init__(self, room_id: str, host_id: str, host_name: str) -> None:
        self.room_id = room_id
        self.host_id = host_id
        self.engine = GameEngine(room_id)
        self.created_at: float = 0
        self.group_id: str = ""
        self.scores: Dict[str, int] = {}

        host = Player(host_id, host_name, is_bot=False)
        self.engine.players.append(host)

    def accumulate_scores(self) -> Dict[str, int]:
        game_scores = self.engine.calculate_game_scores()
        if not game_scores:
            return {}
        for pid, points in game_scores.items():
            self.scores[pid] = self.scores.get(pid, 0) + points
        return game_scores

    def to_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "host_id": self.host_id,
            "phase": self.engine.phase.value,
            "player_count": len(self.engine.players),
            "group_id": self.group_id,
        }


class RoomManager:
    def __init__(self) -> None:
        self._rooms: Dict[str, Room] = {}
        self._player_rooms: Dict[str, str] = {}

    def create_room(self, host_id: str, host_name: str, group_id: str = "") -> Room:
        room_id = _generate_room_id()
        while room_id in self._rooms:
            room_id = _generate_room_id()

        room = Room(room_id, host_id, host_name)
        room.group_id = group_id
        self._rooms[room_id] = room
        self._player_rooms[host_id] = room_id
        return room

    def get_room(self, room_id: str) -> Optional[Room]:
        return self._rooms.get(room_id)

    def get_room_by_player(self, player_id: str) -> Optional[Room]:
        room_id = self._player_rooms.get(player_id)
        if room_id is None:
            return None
        return self._rooms.get(room_id)

    def join_room(self, room_id: str, player_id: str, player_name: str) -> str:
        room = self._rooms.get(room_id)
        if room is None:
            return "房间不存在"

        if room.engine.phase != GamePhase.WAITING:
            return "游戏已开始，无法加入"

        for p in room.engine.players:
            if p.player_id == player_id:
                return "你已经在该房间中"

        if len(room.engine.players) >= 10:
            return "房间已满"

        room.engine.add_player(player_id, player_name)
        self._player_rooms[player_id] = room_id
        return f"{player_name} 加入了房间 {room_id}"

    def leave_room(self, player_id: str) -> str:
        room = self.get_room_by_player(player_id)
        if room is None:
            return "你不在任何房间中"

        if room.engine.phase == GamePhase.PLAYING:
            room.engine.remove_player(player_id)
            self._player_rooms.pop(player_id, None)

            active_players = [p for p in room.engine.players if not p.is_eliminated]
            if len(active_players) < 2:
                room.engine.phase = GamePhase.ENDED
                return "因玩家不足，游戏结束"

            return "已退出房间"

        room.engine.remove_player(player_id)
        self._player_rooms.pop(player_id, None)

        if not room.engine.players:
            self._rooms.pop(room.room_id, None)
            return "房间已解散"

        if player_id == room.host_id:
            room.host_id = room.engine.players[0].player_id

        return "已退出房间"

    def add_bot(self, room_id: str) -> str:
        room = self._rooms.get(room_id)
        if room is None:
            return "房间不存在"

        if room.engine.phase != GamePhase.WAITING:
            return "游戏已开始"

        if len(room.engine.players) >= 10:
            return "房间已满"

        bot_count = sum(1 for p in room.engine.players if p.is_bot)
        bot_id = f"bot_{bot_count + 1}_{room_id}"
        bot_name = f"Bot {bot_count + 1}"
        room.engine.add_player(bot_id, bot_name, is_bot=True)
        return f"{bot_name} 已加入房间"

    def list_rooms(self) -> List[dict]:
        return [
            {
                "room_id": r.room_id,
                "host_id": r.host_id,
                "player_count": len(r.engine.players),
                "phase": r.engine.phase.value,
                "group_id": r.group_id,
            }
            for r in self._rooms.values()
        ]

    def cleanup_room(self, room_id: str) -> None:
        room = self._rooms.pop(room_id, None)
        if room:
            for p in room.engine.players:
                self._player_rooms.pop(p.player_id, None)

    def remove_player_from_all(self, player_id: str) -> None:
        self._player_rooms.pop(player_id, None)

    def is_player_in_game(self, player_id: str) -> bool:
        room = self.get_room_by_player(player_id)
        if room is None:
            return False
        return room.engine.phase == GamePhase.PLAYING
