from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from .card import Card, CardColor
from .engine import GamePhase
from .room import Room, RoomManager

logger = logging.getLogger("plugin.uno.api")


class UnoAPIServer:
    def __init__(self, room_manager: RoomManager, host: str = "127.0.0.1", port: int = 15810) -> None:
        self._room_manager = room_manager
        self._host = host
        self._port = port
        self._server: Optional[asyncio.AbstractServer] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        try:
            self._server = await asyncio.start_server(
                self._handle_client, self._host, self._port
            )
            logger.info("UNO API 服务已启动: %s:%s", self._host, self._port)
        except Exception as e:
            self._running = False
            logger.warning("UNO API 服务启动失败: %s", e)

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("UNO API 服务已停止")

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            data = await reader.read(4096)
            if not data:
                return
            request = json.loads(data.decode("utf-8"))
            response = await self._process_request(request)
            writer.write(json.dumps(response).encode("utf-8"))
            await writer.drain()
        except json.JSONDecodeError:
            error = {"error": "无效的 JSON 请求"}
            writer.write(json.dumps(error).encode("utf-8"))
            await writer.drain()
        except Exception as e:
            error = {"error": str(e)}
            try:
                writer.write(json.dumps(error).encode("utf-8"))
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _process_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        action = request.get("action", "")
        data = request.get("data", {})

        handlers = {
            "list_rooms": self._api_list_rooms,
            "create_room": self._api_create_room,
            "join_room": self._api_join_room,
            "leave_room": self._api_leave_room,
            "start_game": self._api_start_game,
            "play_card": self._api_play_card,
            "draw_card": self._api_draw_card,
            "get_status": self._api_get_status,
            "get_hand": self._api_get_hand,
            "add_bot": self._api_add_bot,
            "say_uno": self._api_say_uno,
            "catch_uno": self._api_catch_uno,
        }

        handler = handlers.get(action)
        if handler is None:
            return {"success": False, "error": f"未知操作: {action}"}

        return await handler(data)

    async def _api_list_rooms(self, data: Dict[str, Any]) -> Dict[str, Any]:
        _ = data
        rooms = self._room_manager.list_rooms()
        return {"success": True, "rooms": rooms}

    async def _api_create_room(self, data: Dict[str, Any]) -> Dict[str, Any]:
        player_id = data.get("player_id", "")
        player_name = data.get("player_name", player_id)
        group_id = data.get("group_id", "")

        if not player_id:
            return {"success": False, "error": "player_id 必填"}

        if self._room_manager.get_room_by_player(player_id):
            return {"success": False, "error": "已在房间中"}

        room = self._room_manager.create_room(player_id, player_name, group_id)
        return {
            "success": True,
            "room_id": room.room_id,
            "host_id": room.host_id,
        }

    async def _api_join_room(self, data: Dict[str, Any]) -> Dict[str, Any]:
        room_id = data.get("room_id", "")
        player_id = data.get("player_id", "")
        player_name = data.get("player_name", player_id)

        if not room_id or not player_id:
            return {"success": False, "error": "room_id 和 player_id 必填"}

        result = self._room_manager.join_room(room_id, player_id, player_name)
        return {"success": "加入" in result, "message": result}

    async def _api_leave_room(self, data: Dict[str, Any]) -> Dict[str, Any]:
        player_id = data.get("player_id", "")
        if not player_id:
            return {"success": False, "error": "player_id 必填"}

        result = self._room_manager.leave_room(player_id)
        return {"success": True, "message": result}

    async def _api_start_game(self, data: Dict[str, Any]) -> Dict[str, Any]:
        player_id = data.get("player_id", "")
        if not player_id:
            return {"success": False, "error": "player_id 必填"}

        room = self._room_manager.get_room_by_player(player_id)
        if room is None:
            return {"success": False, "error": "不在房间中"}

        if room.host_id != player_id:
            return {"success": False, "error": "只有房主可以开始"}

        result = room.engine.start_game()
        return {"success": room.engine.phase == GamePhase.PLAYING, "message": result, "status": room.engine.get_status()}

    async def _api_play_card(self, data: Dict[str, Any]) -> Dict[str, Any]:
        player_id = data.get("player_id", "")
        card_index = data.get("card_index", -1)
        chosen_color = data.get("chosen_color")

        if not player_id:
            return {"success": False, "error": "player_id 必填"}

        room = self._room_manager.get_room_by_player(player_id)
        if room is None:
            return {"success": False, "error": "不在房间中"}

        result = room.engine.play_card(player_id, card_index, chosen_color)
        return {"success": room.engine.phase == GamePhase.PLAYING, "message": result, "status": room.engine.get_status()}

    async def _api_draw_card(self, data: Dict[str, Any]) -> Dict[str, Any]:
        player_id = data.get("player_id", "")
        if not player_id:
            return {"success": False, "error": "player_id 必填"}

        room = self._room_manager.get_room_by_player(player_id)
        if room is None:
            return {"success": False, "error": "不在房间中"}

        result = room.engine.draw_card(player_id)
        return {"success": True, "message": result, "status": room.engine.get_status()}

    async def _api_get_status(self, data: Dict[str, Any]) -> Dict[str, Any]:
        room_id = data.get("room_id", "")
        player_id = data.get("player_id", "")

        room = None
        if room_id:
            room = self._room_manager.get_room(room_id)
        elif player_id:
            room = self._room_manager.get_room_by_player(player_id)

        if room is None:
            return {"success": False, "error": "房间不存在"}

        return {"success": True, "status": room.engine.get_status()}

    async def _api_get_hand(self, data: Dict[str, Any]) -> Dict[str, Any]:
        player_id = data.get("player_id", "")
        if not player_id:
            return {"success": False, "error": "player_id 必填"}

        room = self._room_manager.get_room_by_player(player_id)
        if room is None:
            return {"success": False, "error": "不在房间中"}

        hand = room.engine.get_player_hand(player_id)
        if hand is None:
            return {"success": False, "error": "玩家不存在"}

        return {
            "success": True,
            "hand": [card.to_dict() for card in hand],
            "hand_count": len(hand),
        }

    async def _api_add_bot(self, data: Dict[str, Any]) -> Dict[str, Any]:
        player_id = data.get("player_id", "")
        if not player_id:
            return {"success": False, "error": "player_id 必填"}

        room = self._room_manager.get_room_by_player(player_id)
        if room is None:
            return {"success": False, "error": "不在房间中"}

        if room.host_id != player_id:
            return {"success": False, "error": "只有房主可以添加 Bot"}

        result = self._room_manager.add_bot(room.room_id)
        return {"success": True, "message": result}

    async def _api_say_uno(self, data: Dict[str, Any]) -> Dict[str, Any]:
        player_id = data.get("player_id", "")
        if not player_id:
            return {"success": False, "error": "player_id 必填"}

        room = self._room_manager.get_room_by_player(player_id)
        if room is None:
            return {"success": False, "error": "不在房间中"}

        result = room.engine.say_uno(player_id)
        return {"success": True, "message": result}

    async def _api_catch_uno(self, data: Dict[str, Any]) -> Dict[str, Any]:
        caller_id = data.get("caller_id", "")
        target_id = data.get("target_id", "")

        if not caller_id or not target_id:
            return {"success": False, "error": "caller_id 和 target_id 必填"}

        room = self._room_manager.get_room_by_player(caller_id)
        if room is None:
            return {"success": False, "error": "不在房间中"}

        result = room.engine.catch_uno(caller_id, target_id)
        return {"success": True, "message": result}
